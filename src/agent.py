import json
import logging
import time
import uuid
from datetime import date

from src.api_docs import get_endpoint_schema, get_recipe_examples, get_recipe_schemas, search_api_docs, validate_and_correct_call
from src.vertex_auth import get_openai_client
from src.tripletex_client import TripletexAPIError, TripletexClient

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 25
TIME_BUDGET_SECONDS = 240  # Stop gracefully before 300s platform timeout

# Per-recipe iteration limits — simple tasks need fewer iterations
_RECIPE_MAX_ITERATIONS = {
    'A': 6, 'B': 12, 'C': 6, 'E': 6,      # Simple (B=12 for employment contracts)
    'D': 15, 'F': 10, 'G': 25, 'J': 10,    # Medium: 3-9 calls (D=15 for project+timesheet+supplier, G=25 for bank reconciliation with CSV)
    'H': 15, 'I': 20, 'K': 15, 'L': 15,    # Complex: 3-20 calls (I=20 for multi-correction vouchers)
    'M': 20, 'N': 25,                        # Complex: 4-25 calls
}

# Hardcoded model IDs — do NOT use env vars for these
_PRE_PARSE_MODEL = "google/gemini-2.5-pro"    # Smart model for task understanding + math setup
_EXECUTION_MODEL = "google/gemini-2.5-flash"  # Fast model for recipe execution

_PRE_PARSE_PROMPT = """You are a data extractor for a Tripletex accounting agent. Translate the incoming task prompt (may be in nb, nn, en, es, pt, de, fr) into structured English data. Extract only data — the agent has its own recipes for execution steps.

Output format (plain text):
TASK TYPE: <type>
RECIPE: <letter> (<name>)
COMPLEXITY: <simple|complex>

FIELDS:
- descriptive label: value

FILE DATA: <extracted data from attachments, or "(none)">

COMPLEXITY rules:
- simple: single entity creation, lookups, basic updates (A, B, C, E, simple D/F/J)
- complex: multi-step workflows, calculations, reconciliation, year-end closing, project lifecycle with invoicing (G, K with invoice, I, L, M, N, D with timesheet+supplier, multi-entity F)

Rules:
- Extract every value from the prompt — names, emails, dates, amounts, org numbers, addresses, account numbers, etc.
- Use descriptive labels (e.g. "email", "name", "address line 1"), preserve exact spelling and Norwegian characters (æ, ø, å)
- Map to one of these recipes:
  A(DEPARTMENT), B(EMPLOYEE), C(CUSTOMER/SUPPLIER), D(PROJECT), E(PRODUCT),
  F(CUSTOMER INVOICE — outgoing invoices to customers),
  G(PAYMENT — registering payment on existing invoice, including overdue + reminder fees),
  H(TRAVEL EXPENSE), I(VOUCHER/SUPPLIER INVOICE/JOURNAL ENTRY — incoming invoices, correction vouchers),
  J(CORRECTIONS — credit notes, payment reversals),
  K(TIMESHEET — logging hours, and invoicing based on hours),
  L(PAYROLL),
  M(LEDGER ANALYSIS — analyzing ledger data, comparing periods, creating projects/activities from analysis),
  N(YEAR-END CLOSING — depreciation, prepaid expense reversals, tax provisions, accruals)
- Recipe classification tips:
  · Supplier/vendor invoices (leverandørfakturaer) → Recipe I
  · Correction vouchers for ledger errors → Recipe I
  · Registering hours + invoicing → Recipe K
  · Project + hours + supplier costs (no invoicing) → Recipe D
  · Overdue invoices + reminder fees → Recipe G
- Include all file attachment data in FILE DATA section
- If the task involves arithmetic, add a MATH section with one expression per line using +, -, *, / and numbers:
  MATH:
  - invoice amount: 374900 * 0.75
  - total salary: 59600 + 12900"""

_CORE_RULES = """You are a Tripletex API agent. Complete accounting tasks via API calls. Keep going until the task is fully completed — every sub-task, every entity, every field.

## How to work
- The task has been pre-parsed into English with extracted fields. Use them as your data source.
- Follow the recipe below. Before each API call, think: what data do I need, and which endpoint provides it?
- When unsure about a field name or endpoint, use search_api_docs to look it up. Prefer using tools over guessing.

## Rules
1. Reuse POST/PUT responses directly — they contain the created ID. Move to the next step immediately.
2. Include every value from the task prompt. Every field is scored. Check the API fields section for correct field names.
3. Follow the recipe step by step. On error, read the message and fix in one retry.
4. GET returns {{values:[...]}}, POST/PUT returns {{value:{{...}}}}. Reuse returned IDs across steps.
5. Use today's date ({today}) when none is specified. Dates: YYYY-MM-DD. Addresses: {{addressLine1, postalCode, city}}.
6. Look up reference data once and reuse: GET /v2/ledger/vatType, GET /v2/invoice/paymentType, GET /v2/travelExpense/paymentType, GET /v2/travelExpense/costCategory — call each once with no filters, pick from response.
7. Every task requires at least one mutation call (POST/PUT/DELETE). Complete all mutations before finishing.
8. Preserve Norwegian characters (æ, ø, å) exactly as given.
9. Voucher postings: use "amountGross" and "amountGrossCurrency" (always the same value). Include "row" on every posting, starting at 1. Postings must balance (sum to zero).
10. Voucher endpoint: POST /v2/ledger/voucher. Always include "description" (required). Every voucher requires date + description + postings.
11. For supplier invoices: find incoming VAT by searching for "Inngående" in the vatType name (25% rate). The correct type has "Inngående" or "Fradrag" in its name.
12. After a successful POST/PUT, move to the next step immediately using the returned ID. NEVER GET an entity you just created — the response already contains all the data you need."""

_RECIPES = {
    'A': """## Recipe: DEPARTMENT [1 call]
POST /v2/department/list — send ALL departments as a JSON array in one call (e.g. [{"name":"X"},{"name":"Y"}]). This creates multiple departments in 1 API call. For a single department, still use /list with a 1-element array.""",

    'B': """## Recipe: EMPLOYEE [2-8 calls]
STEP 1: Department — if specific department named: GET /v2/department?name=X. If empty result, create it: POST /v2/department/list with [{"name":"X"}]. If no department named: GET /v2/department?fields=id&count=1 → use first.
STEP 2: POST /v2/employee — MUST include: firstName, lastName, userType:"STANDARD", department:{"id":deptId}, email, dateOfBirth (YYYY-MM-DD). Also include nationalIdentityNumber and bankAccountNumber if given.
STEP 3 (if start date/employment details given): First create division if needed: GET /v2/municipality?count=1 → POST /v2/division {"name":"Main","startDate":"2026-01-01","organizationNumber":"987654321","municipality":{"id":munId},"municipalityDate":"2026-01-01"} → divId. Then POST /v2/employee/employment {"employee":{"id":empId}, "startDate":"YYYY-MM-DD", "division":{"id":divId}, "employmentDetails":[{"date":"YYYY-MM-DD", "employmentType":"ORDINARY", "occupationCode":"STYRK_CODE", "percentageOfFullTimeEquivalent":100.0}]}. CRITICAL: employmentType, occupationCode, percentageOfFullTimeEquivalent go INSIDE the employmentDetails array, NOT as top-level fields. occupationCode is a plain string like "2512" (not an object). workingHoursScheme must be a string enum: "NOT_SHIFT", "ROUND_THE_CLOCK", "SHIFT_365", "OFFSHORE_336", or "CONTINUOUS" — omit if not specified. annualSalary goes inside employmentDetails too.""",

    'C': """## Recipe: CUSTOMER/SUPPLIER [1 call]
For suppliers: use POST /v2/supplier {name, organizationNumber, isSupplier:true}. For customers: use POST /v2/customer {name, organizationNumber, isCustomer:true}. For entities that are both customer and supplier: POST /v2/customer with isCustomer:true AND isSupplier:true. Include all fields from prompt — see API fields below for correct field names. For email: set both "email" and "invoiceEmail" to the given email address. For addresses: use "postalAddress":{addressLine1, postalCode, city}.""",

    'D': """## Recipe: PROJECT [3-15 calls]
CRITICAL: Fixed price field is "fixedprice" (ALL LOWERCASE) with "isFixedPrice":true. Using "fixedPriceAmount" or "fixedPrice" = 422 error.
STEP 1: GET /v2/employee?email=X → managerId. If multiple employees mentioned, look up each.
STEP 2: If customer mentioned: GET /v2/customer?organizationNumber=X → custId.
STEP 3: POST /v2/project with body: {"name":"X", "projectManager":{"id":managerId}, "startDate":"YYYY-MM-DD", "isFixedPrice":true, "fixedprice":amount, "customer":{"id":custId}}. Do NOT set "number" (auto-generated). Use today for startDate if not specified. For budget: set "fixedprice":budgetAmount even if not explicitly called fixed price.
STEP 4 (if timesheet hours to register): POST /v2/activity {"name":"General Project Activity", "activityType":"PROJECT_GENERAL_ACTIVITY", "isChargeable":true}. Then for EACH employee: POST /v2/timesheet/entry {"activity":{"id":actId}, "date":"YYYY-MM-DD", "employee":{"id":empId}, "hours":N, "project":{"id":projId}}.
STEP 5 (if supplier cost to register): GET /v2/supplier?organizationNumber=X → suppId. Then GET /v2/ledger/account?number=4300 (or relevant cost account). POST /v2/ledger/voucher (NOT /v2/voucher!) {"date":"YYYY-MM-DD", "description":"...", "postings":[{account:{id:costAcct}, amountGross:amount, amountGrossCurrency:amount, row:1}, {account:{id:payableAcct}, amountGross:-amount, amountGrossCurrency:-amount, row:2}]}.
STEP 6 (only if task says to invoice partial amount): GET /v2/ledger/account?isBankAccount=true → PUT /v2/ledger/account/{id} with {"bankAccountNumber":"12345678903"} → POST /v2/product → POST /v2/order with orderLines (unitPriceExcludingVatCurrency=partial amount) → PUT /v2/order/{id}/:invoice?invoiceDate=YYYY-MM-DD.""",

    'E': """## Recipe: PRODUCT [1-2 calls]
(1) If VAT mentioned: GET /v2/ledger/vatType → find match. (2) POST /v2/product — see API fields below.""",

    'F': """## Recipe: INVOICE [5-9 calls]
Set up the bank account (step 2) before creating the invoice (step 5) — invoice creation requires a configured bank.
STEP 1: GET /v2/customer?organizationNumber=X → custId.
STEP 2: GET /v2/ledger/account?isBankAccount=true → PUT /v2/ledger/account/{id} with body {"bankAccountNumber":"12345678903"} (11 digits).
STEP 3: Products — if product numbers given like "(1234)", GET /v2/product?number=1234 (they exist). Otherwise POST /v2/product with {name, priceExcludingVatCurrency}. If "without VAT"/"uten MVA"/"sans TVA"/"ohne MwSt", set vatType:{"id":6} on the product (exempt). For multiple new products, use POST /v2/product/list with array body.
STEP 4: POST /v2/order {"customer":{"id":custId}, "orderDate":"YYYY-MM-DD", "deliveryDate":"YYYY-MM-DD", "orderLines":[{"product":{"id":prodId}, "count":qty, "unitPriceExcludingVatCurrency":price}]}. Include both orderDate and deliveryDate. Use "count" for quantity.
STEP 5: PUT /v2/order/{orderId}/:invoice?invoiceDate=YYYY-MM-DD.
STEP 6 (if payment requested): GET /v2/invoice/paymentType (no filters) → find "Bankinnskudd" → PUT /v2/invoice/{invoiceId}/:payment with query params: paymentDate, paymentTypeId, paidAmount, paidAmountCurrency.""",

    'G': """## Recipe: PAYMENT [4-25 calls]
SINGLE PAYMENT: (1) GET /v2/customer?organizationNumber=X. (2) GET /v2/invoice?invoiceDateFrom=2000-01-01&invoiceDateTo=2030-12-31&customerId=X → id, amountOutstanding. (3) GET /v2/invoice/paymentType (no filters) → find "Bankinnskudd". (4) PUT /v2/invoice/{id}/:payment with QUERY PARAMS ONLY: paymentDate, paymentTypeId, paidAmount=amountOutstanding, paidAmountCurrency=amountOutstanding.
BANK RECONCILIATION (CSV file with multiple payments): Process EVERY CSV line — do not skip any. (1) GET /v2/invoice/paymentType ONCE → find "Bankinnskudd", reuse ID for all payments. (2) For each incoming payment: GET /v2/customer?name=X → GET /v2/invoice?customerId=X&invoiceDateFrom=2000-01-01&invoiceDateTo=2030-12-31 → PUT /v2/invoice/{id}/:payment. (3) For bank fees: GET /v2/ledger/account?number=7770 + GET /v2/ledger/account?number=1920, then ONE voucher combining all fees: POST /v2/ledger/voucher {date, description:"Bankgebyr", postings:[{account:{id:7770id}, amountGross:totalFees, amountGrossCurrency:totalFees, row:1}, {account:{id:1920id}, amountGross:-totalFees, amountGrossCurrency:-totalFees, row:2}]}.
REMINDER FEE + PARTIAL PAYMENT: (1) GET /v2/customer?organizationNumber=X → custId. (2) GET /v2/invoice?invoiceDateFrom=2000-01-01&invoiceDateTo=2030-12-31&customerId=custId → find the overdue invoice, note amountOutstanding and invoiceId. (3) GET /v2/invoice/paymentType → find "Bankinnskudd". (4) PUT /v2/invoice/{invoiceId}/:payment with partial amount. (5) GET /v2/ledger/account?number=1500 + GET /v2/ledger/account?number=3400. (6) POST /v2/ledger/voucher {"date":"YYYY-MM-DD", "description":"Purregebyr", "postings":[{account:{id:1500acct}, amountGross:feeAmount, amountGrossCurrency:feeAmount, customer:{id:custId}, row:1}, {account:{id:3400acct}, amountGross:-feeAmount, amountGrossCurrency:-feeAmount, row:2}]}. Reminder fee postings have no vatType — just account, amountGross, amountGrossCurrency, and row. (7) If task says to create invoice for the fee: POST /v2/product {name:"Purregebyr", priceExcludingVatCurrency:feeAmount} → POST /v2/order {"customer":{"id":custId}, "orderDate":"YYYY-MM-DD", "deliveryDate":"YYYY-MM-DD", "orderLines":[{"product":{"id":prodId}, "count":1, "unitPriceExcludingVatCurrency":feeAmount}]} → PUT /v2/order/{id}/:invoice?invoiceDate=YYYY-MM-DD. ALWAYS include orderDate and deliveryDate on the order.""",

    'H': """## Recipe: TRAVEL EXPENSE [3-8 calls]
(1) GET /v2/employee?email=X. (2) GET /v2/travelExpense/paymentType + GET /v2/travelExpense/costCategory (no filters). (3) POST /v2/travelExpense {employee:{id}, title, date, travelDetails:{departureDate, returnDate, destination, purpose, departureFrom}} — include travelDetails to create a proper travel expense report (without it, Tripletex creates an employee expense instead). (4) Per cost: POST /v2/travelExpense/cost — set isPaidByEmployee:true, link via travelExpense:{id}. (5) Accommodation: POST /v2/travelExpense/accommodationAllowance — include location. (6) Per diem: POST /v2/travelExpense/perDiemCompensation — include location. Create all items, then stop (no delivery/submission step needed). DELETE: GET /v2/travelExpense?employeeId=X → DELETE /v2/travelExpense/{id}.""",

    'I': """## Recipe: VOUCHER / SUPPLIER INVOICE [3-10 calls]
Every voucher posting uses "amountGross" and "amountGrossCurrency" (same value), plus "row" starting at 1. Postings must balance (sum to zero). Always include "description" on the voucher.

GENERAL JOURNAL ENTRY / LEDGER CORRECTION:
(1) GET /v2/ledger/account?number=XXXX for each account. ALWAYS look up accounts by number (not by name — name searches return hundreds of results and waste iterations). Look up each unique account number once, reuse IDs.
(2) POST /v2/ledger/voucher {"date":"YYYY-MM-DD", "description":"...", "postings":[{account:{id}, amountGross:X, amountGrossCurrency:X, row:1}, {account:{id}, amountGross:-X, amountGrossCurrency:-X, row:2}]}.
If DEPARTMENT mentioned: GET /v2/department?name=X → add department:{id} to each posting. For free accounting dimensions: use freeAccountingDimension1:{id} on the posting.
For MULTI-CORRECTION tasks (several errors to fix):
(1) Count all corrections mentioned in the task — you must create EXACTLY that many vouchers.
(2) Batch account lookups: GET /v2/ledger/account?number=XXXX for EVERY unique account number mentioned. Do all lookups FIRST, save IDs.
(3) Create one voucher per correction. Each voucher reverses the wrong posting and creates the correct one.
(4) If a department is mentioned for a correction, add department:{id} to EVERY posting in that voucher.
(5) Voucher date: use the date specified in the task, or today if none given.

SUPPLIER INVOICE (leverandørfaktura):
(1) GET /v2/supplier?organizationNumber=X. If not found: POST /v2/customer {name, organizationNumber, isSupplier:true, isCustomer:false}.
(2) GET /v2/ledger/account?number=EXPENSE_ACCT + GET /v2/ledger/account?number=2400.
(3) GET /v2/ledger/vatType → search the response for a vatType with "Inngående" in the name and 25% rate. This is the incoming/input VAT for purchases. Select that ID.
(4) GET /v2/ledger/voucherType?name=Leverandørfaktura.
(5) POST /v2/ledger/voucher {"date":"invoiceDate", "description":"invoice description", "vendorInvoiceNumber":"INV-XXX", "voucherType":{"id":vtId}, "postings":[
  {account:{id:expenseAcct}, amountGross:totalInclVat, amountGrossCurrency:totalInclVat, vatType:{id:incomingVatId}, supplier:{id:suppId}, row:1},
  {account:{id:acct2400}, amountGross:-totalInclVat, amountGrossCurrency:-totalInclVat, supplier:{id:suppId}, row:2}
]}
Both amountGross values use the TOTAL INCLUDING VAT. Set vatType only on the expense posting (row 1). Use "voucherType" for the type field.""",

    'J': """## Recipe: CORRECTIONS [2-4 calls]
CREDIT NOTE (invoice is wrong): GET /v2/invoice?invoiceDateFrom=2000-01-01&invoiceDateTo=2030-12-31&customerId=X → PUT /v2/invoice/{id}/:createCreditNote?date=YYYY-MM-DD (date >= invoiceDate).
PAYMENT REVERSAL (bank returned payment):
STEP 1: GET /v2/customer?organizationNumber=X → custId.
STEP 2: GET /v2/invoice?invoiceDateFrom=2000-01-01&invoiceDateTo=2030-12-31&customerId=custId → invoiceId.
STEP 3: GET /v2/ledger/voucher?dateFrom=2000-01-01&dateTo=2030-12-31 — search all vouchers (no other filters).
STEP 4: Find vouchers with "Betaling" or "Payment" or "Innbetaling" in description → DELETE each payment voucher via DELETE /v2/ledger/voucher/{id}. Keep invoice vouchers, delete only payment vouchers. Multiple payment vouchers may exist — delete all of them.
GET /v2/invoice always requires invoiceDateFrom and invoiceDateTo params.""",

    'K': """## Recipe: TIMESHEET [4-14 calls]
If the task mentions "invoice" or "faktura", complete all steps through step 8.
STEP 1: GET /v2/employee?email=X → employeeId.
STEP 2: GET /v2/project?name=X → projectId, note startDate and customer. If project needs creation: POST /v2/project {"name":"X", "customer":{"id":custId}, "projectManager":{"id":empId}, "startDate":"YYYY-MM-DD", "isFixedPrice":true, "fixedprice":amount}.
STEP 3: GET /v2/activity?name=X — if not found, POST /v2/activity {"name":"X", "activityType":"PROJECT_GENERAL_ACTIVITY", "isChargeable":true}.
STEP 4: POST /v2/timesheet/entry {"employee":{"id":empId}, "project":{"id":projId}, "activity":{"id":actId}, "date":"YYYY-MM-DD", "hours":N}. Use project startDate for date. For multiple timesheet entries, use POST /v2/timesheet/entry/list with array body.
STEP 4b (if supplier cost, do before invoicing): GET /v2/supplier?organizationNumber=X → suppId. GET /v2/ledger/account?number=4300 + GET /v2/ledger/account?number=2400. POST /v2/ledger/voucher {"date":"YYYY-MM-DD", "description":"Supplier cost...", "postings":[{account:{id:4300_id}, amountGross:amount, amountGrossCurrency:amount, row:1}, {account:{id:2400_id}, amountGross:-amount, amountGrossCurrency:-amount, row:2}]}.
STEP 5 (invoicing): GET /v2/ledger/account?isBankAccount=true → PUT /v2/ledger/account/{id} with {"bankAccountNumber":"12345678903"}.
STEP 6: POST /v2/product with name and price (use hourly rate from task).
STEP 7: POST /v2/order {"customer":{"id":custId}, "orderDate":"YYYY-MM-DD", "deliveryDate":"YYYY-MM-DD", "orderLines":[{"product":{"id":prodId}, "count":hours, "unitPriceExcludingVatCurrency":hourlyRate}]}.
STEP 8: PUT /v2/order/{orderId}/:invoice?invoiceDate=YYYY-MM-DD.""",

    'L': """## Recipe: PAYROLL [5-9 calls]
STEP 1: GET /v2/employee?email=X → check dateOfBirth. If null: PUT /v2/employee/{id} with {"dateOfBirth":"1990-01-01"}.
STEP 2: Employee needs employment with division. If no employment: GET /v2/municipality?count=1 → POST /v2/division {"name":"Main", "startDate":"2026-01-01", "organizationNumber":"987654321", "municipality":{"id":munId}, "municipalityDate":"2026-01-01"} → POST /v2/employee/employment {"employee":{"id":empId}, "division":{"id":divId}, "startDate":"2026-03-01"}.
STEP 3: GET /v2/ledger/account?number=5000 + GET /v2/ledger/account?number=2920.
STEP 4: POST /v2/ledger/voucher with body:
{"date":"YYYY-MM-01", "description":"Lønn <month> <year>", "postings":[
  {"account":{"id":acct5000Id}, "amountGross":baseSalary, "amountGrossCurrency":baseSalary, "row":1},
  {"account":{"id":acct5000Id}, "amountGross":bonus, "amountGrossCurrency":bonus, "row":2},
  {"account":{"id":acct2920Id}, "amountGross":-(baseSalary+bonus), "amountGrossCurrency":-(baseSalary+bonus), "row":3}
]}
Debit 5000 (salary expense), credit 2920 (payable). Postings must balance (sum to zero). Use ledger/voucher for payroll — salary/transaction is not needed.""",

    'M': """## Recipe: LEDGER ANALYSIS [4-10 calls]
For tasks requiring analysis of ledger/accounting data, comparing periods, or finding specific accounts.
(1) GET /v2/balanceSheet?dateFrom=YYYY-MM-01&dateTo=YYYY-MM-DD&accountNumberFrom=4000&accountNumberTo=7999 for EACH period to compare. Cost/expense accounts are 4000-7999. This returns aggregated balances per account — no need to sum postings manually.
(2) Compare the results: match accounts by number, calculate differences between periods, identify the top N accounts as requested. Each entry has {account:{number,name}, balanceIn, balanceChange, balanceOut}. Use "balanceChange" for comparison.
(3) GET /v2/employee?count=1 → get any employee as project manager (required even for internal projects).
(4) Create requested entities based on analysis results. For internal projects: POST /v2/project {name:accountName, isInternal:true, projectManager:{id}, startDate:"YYYY-MM-DD"}. For activities: POST /v2/activity {name:activityName, activityType:"PROJECT_GENERAL_ACTIVITY", isChargeable:true}. Use POST /v2/project/list and POST /v2/activity/list for batch creation (send arrays: [{...},{...}]).
IMPORTANT: The field for activity type is "activityType" (not "type"). Parse balanceSheet carefully — compare same accounts across periods to find increases/decreases.""",

    'N': """## Recipe: YEAR-END CLOSING [8-25 calls]
Complete every sub-task — each depreciation, prepaid reversal, and provision gets its own voucher. Use COMPUTED AMOUNTS from the pre-parser for calculated values.
(1) Look up ALL accounts in as few calls as possible. GET /v2/ledger/account?number=XXXX for each unique account number. Save all IDs for reuse — look up each account ONLY ONCE.
(2) DEPRECIATION: One voucher per asset. POST /v2/ledger/voucher {date:"YYYY-12-31", description:"Avskrivning <asset>", postings:[{account:{id:depreciationExpenseAcct}, amountGross:amount, amountGrossCurrency:amount, row:1}, {account:{id:accumDepreciationAcct}, amountGross:-amount, amountGrossCurrency:-amount, row:2}]}. If accumulated depreciation account not specified, try asset_number+9 (e.g. 1200→1209).
(3) PREPAID EXPENSES: Debit expense account, credit prepaid account (1700/1720). One voucher per reversal.
(4) SALARY/OTHER PROVISIONS: Post each provision as a separate voucher. If amount not given, derive from context or COMPUTED AMOUNTS.
(5) TAX PROVISION: GET /v2/balanceSheet?dateFrom=YYYY-01-01&dateTo=YYYY-12-31 → compute taxable profit → tax = profit × rate. Debit 8700, credit 2920.
Every posting: amountGross + amountGrossCurrency (same value), row starting at 1. Use period end date on all vouchers.""",
}

_ACTION = """## Action
Start the first API call now. Continue making calls until every part of the task is done — every entity created, every field set, every sub-task completed. On 403 errors, retry once (transient). If a step fails, fix it and continue with the remaining steps."""

# Full recipes block for fallback when pre-parse fails
_ALL_RECIPES = "## Recipes\n\n" + "\n\n".join(_RECIPES.values())


def get_system_prompt(recipe_letter: str | None = None) -> str:
    """Build system prompt, focused on a single recipe if letter is provided."""
    today = date.today().isoformat()
    rules = _CORE_RULES.format(today=today)

    if recipe_letter and recipe_letter in _RECIPES:
        recipe = _RECIPES[recipe_letter]
        schema = get_recipe_schemas(f"RECIPE: {recipe_letter}")
        examples = get_recipe_examples(recipe_letter)
        parts = [rules, recipe]
        if schema:
            parts.append(schema)
        if examples:
            parts.append(examples)
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
        self.model = model  # Kept for backward compat but not used — models are hardcoded
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
                model=_PRE_PARSE_MODEL,
                messages=[
                    {"role": "system", "content": _PRE_PARSE_PROMPT},
                    {"role": "user", "content": user_input},
                ],
                temperature=0,
                timeout=45,
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
        logger.info("[%s] Models: pre-parse=%s", task_id, _PRE_PARSE_MODEL)
        errors = 0
        doc_searches = 0
        logger.info("[%s] Starting agent for prompt: %s", task_id, _truncate(prompt, 200))

        # Pre-parse the task prompt
        parsed_plan = self._pre_parse(prompt)

        # Extract recipe letter for logging and future dynamic prompt assembly
        recipe_letter = None
        if parsed_plan:
            match = _re.search(r'RECIPE:\s*([A-N])', parsed_plan)
            if match:
                recipe_letter = match.group(1)

            # Override: supplier invoices misclassified as Recipe F → I
            if recipe_letter == 'F':
                plan_lower = parsed_plan.lower()
                if any(kw in plan_lower for kw in ['supplier', 'leverandør', 'inngående', 'vendor', 'fournisseur', 'lieferant', 'proveedor']):
                    recipe_letter = 'I'
                    logger.info("[%s] Override: F → I (supplier invoice detected)", task_id)

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

        # Dynamic model selection based on recipe complexity
        # Hardcoded — don't trust LLM to judge complexity correctly
        _COMPLEX_RECIPES = {'F', 'G', 'I', 'K', 'L', 'M', 'N'}
        is_complex = recipe_letter in _COMPLEX_RECIPES
        execution_model = _PRE_PARSE_MODEL if is_complex else _EXECUTION_MODEL
        logger.info("[%s] Complexity: %s (recipe=%s), execution model: %s",
                    task_id, "complex" if is_complex else "simple", recipe_letter or "?", execution_model)

        # Dynamic iteration limit based on recipe complexity
        max_iters = _RECIPE_MAX_ITERATIONS.get(recipe_letter, MAX_ITERATIONS) if recipe_letter else MAX_ITERATIONS

        messages = [
            {"role": "system", "content": get_system_prompt(recipe_letter)},
            {"role": "user", "content": user_message},
        ]

        for iteration in range(1, max_iters + 1):
            # Time budget check — stop before platform kills us
            elapsed = time.time() - start_time
            if elapsed > TIME_BUDGET_SECONDS:
                logger.warning("[%s] Time budget exceeded (%.0fs > %ds), stopping gracefully",
                             task_id, elapsed, TIME_BUDGET_SECONDS)
                break

            # Adaptive model downgrade: switch Pro→Flash if running out of time
            if execution_model == _PRE_PARSE_MODEL and iteration > 10 and elapsed > 150:
                execution_model = _EXECUTION_MODEL
                logger.info("[%s] Downgrading to Flash (iteration %d, %.0fs elapsed)", task_id, iteration, elapsed)

            # Context pruning: compress old tool results to save tokens
            if iteration > 8 and len(messages) > 10:
                for i in range(2, len(messages) - 6):
                    if messages[i].get("role") == "tool":
                        content = messages[i]["content"]
                        if len(content) > 200:
                            messages[i]["content"] = content[:100] + "... [truncated, see above for details]"

            logger.info("Agent iteration %d/%d (%.0fs elapsed)", iteration, max_iters, elapsed)

            # Select tools based on recipe — simple recipes never need doc search
            _NO_DOCSEARCH_RECIPES = {'A', 'C', 'E'}
            iter_tools = [CALL_API_TOOL] if recipe_letter in _NO_DOCSEARCH_RECIPES else [CALL_API_TOOL, SEARCH_API_DOCS_TOOL]

            try:
                response = self.openai.chat.completions.create(
                    model=execution_model,
                    messages=messages,
                    tools=iter_tools,
                    temperature=0,
                    timeout=45,
                )
            except Exception as timeout_err:
                if "timeout" in str(timeout_err).lower() or "timed out" in str(timeout_err).lower():
                    logger.warning("[%s] LLM timeout, truncating context and retrying", task_id)
                    # Keep system + user + last 4 messages
                    messages = messages[:2] + messages[-4:]
                    if execution_model == _PRE_PARSE_MODEL:
                        execution_model = _EXECUTION_MODEL  # Downgrade to Flash
                    response = self.openai.chat.completions.create(
                        model=execution_model,
                        messages=messages,
                        tools=iter_tools,
                        temperature=0,
                        timeout=45,
                    )
                else:
                    raise

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
                    doc_search_limit = 1 if recipe_letter in {'A', 'B', 'C', 'E', 'J'} else 2
                    logger.info("Docs search: %s (count=%d, limit=%d)", query, doc_searches, doc_search_limit)
                    if doc_searches > doc_search_limit:
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

                # Pre-call validation: auto-correct field names and endpoints
                validation = validate_and_correct_call(method, endpoint, body)
                if validation.was_modified:
                    if validation.corrected_endpoint:
                        endpoint = validation.corrected_endpoint
                    if validation.corrected_body is not None:
                        body = validation.corrected_body
                    for w in validation.warnings:
                        logger.info("[%s] Auto-fix: %s", task_id, w)

                api_calls += 1
                try:
                    result = self._execute_api_call(method, endpoint, body, params)

                    # Truncate large GET responses to save context
                    # Exception: never truncate vatType, paymentType, costCategory — agent needs full list to find correct type
                    _NEVER_TRUNCATE = ("vatType", "paymentType", "costCategory")
                    if method == "GET" and isinstance(result, dict) and "values" in result:
                        vals = result["values"]
                        if len(vals) > 15 and not any(nt in endpoint for nt in _NEVER_TRUNCATE):
                            result["values"] = vals[:15]
                            result["_note"] = f"Showing 15 of {len(vals)}. Filter with query params for specific results."

                    result_str = json.dumps(result, ensure_ascii=False)

                    # Programmatic vatType extraction — find incoming VAT ID for supplier invoices
                    if method == "GET" and "ledger/vatType" in endpoint:
                        values = result.get("values", [])
                        incoming = [v for v in values
                                    if any(kw in v.get("name", "").lower() for kw in ["inngående", "fradrag"])
                                    and v.get("percentage", 0) == 25.0]
                        if incoming:
                            best = incoming[0]
                            result_str += f'\n>>> INCOMING VAT FOR SUPPLIER INVOICES: Use vatType id:{best["id"]} ("{best["name"]}", {best["percentage"]}%). Do NOT use Utgående (output) VAT types.'
                        else:
                            result_str += '\nFor supplier invoices: use the vatType with "Fradrag" or "Inngående" in the name (incoming VAT). Output VAT ("Utgående") is for sales, not purchases.'

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
                    # Bank account "in use" race condition — treat as success
                    if e.status_code == 422 and ("kontonummer" in str(e).lower() or "i bruk" in str(e).lower()):
                        result_str = json.dumps({"value": {"id": 1, "message": "Bank account already configured"}})
                        logger.info("[%s] Bank account race condition — treating as success", task_id)
                        messages.append({
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": result_str,
                        })
                        continue

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

        # Max iterations or time budget reached
        duration = time.time() - start_time
        logger.warning(
            "[%s] Agent stopped (max_iters=%d). recipe=%s, api_calls=%d, errors=%d, doc_searches=%d, duration=%.2fs",
            task_id, max_iters, recipe_letter or "?", api_calls, errors, doc_searches, duration,
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
