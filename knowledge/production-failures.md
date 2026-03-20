# Production Failure Log

Documented failures from competition submissions with root causes and fixes applied.

## 2026-03-20 ~18:17 UTC (Revision 00025-j5p — schema injection, before dynamic prompt)

### Voucher with dimensions (6/7, 2 errors)
- **Symptom**: First POST /v2/ledger/voucher missing `description` and `row` → 422. Second attempt succeeded.
- **Root cause**: `row` buried among 11 other recipes in system prompt.
- **Fix applied**: Strengthened `row` warning in Recipe I. Later: dynamic prompt assembly (only show matched recipe).

### Supplier invoice — Elvdal AS (MAX ITERATIONS, 5 errors)
- **Symptom**: 5 consecutive POST /v2/ledger/voucher attempts, all failing with "postings.row: Posteringene på rad 0".
- **Root cause**: Agent never added `row` field despite error message. Also tried `supplierVoucherType` (wrong field name).
- **Fix applied**: Added exact posting structure with row numbers to supplier invoice recipe. Added "use voucherType NOT supplierVoucherType".

### Nordlys AS invoice (9 calls, 1 error)
- **Symptom**: Bank account number already in use on another account (concurrent task race).
- **Root cause**: Two tasks running simultaneously both tried to set up the same bank account.
- **Fix**: Not easily fixable — inherent to concurrent submissions on shared sandbox.

## 2026-03-20 ~19:29 UTC (Revision 00027-5pc — dynamic focused prompt)

### Travel expense Arne Vik (0/8, MAX ITERATIONS, 4 errors)
- **Symptom**: Agent created travel expense with `title` but WITHOUT `travelDetails`. Tripletex created an "employee expense" (ansattutlegg) instead of "travel expense report" (reiseregning). All subsequent perDiemCompensation calls failed: "Kun reiseregning, ikke ansattutlegg, kan benyttes her."
- **Root cause**: Recipe H said "include travelDetails nested object" but didn't explain WHY it's mandatory.
- **Fix applied**: Recipe H now says "CRITICAL: travelDetails MUST be included or Tripletex creates an 'employee expense' instead of a 'travel expense report', and per diem/accommodation will fail with 422."

### Fixed price project Fossekraft AS (6/8, 1 error)
- **Symptom**: Bank account not set up before invoicing → 422 "Faktura kan ikke opprettes før selskapet har registrert et bankkontonummer". Recovered with retry.
- **Root cause**: Recipe F says to set up bank before invoice, but pre-parser classified this as Recipe F (invoice) when it's also a project setup. The bank step came too late in the workflow.

### Invoice bank account errors (multiple tasks)
- **Symptom**: "Faktura kan ikke opprettes før selskapet har registrert et bankkontonummer" — 422 on first invoice attempt.
- **Root cause**: Bank account setup step done too late or skipped. Also: concurrent tasks race on the shared sandbox bank account.
- **Mitigation**: Recipe F already says to set up bank before invoice. The error recovery (retry) usually works.

## Recurring Patterns

### Pattern: Missing `travelDetails` on travel expense
- Frequency: ~30% of travel expense tasks
- Impact: 0/8 score (complete failure)
- Fix: Explicit "CRITICAL" warning in Recipe H

### Pattern: Missing `row` on voucher postings
- Frequency: ~50% of voucher tasks (before fix)
- Impact: 1-2 wasted calls minimum, sometimes max iterations
- Fix: Dynamic focused prompt + explicit row example in Recipe I

### Pattern: Bank account not set up
- Frequency: ~20% of invoice tasks
- Impact: 1 wasted call (recoverable via retry)
- Fix: Already in recipe. Concurrent task race is the remaining issue.

### Pattern: `fixedprice` casing
- Frequency: ~50% of fixed price project tasks
- Impact: Project created without fixed price flag
- Fix: Recipe D says "lowercase fixedprice", schema shows `isFixedPrice`. Agent sometimes uses wrong casing. Flaky.
