# Deployment History

| Revision | Time (UTC) | Key Changes |
|----------|-----------|-------------|
| 00011-mqk | ~13:42 | Payment reversal workflow |
| 00012-dbm | ~13:51 | Efficiency improvements |
| 00013-qbp | ~13:56 | Voucher and invoice fixes |
| 00014-8qd | ~14:16 | Workflow condensation |
| 00016-hr5 | ~14:56 | Switched to Gemini 2.5 Pro |
| 00018-??? | ~17:05 | Pre-parser implementation |
| 00025-j5p | ~18:19 | Schema injection, compact schemas, dynamic date |
| 00026-xlh | ~19:10 | Compact schema format (72% reduction) + voucher row fix |
| 00027-5pc | ~19:30 | Dynamic focused prompt assembly (only matched recipe) |
| 00028-kd2 | ~20:35 | Travel expense travelDetails fix |

## Deploy Command
```bash
gcloud run deploy tripletex-agent \
  --source . \
  --region europe-north1 \
  --allow-unauthenticated \
  --memory 512Mi \
  --timeout 300 \
  --port 8080 \
  --project ainm26osl-716
```

## Log Command
```bash
gcloud logging read 'resource.type="cloud_run_revision" AND resource.labels.service_name="tripletex-agent" AND timestamp>="2026-03-20T19:28:00Z" AND jsonPayload.message=~"NEW TASK|Tool call|API response|API error|Agent done|Agent summary|Docs search|Pre-parse"' \
  --project ainm26osl-716 --limit 300 \
  --format json 2>&1 | python3 -c "
import json, sys
data = json.load(sys.stdin)
for entry in reversed(data):
    ts = entry.get('timestamp','')
    msg = entry.get('jsonPayload',{}).get('message','')
    if msg:
        print(f'{ts[11:19]}  {msg[:250]}')
"
```
Adjust `timestamp>=` filter for the submission window you want to analyze.
