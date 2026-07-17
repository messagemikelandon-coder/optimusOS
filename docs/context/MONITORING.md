# Monitoring Requirements

Purpose: the Phase 6 Part H deliverable for production monitoring — what OptimusOS already exposes for monitoring, what's genuinely wired up today, and what still requires an owner decision (an external monitoring service, alert destination, and credentials) before it can be called "active." Per `CLAUDE.md`'s explicit instruction, nothing in this document should be read as a claim that monitoring is operational unless a section says so plainly.
Information owner: repository maintainers and the owner responsible for production infrastructure decisions.
Read when: before any production deployment decision; when diagnosing a real outage; when choosing an external monitoring/alerting service.
Update when: an external monitoring service is actually configured, a new health signal is added to `/health`/`/ready`, or a disk-space/alerting gap is closed.
Last verified date: 2026-07-17.
Relevant sources: `app/main.py` (`/health`, `/ready`), `app/observability.py`, `app/security_events.py`, `docker-compose.yml`, `docs/context/RELEASE_CHECKLIST.md`.

## Status today: what exists vs. what's active

**Exists and is real (verified by reading the code, not assumed):**
- `GET /health` — liveness: app version, git commit, migration head, and whether OpenAI/Square/owner-auth are configured. Always returns `200` if the process is up; does not check dependencies.
- `GET /ready` — readiness: checks real TCP reachability of Postgres and Redis, and runs a real schema-compatibility check (comparing the connected database's `alembic_version` against this app's known migration chain). Returns `"status": "ready"` only when Postgres, Redis, and schema compatibility are all healthy; degrades to `"status": "degraded"` (not a crash) otherwise, with `dependencies.postgres`/`dependencies.redis`/`schema_compatibility` broken out so a human or a monitor can tell which dependency is the problem.
- Structured JSON request/error logging (`app/observability.py`) — every request logs one correlated line with method/path/status/duration, and every unhandled exception is logged and classified before the response is returned.
- Structured security-event logging (`app/security_events.py`, Phase 6 Part H) — login failures/successes, rate-limit-exceeded events, and Square API failures are tagged with a `security_event` field, independently filterable from ordinary request logs.

**Does not exist / is not active today:**
- No external uptime/health-check service is configured against `/health` or `/ready` on any real deployment. Nothing currently pages anyone if the app goes down.
- No log aggregation destination is configured. Structured JSON logs go to stdout (captured by `docker compose logs` locally, or whatever the deployment host does with container stdout) — there is no shipped-to-a-dashboard pipeline today.
- No disk-space monitoring exists anywhere in this codebase. A full disk on the Postgres data volume or the application host would not be detected by `/health`, `/ready`, or anything else here before it caused a real outage.
- No alerting (email/SMS/Slack/PagerDuty/etc.) is wired to any of the above. A `"degraded"` `/ready` response or a logged `security_event` today is only visible to someone actively looking.

## Required monitoring surface, and how to close each gap

### 1. Liveness/readiness (health/readiness)
**Already real, nothing to build.** Point any external uptime checker (a cheap, common choice: UptimeRobot, Better Uptime, a cron+curl+webhook, or the cloud host's own load-balancer health check) at `GET /ready`. Alert on a sustained non-`200` or `"status": "degraded"` response, not a single blip — `/ready`'s dependency checks use a 1-second TCP timeout (`app/main.py::_tcp_dependency_ready`), so a single slow-but-recovering check is expected occasionally under real network conditions.

**Open, needs an owner decision**: which external service to use, and who receives the alert. Not chosen yet.

### 2. Error rate / application errors
**Partially real.** Every unhandled exception is already logged as a structured, classified JSON line (`app/observability.py::install_request_context_middleware`) with a request id, so the *data* to detect an error-rate spike already exists in the log stream. What's missing is somewhere that *counts* these over time and alerts on a spike — that requires a log aggregation/metrics destination (see below), not new application code.

**Open, needs an owner decision**: a log-aggregation or metrics destination (examples: a hosted log service with alerting, or a self-hosted stack like Loki+Grafana or Prometheus+Grafana). Given this is currently a single-instance deployment, even a lightweight solution (e.g. a scheduled script that greps recent container logs for `"level": "ERROR"` and alerts past a threshold) would close most of this gap without new infrastructure — a reasonable minimum-viable option if a full observability stack isn't justified yet at this scale.

### 3. Security events
**Real as of this Part H pass**, same caveat as #2: the events are logged and structurally filterable (`security_event` field), but nothing currently watches the log stream for them. Once a log destination exists, alerting on `security_event: rate_limit.exceeded` occurring repeatedly from one source, or any `auth.login_failed` volume spike, is a reasonable first alerting rule to add.

### 4. Disk space
**Not implemented at all — the most concrete, easiest-to-close gap in this document.** Recommended minimum: a scheduled check (cron, or the hosting platform's own disk-usage alerting if it has one) on the host running the Postgres data volume, alerting below some free-space threshold (e.g. 15-20% free, adjusted for actual data growth rate once real usage history exists). This does not require any application code change — it's an infrastructure-level check against the host/volume, not something `/health` or `/ready` can see from inside the app container.

**Open, needs an owner decision**: the hosting platform's own disk-alerting capability (if the target host has one) vs. a small custom script; either is reasonable, neither is built yet.

### 5. Database health
**Partially real** — `/ready`'s Postgres check confirms real TCP reachability and a real schema-compatibility comparison, which catches "Postgres is down" and "the database schema doesn't match this app version" (both real, previously-tested failure modes — see `app/migration_compat.py` and its test suite). **Not covered**: connection-pool exhaustion, replication lag (not applicable today, single-instance Postgres), or slow-query buildup. None of these have been a real problem at this app's current single-shop scale; revisit if usage grows enough to make them plausible.

## What "before any production deployment" requires, restated plainly

Per `CLAUDE.md`'s Production boundary section, local completion (everything above that says "real" or "exists") does not equal production readiness. Before treating this app as monitored in a real deployment, the owner needs to make three concrete decisions this document cannot make on its own:

1. **Pick an external uptime checker** and point it at `/ready`. (Section 1 — trivial once decided, the endpoint already does the real work.)
2. **Pick a log destination** (or accept the minimum-viable grep-and-alert script) so error-rate and security-event data already being logged actually reaches a human. (Sections 2-3.)
3. **Pick a disk-space alerting mechanism** for the production host. (Section 4 — currently the single biggest concrete gap, since zero code or infrastructure exists for it today.)

None of these three have been configured as part of this Part H pass — doing so requires choosing and likely paying for an external service, which is exactly the kind of decision this project's own rules (`AGENTS.md`'s stop conditions: "spending money," "any cloud provider action") require the owner to make explicitly, not something to guess at or silently wire up.
