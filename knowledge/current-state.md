# Current State (2026-03-20 evening)

## Latest Deployment
- **Revision**: tripletex-agent-00028-kd2
- **Model**: Gemini 2.5 Pro (google/gemini-2.5-pro)
- **Service URL**: https://tripletex-agent-rzkmnmpmpq-lz.a.run.app/solve

## What Changed Today (chronological)

### Session 1 (~13:40-14:00): Payment reversal + efficiency
- Added payment reversal workflow (separate from credit note)
- Clarified payment workflow to avoid filter params on payment type lookup
- Reordered order-invoice workflow to defer bank account setup
- Enhanced API call minimization rules

### Session 2 (~14:00-14:10): Product creation + test expansion
- Product creation logic clarified to prevent duplicates
- Added tuning tests for: invoice with existing products, payment reversal, order invoice payment

### Session 3 (~14:00-15:00): Workflow condensation + model upgrade
- Condensed all workflow docs (order+invoice, payment reversal, supplier invoice) to terse format
- 4 previously failing tests started passing after condensation
- Researched Gemini 3 Flash (restricted), settled on Gemini 2.5 Pro
- Switched from Flash to Pro: 75% → 90% tuning test pass rate
- Deployed revision 00016 with Gemini 2.5 Pro

### Session 4 (~15:00-17:00): Pre-parser architecture
- Designed and implemented pre-parsing phase for multilingual prompts
- Pre-parser translates + classifies, executor follows recipe
- Deployed revision 00018 with pre-parser

### Session 5 (~18:00-19:00, this conversation): Schema-driven architecture
- Added `RECIPE_ENDPOINTS` + `get_recipe_schemas()` to api_docs.py
- Proactive OpenAPI schema injection before agent makes calls
- Dynamic today's date in system prompt
- Simplified recipe field listings (schemas provide fields now)
- Compact schema format (72% smaller than verbose format)
- All deployed as revision 00025

### Session 5 continued (~19:00-20:30): Dynamic focused prompt
- Split `_SYSTEM_PROMPT` into `_CORE_RULES` + `_RECIPES` dict + `_ACTION`
- `get_system_prompt(recipe_letter)` assembles focused prompt with only matched recipe
- System prompt: 7726 chars → 2000-3400 chars (55-75% reduction)
- Recipe letter logged in agent summary for production debugging
- Deployed as revision 00027

### Session 5 continued (~20:30): Travel expense fix
- Fixed Recipe H: `travelDetails` MUST be included or Tripletex creates wrong entity type
- Deployed as revision 00028

## Latest Submission Results (revision 00027, ~19:29 UTC)
- Payment: 7/7 (100%) - recipe G
- Invoice (2 products): 7/7 (100%) - recipe F
- Fixed price project: 6/8 (75%) - recipe F, bank account race
- Product: 8/8 (100%) - recipe E
- Travel expense #1: 8/8 (100%) - recipe H
- Travel expense #2: 0/8 (0%) - recipe H, travelDetails missing → FIXED in 00028
- Invoice (3 products): likely good - recipe F

## Known Remaining Issues
1. **fixedprice casing**: Agent sometimes uses `fixedPrice` (camelCase) instead of `fixedprice` (all lowercase). Flaky ~50%.
2. **Bank account race**: Concurrent tasks on same sandbox can conflict on bank account setup. Not easily fixable.
3. **Voucher row field**: Much improved with dynamic prompt, but may still occasionally miss on first attempt.
4. **Tuning test flakiness**: 26-30/32 pass per run. LLM non-determinism causes 2-6 random failures.

## Uncommitted Changes
Check `git status` — there may be uncommitted changes from the latest fixes.
