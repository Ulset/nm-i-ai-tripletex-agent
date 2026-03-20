# Recipes Reference

The 12 recipes map task types to API workflows. Each recipe is stored in `_RECIPES` dict in `src/agent.py`.

## Recipe → Task Type Mapping

| Letter | Name | Calls | What It Does |
|--------|------|-------|--------------|
| A | DEPARTMENT | 1 | POST /v2/department |
| B | EMPLOYEE | 2-3 | GET department → POST employee → POST employment |
| C | CUSTOMER/SUPPLIER | 1 | POST customer or supplier |
| D | PROJECT | 3-4 | GET employee → GET customer → POST project. Optional: invoice partial |
| E | PRODUCT | 1-2 | Optional GET vatType → POST product |
| F | INVOICE | 5-9 | GET customer → GET/POST products → bank setup → POST order → invoice → optional payment |
| G | PAYMENT | 4 | GET customer → GET invoice → GET paymentType → PUT payment |
| H | TRAVEL EXPENSE | 3-8 | GET employee → GET paymentType/costCategory → POST travelExpense → POST costs/per diem/accommodation |
| I | VOUCHER | 3-8 | GET accounts → POST voucher. Sub-types: dimensions, supplier invoice |
| J | CORRECTIONS | 2-4 | Credit note (PUT createCreditNote) or payment reversal (DELETE vouchers) |
| K | TIMESHEET | 4-14 | GET employee → GET project → GET/POST activity → POST timesheet entry → optional invoice |
| L | PAYROLL | 3-8 | GET employee → ensure employment/division → GET salary types → POST salary transaction |

## Pre-Parser Classification

The pre-parser maps incoming prompts to recipes. Common confusions:
- **Supplier invoice → Recipe I** (NOT F). F is for customer invoices (outgoing). This is the #1 misclassification risk.
- **Payment reversal → Recipe J** (delete vouchers, NOT createCreditNote)
- **Credit note → Recipe J** (createCreditNote, NOT delete vouchers)

## Recipe-Specific Gotchas

### Recipe I (Voucher) — THE HARDEST
- EVERY posting MUST have `row` field starting at 1 (NOT 0). Omitting row = instant 422.
- Use `amountGross` + `amountGrossCurrency` (same value). NEVER "amount", "isDebit", "debit", "credit".
- `description` on the voucher is REQUIRED.
- Supplier invoice: use `voucherType` (NOT `supplierVoucherType`). Get it via `GET /v2/ledger/voucherType?name=Leverandørfaktura`.

### Recipe H (Travel Expense)
- `travelDetails` MUST be included in POST /v2/travelExpense or Tripletex creates an "employee expense" (ansattutlegg) instead of a "travel expense report" (reiseregning). Per diem and accommodation only work on travel expense reports.
- Per diem and accommodation MUST include `location`.

### Recipe D (Project)
- Do NOT set `number` — it's auto-generated.
- Fixed price: use `fixedprice` (all lowercase, NOT `fixedPriceAmount` or `fixedPrice`).
- Set `isFixedPrice: true` alongside `fixedprice`.

### Recipe F (Invoice)
- Bank account MUST be set up before creating invoice: GET /v2/ledger/account?isBankAccount=true → PUT with bankAccountNumber:"12345678903" (11 digits).
- Order MUST include both `orderDate` AND `deliveryDate`.
- OrderLine price field is `unitPriceExcludingVatCurrency` (NOT `priceExcludingVatCurrency`).
- Use `count` not `quantity`.

### Recipe G (Payment)
- PUT /v2/invoice/{id}/:payment uses QUERY PARAMS ONLY, no body.
