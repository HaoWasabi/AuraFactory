# Load Testing

## Prerequisites

Install k6: https://k6.io/docs/get-started/installation/

## Running

```bash
# Start the app first
uvicorn app.main:app --host 0.0.0.0 --port 8000

# Run basic load test (default: localhost:8000)
k6 run tests/load/k6_basic.js

# Custom base URL
k6 run -e BASE_URL=https://aurafactory.onrender.com tests/load/k6_basic.js
```

## Thresholds

| Metric | Target |
|--------|--------|
| Health endpoint p95 | < 500ms |
| Error rate | < 1% |
| Concurrent users (baseline) | 50 VUs sustained |

## Results

Results are saved to `tests/load/results.json` after each run.
