# /goal Evidence Matrix — OptimusOS Multi-Shop Pilot Readiness

Purpose: evidence-based reconciliation of the `/goal` multi-shop pilot specification against actual, verified repository state — not documentation claims, not aspiration. Built 2026-07-17 as Phase 0 of the `/goal` roadmap.
Information owner: the active session author.
Read when: deciding what `/goal` work remains, or auditing a completion claim against this matrix.
Update when: a `/goal` requirement's status changes.
Verification method: direct source/migration/test/CI inspection this session, not carried forward from prior docs. Where a claim could not be independently re-verified in this pass, it is marked accordingly.

## How to read this matrix

- **Status**: `Complete` (implemented + migrated + tested + CI-covered), `Partial` (some but not all of those), `Absent` (not built), `Blocked` (needs owner/credentials).
- Percentages and "Complete" statuses in this document are the authoritative basis for Phase 17's final readiness report — that report must not claim more than what's justified here.

## Part A — Existing single-shop baseline (verify, don't rebuild)

| Requirement | Implementation | Source | Migration | Tests | CI | Status |
|---|---|---|---|---|---|---|
| FastAPI app | `app/main.py`, ~3900 lines, 100+ routes | `app/main.py` | — | full suite | lint-typecheck-test | Complete |
| SQLAlchemy + Alembic + Postgres | `app/db.py`, `app/db_models.py`, `alembic/versions/001-021` | linear chain, single head confirmed | migration CI job | migrations job | Complete |
| Redis (rate limiting) | `app/rate_limit.py::RedisSlidingWindowRateLimiter` | — | `tests/test_rate_limit.py` (real Redis, skipped if unreachable) | Redis service in lint-typecheck-test job | Complete |
| Docker Compose | `docker-compose.yml`, `ops/docker-compose.staging.yml` | — | — | docker-compose-integration job | Complete |
| Owner/technician auth | `app/auth.py`, migration `011_multi_role_auth` | 011 | `tests/test_role_isolation.py`, `tests/test_technicians_api.py` | full suite | Complete |
| Customers/Vehicles | `app/customer_store.py`, `app/vehicle_store.py` | `004`, `005` | `tests/test_context_api.py` + others | full suite | Complete |
| Estimates/revisions/approvals | `app/estimate_store.py` | `006` | `tests/test_estimate_approval_api.py` | full suite | Complete |
| Work orders | `app/work_order_store.py` | `007` | `tests/test_work_orders_api.py` | full suite | Complete |
| Invoices | `app/invoice_store.py` | `008` | `tests/test_invoices_api.py` | full suite | Complete |
| Payments | `app/payment_store.py` | `009` | `tests/test_payments_api.py` | full suite | Complete |
| Notifications | `app/notification_store.py` | `010` | `tests/test_notifications_api.py` | full suite | Complete |
| Square sandbox | `app/square_store.py` | `010` | `tests/test_square_api.py` | full suite | Complete (sandbox only, no production credentials, by design) |
| Technicians + time tracking | `app/technician_store.py` | `012` | `tests/test_technicians_api.py` | full suite | Complete |
| Service Desk intake | `app/intake_store.py` | `014` | `tests/test_service_desk_api.py` | full suite + `optimus-security-reviewer` PASS (2026-07-17) | Complete |
| Diagnostics/Inspections | `app/diagnostics_store.py`, `app/inspection_store.py` | `015`, `019` | `tests/test_diagnostics_and_inspections_api.py` | full suite + `optimus-security-reviewer` PASS | Complete |
| Vendors/Parts/POs/Receiving/Allocation | `app/vendor_store.py`, `app/part_store.py`, `app/purchase_order_store.py`, `app/part_allocation_store.py` | `013`, `020`, `021` | `tests/test_vendors_and_parts_api.py`, `tests/test_purchase_orders_api.py`, `tests/test_part_allocations_api.py` | full suite + `optimus-security-reviewer` PASS with 1 fixed finding (technician cost-leak) | Complete |
| Scheduling | `app/scheduling_store.py` | `016` | `tests/test_scheduling_api.py` + `tests/e2e/test_scheduling_concurrency.py` (real-Postgres row-lock proof) | full suite + e2e | Complete |
| Reports | `app/report_store.py` | uses existing tables | `tests/test_reports_api.py` + `optimus-security-reviewer` PASS | full suite | Complete |
| Authenticated Playwright core workflow | `tests/e2e/test_core_workflow.py` | — | 1 test, real browser/Postgres/sessions | e2e-core-workflow job | Complete, narrow scope (one linear workflow only) |
| Structured logs, request IDs | `app/observability.py` | — | `tests/test_observability.py` | full suite | Complete |
| Security-event logging | `app/security_events.py` | — | included in `tests/test_api.py` | full suite + `optimus-security-reviewer` PASS on Part H code | Complete |
| OpenAI usage logging | `app/services/openai_web.py::_log_usage`/`_estimate_cost_usd` | `Settings` cost fields | `tests/test_openai_research.py` | full suite | Complete (cost only when owner configures pricing, never fabricated) |
| Release versioning + migration compatibility | `app/__init__.py.__version__` (`7.1.0`), `app/migration_compat.py` | — | `tests/test_release.py`, `tests/test_migration_compat.py` | full suite | Complete |
| Release/rollback docs | `docs/context/RELEASE_CHECKLIST.md` | — | — | — | Complete (docs only; real droplet execution needs owner credentials) |

**Part A conclusion**: the single-shop baseline the goal describes as "substantial... but verify all of it" is genuinely real, tested, and CI-covered. No rebuild needed. Phases 1-2 harden it; Phases 3+ are net-new.

## Part B — Request concurrency (Phase 1 target)

| Requirement | Current state | Evidence | Status |
|---|---|---|---|
| Async routes not blocking the event loop | **Fixed 2026-07-17 (PR #50).** Every route in `app/main.py` now offloads its blocking work via `await asyncio.to_thread(...)`. Applied via an AST script, then independently re-verified twice more (once by an `optimus-reviewer` pass, once by a stricter import-AST script) after the first pass was found to have missed `payment_store.py`'s two exports plus `/ready`'s and `ensure_context_dependencies`'s local blocking calls — all fixed, zero remaining unwrapped call sites confirmed. | `tests/e2e/test_request_concurrency.py` (2 tests, both confirmed to fail against pre-fix code); full fast + e2e suites green; `docs/context/KNOWN_ISSUES.md`'s "Request-level concurrency fixed" entry. | Complete |
| Single-worker deployment | `Dockerfile:25`: `CMD ["uvicorn", "app.main:app", ...]`, no `--workers` flag. **Deliberately unchanged** — the `asyncio.to_thread` fix above doesn't need multiple workers, and adding them would require a separate process-local-singleton audit (rate limiters, `tests/conftest.py`'s reset fixture) explicitly out of this phase's scope per `/goal`'s own instruction. | Direct grep | Confirmed, deliberately not changed (documented capacity limit, see KNOWN_ISSUES.md) |
| Row-lock correctness under real concurrency | Proven for Scheduling (`tests/e2e/test_scheduling_concurrency.py`, revert-and-recheck verified) and preserved-by-construction for Purchase Orders/Part Allocation/Payments/Intake (no store-file changed by the Phase 1 fix; full test suite green). No dedicated real-concurrency test exists yet for the latter four beyond Scheduling's. | Direct grep + one committed test + full suite green | Partial (Scheduling proven directly; others proven only by construction + existing unit tests) |
| Redis-backed rate limiting is multi-instance-safe already | `app/rate_limit.py::RedisSlidingWindowRateLimiter` | `tests/test_rate_limit.py` | Complete — this part of a future multi-worker fix is already done |
| Backup/restore/rollback rehearsal in CI | **Added 2026-07-17 (Phase 2).** New `backup-restore-rollback-rehearsal` CI job runs the real sequence: backup → restore into a scratch DB with row-count verification → tag `:previous` → deliberately break the backend → confirm failure → `rollback` → confirm recovery. Found and fixed a real bug while building it: `scripts/optimusctl.sh` hardcoded the Docker image prefix as `optimus-server`, which silently doesn't match any checkout not literally named that — now derived dynamically via `docker compose config --images`. | Full local rehearsal run against a real Docker stack before committing; CI job added. | Complete |

**Phase 1 status: Complete, merged.** Phase 2's remaining items (cross-shop isolation, account-recovery, export isolation, billing webhook, support-admin, feature-flag CI tests) depend on Phase 3+ existing and will be added alongside those phases' own PRs, per `/goal`'s own instruction not to bundle unrelated architectural work into one diff.

## Part C — Net-new `/goal` requirements (Phases 3-13)

| Requirement | Current state | Status | Remaining action |
|---|---|---|---|
| `Shop`/`ShopSettings`/`ShopMembership`/`ShopInvitation`/`ShopRole`/`ShopStatus` models | **None exist.** Confirmed via `grep -n "class Shop" app/db_models.py` → no match. Tenancy today is `UserAccount.id` (owner) / `UserAccount.shop_owner_id` (technician), not a first-class Shop entity. | Absent | Phase 3 |
| `shop_id` on every business table | Every business table uses `owner_user_id` (a `UserAccount.id`), confirmed across all 21 migrations. | Absent | Phase 3 |
| Cross-shop isolation tests | Cross-*owner* isolation tests exist extensively (`test_*_cross_owner_isolation` in nearly every test file) — this is the correct pattern to extend once `shop_id` exists, not a rebuild. | Partial (pattern proven, entity doesn't exist yet) | Phase 3 |
| Self-service shop onboarding | **None exists.** The only owner account today is bootstrapped from `.env` (`OPTIMUS_OWNER_USERNAME`/`OPTIMUS_OWNER_PASSWORD` per `docs/context/SECURITY.md`) or via the test-support synthetic-account routes (test-only, gated off in production). No public signup route. | Absent | Phase 4 |
| Email verification | No email field, no verification token table, no email-sending abstraction of any kind exists in `app/`. | Absent | Phase 5 |
| Password reset/change | `PATCH` on `UserAccount` exists for technician fields; no self-service password-change or reset-token route for any role. | Absent | Phase 5 |
| Session listing/revocation | `AuthSession` table exists (`app/db_models.py`) and single-session logout exists (`POST /api/auth/logout`), but no "list my sessions" or "revoke one/all others" route. | Partial | Phase 5 |
| Login-event history (user-facing) | `security_events.py` logs login success/failure server-side (for operators), but there is no user-facing "your recent logins" feature. | Partial | Phase 5 |
| Account lockout/throttling | Login rate limiting exists (`enforce_login_rate_limit`, IP-keyed, per Part H) — this is throttling, not per-account lockout. | Partial | Phase 5 |
| Owner/manager/technician invitations | Only technician provisioning exists (`technician_store.py::provision_login`, owner-initiated, no token/email/acceptance flow — the owner sets the username/password directly). No "Manager" role exists at all (`UserAccount.role` CHECK constraint is `IN ('owner','technician')`). | Absent | Phase 5 (and Phase 3 for the Manager role) |
| MFA-ready architecture | Not started. | Absent | Phase 5 |
| Workflow-gap tracking | Not started. | Absent | Phase 6 |
| Subscription billing | Not started. Square sandbox integration exists but is for *customer-facing invoices*, a completely separate concern from shop subscription billing. | Absent | Phase 7 |
| Support administration domain | Not started. `UserAccount.role` has no `support` value. | Absent | Phase 8 |
| Extended observability (metrics, Prometheus/Grafana/Loki) | Structured logging exists (Part A); no metrics exporter, no local observability stack, no alert rules. | Partial | Phase 9 |
| Shop export (background job, signed download) | `GET /api/customers/{id}/history` exists as a manual owner-driven aggregation (documented in `docs/context/DATA_RETENTION.md` as "today's export mechanism") — no background job, no ZIP/CSV bundle, no signed expiring download link. | Partial | Phase 10 |
| Retention/deletion | Documented policy defaults only (`docs/context/DATA_RETENTION.md`); no enforcement code, no anonymization route, explicitly deferred pending owner policy answers. | Absent (by design, owner-gated) | Phase 10, partially blocked on 3 policy questions already on record |
| Pilot controls/feature flags | Not started. No flag-checking code exists anywhere in `app/`. | Absent | Phase 11 |
| Onboarding checklist | Not started (depends on Phase 4). | Absent | Phase 12 |
| Feedback/support workflow | Not started. | Absent | Phase 13 |

## Part D — Baseline gates re-run for this Phase 0 pass

- `env UV_CACHE_DIR=/tmp/uv-cache uv run ruff format --check .` and `ruff check .` — clean (re-run 2026-07-17, see Phase 1 commit for exact output).
- `env UV_CACHE_DIR=/tmp/uv-cache uv run pyright` — 0 errors.
- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q` — full suite green, 2 pre-existing unrelated Redis-skips.
- `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q tests/e2e/` — 5 passed against real Postgres 16 + real uvicorn.
- Migration chain: single linear head at `021_part_allocations`, confirmed via `alembic heads`.

## Reconciliation with `/goal`'s "current verified baseline" section

The goal document's own baseline list is accurate for Part A. Its statement that "the current application still appears to use the owner account as the business boundary... a separate shop or tenant model is not yet fully implemented" is **confirmed true** by direct source inspection, not assumed. Its statement about request-throughput serialization is **confirmed true** empirically (Part B). No baseline claim in the goal document needed correction.

## What this matrix does NOT attempt

Given the scope of Phases 3-13 (a full multi-tenant SaaS conversion: new core data model touching every table in the schema, a billing system, a support-admin domain, an observability stack, and five separate user-facing workflows), this matrix does not pre-build empty test scaffolding for features that don't exist yet. Each phase's own PR(s) will add its own tests, migrations, and CI coverage as that phase's functionality is built — per `/goal`'s own instruction not to "leave several unrelated architectural migrations in one uncontrolled diff."
