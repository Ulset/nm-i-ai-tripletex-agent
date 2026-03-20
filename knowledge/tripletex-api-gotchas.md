# Tripletex API Gotchas

Hard-won knowledge from production failures. These are things that are NOT obvious from the API docs.

## Authentication
- Basic Auth: username `0`, password = session token
- `base_url` is a proxy URL (tx-proxy.ainm.no) — all calls go through it
- TripletexClient auto-strips /v2 when base_url already has it
- 403 errors are sometimes transient — retry once

## Entity Creation

### Employee
- `userType` MUST be "STANDARD" (not 0, not empty)
- `department:{id}` is required — GET a department first
- `dateOfBirth` is required BEFORE creating employment
- Employment is a SEPARATE entity — POST /v2/employee/employment, not a field on employee

### Customer/Supplier
- `organizationNumber` must be digits only (9-digit Norwegian org numbers)
- `postalAddress` must be an object `{addressLine1, postalCode, city}`, NOT a string
- Supplier: set `isSupplier: true`

### Project
- `number` is auto-generated — do NOT set it
- `fixedprice` is all lowercase (NOT `fixedPriceAmount`, NOT `fixedPrice`)
- Set `isFixedPrice: true` alongside `fixedprice`

### Order
- `orderLines` price field is `unitPriceExcludingVatCurrency` (NOT `priceExcludingVatCurrency`)
- Use `count` (NOT `quantity`)
- MUST include both `orderDate` AND `deliveryDate`

### Invoice
- Bank account MUST be set up before creating invoice
- `PUT /v2/order/{id}/:invoice?invoiceDate=YYYY-MM-DD` (query param, not body)
- GET /v2/invoice requires both `invoiceDateFrom` AND `invoiceDateTo`

### Payment
- `PUT /v2/invoice/{id}/:payment` uses QUERY PARAMS ONLY (paymentDate, paymentTypeId, paidAmount, paidAmountCurrency)
- Get payment type via `GET /v2/invoice/paymentType` (no filters), find "Bankinnskudd"

### Travel Expense
- `travelDetails` nested object MUST be included on POST /v2/travelExpense
- Without `travelDetails`, Tripletex creates an "employee expense" (ansattutlegg) instead of "travel expense report" (reiseregning)
- Per diem and accommodation ONLY work on travel expense reports
- Per diem and accommodation MUST include `location`
- Cost categories and payment types: GET without filters, pick from full list

### Voucher/Journal Entry
- EVERY posting MUST have `row` starting at 1 (NOT 0)
- Use `amountGross` AND `amountGrossCurrency` (same value) — NEVER "amount", "isDebit", "debit", "credit"
- `description` on the voucher is required
- Postings must balance (sum to zero)

### Supplier Invoice (via Voucher)
- Use `voucherType:{id}` (NOT `supplierVoucherType`)
- Get voucher type via `GET /v2/ledger/voucherType?name=Leverandørfaktura`
- Set `vendorInvoiceNumber` on the voucher

### Salary/Payroll
- Employee must have `dateOfBirth`, employment, and employment must have a division
- MUST include `year` field on salary transaction
- Use fiscal year 2026
- Do NOT use vouchers for payroll

## Response Shapes
- GET returns `{"fullResultSize": N, "values": [...]}`
- POST/PUT returns `{"value": {...}}`
- Created entity ID is in the response — don't GET after POST

## VAT Types
- Endpoint: `GET /v2/ledger/vatType` (NOT `/v2/product/vatType`)
- ID 3 = 25% (standard/høy sats, utgående)
- ID 6 = 0% (exempt/fritatt)
