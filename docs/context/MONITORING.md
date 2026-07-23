# Monitoring Requirements

Purpose: the Phase 6 Part H deliverable for production monitoring — what OptimusOS already exposes for monitoring, what's genuinely wired up today, and what still requires an owner decision (an external monitoring service, alert destination, and credentials) before it can be called "active." Per `CLAUDE.md`'s explicit instruction, nothing in this document should be read as a claim that monitoring is operational unless a section says so plainly.
Information owner: repository maintainers and the owner responsible for production infrastructure decisions.
Read when: before any production deployment decision; when diagnosing a real outage; when choosing an external monitoring/alerting service.
Update when: an external monitoring service is actually configured, a new health signal is added to `/health`/`/ready`, or a disk-space/alerting gap is closed.
Last verified date: 2026-07-23.
Relevant sources: `app/main.py` (`/health`, `/ready`, `/api/operations/storage`, `/api/operations/summary`), `app/operations_monitor.py`, `app/storage_monitor.py`, `app/runtime_monitor.py`, `app/runtime_metrics.py`, `app/capability_metrics.py`, `app/observability.py`, `app/security_events.py`, `scripts/optimus_worker.py`, `docker-compose.yml`, `docs/context/RELEASE_CHECKLIST.md`.

## Status today: what exists vs. what's active

**Exists and is real (verified by reading the code, not assumed):**
- `GET /health` — liveness: app version, git commit, migration head, and whether OpenAI/Square/owner-auth are configured. Always returns `200` if the process is up; does not check dependencies.
- `GET /ready` — readiness: checks real TCP reachability of Postgres and Redis, and runs a real schema-compatibility check (comparing the connected database's `alembic_version` against this app's known migration chain). Returns `"status": "ready"` only when Postgres, Redis, and schema compatibility are all healthy; degrades to `"status": "degraded"` (not a crash) otherwise, with `dependencies.postgres`/`dependencies.redis`/`schema_compatibility` broken out so a human or a monitor can tell which dependency is the problem.
- Structured JSON request/error logging (`app/observability.py`) — every request logs one correlated line with method/path/status/duration, and every unhandled exception is logged and classified before the response is returned.
- Structured security-event logging (`app/security_events.py`, Phase 6 Part H) — login failures/successes, rate-limit-exceeded events, and Square API failures are tagged with a `security_event` field, independently filterable from ordinary request logs.

**Does not exist / is not active today:**
- No external uptime/health-check service is configured against `/health` or `/ready` on any real deployment. Nothing currently pages anyone if the app goes down.
- No log aggregation destination is configured. Structured JSON logs go to stdout (captured by `docker compose logs` locally, or whatever the deployment host does with container stdout) — there is no shipped-to-a-dashboard pipeline today.
- Disk/Docker-storage *visibility* now exists in-app as a read-only endpoint (Phase 2A — `GET /api/operations/storage`, Section 4), but nothing yet *watches* it: there is no scheduler polling it and no alert on its threshold events, so a full disk is now inspectable on demand but still not automatically detected. Note also the container-visibility limitation in Section 4.
- A consolidated read-only *runtime* summary now exists in-app (Phase 2B — `GET /api/operations/summary`, Section 6): request traffic/latency, Postgres/Redis reachability, background-worker heartbeat, an (off-by-default) work-queue condition, capability-observe counters, and the reused Phase 2A storage snapshot. Like the storage endpoint it is **pull-only** — a support operator can inspect it on demand, but nothing polls it and no alert fires on a degraded value.
- No alerting (email/SMS/Slack/PagerDuty/etc.) is wired to any of the above. A `"degraded"` `/ready` response, a logged `security_event`, or a `reliability_event` today is only visible to someone actively looking.

## Required monitoring surface, and how to close each gap

### 1. Liveness/readiness (health/readiness)
**Already real, nothing to build.** Point any external uptime checker (a cheap, common choice: UptimeRobot, Better Uptime, a cron+curl+webhook, or the cloud host's own load-balancer health check) at `GET /ready`. Alert on a sustained non-`200` or `"status": "degraded"` response, not a single blip — `/ready`'s dependency checks use a 1-second TCP timeout (`app/main.py::_tcp_dependency_ready`), so a single slow-but-recovering check is expected occasionally under real network conditions.

**Open, needs an owner decision**: which external service to use, and who receives the alert. Not chosen yet.

### 2. Error rate / application errors
**Partially real.** Every unhandled exception is already logged as a structured, classified JSON line (`app/observability.py::install_request_context_middleware`) with a request id, so the *data* to detect an error-rate spike already exists in the log stream. What's missing is somewhere that *counts* these over time and alerts on a spike — that requires a log aggregation/metrics destination (see below), not new application code.

**Open, needs an owner decision**: a log-aggregation or metrics destination (examples: a hosted log service with alerting, or a self-hosted stack like Loki+Grafana or Prometheus+Grafana). Given this is currently a single-instance deployment, even a lightweight solution (e.g. a scheduled script that greps recent container logs for `"level": "ERROR"` and alerts past a threshold) would close most of this gap without new infrastructure — a reasonable minimum-viable option if a full observability stack isn't justified yet at this scale.

### 3. Security events
**Real as of this Part H pass**, same caveat as #2: the events are logged and structurally filterable (`security_event` field), but nothing currently watches the log stream for them. Once a log destination exists, alerting on `security_event: rate_limit.exceeded` occurring repeatedly from one source, or any `auth.login_failed` volume spike, is a reasonable first alerting rule to add.

### 4. Disk space and Docker storage

**A read-only, in-app *process-visibility* endpoint exists (Phase 2A). It is NOT production host monitoring, and it is not wired to any alert.**

`GET /api/operations/storage` is **platform-support-only** (`require_support_context`; a shop owner, manager, technician, suspended-shop account, unauthenticated caller, or impersonated-owner session cannot reach it — it exposes platform infrastructure telemetry, not shop data). It returns, on demand:
- Host filesystem total / used / available bytes and used-percent for the process's configured filesystem, plus an `ok` / `warning` / `critical` / `unknown` status against `DISK_WARNING_PERCENT` (default 80) and `DISK_CRITICAL_PERCENT` (default 90). The measured filesystem is identified by a non-sensitive **label** (`STORAGE_TARGET_LABEL`, default `application_filesystem`) — the raw path (`DISK_MONITOR_PATH`) is used internally only and is never returned or logged.
- Aggregate Docker storage usage — images, containers, volumes, build cache (count, size, reclaimable) — via a read-only `docker system df`, with an explicit `available` vs `unavailable` state so an inaccessible Docker daemon is never mistaken for a healthy empty host. Partial/truncated `df` output is treated as `unavailable`, never presented as a complete healthy snapshot.

**Bounded collection.** The snapshot is cached for `STORAGE_SNAPSHOT_TTL_SECONDS` (default 30) with single-flight refresh, so at most one `docker system df` (5-second timeout) runs per TTL window regardless of request volume; concurrent requests serve the last snapshot rather than launching duplicate subprocesses. The response includes `freshness` (`fresh`/`cached`/`stale`), `collected_at`, and `age_seconds`. The endpoint is rate-limited (`MAX_OPERATIONS_STORAGE_REQUESTS_PER_MINUTE`, default 30, per client) and sets `Cache-Control: no-store`.

**Warning signal (throttled).** On a fresh collection at/above a threshold, one structured log line is emitted (`reliability_event: disk.usage_warning` / `disk.usage_critical`) carrying only the target label, numeric percentages, and the support actor's role and internal id (never the raw path, username, or email). It is emitted on a severity transition or at most once per `STORAGE_WARNING_COOLDOWN_SECONDS` (default 300) while elevated — repeated requests in the same state do not amplify into repeated events.

**Behavior guarantees:** strictly read-only — it never deletes, prunes, restarts, resizes, or mutates any host or Docker resource (`docker system df` reports usage only; no other docker subcommand is ever invoked). Every host/Docker call fails safe: an unreadable path degrades to `unknown` (never a fabricated healthy zero), and any Docker failure (CLI absent, daemon down, timeout, malformed/partial output) degrades to `unavailable` with a short static reason that never includes raw stderr.

**This endpoint reports only what the application process can see — it does NOT monitor the production host.** By default the `backend` container is `read_only: true`, has no Docker socket, and does not mount the Postgres data volume, so from inside it the filesystem reading is the container root and `docker.availability` is `unavailable`. That is expected: the in-process probe is a convenience for a support operator, not host monitoring, and the endpoint must not be read as monitoring the production host when it cannot.

**Real host/Docker monitoring requires a separate least-privileged collector — NOT changes to this internet-facing backend.** Do **not** mount `/var/run/docker.sock` into the web backend, and do **not** expose raw PostgreSQL data files to the web backend just to read filesystem statistics — either would materially widen the attack surface of an internet-facing service. Instead, run one of: a dedicated least-privileged host collector or sidecar with only the access it needs, the hosting platform's own disk/volume metric, or a small host-side script (alerting below ~15–20% free). No deployment or Compose change is made or authorized by this slice.

**Rollback:** the whole slice is additive and revert-safe. A `git revert` of the Phase 2A commit removes the `/api/operations/storage` route, the `app/storage_monitor.py` collector and `app/operations_monitor.py` bounded-collection service, the support-endpoint rate limiter, and the `STORAGE_*`/`DISK_*` settings (safe defaults, read only by this endpoint). No migration, no schema change, no data, and no change to any existing route or behavior — the OpenAPI change is purely additive (one new GET).

**Next recommended Phase 2 slice:** surface these signals where they are watched rather than pulled — either (a) a small addition to the existing background worker (`scripts/optimus_worker.py`) that samples disk on its existing loop and logs the same throttled `reliability_event` warnings so they reach the log stream without a manual GET, or (b) fold the disk `status` into `/ready` so the existing readiness signal degrades on a full disk. Both are additive; neither authorizes mounting a Docker socket or database volume into the web backend — production host/Docker coverage remains the separate least-privileged-collector work above.

**Open, needs an owner decision**: the separate least-privileged host/Docker collector (or hosting-platform metric / host script) that actually watches the production host, plus a consumer for the endpoint's `reliability_event` logs (a log-based alert rule) if the in-app signal is used.

### 5. Database health
**Partially real** — `/ready`'s Postgres check confirms real TCP reachability and a real schema-compatibility comparison, which catches "Postgres is down" and "the database schema doesn't match this app version" (both real, previously-tested failure modes — see `app/migration_compat.py` and its test suite). **Not covered**: connection-pool exhaustion, replication lag (not applicable today, single-instance Postgres), or slow-query buildup. None of these have been a real problem at this app's current single-shop scale; revisit if usage grows enough to make them plausible.

### 6. Runtime observability summary (Phase 2B)

**A read-only, bounded, in-app *process-visibility* summary exists. Like Section 4 it is NOT production host monitoring, and it is not wired to any alert.**

`GET /api/operations/summary` is **platform-support-only** (`require_support_context`; same gate and rejections as Section 4 — owner/manager/technician/suspended/unauthenticated/impersonated-owner cannot reach it). It consolidates, on demand, six non-sensitive signals about the running application process:

- **Request traffic/latency** — from an in-process metrics registry (`app/runtime_metrics.py`) the request-context middleware feeds one record per request: process uptime, total requests, counts by status class (2xx/3xx/4xx/5xx/…), average and max latency, and a bounded top-N per-route breakdown. Route labels are the **route template** (`/api/customers/{customer_id}`) — never a concrete path or id — and label cardinality is capped (overflow folds into a single `<other>` bucket), so this cannot grow without bound or leak a path/PII.
- **Dependency status** — Postgres and Redis TCP reachability, via the same fail-safe probe `/ready` uses (`app/net.py`), reported as a fixed `reachable`/`unreachable` enum (never a URL).
- **Worker heartbeat** — the background worker (`scripts/optimus_worker.py`) now refreshes a single fixed Redis key (`WORKER_HEARTBEAT_REDIS_KEY`) each loop with a bounded TTL (`WORKER_HEARTBEAT_TTL_SECONDS`, validated ≥ 2× `WORKER_HEARTBEAT_INTERVAL_SECONDS`); the value is a single epoch second, never job/customer data. The summary reads it and reports `alive`/`stale`/`missing`/`unknown` plus age.
- **Work-queue condition** — **off by default.** There is no application work queue today (ADR-014 records that any future queue would be a Postgres `SKIP LOCKED` queue, **not** Redis), so with `WORKER_QUEUE_REDIS_KEY` empty this reports `not_configured` and never touches Redis for a queue. If an operator ever points it at a real Redis list, it is read with a single bounded `LLEN` and reported as `idle`/`backlog`/`unknown` (depth only).
- **Capability-observe counters** — OBSERVE-only cumulative `would_allow`/`would_deny`/`resolution_error` counts (`app/capability_metrics.py`), the same signal the per-request `authz.capability_observed` event carries, rolled up in-process. Carries **no** enforcement semantics — Bays stays OBSERVE-only.
- **Storage** — the Phase 2A storage snapshot **reused from its cache** (`peek`, never re-collected): this endpoint never launches a `docker system df`. Reports `collected`/`not_collected`, freshness, disk status, and Docker availability.

**Bounded collection.** The dependency/worker/queue signals are served from a TTL cache with single-flight refresh (`RUNTIME_SNAPSHOT_TTL_SECONDS`, default 15), so at most one probe/Redis-read pass runs per window regardless of request volume; dependency probes use `DEPENDENCY_PROBE_TIMEOUT_SECONDS` (default 1.0). The request-metrics and capability counters are read from cheap in-process registries. The endpoint is rate-limited (`MAX_OPERATIONS_SUMMARY_REQUESTS_PER_MINUTE`, default 30, per client) and sets `Cache-Control: no-store`.

**Warning signal (throttled).** On a fresh collection that is *degraded* (a core dependency unreachable, or the worker `missing`/`stale`) one structured log line is emitted (`reliability_event: runtime.degraded`) carrying only fixed enum statuses and the support actor's role and internal id — never a URL, host, path, username, or email. It is throttled on transition or `RUNTIME_WARNING_COOLDOWN_SECONDS` (default 300), so repeated requests in the same state do not amplify.

**Behavior guarantees:** strictly read-only and additive. Every field is a non-sensitive aggregate (counts, latencies, ages, fixed enum statuses, static route templates). Every dependency/Redis boundary fails safe — an unreachable Postgres/Redis, a missing/malformed heartbeat, or an unreadable queue degrades to a fixed status, never a raised exception and never a leaked value. It performs no enforcement, no mutation, and no host/Docker access.

**This endpoint reports only what the application process (and its worker) can see — it does NOT monitor the production host,** the same boundary as Section 4. The worker heartbeat additionally depends on Redis being reachable from both the worker and the backend; a `unknown` heartbeat means "Redis unreadable from here," not necessarily "worker down."

**Note — worker responsibility vs. the earlier removal evaluation.** `docs/architecture/PHASE2-READINESS.md` §2A (an *evaluation*, never executed) recommended removing the worker as a proven no-op. Phase 2B instead gives the still-present worker a small, real, bounded responsibility (the heartbeat). That is a deliberate, owner-instructed choice: if the worker is later removed, the heartbeat write goes with it and the summary simply reports `missing`/`unknown` (fail-safe) until another heartbeat source exists. The two tracks are reconciled here so neither silently contradicts the other.

**Rollback:** additive and revert-safe. A `git revert` of the Phase 2B commit removes the `/api/operations/summary` route, `app/runtime_monitor.py` / `app/runtime_metrics.py` / `app/capability_metrics.py`, the middleware metric-recording and the capability-counter increment (both behavior-neutral), the worker heartbeat write, and the new settings. No migration, no schema, no data, and no change to any existing route's behavior; the OpenAPI change is purely additive (one new GET).

**Open, needs an owner decision**: a consumer that actually *watches* this summary (a scheduled poll + alert on a degraded dependency/worker, or shipping the `runtime.degraded` `reliability_event` to a log-based alert). Pull-only until then.

## What "before any production deployment" requires, restated plainly

Per `CLAUDE.md`'s Production boundary section, local completion (everything above that says "real" or "exists") does not equal production readiness. Before treating this app as monitored in a real deployment, the owner needs to make three concrete decisions this document cannot make on its own:

1. **Pick an external uptime checker** and point it at `/ready`. (Section 1 — trivial once decided, the endpoint already does the real work.)
2. **Pick a log destination** (or accept the minimum-viable grep-and-alert script) so error-rate and security-event data already being logged actually reaches a human. (Sections 2-3.)
3. **Pick a disk-space alerting mechanism** for the production host. (Section 4 — currently the single biggest concrete gap, since zero code or infrastructure exists for it today.)

None of these three have been configured as part of this Part H pass — doing so requires choosing and likely paying for an external service, which is exactly the kind of decision this project's own rules (`AGENTS.md`'s stop conditions: "spending money," "any cloud provider action") require the owner to make explicitly, not something to guess at or silently wire up.
