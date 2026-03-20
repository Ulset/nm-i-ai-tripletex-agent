# Testing Guide

## Test Types

### Unit Tests (fast, no network)
```bash
python3 -m pytest tests/ --ignore=tests/tuning --ignore=tests/e2e -q --tb=short
```
- 124 tests, ~6 seconds
- Mock everything (OpenAI, Tripletex API)
- `tests/conftest.py` auto-patches `_pre_parse` to return None (skips the extra LLM call)
- Tests in `tests/tuning/` are excluded from this patch

### Tuning Tests (real LLM, mock API)
```bash
python3 -m pytest tests/tuning -v -n auto           # parallel, fast (~2-3 min)
python3 -m pytest tests/tuning -v -s --capture=no   # sequential with output (~6 min)
```
- Uses REAL Gemini via Vertex AI + MockTripletexClient
- Tests agent behavior: call count, error count, field correctness
- Requires Vertex AI credentials (gcloud auth locally)
- ~26-30/32 pass typically (LLM flakiness causes 2-6 failures per run)
- Flaky tests: re-run individually to confirm. If it passes on re-run, it's LLM noise.

### E2E Tests (real everything)
```bash
python3 -m pytest tests/e2e/ -m e2e -v
```
- Requires sandbox credentials

## Key Test Files

| File | What It Tests |
|------|---------------|
| `tests/test_agent.py` | Agent loop, tool calls, system prompt content, logging |
| `tests/test_prompt_validation.py` | OpenAPI spec validation, recipe schemas, endpoint registry |
| `tests/test_integration.py` | Full flow through TaskOrchestrator with mocked services |
| `tests/test_regression.py` | Specific production failures (postal address, employee fields, etc.) |
| `tests/tuning/test_voucher.py` | Voucher workflows (the hardest recipe) |
| `tests/tuning/test_payment_reversal.py` | Payment reversal (delete vouchers) |
| `tests/tuning/test_invoice_existing_products.py` | Invoice with pre-existing products |
| `tests/tuning/mock_client.py` | MockTripletexClient + AgentTestResult |

## The conftest.py Pattern

`tests/conftest.py` has an `autouse` fixture that patches `TripletexAgent._pre_parse` to return None for all non-tuning tests. This prevents the extra `openai.chat.completions.create()` call from breaking mock `side_effect` lists in unit tests. Tuning tests (detected by "tuning" in the file path) skip this patch because they need the real pre-parser.

## Creating New Tuning Tests

```python
import pytest
from tests.tuning.conftest import skip_no_vertex
from tests.tuning.mock_client import MockTripletexClient

@skip_no_vertex
class TestSomething:
    def test_task(self, run_agent):
        mock = MockTripletexClient()
        mock.register_entity("employee", {"id": 100, "email": "test@example.org"})

        result = run_agent("The prompt...", mock)
        result.print_summary()

        result.assert_no_errors()
        result.assert_max_calls(5)
        result.assert_endpoint_called("POST", "/v2/employee")
        result.assert_body_contains("POST", "/v2/employee", {"firstName": "Test"})
```
