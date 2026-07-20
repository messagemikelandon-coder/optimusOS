# Phase 1 — Security Kernel: Completion Report

**Status:** Implemented on branch `agent/claude/architecture-decision-preservation` (not merged; `main` untouched). Awaiting review before any Phase 2 work.
**Governs:** ADR-020, per the plan in `PHASE1-SECURITY-KERNEL-PLAN.md`.
**Discipline honored:** extract/centralize/test/harden existing controls only. No Laravel/PHP, no new database, no new microservice, no destructive migration, no new dependency, no UI work, no vehicle-ownership implementation, no broad API-key lifecycle, no Sentinel autonomy. No authentication, authorization, validation, tenant-isolation, approval, or logging control was weakened.

---

## 1. Commit list (in order, each independently revertible)

| # | Commit | Subject |
|---|---|---|
| 1 | `bc25e0f` | security: remove unauthenticated OptimusInternetSkill bypass adapter |
| 2 | `ac5024e` | security: fail startup on unsafe production configuration |
| 3 | `a61c21e` | test: verified 429 coverage for all seven rate-limiter paths |
| 4 | `a8ac217` | security: normalize the security-audit event contract for Sentinel ingestion |
| 5 | `7b049e5` | security: centralize rate-limiter wiring into one registry; verify no bypass |
| 6 | `e4843d9` | test: positively assert tenant-scope enforcement across stores and jobs |
| 7 | `01728b6` | security: add shared secret-redaction utility and scrub structured logs |

(Preceded on the same branch by the documentation-only preservation commit `dbbcdac` and plan commit `ea529f5`.)

---

## 2. Files added, changed, removed

**Added (production):** `app/startup_checks.py`, `app/redaction.py`.
**Added (tests):** `tests/test_optimus_adapter_removed.py`, `tests/test_startup_checks.py`, `tests/test_rate_limit_endpoints.py`, `tests/test_security_events.py`, `tests/test_background_job_tenant_safety.py`, `tests/test_redaction.py`.
**Changed (production):** `app/main.py` (startup-check call; rate-limiter registry replacing 7 copy-pasted blocks; actor context on 7 Square audit sites; removed unused Redis imports), `app/security_events.py` (normalized `SecurityAuditEvent` contract + `ActorType`/`EventResult` + extended taxonomy, backward-compatible `log_security_event`), `app/rate_limit.py` (`RateLimiterRegistry`; generic overflow message), `app/observability.py` (redaction pass in the JSON formatter), `app/context_store.py` (imports shared `contains_secret`, behavior unchanged).
**Changed (tests/docs):** `tests/conftest.py` (identity-preserving test-settings accessor; registry reset), `tests/test_membership_tenant_boundary.py` (positive tenant-primitive assertion), `docs/context/RELEASE_CHECKLIST.md` (dropped the deleted adapter's mention).
**Removed:** `integration/optimus_adapter.py`, `INTEGRATION.md`, and its `MANIFEST.in` include line.

Net: +1315 / −360 across 19 files (excluding the architecture docs).

---

## 3. Test commands and results

All run with `env UV_CACHE_DIR=/tmp/uv-cache`:

- `uv run ruff format --check .` → 266 files already formatted.
- `uv run ruff check .` → All checks passed.
- `uv run pyright` → 0 errors, 0 warnings, 0 informations.
- `uv run pytest --ignore=tests/e2e` → **exit 0**, full fast unit/integration suite green (542 tests; +77 net-new Phase 1 tests, 0 pre-existing tests modified in a way that changed their assertions).
- **Real-Postgres production-parity boot check** (mimicking the CI e2e boot: throwaway `postgres:16-alpine`, `alembic upgrade head`, `uvicorn app.main:app` from a clean cwd with `APP_ENV=test`): `/health` → HTTP 200 `status: ok`; "Application startup complete", no validation error. Fail-closed variant (`APP_ENV=production` + blank secrets, real Postgres) → process refuses to boot with `UnsafeProductionConfigError` and no secret values in the message. Throwaway container removed.

Note on the Docker E2E/Playwright suite (`tests/e2e`): it is CI's job to run it, and it is expected green there because CI checks out no `.env`, so the harness's `APP_ENV=test` wins and the startup guard is a no-op. It was not run in full locally because this sandbox's real `.env` (production-mode with a short dev owner password, which these instructions forbid touching) would make a locally-booted e2e server correctly refuse to start — the new control working as designed, not a regression. The real-Postgres boot check above exercises the same boot path directly instead.

---

## 4. Controls consolidated

- **Rate limiting**: 7 copy-pasted lazy-singleton wiring blocks (~260 lines, 14 module globals) → one `RateLimiterRegistry`. Per-concern policy (limit/window/key/message) preserved at the call sites; the 7 `get_*` accessors retained (tests patch them by name).
- **Security-audit emission**: 4 incompatible ad-hoc shapes at the logging layer → one normalized `SecurityAuditEvent` contract (actor / tenant / request / action / resource / result / correlation-id / timestamp / metadata). `log_security_event` is now an adapter over it, fully backward compatible.
- **Secret handling**: the previously single-purpose `context_store` pattern list → one shared `app/redaction.py` with a clear split between conservative input-rejection (`contains_secret`, unchanged behavior) and value-only output-redaction (`redact_secrets`).
- **Startup/config validation**: logic that existed only in two never-invoked CLI scripts → one importable `validate_production_config` that gates real app boot.

---

## 5. Security gaps closed

- **CRITICAL** — the unauthenticated, tenant-unscoped, un-rate-limited `OptimusInternetSkill` AI bypass is deleted, with a regression test that fails if it (or an equivalent unguarded wrapper at that import path) returns.
- **HIGH** — production no longer boots with blank/placeholder/short-password secrets or a sqlite `DATABASE_URL`; it fails closed, without leaking values.
- **HIGH** — all seven rate limiters now have a test proving they actually return 429 (previously only four did), plus bypass tests proving forwarded headers and alternate endpoints don't escape a client's budget.
- **HIGH** — every structured security-audit event now carries a consistent actor type (user/service/api_key/background_job/ai_tool/anonymous), result, correlation id, and timestamp; the 7 Square audit sites gained real actor identity.
- **MEDIUM** — logs are scrubbed of secret-shaped values (API keys, bearer tokens, session-cookie values, password assignments, connection-URL credentials) as defense in depth, over the fully-serialized line.
- **MEDIUM** — a positive AST test now requires every store to resolve tenant scope through a canonical primitive (or a tiny justified allowlist), closing the "scopes on neither" blind spot; a background-job test locks in that the only worker touches no tenant data.

---

## 6. Remaining findings (not security-critical; recommended as their own later changes)

1. **ShopEvent DB-writer actor consistency** (MEDIUM→LOW): the 16 `ShopEvent` construction sites populate actor fields inconsistently. The table's columns are already schema-consistent, and much of the variance is *legitimate* (time-/system-triggered events like `trial_started` genuinely have no user actor). This is an audit-cosmetics improvement, not a security defect, and retrofitting 16 sites across the well-tested billing/support flows exceeds this phase's risk budget. Recommend a focused follow-up that adds a `record_shop_event()` helper and only changes the genuinely-incidental sites. **Deliberately not done here** to avoid a risky retrofit for no security gain.
2. **Message-sniffing error handlers** (MEDIUM): three handlers (`ContextStoreError`, `WorkOrderStoreError`, `EstimateStoreError`) choose an HTTP status by substring-matching the exception message, which is fragile. Their status codes are already pinned by existing tests, so behavior is safe today; the robust fix is typed exception subclasses, which touches store exception hierarchies and belongs in its own change.
3. **Two unrelated `request_id` concepts** (LOW): the per-request correlation id and an unrelated id inside `openai_web.research()` share a name. No functional bug; worth renaming when the AI path gets its Sentinel "agent run" id.

---

## 7. Deferred API-key lifecycle scope (as approved)

Per the approved decision, a broad API-key lifecycle product (a key-management UI, rotation system, per-key subscription limits, new commercial functionality) is **out of Phase 1 and not built**. What the existing single static OpenAI key path now has: it is validated at startup (shape + presence) instead of only by an un-run CLI script; it is never returned to the browser (pre-existing invariant, unchanged); its use is representable in the normalized audit contract via `ActorType.API_KEY`; and any value that leaks into a log is redacted. There is exactly one key and no runtime rotation/scoping/expiration/usage-tracking mechanism — building one is a genuine data-model design decision (most likely an `api_keys` table) that should be its own separately-approved sub-phase with its own ADR, not a rider on a consolidation phase.

---

## 8. Sentinel integration points now available (observation-only; no autonomy)

- **One normalized event contract** (`SecurityAuditEvent`) with the exact field set a Sentinel pipeline needs: tenant (`shop_id`), actor (typed), request, action, resource, result, correlation id, timestamp, metadata — emitted consistently by `log_security_event`.
- **An enumerable taxonomy** (`SecurityEventType`) extended with the sensitive-activity categories (access-denied, sensitive-read, record-written, approval-granted, api-key-used, support-access, security-setting-changed) a Sentinel consumer can subscribe to without new free-text types being invented at call sites.
- **A correlation id on every event**, sourced from the per-request context, so a Sentinel can stitch a security event to its full request-completion log line.
- **Redaction guaranteeing the stream is safe to ingest** — no secret reaches the log store, so forwarding logs to a Sentinel collector does not exfiltrate credentials.
- **A typed actor model including `background_job` and `ai_tool`**, so when the prompt/manual execution path (ADR-017) and any future job emit events, a non-request actor is first-class in the audit stream rather than indistinguishable from anonymous.

These are integration *points* only. No Sentinel code, no event consumer, no autonomous action, and no registered playbooks were added — that is later, separately-approved work per ADR-021's hard sequencing (security kernel → observation-only → playbook-gated action).

---

## 9. Phase 2 recommendation

Phase 1's definition of done is met and every CRITICAL/HIGH gap is closed. Recommended next step, **pending explicit approval** (do not start without it): **Phase 2 = deployment simplification (ADR-014)** — drop the no-op `worker` and the `frontend` nginx container (serve `app/static/` from FastAPI directly), and split `app/main.py`'s 178 endpoints into `APIRouter` modules. It is low-risk, independently valuable, unblocks a cleaner home for the future Command Center/plan-executor endpoints, and is well-protected by the existing 542-test suite plus the CI docker-compose + backup/restore/rollback rehearsal. The prompt/manual shared-execution feature (ADR-017) and vehicle-ownership history (ADR-015) remain gated behind it per the roadmap.

Do not begin Phase 2 without approval.
