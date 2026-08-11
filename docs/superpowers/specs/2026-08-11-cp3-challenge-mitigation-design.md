# CP3 Official Challenge Investigation and Mitigation Design

## Context

Checkpoint 3 requires the team to run the released K3 challenge, identify the user-visible symptom from metrics, localize the abnormal span in Langfuse, prove the root cause with a log that shares the same correlation ID, and document a fix plus a preventive measure.

The released `config/challenge.json` identifies challenge `day13-k3-observability-v1`, incident `rag_slow`, affected feature `refund`, and a latency threshold of 2000 ms. The current implementation delays retrieval by 2.5 seconds when `rag_slow` is enabled. CP2 already provides six dashboard panels and child spans named `retrieve-docs` and `llm-generate`, but application logs do not yet expose retrieval duration. Consequently, the current logs can show a slow response but cannot independently prove which pipeline stage caused it.

The repository baseline is 47 passing tests, a valid 6/6 dashboard contract, and an 80/100 log-validator result from a test-generated log containing only one correlation ID. The existing local modification to `.env.example` is outside this work and must remain untouched.

## Goal

Produce a reproducible CP3 investigation that connects Metrics -> Traces -> Logs, then implement and verify a real retrieval timeout with degraded fallback. The final evidence must show both the original failure mode and the post-mitigation result without modifying or hard-coding the released challenge.

## Chosen Approach

Use an evidence-first, two-mode workflow:

1. Add retrieval-stage observability and a configurable timeout mechanism.
2. Run the official challenge with the timeout disabled to capture the original incident.
3. Run the same challenge with a 1500 ms timeout to demonstrate mitigation.
4. Compare latency and quality, preserve trace and correlation identifiers, and update the submission report.

This approach is preferred over an evidence-only response because it proves the proposed fix. It is preferred over a full async, retry, and circuit-breaker refactor because that scope is disproportionate to a one-hour checkpoint and creates unnecessary regression risk.

## Architecture

### Retrieval boundary

`app/mock_rag.py` will define a dedicated `RetrievalTimeoutError` and extend the retrieval interface to accept a timeout budget in milliseconds. The interface will remain independent of the challenge ID and requested feature. A timeout value of zero disables the budget so the original behavior remains reproducible; a positive value enforces the budget.

The mock dependency will model the behavior of a real client-side timeout: if the simulated dependency delay exceeds the configured budget, it consumes only that budget and raises `RetrievalTimeoutError`. The implementation must not inspect `config/challenge.json` or special-case `refund` to decide whether to time out.

### Agent orchestration

`app/agent.py` will make the retrieval timeout an explicit `LabAgent` setting. If no constructor value is provided, the agent reads `RETRIEVAL_TIMEOUT_MS`; the default is 1500 ms. Zero is valid, while negative and non-integer values fail during agent construction.

The agent will measure retrieval duration with `time.perf_counter()` and add the following structured observability fields:

- `retrieval_duration_ms`
- `doc_count`
- `degraded`
- `timeout_ms` when a timeout occurs

A successful retrieval emits `retrieval_completed` at info level and updates the `retrieve-docs` span with `degraded=false`. A timeout emits `retrieval_timed_out` at warning level, updates the same span with `degraded=true`, and continues generation with `docs=[]`.

Only `RetrievalTimeoutError` is converted to a degraded response. Other dependency failures, including the existing `tool_fail` scenario, continue through the current error path and produce `request_failed` plus HTTP 500. This boundary prevents the mitigation from hiding unrelated failures.

### Existing interfaces that remain unchanged

- The `/chat`, `/health`, `/metrics`, and incident-control HTTP contracts remain unchanged.
- `config/challenge.json` is read-only and is never generated or edited by the implementation.
- The six-panel dashboard contract, SLO values, alert rules, and prompt-version workflow remain unchanged.
- The PII scrubbing processor remains the final authority before JSON is written. New events contain durations, counts, booleans, and sanitized context only; they do not contain the raw query or raw user ID.

## Runtime Data Flow

### Before-fix evidence run

1. Start a fresh API process with Langfuse enabled, `RETRIEVAL_TIMEOUT_MS=0`, and a dedicated before-fix log path.
2. Verify `/health` reports `tracing_enabled: true` and all incidents are disabled.
3. Enable the incident using `python scripts/inject_incident.py`, which resolves the incident from the released challenge file.
4. Run `python scripts/load_test.py --challenge --concurrency 5`.
5. Capture `/metrics`, the dashboard, and the correlation IDs printed by the load test.
6. Select a representative response above 2000 ms. Use its correlation ID to find `retrieval_completed` and `response_sent` in the log, then use the same correlation ID in Langfuse trace metadata to identify the trace.
7. Record the trace ID and verify that `retrieve-docs` is approximately 2.5 seconds while `llm-generate` remains approximately 0.15 seconds.

### After-fix evidence run

1. Stop the API, disable the incident if necessary, and start a fresh process with `RETRIEVAL_TIMEOUT_MS=1500` and a separate after-fix log path.
2. Verify health and incident state, enable the same official incident, and run the same challenge with the same seed and concurrency.
3. Capture `/metrics`, the dashboard, response status codes, and correlation IDs.
4. Select a representative degraded response. Link its `retrieval_timed_out` and `response_sent` events to a Langfuse trace using the shared correlation ID.
5. Verify that the retrieval span and log show a timeout near 1500 ms, the request still returns HTTP 200, and P95 is below 2000 ms.
6. Record the lower quality proxy as an explicit availability-versus-quality trade-off.
7. Disable the incident and confirm `/health` shows all incident flags false.

Separate API processes ensure in-memory metrics do not mix the before and after populations. Separate log paths prevent unrelated CP1/CP2 records from contaminating the comparison.

## Error Handling

- Missing Langfuse credentials are a preflight failure for evidence collection. The application can still run, but CP3 trace evidence must not be claimed unless `/health` reports tracing enabled and the trace is visible in Langfuse.
- Invalid timeout configuration fails fast during application startup rather than silently selecting another value.
- Retrieval timeout returns a degraded HTTP 200 response and is visible in both trace and log.
- Unexpected retrieval exceptions retain the current HTTP 500 behavior and error metrics.
- Evidence collection must end by disabling the incident, including when an intermediate command fails.
- No trace ID, log line, screenshot, or metric value may be fabricated. Every claim in the report must point to an artifact produced by the official run.

## Testing Strategy

### Retrieval unit tests

Add focused tests for:

- normal retrieval returning the matching document;
- `rag_slow` raising `RetrievalTimeoutError` under a 1500 ms budget;
- a zero budget preserving the original slow behavior;
- cleanup of global incident state after each test.

The timeout tests will replace real sleeps with a recording fake so the test suite remains fast and deterministic.

### Agent and trace tests

Extend the recording Langfuse client tests to verify:

- successful retrieval span metadata includes duration, document count, and `degraded=false`;
- timeout span metadata includes duration, timeout budget, zero documents, and `degraded=true`;
- generation still runs after a retrieval timeout;
- `tool_fail` is not swallowed by the timeout fallback.

### HTTP and log integration tests

Use a temporary log path and the FastAPI test client to verify:

- a timed-out retrieval returns HTTP 200 with a correlation ID;
- `retrieval_timed_out` and `response_sent` share that correlation ID;
- the timeout event contains the approved structured fields;
- raw user ID and test PII do not appear in the JSONL output;
- invalid timeout values are rejected during agent construction.

### Regression checks

The implementation is complete only when:

- the full pytest suite passes with at least the existing 47 tests;
- `python scripts/validate_dashboard.py` reports 6/6 panels;
- `python scripts/validate_logs.py` reaches at least 80/100 on a multi-request generated log;
- no unexpected tracked changes or secrets appear in `git status` or the staged diff.

## Evidence and Report Artifacts

Store the following CP3 artifacts under `submission/evidence/`:

- `cp3-before-metrics.txt`
- `cp3-before-dashboard.png`
- `cp3-slow-trace.png`
- `cp3-root-cause-log.txt`
- `cp3-after-metrics.txt`
- `cp3-after-dashboard.png`
- `cp3-timeout-trace.png`
- `cp3-verification.txt`

`submission/REPORT.md` section 6 will include the challenge ID, before-fix symptom, representative trace ID, correlation ID and log event, root cause, implemented fix, quality trade-off, and preventive measure. The contribution table will name the CP3 files and final commit or PR.

Screenshots remain manual artifacts because they must show the real dashboard and Langfuse UI. Text evidence must include the exact commands used and enough output to reproduce each claim.

## Acceptance Criteria

- Before-fix P95 exceeds the challenge threshold of 2000 ms.
- A representative before-fix trace shows `retrieve-docs` at approximately 2.5 seconds and a much shorter `llm-generate` span.
- A before-fix log with the same correlation ID records the retrieval duration and slow response.
- All five after-fix requests return HTTP 200.
- After-fix P95 is below 2000 ms.
- A representative after-fix log and trace show a retrieval timeout near 1500 ms with `degraded=true`.
- The report explicitly documents any quality-score reduction caused by the empty-document fallback.
- The official challenge file is unchanged, the incident is disabled after testing, and no secret or raw PII is committed.

## Out of Scope

- Converting the entire request pipeline to async.
- Adding retries, a circuit breaker, or a new alert family.
- Changing dashboard thresholds, SLO objectives, prompt versions, or fake-LLM answer quality.
- Editing the released challenge or hard-coding output to pass a validator.
