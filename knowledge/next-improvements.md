# Next Improvements to Investigate

## High Priority (Score Impact)

### 1. fixedprice Casing Issue
- Agent sometimes sends `fixedPrice` (camelCase) instead of `fixedprice` (all lowercase)
- The OpenAPI schema lists it beyond the 20-field cap, so the compact schema doesn't show it
- Options: (a) hardcode `fixedprice` in the compact schema filter, (b) increase cap for project endpoint, (c) rely on recipe text (already says lowercase)

### 2. Batch Endpoints
- `POST /v2/product/list` could create multiple products in one call
- `POST /v2/timesheet/entry/list` for multiple timesheet entries
- Would improve efficiency scores on multi-entity tasks

### 3. Bank Account Race Condition
- Concurrent submissions on same sandbox both try to set bank account number
- Second one fails with "kontonummeret er i bruk"
- Possible fix: check if bank account already has a number before PUT

## Medium Priority (Robustness)

### 4. Pre-Parser Misclassification
- Monitor logs for recipe mismatches (compare pre-parser recipe vs actual task)
- Common confusion: supplier invoice (I) vs customer invoice (F)
- Fix by improving _PRE_PARSE_PROMPT examples

### 5. Travel Expense Sub-Types
- Current recipe handles costs, per diem, accommodation
- Mileage allowance not yet in recipe
- May need to add if competition includes it

### 6. Tier 3 Tasks
- Opens early Saturday
- These are complex multi-step workflows worth up to 6.0 points
- Need to analyze what they look like and add recipes

## Low Priority (Polish)

### 7. Call Count Optimization
- Some recipes use more calls than necessary
- E.g., Recipe F fetches bank account even when not invoicing
- Tighten tuning test budgets to drive efficiency

### 8. Error Message Parsing
- Agent sometimes searches docs after a 422 instead of reading the error message
- The error message usually tells exactly what's wrong
- Rule 4 already says "read error message and fix in ONE retry"
