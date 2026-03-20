# Architecture Overview

## What This Is
An AI agent for NM i AI 2026 (Norwegian AI competition). It receives accounting tasks in 7 languages, calls the Tripletex accounting API to complete them, and gets scored on correctness + efficiency.

## Request Flow

```
Competition platform → POST /solve
    → TaskOrchestrator.solve()
        → FileProcessor (if PDFs/images attached)
        → TripletexAgent.solve()
            → _pre_parse() — LLM call #1: translate + classify prompt
            → get_system_prompt(recipe_letter) — dynamic prompt assembly
            → ReAct loop (up to 15 iterations):
                → LLM decides: call_api or search_api_docs or done (text)
                → Execute tool, return result to LLM
                → Repeat
        → Return {"status": "completed"}
```

## Key Files

| File | Purpose |
|------|---------|
| `src/agent.py` | Core agent: system prompt, pre-parser, tool definitions, ReAct loop |
| `src/api_docs.py` | OpenAPI spec loader, endpoint registry, schema extraction, recipe schemas |
| `src/tripletex_client.py` | HTTP wrapper for Tripletex API (Basic Auth, error handling) |
| `src/vertex_auth.py` | Vertex AI / Gemini authentication (OpenAI-compatible client) |
| `src/orchestrator.py` | Request routing, file processing, agent invocation |
| `src/file_processor.py` | PDF/image text extraction via LLM |
| `src/models.py` | Pydantic models for API contracts |
| `src/config.py` | Settings (model, port, etc.) |
| `src/main.py` | FastAPI app, /solve endpoint |

## LLM Model
- **Gemini 2.5 Pro** via Vertex AI (OpenAI-compatible endpoint)
- Region: europe-north1
- Auth: Service account on Cloud Run, `gcloud auth print-access-token` locally

## Two-Phase Architecture

### Phase 1: Pre-Parser
- Translates multilingual prompt (nb, nn, en, es, pt, de, fr) into structured English
- Identifies recipe letter (A-L) and extracts all field values
- Single LLM call, no tools, temperature=0
- Output format: TASK TYPE, RECIPE letter, FIELDS list, STEPS, FILE DATA

### Phase 2: Dynamic Focused Prompt + ReAct Agent
- `get_system_prompt(recipe_letter)` assembles: core rules + ONE matched recipe + compact OpenAPI schema
- Agent gets two tools: `call_api` and `search_api_docs`
- Each iteration: LLM picks a tool → execute → show result → repeat
- Agent responds with text (no tool call) when done
- Max 15 iterations, 5-minute timeout

## Dynamic Prompt Assembly (implemented 2026-03-20)

Before: System prompt had ALL 12 recipes (~7700 chars). Agent had to find the right one.
After: System prompt has ONLY the matched recipe (~2000-3400 chars). Pre-parser identifies the recipe, `get_system_prompt(letter)` injects just that one.

Structure:
```python
_CORE_RULES  — 9 universal rules (~400 tokens)
_RECIPES     — dict keyed by letter A-L, one recipe each
_ACTION      — "start immediately, use call_api"
_ALL_RECIPES — fallback: all recipes concatenated

get_system_prompt(letter) → rules + RECIPES[letter] + compact_schema + action
get_system_prompt(None)   → rules + ALL_RECIPES + action  (fallback)
```

## Compact Schema Injection

After identifying the recipe, `get_recipe_schemas()` in `api_docs.py`:
1. Looks up `RECIPE_ENDPOINTS[letter]` → list of (method, spec_path) for POST/PUT endpoints
2. Fetches OpenAPI schemas at depth=0 (field names only, no descriptions)
3. Formats as compact one-liner: `POST /v2/employee — opt: firstName, lastName, email, ...`
4. Caps at 20 optional fields per endpoint, with "+N more" overflow
5. Filters out read-only/meta fields (id, version, url, changes, displayName, etc.)

This is injected INTO the system prompt alongside the recipe (not in the user message).

## 422 Error Schema Hints

When a 422 error occurs, `get_endpoint_schema()` is called to provide the full field list as a hint in the error message back to the LLM. This is belt-and-suspenders with the proactive schema injection.
