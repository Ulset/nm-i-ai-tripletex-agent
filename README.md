# Tripletex AI Agent

### NM i AI 2026 — Norwegian National Championship in AI

> An autonomous AI agent that reads accounting task prompts in 7 languages, reasons about what to do, and executes multi-step workflows against the [Tripletex](https://tripletex.no) ERP API — all without human intervention.

---

## The Competition

**NM i AI** (Norgesmesterskapet i AI) is Norway's national AI championship. The 2026 Tripletex challenge: build an agent that can complete real-world accounting tasks — creating customers, registering employees, issuing invoices, recording payments — by talking directly to a live Tripletex API.

- **30 task types** across 56 variants (7 languages × 8 data sets)
- **5-minute timeout** per task
- Tasks arrive in Norwegian Bokmål, Nynorsk, English, Spanish, Portuguese, German, and French
- The agent must figure out which API calls to make, in what order, with what data

No templates. No hardcoded flows. Just an LLM, two tools, and an API.

---

## How It Works

The agent uses a **ReAct (Reason-Act-Observe)** loop — it thinks about what to do, takes an action, observes the result, and repeats until the task is done.

```mermaid
flowchart TD
    A["POST /solve\n<i>Task prompt + credentials + files</i>"] --> B{"Has file\nattachments?"}
    B -- Yes --> C["Extract text\n<i>PDF → PyMuPDF / Images → Vision API</i>"]
    C --> D["Build prompt\n<i>Task + extracted file contents</i>"]
    B -- No --> D

    D --> E["ReAct Agent Loop\n<i>Max 15 iterations</i>"]

    E --> F{"LLM reasons\n<i>GPT-4o</i>"}

    F -- "Tool call" --> G{"Which tool?"}
    G -- "call_api" --> H["Execute API call\n<i>GET / POST / PUT / DELETE</i>\nagainst Tripletex"]
    G -- "search_api_docs" --> I["Search OpenAPI spec\n<i>Endpoint discovery</i>"]

    H --> J{"Success?"}
    J -- "200 ✓" --> K["Feed response\nback to LLM"]
    J -- "422 ✗" --> L["Enrich error with\nendpoint schema"]
    L --> K

    I --> K
    K --> F

    F -- "Text response\n<i>(no tool call)</i>" --> M["Task complete ✓"]
    M --> N["Return\n<code>{'status': 'completed'}</code>"]

    style A fill:#4a9eff,color:#fff,stroke:none
    style E fill:#7c3aed,color:#fff,stroke:none
    style F fill:#7c3aed,color:#fff,stroke:none
    style H fill:#10b981,color:#fff,stroke:none
    style I fill:#f59e0b,color:#fff,stroke:none
    style M fill:#10b981,color:#fff,stroke:none
    style N fill:#4a9eff,color:#fff,stroke:none
    style L fill:#ef4444,color:#fff,stroke:none
```

### The Two Tools

The LLM has exactly two tools at its disposal:

| Tool | Purpose |
|------|---------|
| `call_api` | Make HTTP requests (GET/POST/PUT/DELETE) to the Tripletex API |
| `search_api_docs` | Search the Tripletex OpenAPI spec to discover endpoints and required fields |

That's it. The LLM decides everything else — which endpoints to hit, what data to send, how to chain multi-step workflows, and how to recover from errors.

---

## What It Can Do

The agent handles complex, multi-step accounting workflows autonomously:

```
"Opprett en kunde med navn Fjord Solutions AS,
 organisasjonsnummer 987654321,
 adresse Storgata 15, 3015 Drammen"
```

The agent will:
1. Parse the Norwegian prompt
2. POST to `/v2/customer` with the correct structured payload
3. Format the address as a proper JSON object (not a string!)
4. Respond confirming the customer was created

More complex tasks chain multiple API calls:

```
"Register a payment for invoice #42 — full amount, paid today"
```

→ GET customer → GET invoices (with date range) → GET payment types → PUT payment with query params

---

## Tech Stack

| Component | Technology |
|-----------|-----------|
| Web Framework | FastAPI + Uvicorn |
| LLM | OpenAI GPT-4o (function calling) |
| API Client | requests (sync) |
| PDF Processing | PyMuPDF + OpenAI Vision API |
| Deployment | Docker → Google Cloud Run |
| Testing | pytest (93 unit/integration + e2e) |

---

## Project Structure

```
tripletex-agent/
├── src/
│   ├── main.py              # FastAPI app, /solve endpoint
│   ├── orchestrator.py       # Coordinates file processing → agent
│   ├── agent.py              # ReAct loop — the brain
│   ├── api_docs.py           # OpenAPI spec search tool
│   ├── tripletex_client.py   # HTTP client for Tripletex API
│   ├── file_processor.py     # PDF/image text extraction
│   ├── models.py             # Pydantic request/response models
│   ├── config.py             # Environment configuration
│   └── logging_config.py     # Structured JSON logging
├── tests/
│   ├── test_*.py             # Unit & integration tests
│   └── e2e/                  # End-to-end tests against sandbox
├── Dockerfile
└── CLAUDE.md
```

---

## Running Locally

```bash
# Install dependencies
pip install -e ".[dev]"

# Set your OpenAI API key
export OPENAI_API_KEY=sk-...

# Start the server
uvicorn src.main:app --port 8080

# Run tests
python3 -m pytest --tb=short
```

---

## Deployment

Deployed as a serverless container on Google Cloud Run:

```bash
gcloud run deploy tripletex-agent \
  --source . \
  --region europe-north1 \
  --allow-unauthenticated \
  --memory 512Mi \
  --timeout 300 \
  --port 8080
```

---

## Architecture Decisions

**Why ReAct over plan-then-execute?** Earlier versions generated a full plan upfront, then executed it blindly. This failed when the API returned unexpected validation errors or when tasks required dynamic lookups (e.g., finding a customer ID by organization number before creating a project). The ReAct loop lets the agent adapt on every step.

**Why only 2 tools?** Simplicity. The LLM is remarkably good at figuring out multi-step workflows when given just `call_api` and `search_api_docs`. More tools would mean more confusion in the prompt, more edge cases, and slower iteration.

**Why limit doc searches to 2 per task?** Production logs showed the agent sometimes spiraling into 9+ consecutive doc searches instead of just trying an API call. Capping at 2 forces it to rely on its built-in knowledge of common endpoints and only search when truly stuck.

---

*Built for [NM i AI 2026](https://ainm.no) — Norway's national championship in artificial intelligence.*
