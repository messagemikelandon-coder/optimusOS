# Session Handoff

Purpose: replaceable handoff for the next substantial Codex/Claude session.
Information owner: the active session author.
Read when: starting or resuming work.
Update when: a substantial task completes or context needs to be handed forward.
Last verified date: 2026-07-23.

## Identity

- Agent/task owner: Claude — Phase 2B (observability): platform-support-only, read-only, bounded runtime observability summary.
- Branch/HEAD: `agent/claude/phase2b-runtime-observability`, one implementation commit on top of `main` at `b81aad5147f0e9ff49989817379a9c03b3ee6f00` (the merge of PR #83, Phase 2A). Branched from `origin/main`, NOT from the Phase 2A feature branch.
- Working directory: primary repo checkout with `origin` = the optimusOS GitHub repository.

## Context

Phase 1 is complete; Phase 2A (storage observability, ADR-023) is merged. Phase 2B is the second observability slice: an additive, read-only, **platform-support-only** endpoint that consolidates process-visible runtime signals for a support operator. It is explicitly NOT production host monitoring (same boundary as Phase 2A) and is pull-only. Decision: ADR-024. Operator-facing behavior, the boundary, rollback, and the open owner decision are in `docs/context/MONITORING.md` §6.

## Active task

**Phase 2B read-only, support-only bounded runtime observability summary.** Surface and files:

- `app/runtime_metrics.py` — in-process request-metrics registry the request-context middleware feeds one record per request. Bounded label cardinality (route-template labels via `route.path_format`, never a raw path/id; unmatched → `<unmatched>`; capped, overflow → `<other>`). `snapshot()` returns uptime, totals, status-class counts, avg/max latency, and a bounded top-N per-route breakdown. `record` is total (cannot raise). Process-wide `request_metrics`; `reset()` for tests.
- `app/capability_metrics.py` — OBSERVE-only capability-decision counters (`would_allow`/`would_deny`/`resolution_error`), a fixed bounded key set. Incremented by `app/capability_gate.py` beside the existing telemetry event; `record` is total. Process-wide `capability_metrics`; `reset()` for tests. No enforcement semantics; Bays stays OBSERVE-only.
- `app/runtime_monitor.py` — bounded runtime snapshot service (TTL cache + single-flight + throttled degraded warning, modeled on `app/operations_monitor.py`). `collect_runtime_signals` gathers dependency reachability (fail-safe TCP probe from `app/net.py`), worker heartbeat (fixed Redis key, bounded TTL, epoch-second value), and queue condition. All host/Redis boundaries injected. Process-wide `runtime_service`; `reset()` for tests.
- `app/operations_monitor.py` — added `peek_snapshot()`: returns the cached Phase 2A storage snapshot WITHOUT collecting, so the summary reuses storage and never launches `docker system df`.
- `app/observability.py` — the request-context middleware records one request metric on the success path and (as a 500) on the exception path before re-raising; it never suppresses the exception.
- `app/main.py` — `GET /api/operations/summary`, gated **support-only** (`SupportAuthContextDep`/`require_support_context`), rate-limited via the existing registry (`enforce_operations_summary_rate_limit`), sets `Cache-Control: no-store`, and emits a throttled `reliability_event: runtime.degraded` identifying the support actor by role + internal id. Each subsection is independently fail-safe; storage is a `peek` (never re-collected).
- `app/config.py` — new bounded settings: `worker_heartbeat_redis_key`, `worker_heartbeat_interval_seconds` (30), `worker_heartbeat_ttl_seconds` (150, validated ≥ 2× interval), `worker_queue_redis_key` (empty ⇒ not_configured), `runtime_snapshot_ttl_seconds` (15), `dependency_probe_timeout_seconds` (1.0), `runtime_warning_cooldown_seconds` (300), `max_operations_summary_requests_per_minute` (30). `.env.example` documents all.
- `app/models.py` — response models (`OperationsSummaryRead` + `RequestTrafficRead`/`RouteTrafficRead`/`DependencyStatusRead`/`WorkerHeartbeatRead`/`QueueConditionRead`/`CapabilityObserveCountersRead`/`StorageSummaryRead`), typed with the collectors' enums; UTC timestamps.
- `scripts/optimus_worker.py` — writes a bounded heartbeat each loop (fixed key, TTL, epoch-second value only — no job/customer data; fail-safe on Redis error).
- `tests/test_role_isolation.py` — classified the new route under `_SUPPORT_ROUTES`.
- Docs: `MONITORING.md` §6 added; `CURRENT_STATE.md`, `KNOWN_ISSUES.md`, `DECISIONS.md` (ADR-024), and this handoff updated.

Out of scope (deliberately not done): any capability enforcement or Bays OBSERVE→ENFORCE change (AST safeguard untouched); mounting the Docker socket or Postgres data volume into the backend; any unauthenticated `/metrics` surface, scraping token, or IP-allowlist bypass; inventing a Redis work-queue (none exists; ADR-014 records a future queue is Postgres `SKIP LOCKED`, not Redis); any deployment/Compose change; any migration/schema change; automatic remediation/restart/cleanup; a frontend surface; external/paid monitoring; wiring the summary into `/ready`.

## Verified baseline

- `ruff format --check .`, `ruff check .`, `pyright` — all clean (0 errors).
- `pytest --ignore=tests/e2e` — **786 passed, 2 skipped** (was 707 passed, 2 skipped on `b81aad5`; +79 net-new Phase 2B tests; no pre-existing test weakened).
- `alembic heads` — unchanged single head `035_operating_mode_confirmed_at` (no migration).

## Evidence

- Authorization: real-HTTP (TestClient) endpoint tests prove support gets 200; owner, manager, technician, a suspended-shop owner, and an impersonated-owner session (driven through the real `/api/support/shops/{id}/impersonate` flow) all get 403; unauthenticated gets 401. Dependency-level unit gate tests additionally cover the role matrix. New route classified in the static route-audit.
- Bounded collection: injected clock/collect prove first call fresh; within-TTL cached without re-collecting; after-TTL re-collects; single-flight serves `stale` without a second collection; a 10-thread concurrency test confirms exactly one collection under contention; reset clears cache. API-level: 5 rapid GETs trigger exactly one runtime collection.
- Storage reuse: API tests prove the summary reports `not_collected` and never launches a storage collection when nothing is cached, and reports `collected` (reusing the cache) after the dedicated storage endpoint populated it — with the storage collection count staying at exactly one.
- Request metrics: middleware tests prove a success records the route template (never the raw path/id), a raised handler records a 500 while the exception propagates (never suppressed), and a 404 records the `<unmatched>` sentinel; registry unit tests cover status-class bucketing, latency avg/max, negative-duration clamping, label-cardinality overflow into `<other>`, top-N ordering, reset, and concurrency.
- Runtime signals: unit tests cover dependency reachable/unreachable; heartbeat alive/stale/missing/unknown (incl. malformed and infinite values, and future-timestamp clamp); queue not_configured/idle/backlog/unknown (incl. wrong-type and negative depth); severity ok/degraded; and the default Redis reader degrading to unreachable (fail-safe) against a closed port.
- Capability counters: unit tests prove per-decision counting, that an unknown value is ignored (bounded key set), reset, and concurrency; API test proves the counts surface in the summary.
- Throttled warning: API test proves repeated degraded GETs emit exactly one `runtime.degraded` event carrying only fixed statuses + the support actor's role and internal id; monitor unit tests prove transition/cooldown dedup and that ok never emits.
- Non-leakage: a test configures credential-shaped database/redis URLs and a queue key and proves none of those substrings appear in the response body or any emitted log record; `Cache-Control: no-store` asserted; rate limit 1/min yields 200 then 429; additive OpenAPI test confirms the new GET is present and `/api/operations/storage`/`/api/bays`/`/health`/`/ready` are unchanged.
- Config validation: heartbeat TTL below interval, out-of-range snapshot TTL / probe timeout / summary rate limit all raise `ValidationError`; defaults are sane (queue empty, TTL ≥ 2× interval).

## Unverified

- Full Docker/Playwright `tests/e2e` not run in this container (no Docker/Postgres/Redis) — CI's job. This slice adds no e2e test.
- Behavior against a real Redis (heartbeat round-trip worker→backend, real `LLEN`) and a real Postgres is proven through injected boundaries plus the fail-safe design, not exercised end-to-end here.
- Local commit-signature verification is unavailable in this container (no `ssh-keygen`); the commit carries a signature header and GitHub renders it Verified.

## Unrelated preexisting changes

- None functional. Every code change is scoped to this Phase 2B slice. No migration, no schema change, no edit to any existing route's behavior. One adjacent doc correction: ADR-023's status line in `DECISIONS.md` was updated from "draft PR pending" to "merged (PR #83, `b81aad5`)" because it had gone stale after the Phase 2A merge.

## Blockers and risks

- No engineering blocker. Additive and revert-safe (revert the single commit; no migration/schema/data).
- Egress: pushing to `origin` is blocked by org egress policy (403) in this container, and `gh` is absent — the branch is delivered as a `git format-patch` and the draft PR must be opened manually (title: `Phase 2B: bounded runtime observability`).
- Process-visibility boundary (by design, not a defect): the summary reports only what the app process and its worker can see — it is NOT production host monitoring, and it is pull-only until a consumer watches the `runtime.degraded` logs or polls it (owner decision).
- No Redis work-queue exists: the queue subsection reports the true `not_configured` state; a future queue is recorded (ADR-014) as Postgres `SKIP LOCKED`, not Redis. The worker heartbeat depends on Redis reachability from both the worker and the backend.
- Publishing gate: opening/merging the PR requires the owner's explicit current-turn approval.

## Exact next task

1. Owner reviews and merges the draft Phase 2B PR (do not merge without explicit approval).
2. After merge, the recommended next observability slice moves these signals from pull-only to watched: add a scheduled poll + alert on a degraded dependency/worker, or ship the `runtime.degraded` `reliability_event` to a log-based alert rule. Both additive; neither authorizes mounting a Docker socket or DB volume into the web backend, nor any capability enforcement.
3. Do not begin that next slice, enable automatic remediation/cleanup, deploy, mount sockets/volumes, wire a Redis work-queue, or change capability enforcement without explicit approval. Bays stays OBSERVE-only.
