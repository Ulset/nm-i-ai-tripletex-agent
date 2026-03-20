# Scoring System and Competition Strategy

## How Scoring Works

### Per-Task Scoring
1. Agent completes task → platform queries Tripletex API to verify what was created
2. Each task has field-level checks worth different points
3. `correctness = points_earned / max_points` (0 to 1)
4. Score = `correctness × tier_multiplier`
5. If correctness = 1.0 (perfect), efficiency bonus can UP TO DOUBLE the score

### Tier Multipliers
- Tier 1 (×1): Create employee, customer, department — max 2.0
- Tier 2 (×2): Create invoice, register payment — max 4.0
- Tier 3 (×3): Complex multi-step workflows — max 6.0

### Efficiency Bonus (ONLY on perfect correctness)
Two factors:
- **Call efficiency**: fewer API calls vs best known solution = higher bonus
- **Error cleanliness**: fewer 4xx errors (400, 404, 422) = higher bonus

Example (Tier 2 task):
| Scenario | Score |
|----------|-------|
| Failed all checks | 0.0 |
| 80% checks passed | 1.6 |
| Perfect, many errors | ~2.1 |
| Perfect, few errors | ~2.6 |
| Perfect, best efficiency | 4.0 |

### Leaderboard
- Best score per task is kept (bad runs never lower score)
- Leaderboard = sum of best scores across all 30 task types
- Benchmarks recalculated every 12 hours

## Current Strategy Priority

1. **Correctness first** — include ALL data from prompt, every field matters
2. **Zero 4xx errors** — avoid trial-and-error, validate before sending
3. **Minimize API calls** — plan before calling, don't fetch unnecessary entities
4. **Handle all 7 languages** — pre-parser handles translation
5. **Handle file attachments** — PDFs/images with invoice data

## What's Working (as of 2026-03-20 evening)
- Simple tasks (department, customer, product, payment): consistently 100%
- Invoice tasks: usually 100%, occasional bank account race condition
- Travel expense: fixed the travelDetails issue, should improve

## What's Still Failing
- Voucher/supplier invoice: `row` field still occasionally missed
- Fixed price projects: `fixedprice` casing is flaky
- Complex multi-step tasks under concurrent load: bank account races

## Submission Workflow
1. Deploy: `gcloud run deploy tripletex-agent --source . --region europe-north1 --allow-unauthenticated --memory 512Mi --timeout 300 --port 8080 --project ainm26osl-716`
2. Go to https://app.ainm.no/submit/tripletex
3. Enter endpoint: https://tripletex-agent-rzkmnmpmpq-lz.a.run.app/solve
4. Click Submit (can submit 3 concurrent)
5. Check results on page — x/y scores are preliminary health checks, real scores on leaderboard
6. Read logs: see CLAUDE.md for gcloud logging command

## Rate Limits
- 3 concurrent submissions (verified teams)
- 4 per task per day
