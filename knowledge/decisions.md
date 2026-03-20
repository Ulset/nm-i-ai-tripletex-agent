# Key Design Decisions

## 1. ReAct over Plan-Then-Execute
**Decision**: Agent uses ReAct pattern (observe → decide → act → repeat), NOT upfront planning.
**Why**: Plan-then-execute was tried and failed because the LLM can't predict API response shapes, required fields, or IDs without seeing actual data. The ReAct loop sees real responses and adapts.
**Date**: Early in competition, before 2026-03-20.

## 2. Pre-Parser (Lightweight Classification + Translation)
**Decision**: Add a separate LLM call before the ReAct loop that translates multilingual prompts to English and identifies the recipe letter.
**Why**: The agent was failing on novel tasks because it had to simultaneously parse 7 languages, identify task type, extract fields, AND execute API calls. Separating translation/classification from execution reduced cognitive load.
**Constraints**: Pre-parser is intentionally simple — it does NOT generate API call sequences or field mappings. That would reintroduce plan-then-execute brittleness.
**Date**: 2026-03-20 ~17:00.

## 3. Dynamic Focused Prompt Assembly
**Decision**: System prompt contains only the matched recipe (not all 12).
**Why**: Production evidence showed voucher tasks failing because `row` was buried among 11 irrelevant recipes. Reducing prompt from ~7700 to ~2000-3400 chars improved signal-to-noise.
**Trust model**: Trust the pre-parser. If it misclassifies, fix the pre-parser — don't add fallback recipes.
**Fallback**: If pre-parse fails entirely (returns None), fall back to full prompt with all recipes.
**Date**: 2026-03-20 ~20:00.

## 4. Compact Schema Injection (Dynamic from OpenAPI)
**Decision**: Inject field names from the real OpenAPI spec, NOT hardcoded field lists.
**Why**: Hardcoded field lists were always incomplete. With 30 task types × 56 variants, we can't anticipate every field. Dynamic schemas break the whack-a-mole cycle.
**Format**: Compact one-liner per endpoint: `POST /v2/employee — opt: firstName, lastName, email, ...`
**Cap**: 20 optional fields shown per endpoint, with "+N more, use search_api_docs" overflow.
**Date**: 2026-03-20 ~18:00.

## 5. Gemini 2.5 Pro over Gemini 2.5 Flash
**Decision**: Switched from Flash to Pro for more reasoning power.
**Why**: Flash had 75% pass rate on tuning tests, Pro achieved 90%+. Pro handles complex multi-step workflows (vouchers, payroll) significantly better.
**Trade-off**: Slower (~2x latency) but within 5-minute timeout.
**Date**: 2026-03-20 ~14:50.

## 6. Global Vertex AI Endpoint
**Decision**: Use europe-north1 regional endpoint.
**Why**: Gemini 2.5 Pro requires regional endpoints. Initially tried global, switched to europe-north1 for lower latency to Cloud Run in same region.
**Date**: 2026-03-20 ~14:28.

## 7. Keep 422 Schema Hints (Belt-and-Suspenders)
**Decision**: Even though schemas are proactively injected, still attach schema hints on 422 errors.
**Why**: The proactive schema prevents MOST first-attempt 422s. But when they still happen, the hint helps the agent self-correct on retry.

## 8. Rules Stay Universal, Gotchas in Recipes
**Decision**: All 9 rules in `_CORE_RULES` apply to every task. Endpoint-specific warnings (like `row` starts at 1) live in the recipe text.
**Why**: Rules are short and universal. Putting gotchas next to the endpoint they apply to maximizes the chance the LLM sees them when it matters.

## 9. Mock Client for Tuning Tests
**Decision**: Tuning tests use real LLM + mock Tripletex API (not real sandbox).
**Why**: Real sandbox is shared, has state, rate limits, and costs money. Mock client lets us test agent behavior (call count, error count, field correctness) without side effects.
**How**: MockTripletexClient auto-generates IDs for POST, returns registered entities for GET. AgentTestResult provides assertion helpers.
