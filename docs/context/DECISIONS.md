# Decisions

Purpose: lightweight architecture decision record for verified repository choices.
Information owner: repository maintainers and owners approving architectural direction.
Read when: changing architecture, auth, deployment, or data flow.
Update when: a decision is made, superseded, or explicitly revisited.
Last verified date: 2026-07-19.
Relevant sources: `git show 060ab68 --stat --summary`, `app/main.py`, `app/auth.py`, `app/config.py`, `app/services/openai_web.py`, `app/services/optimus_chat.py`, `docker-compose.yml`, `ops/nginx/default.conf`, `alembic/versions/002_authentication_tables.py`.

## ADR-001

- ID: ADR-001
- Date: 2026-07-01
- Status: Accepted
- Context: The repository is centered on a FastAPI backend and already ships authenticated API routes.
- Decision: Retain FastAPI as the backend until an approved architecture decision changes it.
- Alternatives considered: replacing the backend stack or introducing a second server framework.
- Consequences: routing, tests, and docs should continue to treat FastAPI as the current backend.
- Files affected: `app/main.py`, `app/auth.py`, `app/config.py`, `tests/test_api.py`.
- Revisit if: an approved migration plan replaces the current backend framework.

## ADR-002

- ID: ADR-002
- Date: 2026-07-01
- Status: Accepted
- Context: Chat and research features use OpenAI and web lookup from the server side.
- Decision: Keep the OpenAI gateway on the server, not in the browser.
- Alternatives considered: browser-side API calls or exposing API keys to client code.
- Consequences: browser code must never receive server API keys.
- Files affected: `app/services/openai_web.py`, `app/services/optimus_chat.py`, `app/main.py`.
- Revisit if: a new approved security design changes the trust boundary.

## ADR-003

- ID: ADR-003
- Date: 2026-07-01
- Status: Accepted
- Context: The frontend currently fetches API paths from the same origin through Nginx.
- Decision: Keep same-origin frontend API calls using `/api/...`.
- Alternatives considered: cross-origin browser API calls or direct backend calls from client code.
- Consequences: the Nginx proxy remains part of the local browser path.
- Files affected: `ops/nginx/default.conf`, `app/static/app.js`, `app/main.py`.
- Revisit if: a new approved frontend deployment topology changes the origin model.

## ADR-004

- ID: ADR-004
- Date: 2026-07-01
- Status: Accepted
- Context: Authentication is already implemented as server-side sessions.
- Decision: Use HttpOnly cookie authentication for browser sessions.
- Alternatives considered: browser-stored bearer tokens or localStorage-based auth.
- Consequences: browser JavaScript cannot read the auth cookie.
- Files affected: `app/auth.py`, `app/main.py`, `tests/test_auth.py`, `app/static/index.html`.
- Revisit if: an approved auth redesign replaces cookie-backed sessions.

## ADR-005

- ID: ADR-005
- Date: 2026-07-01
- Status: Accepted
- Context: Auth tables were added to the database.
- Decision: Store users and sessions in PostgreSQL.
- Alternatives considered: SQLite-only auth persistence or file-based state.
- Consequences: Alembic migrations must remain the source of truth for schema changes.
- Files affected: `alembic/versions/002_authentication_tables.py`, `app/db_models.py`, `app/auth.py`.
- Revisit if: an approved storage redesign changes the persistence layer.

## ADR-006

- ID: ADR-006
- Date: 2026-07-01
- Status: Accepted
- Context: Owner passwords must not be stored in plaintext.
- Decision: Hash passwords with Argon2.
- Alternatives considered: plaintext passwords or weaker hashing.
- Consequences: password verification stays server-side and tests should cover it.
- Files affected: `app/auth.py`, `tests/test_auth.py`, `tests/test_security.py`.
- Revisit if: an approved security review mandates a different password hashing standard.

## ADR-007

- ID: ADR-007
- Date: 2026-07-01
- Status: Accepted
- Context: Browser sessions are stored in a database table.
- Decision: Hash session tokens before storing them.
- Alternatives considered: raw token storage or bearer-token persistence in the browser.
- Consequences: the database does not contain reusable raw session tokens.
- Files affected: `app/auth.py`, `app/db_models.py`, `tests/test_auth.py`.
- Revisit if: an approved auth redesign changes token storage semantics.

## ADR-008

- ID: ADR-008
- Date: 2026-07-01
- Status: Accepted
- Context: Local development and deployment are already orchestrated through Compose.
- Decision: Use Docker Compose for the current deployment stage.
- Alternatives considered: ad hoc process management or a Kubernetes stack.
- Consequences: startup, health, and readiness commands should keep referencing Compose.
- Files affected: `docker-compose.yml`, `scripts/optimusctl.sh`, `docs/UBUNTU_DEPLOYMENT_REPORT.md`.
- Revisit if: an approved deployment plan introduces a different stage target.

## ADR-009

- ID: ADR-009
- Date: 2026-07-01
- Status: Accepted
- Context: There is no approved Kubernetes deployment in the repository.
- Decision: Do not introduce Kubernetes at the current stage.
- Alternatives considered: Kubernetes manifests or cluster orchestration.
- Consequences: deployment docs should stay aligned with Compose and local stack usage.
- Files affected: `docker-compose.yml`, `docs/context/ARCHITECTURE.md`, `docs/context/CURRENT_STATE.md`.
- Revisit if: a production deployment decision explicitly adopts Kubernetes.

## ADR-010

- ID: ADR-010
- Date: 2026-07-01
- Status: Accepted
- Context: The repository contains generated `dist/` artifacts from packaged builds.
- Decision: Do not edit generated dist files directly.
- Alternatives considered: patching generated bundles in place.
- Consequences: source changes must land in real source files and then be regenerated.
- Files affected: `dist/`, `app/`, `docs/`.
- Revisit if: a future packaging workflow changes the generated-artifact policy.

## ADR-011

- ID: ADR-011
- Date: 2026-07-09
- Status: Accepted
- Context: Phase 5 (Private Staging) requires a separate host/environment; the roadmap explicitly calls for deciding where staging will live before Phase 5 stalls on unmade infrastructure decisions. This is a real-money, real-credentials decision that requires the owner's direct choice, not an autonomous one.
- Decision: Staging will be hosted on a DigitalOcean droplet (recommended over Hetzner Cloud for setup simplicity/documentation quality at a small cost premium), with the domain registered through Cloudflare (at-cost registration, and Cloudflare's free proxy/DNS will terminate HTTPS at the edge, satisfying the HTTPS/HSTS requirement without self-managed TLS certificates).
- Alternatives considered: Hetzner Cloud (cheaper, stricter signup, less beginner-friendly docs); a managed PaaS (Railway/Render/Fly.io) instead of a raw VPS (less ops work, but a bigger departure from the existing Docker Compose deployment model already decided in ADR-008).
- Consequences: actual account creation, payment setup, droplet provisioning, and domain purchase are owner actions — no agent can perform these (real credentials, spending money, cloud provider actions all require explicit owner action per `AGENTS.md`). Once the droplet and domain exist, deployment configuration (Compose on the droplet, Cloudflare DNS/proxy settings, secrets handling) can proceed as agent-assisted work.
- Files affected: `docs/context/PLANS.md`, `docs/context/CURRENT_STATE.md`, `docs/context/SESSION_HANDOFF.md`.
- Revisit if: cost, region/latency requirements, or a preference change makes a different provider or a managed PaaS more suitable.

## ADR-012

- ID: ADR-012
- Date: 2026-07-14
- Status: Accepted
- Context: The release process required a way to prevent an application version from starting against a database schema it doesn't understand, without breaking the existing documented deploy runbook (`scripts/optimusctl.sh update` then a separate `migrate` step), which creates a normal, expected window where new app code runs briefly against old-but-compatible schema.
- Decision: `app/migration_compat.py::check_schema_compatibility()` classifies the database's schema state relative to the app's own Alembic head into five states (`matched`, `behind`, `unmigrated`, `unsupported`, `unreachable`). Only `unsupported` and `unreachable` are treated as unsafe to serve; `behind` and `unmigrated` are tolerated. Schema incompatibility degrades `/ready` (`status: "degraded"`, kept out of load-balancer rotation) rather than crashing the process outright.
- Alternatives considered: crashing/refusing to start the process on any schema mismatch (rejected — would turn the runbook's normal deploy-order window into a routine outage, since `update` runs before `migrate`); doing no compatibility check at all (rejected — silently serving against an unrecognized/future/diverged schema is exactly the failure mode this decision exists to prevent).
- Consequences: the deploy runbook's `update`-then-`migrate` ordering remains safe by design, not by luck; a genuinely unsupported schema (future revision this app predates, or a diverged history) correctly blocks readiness instead of serving unpredictable behavior. Changing which states block readiness requires updating this ADR and `docs/context/RELEASE_CHECKLIST.md` together, since the deploy runbook depends on the current tolerance boundary.
- Files affected: `app/migration_compat.py`, `app/main.py`, `tests/test_migration_compat.py`, `tests/test_api.py`, `docs/context/RELEASE_CHECKLIST.md`.
- Revisit if: the deploy runbook's ordering changes (e.g., migrations always run before the app restarts), which would remove the need to tolerate `behind`/`unmigrated`.

## ADR-013

- ID: ADR-013
- Date: 2026-07-19
- Status: Accepted
- Context: The multi-shop pilot needs self-service recovery, session control, delegated invitations, durable account status, and a future MFA integration without storing reusable recovery or factor secrets in plaintext.
- Decision: Keep authentication lifecycle state in PostgreSQL; store password-reset and invitation tokens as hashes only; enforce account and membership status together; revoke sessions and outstanding grants on security-sensitive lifecycle changes; revalidate inviter authority at acceptance; and represent MFA factors with provider-neutral external references and lifecycle metadata rather than raw shared-secret columns.
- Alternatives considered: stateless reset/invitation tokens, application-memory lockout, trusting authority captured only when an invitation was created, or storing TOTP/shared secrets directly in the core account table.
- Consequences: lifecycle changes are auditable and transactionally enforceable across app restarts; public token responses remain generic; concurrent provisioning paths must share database row locks; an eventual MFA provider can be integrated without a schema redesign that exposes raw factor material.
- Files affected: `alembic/versions/029_account_lifecycle.py`, `app/account_security_store.py`, `app/auth.py`, `app/db_models.py`, `app/main.py`, `app/technician_store.py`, `tests/test_account_security_api.py`, `tests/e2e/test_account_lifecycle_concurrency.py`.
- Revisit if: an approved identity provider becomes the system of record for accounts/sessions or requires a different factor-secret custody model.

## ADR-014

- ID: ADR-014
- Date: 2026-07-20
- Status: Accepted
- Context: A Laravel 12 + Livewire 4 proof-of-concept was built and evaluated (per an approved investigation) to decide whether OptimusOS should migrate off FastAPI. This is a pointer entry, not the full record — see below for where the complete analysis lives, since it was large enough to warrant its own directory rather than inline text here.
- Decision: Retain and simplify the existing FastAPI/JavaScript OptimusOS. Do not migrate to Laravel, begin a phased Laravel rewrite, or run two production applications. This reaffirms ADR-001 above now that the alternative has actually been evaluated, not just deferred. The full verified comparison, weighted decision matrix, two architecture lessons the PoC surfaced (vehicle ownership modeling, environment/database validation), an 8-item ADR set (ADR-014 through ADR-021, continuing this file's numbering but held in their own files), the roadmap, and the first security-kernel phase all live in `docs/architecture/`.
- Alternatives considered: a phased Laravel migration and a full Laravel rebuild — both rejected; full reasoning in `docs/architecture/STACK-DECISION.md` §2-3.
- Consequences: Phase 1 (extracting and hardening the existing security kernel) is now the approved next implementation step, before any prompt/manual shared-execution or Sentinel work begins. The Laravel PoC repository (`/home/dejake/optimus-laravel-poc/`) is retained as research evidence, not deleted, and is not deployed.
- Files affected: `docs/architecture/README.md`, `docs/architecture/STACK-DECISION.md`, `docs/architecture/adr/ADR-014-*.md` through `ADR-021-*.md`, `docs/architecture/PHASE1-SECURITY-KERNEL-PLAN.md`.
- Revisit if: a future, separately-approved architecture review changes this decision — as a new dated ADR, never by editing `docs/architecture/STACK-DECISION.md`'s body.
## ADR-022

- ID: ADR-022
- Date: 2026-07-20
- Status: Accepted — implemented (non-enforcing). Foundation + owner-only non-blocking post-signup onboarding merged (PR #81, merge commit `7050bb8`, migration head `035_operating_mode_confirmed_at`); no capability enforcement has shipped (Bays OBSERVE-only). Full status in the linked ADR's implementation-status amendment.
- Context: This is a pointer entry, not the full record — the OptimusOS `/goal` roadmap requires one codebase to support three operating modes (Solo, Mobile Field, Shop) plus a Technician role workspace, and existing subscription tiers, without duplicated business logic. The full inventory, capability matrix, domain model, capability-resolution service design, safe-transition rules, role-vs-mode boundaries, Optimus prompt-first rules, Mobile Field gap analysis, reversible implementation slices, and route classification live in `docs/architecture/OPERATING-MODES-ARCHITECTURE-BRIDGE.md`.
- Decision: Operating mode and subscription tier are separate, service-resolved axes — one backend capability service (modeled on the existing `effective_shop_id()` tenant-boundary precedent, ADR-019) is the single point every route, store function, the manual UI, and any future AI action must call; UI hiding alone is never sufficient enforcement; hidden data is never deleted. Full reasoning in `docs/architecture/adr/ADR-022-operating-mode-tier-separation.md`.
- Alternatives considered: forking the codebase per mode, encoding mode as a tier attribute, gating via a general-purpose feature-flag service, and renaming modes to avoid their word overlap with existing tier names — all rejected; full reasoning in the linked ADR.
- Consequences: implemented as non-enforcing slices per the linked document's §9 (capability-resolution service, OBSERVE-only Bays pilot, owner/manager settings-based operating-mode management, capability-shaped navigation, and owner-only non-blocking post-signup onboarding). Every future mode/tier-aware behavior must go through the one capability service. No capability **enforcement** has shipped: Bays stays OBSERVE-only and an AST safeguard blocks any route from referencing `CapabilityGateMode.ENFORCE`; hidden data is never deleted.
- Files affected: `docs/architecture/README.md`, `docs/architecture/OPERATING-MODES-ARCHITECTURE-BRIDGE.md`, `docs/architecture/adr/ADR-022-operating-mode-tier-separation.md`.
- Revisit if: implementation of any slice in the linked document's §9 finds the single-service model cannot express a real requirement.

## ADR-023

- ID: ADR-023
- Date: 2026-07-22
- Status: Accepted — implemented and merged (Phase 2A, PR #83, merge commit `b81aad5`). Revised after review: platform-support-only, bounded collection, label-not-path, and an explicit deployment boundary. This endpoint provides *process-visibility* only; it does NOT directly provide production host/Docker monitoring (see Consequences).
- Context: Phase 2 (observability) begins with disk/Docker-storage visibility — the roadmap's stated first priority after the volume incident. `docs/context/MONITORING.md` recorded that no in-app disk monitoring existed and framed it as infrastructure-only; a read-only, platform-support-only in-app endpoint gives a support operator on-demand visibility (and a throttled structured warning signal) into what the application process can see, without standing up an external stack — while real host monitoring remains a separate least-privileged collector.
- Decision: add one additive, read-only endpoint `GET /api/operations/storage`, gated **support-only** by the existing `require_support_context`/`SupportAuthContextDep`. It is platform-infrastructure telemetry, so shop owners, managers, technicians, suspended-shop accounts, unauthenticated callers, and impersonated-owner sessions (which carry role `owner`) are all denied; the endpoint is not shop-scoped. Stateless collection lives in a stdlib-only leaf (`app/storage_monitor.py`, dependency-injected host/Docker boundaries, modeled on `app/net.py`); a bounded-collection service (`app/operations_monitor.py`) adds a TTL cache + single-flight so at most one `docker system df` (5s timeout) runs per TTL window, and throttles the reliability warning to a severity transition or a cooldown. It converts the expected host, subprocess, and malformed-output failures (missing/timed-out/erroring Docker, unparseable or oversized `df` measurements, unreadable filesystem) into sanitized `unknown`/`unavailable` results rather than raising, and never mutates any host/Docker resource (`docker system df` only; no other subcommand). Responses expose a non-sensitive target **label** (never the raw `DISK_MONITOR_PATH`), carry `freshness`/`collected_at`/`age_seconds`, set `Cache-Control: no-store`, and are rate-limited via the existing limiter registry. Threshold crossings emit a secret-free `reliability_event` log line (operational, not the curated `SecurityEventType` taxonomy) identifying the support actor by role + internal id only. Docker `unavailable` (and partial/truncated `df` output) is kept distinct from a healthy zero-usage state.
- Alternatives considered: gating owner+support (rejected on review — infrastructure telemetry must not be exposed to shop owners); returning the raw filesystem path (rejected — replaced with a non-sensitive label to prevent host-path disclosure); collecting per request (rejected — replaced with TTL cache + single-flight to bound Docker subprocess amplification); mounting `/var/run/docker.sock` or the Postgres data volume into the internet-facing backend to see real host/Docker (rejected — widens the attack surface of a web service; real coverage is a separate least-privileged host collector/sidecar/hosting metric/script); a `docker` SDK / `psutil` dependency (rejected — stdlib `shutil.disk_usage` + a read-only `docker system df` keep the minimal-dependency posture).
- Consequences: a support operator has an in-app, process-visibility disk/Docker signal, but **this is not production host monitoring**: it reports only what the app process can see, and by default the hardened backend container has no Docker socket and does not mount the Postgres data volume, so from there Docker is `unavailable` and the filesystem is the container root. Real host/Docker monitoring requires a separate least-privileged collector (no socket/volume mounting into the web backend is done or authorized here). The endpoint is also pull-only until a consumer watches its `reliability_event` logs. Additive and revert-safe: no migration, no schema, no change to any existing route/behavior; the OpenAPI change is one new GET. Documented in `MONITORING.md` §4 and `KNOWN_ISSUES.md`.
- Files affected (implementation and tests): `app/storage_monitor.py`, `app/operations_monitor.py`, `app/config.py`, `app/models.py`, `app/main.py`, `.env.example`, `tests/test_storage_monitor.py`, `tests/test_operations_monitor.py`, `tests/test_operations_storage_api.py`, `tests/test_role_isolation.py`. Documentation updated per the context-update rules: `docs/context/MONITORING.md` (§4), `docs/context/CURRENT_STATE.md`, `docs/context/KNOWN_ISSUES.md`, `docs/context/SESSION_HANDOFF.md`, and this `docs/context/DECISIONS.md` entry. (The owner-or-support gate that briefly touched `app/auth.py`/`app/api/deps.py` in an earlier draft was reverted; both are net-unchanged from `main`.)
- Revisit if: the next slice (worker or `/ready` integration) is built, or real usage shows the process-visibility scope or bounded-collection parameters need adjustment. Any move toward real host coverage must go through a separate least-privileged collector, never by widening this backend's access.

## ADR-024

- ID: ADR-024
- Date: 2026-07-23
- Status: Accepted — implemented (Phase 2B, branch `agent/claude/phase2b-runtime-observability`, draft PR pending). Additive slice on top of merged Phase 2A (ADR-023). Process-visibility only; NOT production host monitoring (same boundary as ADR-023).
- Context: Phase 2 (observability) continues after the Phase 2A storage endpoint with a consolidated, read-only *runtime* summary a platform-support operator can inspect on demand — request traffic/latency, dependency reachability, background-worker liveness, work-queue condition, capability-observe rollups, and the reused storage snapshot — without standing up an external metrics/log stack or exposing any unauthenticated `/metrics` surface. Recorded in `docs/context/MONITORING.md` §6.
- Decision: add one additive, read-only endpoint `GET /api/operations/summary`, gated **support-only** by the existing `require_support_context`/`SupportAuthContextDep` (same platform-infrastructure rejections as ADR-023: owner/manager/technician/suspended/unauthenticated/impersonated-owner all denied). It assembles six non-sensitive signals: (1) in-process request metrics from a bounded registry (`app/runtime_metrics.py`) the request-context middleware feeds, labelled by **route template** (never a raw path/id) with capped cardinality; (2) Postgres/Redis TCP reachability via the same fail-safe probe `/ready` uses; (3) a background-worker heartbeat — the worker (`scripts/optimus_worker.py`) writes a single fixed Redis key with a bounded TTL (validated ≥ 2× its write interval), value = one epoch second, and the summary reads it as `alive`/`stale`/`missing`/`unknown`; (4) a work-queue condition that is **off by default** (`WORKER_QUEUE_REDIS_KEY` empty ⇒ `not_configured`, no Redis touched), with an opt-in bounded `LLEN` read only if a real Redis list is ever configured; (5) OBSERVE-only capability-decision counters (`app/capability_metrics.py`), rolled up beside the existing `authz.capability_observed` event; (6) the Phase 2A storage snapshot **reused from cache** via a new `peek_snapshot()` that never re-collects (the summary never launches `docker system df`). The dependency/worker/queue signals are served from a TTL cache + single-flight (`app/runtime_monitor.py`, modeled on `app/operations_monitor.py`); the endpoint is rate-limited via the existing registry, sets `Cache-Control: no-store`, and emits a throttled secret-free `reliability_event: runtime.degraded` (operational, not the curated `SecurityEventType` taxonomy) identifying the support actor by role + internal id only.
- Alternatives considered: an unauthenticated Prometheus-style `/metrics` scrape endpoint (rejected — the spec forbids a new unauthenticated diagnostic surface and any scraping secret/bearer/IP-allowlist bypass; this is support-gated instead); fabricating a Redis work-queue to satisfy the "queue condition" requirement (rejected — no application queue exists and ADR-014 records a future queue would be Postgres `SKIP LOCKED`, not Redis, so the summary reports the *true* `not_configured` condition and never invents one); re-collecting storage inside the summary (rejected — reuses the Phase 2A cache via `peek` so no second Docker subprocess is ever launched); per-request dependency probing (rejected — TTL cache + single-flight bounds it, mirroring ADR-023); labelling request metrics by raw path (rejected — route templates only, capped cardinality, to keep labels bounded and PII/path-free); flipping any capability gate to ENFORCE to power the counters (rejected — counters are OBSERVE-only, Bays stays OBSERVE-only, the AST safeguard is untouched).
- Consequences: a support operator has a single in-app, process-visibility runtime summary, but **this is not production host monitoring** (same boundary as ADR-023) and it is **pull-only** until a consumer watches its `runtime.degraded` logs or polls it. The still-present background worker gains one small, real, bounded responsibility (the heartbeat), which partly supersedes `PHASE2-READINESS.md` §2A's (never-executed) "remove the worker as a no-op" evaluation; if the worker is later removed the heartbeat simply reads `missing`/`unknown` (fail-safe). No capability enforcement ships; Bays stays OBSERVE-only. Additive and revert-safe: no migration, no schema, no change to any existing route's behavior; the OpenAPI change is one new GET. Documented in `MONITORING.md` §6 and `KNOWN_ISSUES.md`.
- Files affected (implementation and tests): `app/runtime_metrics.py`, `app/capability_metrics.py`, `app/runtime_monitor.py`, `app/operations_monitor.py` (added `peek_snapshot`), `app/observability.py` (middleware records metrics), `app/capability_gate.py` (increments OBSERVE counters), `app/config.py`, `app/models.py`, `app/main.py`, `scripts/optimus_worker.py`, `.env.example`, `tests/test_runtime_metrics.py`, `tests/test_capability_metrics.py`, `tests/test_runtime_monitor.py`, `tests/test_request_metrics_middleware.py`, `tests/test_runtime_config.py`, `tests/test_operations_summary_api.py`, `tests/test_operations_monitor.py` (peek cases), `tests/test_role_isolation.py` (route classification). Documentation: `docs/context/MONITORING.md` (§6), `docs/context/CURRENT_STATE.md`, `docs/context/KNOWN_ISSUES.md`, `docs/context/SESSION_HANDOFF.md`, and this entry.
- Revisit if: a real Redis (or Postgres `SKIP LOCKED`) work queue is introduced (wire the queue condition to it), a consumer is built to watch/poll this summary, or request-metric cardinality/latency-aggregation needs (e.g. percentiles) outgrow the current bounded aggregates.
- **Note for future entries in this file:** the next available number in this file's own sequence is **ADR-025**.
