import json
import logging
import time
import uuid
from datetime import date

from src.api_docs import get_endpoint_schema, get_recipe_schemas, search_api_docs
from src.vertex_auth import get_openai_client
from src.tripletex_client import TripletexAPIError, TripletexClient

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 15

_PRE_PARSE_PROMPT = """You are a task parser for a Tripletex accounting agent. Translate the incoming task prompt (may be in nb, nn, en, es, pt, de, fr) into a structured English plan.

Output format (plain text, NOT JSON):
TASK TYPE: <type>
RECIPE: <letter> (<name>)

FIELDS:
- descriptive label: value

STEPS:
1. First step
2. Second step

FILE DATA: <extracted data from attachments, or "(none)">

Rules:
- Extract EVERY value from the prompt — names, emails, dates, amounts, org numbers, addresses, etc.
- Use descriptive labels (e.g. "email", "name", "address line 1"), NOT Tripletex API field names. Never guess API field names like invoiceEmail, phoneNumberMobile, etc.
- Preserve exact spelling, numbers, and Norwegian characters (æ, ø, å)
- Map to one of these recipes:
  A(DEPARTMENT), B(EMPLOYEE), C(CUSTOMER/SUPPLIER), D(PROJECT), E(PRODUCT),
  F(CUSTOMER INVOICE — creating invoices for customers),
  G(PAYMENT — registering payment on existing invoice),
  H(TRAVEL EXPENSE), I(VOUCHER/SUPPLIER INVOICE/JOURNAL ENTRY),
  J(CORRECTIONS — credit notes, payment reversals),
  K(TIMESHEET), L(PAYROLL)
- IMPORTANT: Supplier/vendor invoices (incoming invoices, leverandørfakturaer) are RECIPE I, NOT F. Recipe F is only for customer invoices (outgoing invoices).
- IMPORTANT: If the task involves registering/logging hours or time on an activity/project AND THEN creating an invoice based on those hours, use RECIPE K (TIMESHEET), NOT F. Recipe F is for direct invoicing with specified products/amounts, not time-based billing.
- Include ALL file attachment data in FILE DATA section
- Be concise — no explanations, just the structured output
- If the task involves ANY arithmetic (percentages, totals, multiplying hours×rate, VAT splits, summing salary components), add a MATH section with one expression per line. Use only +, -, *, / and numbers. Examples:
  MATH:
  - invoice amount: 374900 * 0.75
  - total salary: 59600 + 12900
  - hourly total: 25 * 1200
  - net amount: 39750 / 1.25"""

_CORE_RULES = """You are a Tripletex API agent. Complete accounting tasks via API calls. The task has been pre-parsed into English with extracted fields — trust the parsed plan. API field names from the OpenAPI spec are provided below — use them to include ALL available fields.

## Rules
1. API success IS confirmation. NEVER GET after POST/PUT/DELETE — you already have the response.
2. Include EVERY value from the task prompt. Every field is scored. Check the API fields below for correct field names.
3. Follow the recipe below. Do not add verification steps.
4. On error, read the error message and fix in ONE retry. Only search docs if the error suggests you're using the wrong endpoint entirely.
5. GET returns {{values:[...]}}, POST/PUT returns {{value:{{...}}}}. Reuse returned IDs.
6. When no date is specified, use today's date ({today}). Never invent future dates. Dates: YYYY-MM-DD. For vouchers/journal entries, use current fiscal year 2026 (convert older dates). Addresses: {{addressLine1, postalCode, city}} — never a string.
7. VAT types are at GET /v2/ledger/vatType (NOT /v2/vatType). Payment types: GET /v2/invoice/paymentType. Travel payment types: GET /v2/travelExpense/paymentType. Cost categories: GET /v2/travelExpense/costCategory. Call ONCE with no filters, pick from response.
8. If the task says to create/register/add/update/delete, you MUST make a mutation call. Never finish with only GETs.
9. Preserve Norwegian characters (æ, ø, å) exactly as given."""

_RECIPES = {
    'A': """## Recipe: DEPARTMENT [1 call]
POST /v2/department/list — send ALL departments as a JSON array in one call (e.g. [{"name":"X"},{"name":"Y"}]). This creates multiple departments in 1 API call. For a single department, still use /list with a 1-element array.""",

    'B': """## Recipe: EMPLOYEE [2-3 calls]
(1) GET /v2/department?fields=id&count=1 → deptId. (2) POST /v2/employee — set userType:"STANDARD", department:{id}. Include dateOfBirth if given — required before employment. (3) If start date given: POST /v2/employee/employment — always a separate POST.""",

    'C': """## Recipe: CUSTOMER/SUPPLIER [1 call]
ALWAYS use POST /v2/customer for BOTH customers AND suppliers. For customers: set isCustomer:true. For suppliers: set isSupplier:true AND isCustomer:false. Do NOT use POST /v2/supplier. Include all fields from prompt — see API fields below for correct field names. For email: always set BOTH "email" AND "invoiceEmail" to the given email address.""",

    'D': """## Recipe: PROJECT [3-4 calls]
(1) GET /v2/employee?email=X → managerId. (2) If customer: GET /v2/customer?organizationNumber=X → custId. (3) POST /v2/project — MUST include startDate (use today if not specified). Do NOT set "number" (auto-generated). Fixed price: set isFixedPrice:true, fixedprice:amount (lowercase "fixedprice", NOT "fixedPriceAmount"). (4) To invoice partial: GET /v2/ledger/account?isBankAccount=true → PUT with bankAccountNumber:"12345678903" (11 digits), POST /v2/product, POST /v2/order with orderLines (unitPriceExcludingVatCurrency=partial amount), PUT /v2/order/{id}/:invoice?invoiceDate=YYYY-MM-DD.""",

    'E': """## Recipe: PRODUCT [1-2 calls]
(1) If VAT mentioned: GET /v2/ledger/vatType → find match. (2) POST /v2/product — see API fields below.""",

    'F': """## Recipe: INVOICE [5-9 calls]
FOLLOW THIS EXACT ORDER — do NOT skip or reorder steps:
(1) GET /v2/customer?organizationNumber=X → custId.
(2) BANK FIRST: GET /v2/ledger/account?isBankAccount=true → PUT /v2/ledger/account/{id} with bankAccountNumber:"12345678903" (11 digits). MUST be done before step 5 or invoice WILL fail with 422.
(3) Products: if numbers given like "(1234)", GET /v2/product?number=1234 (they exist). Otherwise POST /v2/product — if "without VAT"/"uten MVA"/"sans TVA"/"ohne MwSt", set vatType:{id:6} on the product (exempt). For multiple new products, use POST /v2/product/list with array body. Only GET /v2/ledger/vatType if you need a specific rate.
(4) POST /v2/order — MUST include BOTH orderDate AND deliveryDate (both required!), with orderLines (use "count" not "quantity", price field is unitPriceExcludingVatCurrency).
(5) PUT /v2/order/{id}/:invoice?invoiceDate=YYYY-MM-DD.
For payment after invoice: GET /v2/invoice/paymentType (no filters) → find "Bankinnskudd", PUT /v2/invoice/{id}/:payment with query params only: paymentDate, paymentTypeId, paidAmount, paidAmountCurrency.""",

    'G': """## Recipe: PAYMENT [4 calls]
(1) GET /v2/customer?organizationNumber=X. (2) GET /v2/invoice?invoiceDateFrom=2000-01-01&invoiceDateTo=2030-12-31&customerId=X → id, amountOutstanding. (3) GET /v2/invoice/paymentType (no filters) → find "Bankinnskudd". (4) PUT /v2/invoice/{id}/:payment with QUERY PARAMS ONLY: paymentDate, paymentTypeId, paidAmount=amountOutstanding, paidAmountCurrency=amountOutstanding.""",

    'H': """## Recipe: TRAVEL EXPENSE [3-8 calls]
(1) GET /v2/employee?email=X. (2) GET /v2/travelExpense/paymentType + GET /v2/travelExpense/costCategory (no filters). (3) POST /v2/travelExpense {employee:{id}, title, date, travelDetails:{departureDate, returnDate, destination, purpose, departureFrom}} — CRITICAL: travelDetails MUST be included or Tripletex creates an "employee expense" instead of a "travel expense report", and per diem/accommodation will fail with 422. (4) Per cost: POST /v2/travelExpense/cost — set isPaidByEmployee:true, link via travelExpense:{id}. (5) Accommodation: POST /v2/travelExpense/accommodationAllowance — MUST include location. (6) Per diem: POST /v2/travelExpense/perDiemCompensation — MUST include location. Do NOT try to deliver/submit/complete the expense — just create it with all items. DELETE: GET /v2/travelExpense?employeeId=X → DELETE /v2/travelExpense/{id}.""",

    'I': """## Recipe: VOUCHER [3-8 calls]
(1) GET /v2/ledger/account?number=XXXX for each account. (2) POST /v2/ledger/voucher {date, description (REQUIRED), postings:[{account:{id}, amountGross:X, amountGrossCurrency:X, row:1}, {account:{id}, amountGross:-X, amountGrossCurrency:-X, row:2}]}. CRITICAL: EVERY posting MUST have "row" field starting at 1 (NOT 0) — omitting row causes instant 422. Use amountGross+amountGrossCurrency (same value), never "amount"/"isDebit"/"debit"/"credit". Postings must balance (sum to zero).
DIMENSIONS: POST /v2/ledger/accountingDimensionName — set dimensionIndex:1, active:true. Per value: POST /v2/ledger/accountingDimensionValue — set showInVoucherRegistration:true. Link via freeAccountingDimension1:{id} on posting (or 2/3). NEVER use "dimensions"/"dimensionValue1"/"freeDimension1".
SUPPLIER INVOICE: GET /v2/supplier?organizationNumber=X, GET accounts (expense + 2400), GET /v2/ledger/vatType → CRITICAL: find the VAT type with "Inngående" (incoming/input) in the name AND 25% rate. Do NOT use "Utgående" (outgoing/output) VAT — that is for sales, not purchases. The correct one is typically named "Inngående avgift, høy sats" or similar. GET /v2/ledger/voucherType?name=Leverandørfaktura. POST /v2/ledger/voucher {date, description, vendorInvoiceNumber:"INV-XXX", voucherType:{id}, postings:[{account:{id:expenseAcct}, amountGross:totalInclVat, amountGrossCurrency:totalInclVat, vatType:{id:incomingVAT}, supplier:{id}, row:1}, {account:{id:2400acct}, amountGross:-totalInclVat, amountGrossCurrency:-totalInclVat, supplier:{id}, row:2}]}. CRITICAL VAT HANDLING: set amountGross on the EXPENSE posting to the TOTAL INCLUDING VAT (same as AP line but positive). Set vatType on the expense posting — Tripletex will auto-split the amount into net expense + VAT. Postings MUST balance (sum to zero). Only 2 postings needed. Only set vatType on the expense posting, NOT on the 2400 posting. Use "voucherType" (NOT "supplierVoucherType"). CRITICAL: always set voucherType to "Leverandørfaktura" type.""",

    'J': """## Recipe: CORRECTIONS [2-4 calls]
CREDIT NOTE (invoice is wrong): GET /v2/invoice?invoiceDateFrom=2000-01-01&invoiceDateTo=2030-12-31&customerId=X → PUT /v2/invoice/{id}/:createCreditNote?date=YYYY-MM-DD (date >= invoiceDate). PAYMENT REVERSAL (bank returned payment): GET /v2/customer → GET /v2/invoice?invoiceDateFrom=2000-01-01&invoiceDateTo=2030-12-31&customerId=X → GET /v2/ledger/voucher?dateFrom=2000-01-01&dateTo=2030-12-31 → find ALL vouchers with "Betaling" or "Payment" or "Innbetaling" in description → DELETE each payment voucher (NOT the invoice voucher). Multiple payment vouchers may exist — delete ALL. Use DELETE voucher, NOT createCreditNote. CRITICAL: GET /v2/invoice ALWAYS requires invoiceDateFrom and invoiceDateTo params.""",

    'K': """## Recipe: TIMESHEET [4-14 calls]
(1) GET /v2/employee?email=X. (2) GET /v2/project?name=X → projectId, note startDate and customer. (3) GET /v2/activity?name=X or POST /v2/activity — set isProjectActivity:true, isChargeable:true. (4) POST /v2/timesheet/entry {employee:{id}, project:{id}, activity:{id}, date:YYYY-MM-DD, hours:N} — use project startDate for date (not past date). ONLY use /v2/timesheet/entry (NOT /v2/time-tracking). If task says to invoice: (5) GET /v2/ledger/account?isBankAccount=true → PUT with bankAccountNumber:"12345678903" (11 digits). (6) POST /v2/product with name and price (use hourly rate from task). (7) POST /v2/order with customer:{id}, orderDate, deliveryDate, orderLines:[{product:{id}, count:hours, unitPriceExcludingVatCurrency:hourlyRate}]. (8) PUT /v2/order/{id}/:invoice?invoiceDate=YYYY-MM-DD. CRITICAL: steps 5-8 must ALL be done. Set up bank BEFORE invoice.""",

    'L': """## Recipe: PAYROLL [5-9 calls]
(1) GET /v2/employee?email=X → check dateOfBirth. If null: PUT /v2/employee/{id} with dateOfBirth:"1990-01-01".
(2) Employee needs employment with division. If no employment: GET /v2/municipality?count=1 → POST /v2/division {name:"Main", startDate:"2026-01-01", organizationNumber:"987654321", municipality:{id}, municipalityDate:"2026-01-01"} → POST /v2/employee/employment {employee:{id}, division:{id}, startDate:"2026-03-01"}.
(3) GET /v2/ledger/account?number=5000 + GET /v2/ledger/account?number=2920.
(4) POST /v2/ledger/voucher {date:"YYYY-MM-01" (first of payroll month), description:"Lønn <month> <year>", postings:[
  {account:{id:5000acct}, amountGross:baseSalary, amountGrossCurrency:baseSalary, row:1},
  {account:{id:5000acct}, amountGross:bonus, amountGrossCurrency:bonus, row:2},
  {account:{id:2920acct}, amountGross:-(baseSalary+bonus), amountGrossCurrency:-(baseSalary+bonus), row:3}
]}. Debit 5000, credit 2920. Postings MUST balance. EVERY posting needs "row" starting at 1. Do NOT use /v2/salary/transaction.""",
}

_ACTION = """## Action
You MUST use call_api to complete the task. Start immediately — make the first API call now. Never respond with only text. On 403 auth errors, retry — they are transient. NEVER give up or say you cannot complete the task."""

# Full recipes block for fallback when pre-parse fails
_ALL_RECIPES = "## Recipes\n\n" + "\n\n".join(_RECIPES.values())


def get_system_prompt(recipe_letter: str | None = None) -> str:
    """Build system prompt, focused on a single recipe if letter is provided."""
    today = date.today().isoformat()
    rules = _CORE_RULES.format(today=today)

    if recipe_letter and recipe_letter in _RECIPES:
        recipe = _RECIPES[recipe_letter]
        schema = get_recipe_schemas(f"RECIPE: {recipe_letter}")
        parts = [rules, recipe]
        if schema:
            parts.append(schema)
        parts.append(_ACTION)
        return "\n\n".join(parts)

    # Fallback: all recipes (pre-parse failed or unknown letter)
    return "\n\n".join([rules, _ALL_RECIPES, _ACTION])

CALL_API_TOOL = {
    "type": "function",
    "function": {
        "name": "call_api",
        "description": "Make an API call to the Tripletex API",
        "parameters": {
            "type": "object",
            "properties": {
                "method": {
                    "type": "string",
                    "enum": ["GET", "POST", "PUT", "DELETE"],
                    "description": "HTTP method",
                },
                "endpoint": {
                    "type": "string",
                    "description": "API endpoint path, e.g. /v2/customer",
                },
                "body": {
                    "type": ["object", "null"],
                    "description": "JSON body for POST/PUT requests",
                },
                "params": {
                    "type": ["object", "null"],
                    "description": "Query parameters (used for GET and PUT requests)",
                },
            },
            "required": ["method", "endpoint"],
        },
    },
}


SEARCH_API_DOCS_TOOL = {
    "type": "function",
    "function": {
        "name": "search_api_docs",
        "description": "Search the official Tripletex OpenAPI specification for endpoint details, required fields, parameters, and schemas. Use this when you need to discover the correct endpoint, field names, or required parameters for an API call.",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search term — e.g. 'invoice', 'payment', 'employee', 'vatType', 'project'",
                },
            },
            "required": ["query"],
        },
    },
}


import re as _re

def _evaluate_math(parsed: str) -> str:
    """Find MATH: section in pre-parser output, evaluate expressions with Python, append results."""
    math_match = _re.search(r'MATH:\s*\n((?:\s*-\s*.+\n?)+)', parsed)
    if not math_match:
        return parsed

    results = []
    for line in math_match.group(1).strip().split('\n'):
        line = line.strip().lstrip('- ')
        if ':' not in line:
            continue
        label, expr = line.split(':', 1)
        label = label.strip()
        expr = expr.strip()
        # Only allow safe characters: digits, operators, decimal points, spaces, parens
        if not _re.match(r'^[\d\s\+\-\*/\.\(\)]+$', expr):
            continue
        try:
            result = eval(expr)  # Safe: validated to only contain math chars
            # Round to 2 decimal places for currency
            if isinstance(result, float):
                result = round(result, 2)
            results.append(f"- {label}: {result}")
        except Exception:
            continue

    if results:
        computed = "COMPUTED AMOUNTS:\n" + "\n".join(results)
        # Insert computed amounts before the MATH section
        parsed = parsed[:math_match.start()] + computed + "\n\n" + parsed[math_match.start():]

    return parsed


class TripletexAgent:
    def __init__(
        self,
        model: str,
        tripletex_client: TripletexClient,
        file_contents: list[dict] | None = None,
    ):
        self.openai = get_openai_client()
        self.model = model
        self.client = tripletex_client
        self.file_contents = file_contents

    def _pre_parse(self, prompt: str) -> str | None:
        """Translate and normalize the task prompt into a structured English plan."""
        parse_start = time.time()
        try:
            user_input = f"Task prompt:\n{prompt}"
            if self.file_contents:
                file_text = "\n\n".join(
                    f"--- {f['filename']} ---\n{f['extracted_text']}"
                    for f in self.file_contents
                )
                user_input += f"\n\nAttached file contents:\n{file_text}"

            response = self.openai.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": _PRE_PARSE_PROMPT},
                    {"role": "user", "content": user_input},
                ],
                temperature=0,
            )
            parsed = response.choices[0].message.content or ""
            parsed = _evaluate_math(parsed)
            duration = time.time() - parse_start
            logger.info("Pre-parse completed in %.2fs:\n%s", duration, parsed)
            return parsed
        except Exception as e:
            duration = time.time() - parse_start
            logger.warning("Pre-parse failed in %.2fs: %s — falling back to raw prompt", duration, e)
            return None

    def solve(self, prompt: str) -> None:
        task_id = uuid.uuid4().hex[:8]
        start_time = time.time()
        api_calls = 0
        errors = 0
        doc_searches = 0
        logger.info("[%s] Starting agent for prompt: %s", task_id, _truncate(prompt, 200))

        # Pre-parse the task prompt
        parsed_plan = self._pre_parse(prompt)

        # Extract recipe letter for logging and future dynamic prompt assembly
        recipe_letter = None
        if parsed_plan:
            match = _re.search(r'RECIPE:\s*([A-L])', parsed_plan)
            if match:
                recipe_letter = match.group(1)

        if parsed_plan:
            # Schema is now injected into the system prompt via get_system_prompt()
            user_message = f"Pre-parsed task plan:\n{parsed_plan}\n\nOriginal prompt:\n{prompt}"
        else:
            # Fallback: use raw prompt with file contents
            user_message = f"Task: {prompt}"
            if self.file_contents:
                file_text = "\n\n".join(
                    f"--- {f['filename']} ---\n{f['extracted_text']}"
                    for f in self.file_contents
                )
                user_message += f"\n\nAttached file contents:\n{file_text}"

        messages = [
            {"role": "system", "content": get_system_prompt(recipe_letter)},
            {"role": "user", "content": user_message},
        ]

        for iteration in range(1, MAX_ITERATIONS + 1):
            logger.info("Agent iteration %d/%d", iteration, MAX_ITERATIONS)

            response = self.openai.chat.completions.create(
                model=self.model,
                messages=messages,
                tools=[CALL_API_TOOL, SEARCH_API_DOCS_TOOL],
                temperature=0,
            )

            choice = response.choices[0]

            # If no tool calls, the LLM considers the task done
            if choice.finish_reason != "tool_calls" or not choice.message.tool_calls:
                final_message = choice.message.content or ""
                logger.info("[%s] Agent done: %s", task_id, final_message)
                duration = time.time() - start_time
                logger.info(
                    "[%s] Agent summary: recipe=%s, api_calls=%d, errors=%d, doc_searches=%d, iterations=%d, duration=%.2fs",
                    task_id, recipe_letter or "?", api_calls, errors, doc_searches, iteration, duration,
                )
                return

            # Process tool calls
            messages.append(choice.message)

            for tool_call in choice.message.tool_calls:
                func_name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)

                if func_name == "search_api_docs":
                    query = args.get("query", "")
                    doc_searches += 1
                    logger.info("Docs search: %s (count=%d)", query, doc_searches)
                    if doc_searches > 2:
                        result_str = "Doc search limit reached (max 2). Use the common endpoints from your instructions and fix based on the error message."
                    else:
                        result_str = search_api_docs(query)
                    logger.info("Docs result: %s", _truncate(result_str))
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result_str,
                    })
                    continue

                if func_name != "call_api":
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps({"error": f"Unknown tool: {func_name}"}),
                    })
                    continue

                method = args["method"]
                endpoint = args["endpoint"]
                body = args.get("body")
                params = args.get("params")

                logger.info(
                    "Tool call: %s %s body=%s params=%s",
                    method, endpoint,
                    _truncate(json.dumps(body, ensure_ascii=False)) if body else "null",
                    _truncate(json.dumps(params, ensure_ascii=False)) if params else "null",
                )

                api_calls += 1
                try:
                    result = self._execute_api_call(method, endpoint, body, params)
                    result_str = json.dumps(result, ensure_ascii=False)
                    logger.info("API response: %s", _truncate(result_str))
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": result_str,
                    })
                except TripletexAPIError as e:
                    # Retry once on 403 (token may be temporarily invalid)
                    if e.status_code == 403:
                        logger.warning("Got 403, retrying once...")
                        time.sleep(1)
                        try:
                            result = self._execute_api_call(method, endpoint, body, params)
                            result_str = json.dumps(result, ensure_ascii=False)
                            logger.info("API response (retry): %s", _truncate(result_str))
                            messages.append({
                                "role": "tool",
                                "tool_call_id": tool_call.id,
                                "content": result_str,
                            })
                            continue
                        except TripletexAPIError:
                            pass  # Fall through to normal error handling
                    errors += 1
                    error_dict = {"error": str(e)}
                    if e.status_code == 422:
                        schema_hint = get_endpoint_schema(method, endpoint)
                        if schema_hint:
                            error_dict["schema_hint"] = schema_hint
                    error_msg = json.dumps(error_dict, ensure_ascii=False)
                    logger.warning("API error: %s", error_msg)
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": error_msg,
                    })

        # Max iterations reached
        duration = time.time() - start_time
        logger.warning(
            "[%s] Agent reached max iterations (%d). recipe=%s, api_calls=%d, errors=%d, doc_searches=%d, duration=%.2fs",
            task_id, MAX_ITERATIONS, recipe_letter or "?", api_calls, errors, doc_searches, duration,
        )

    def _execute_api_call(
        self, method: str, endpoint: str, body: dict | None, params: dict | None
    ) -> dict:
        method = method.upper()
        if method == "GET":
            return self.client.get(endpoint, params=params)
        elif method == "POST":
            return self.client.post(endpoint, json=body)
        elif method == "PUT":
            return self.client.put(endpoint, json=body, params=params)
        elif method == "DELETE":
            return self.client.delete(endpoint)
        else:
            raise ValueError(f"Unsupported HTTP method: {method}")


def _truncate(s: str, max_len: int = 500) -> str:
    if len(s) > max_len:
        return s[:max_len] + "..."
    return s
