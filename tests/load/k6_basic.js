// k6 Load Test for AuraFactory
// Run: k6 run tests/load/k6_basic.js
//
// Scenarios:
//   1. Health check throughput (baseline)
//   2. Metrics endpoint under load
//   3. Simulated concurrent guild requests

import http from 'k6/http';
import { check, sleep } from 'k6';
import { Counter, Rate, Trend } from 'k6/metrics';

// Custom metrics
const healthCheckDuration = new Trend('health_check_duration');
const errorRate = new Rate('error_rate');

// Configuration
const BASE_URL = __ENV.BASE_URL || 'http://localhost:8000';

export const options = {
    scenarios: {
        // Scenario 1: Health check baseline
        health_check: {
            executor: 'constant-vus',
            vus: 10,
            duration: '30s',
            exec: 'healthCheck',
        },
        // Scenario 2: Metrics endpoint
        metrics_check: {
            executor: 'constant-vus',
            vus: 5,
            duration: '30s',
            exec: 'metricsCheck',
            startTime: '10s',
        },
        // Scenario 3: Ramp-up stress test
        stress: {
            executor: 'ramping-vus',
            startVUs: 0,
            stages: [
                { duration: '10s', target: 20 },
                { duration: '20s', target: 50 },
                { duration: '10s', target: 0 },
            ],
            exec: 'healthCheck',
            startTime: '35s',
        },
    },
    thresholds: {
        http_req_duration: ['p(95)<500'],  // 95th percentile < 500ms
        error_rate: ['rate<0.01'],          // Less than 1% errors
    },
};

export function healthCheck() {
    const res = http.get(`${BASE_URL}/health`);
    const success = check(res, {
        'health returns 200': (r) => r.status === 200,
        'health has status field': (r) => JSON.parse(r.body).status !== undefined,
        'health response time < 200ms': (r) => r.timings.duration < 200,
    });
    healthCheckDuration.add(res.timings.duration);
    errorRate.add(!success);
    sleep(0.1);
}

export function metricsCheck() {
    const res = http.get(`${BASE_URL}/metrics`);
    check(res, {
        'metrics returns 200': (r) => r.status === 200,
        'metrics has prometheus format': (r) => r.body.includes('aurafactory_'),
    });
    sleep(0.5);
}

export function handleSummary(data) {
    return {
        'tests/load/results.json': JSON.stringify(data, null, 2),
    };
}
