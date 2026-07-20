# Phase 1 — Security Kernel: Inventory, Gaps, and Plan

**Status:** Awaiting approval. No code changes have been made under this plan.
**Governs:** ADR-020 (`docs/architecture/adr/ADR-020-security-kernel-integration.md`), the first implementation phase of the roadmap in `docs/architecture/STACK-DECISION.md` §7.
**Scope discipline:** extract, centralize, test, and harden *existing* authentication, authorization, tenant scoping, audit, validation, API-key, rate-limit, and error-handling code. No redesign. No new cryptography, password hashing, token format, or TLS. Remove duplication only where a test first captures current behavior. Vehicle ownership history (ADR-015) is explicitly out of scope for this phase.

---

## 1. Preserved file locations, source commits, and checksums

Recorded in full in `docs/architecture/README.md` and `docs/architecture/CHECKSUMS.txt`. Summary:

- Full report: `docs/architecture/STACK-DECISION.md` (preserved verbatim, never edited after preservation).
- 8 ADRs: `docs/architecture/adr/ADR-014-*.md` through `ADR-021-*.md`.
- Source PoC repo: `/home/dejake/optimus-laravel-poc/` (retained, not deleted), report commit `c889e6d8ac81abf8962974bae734b0561e2c24e5`, source-file SHA-256 `b8583ac3aececf829ce838c7948efaea7c4cc0de73be263109433f9ab2665768`.
- Preservation commit in this repo: `dbbcdac` on branch `agent/claude/architecture-decision-preservation` — "Preserve the approved OptimusOS stack decision (retain and simplify FastAPI)".
- Preserved-copy checksums verified via `sha256sum -c docs/architecture/CHECKSUMS.txt` (all `OK`).

---

## 2. Security inventory and duplication map

Full detail gathered by three independent code-reading passes over `app/auth.py`, all 178 routes in `app/main.py`, `app/rate_limit.py`, `app/security_events.py`, `app/openai_key_info.py`, `app/context_store.py`, `app/observability.py`, `app/errors.py`, `scripts/`, `app/orchestrator.py`, `app/services/optimus_chat.py`, and `integration/optimus_adapter.py`. Summary by capability:

### 2.1 Authentication & authorization — solid, well-covered, no redesign needed
`app/auth.py` already has one clean dependency ladder (`get_current_auth_context` → `require_owner_context`/`require_owner_or_technician_context`/`require_billing_context`/`require_support_context`), and all 178 endpoints classify cleanly: 108 owner-only, 21 owner-or-technician (self-scoped), 7 billing, 2 support, 10 authenticated-self-service, 3 verified-any-role, 2 current-user-any-role, 25 intentionally unauthenticated (SPA shell, health/ready, login/signup, mailed-token flows, public estimate-approval links, feature-flagged test-support routes). Two automated tests already enforce this: `tests/test_role_isolation.py::test_every_business_route_is_role_gated_as_expected` (enumerates every route's actual dependency graph against hand-maintained allowlists) and `tests/test_membership_tenant_boundary.py::test_store_authorization_queries_do_not_compare_legacy_owner_user_id` (AST-forbids the legacy `owner_user_id` anti-pattern). A tenant-scoping spot-check across 8 domains (customers, vehicles, estimates, work orders, invoices, technicians, vendors, purchase orders) found every write path routing through an `effective_shop_id()`-scoped query. **No redesign needed here — Phase 1 work is closing the one blind spot the AST test has (it forbids the legacy pattern but doesn't positively assert every store scopes on *something*) and handling the one bypass found (§2.6).**

### 2.2 Audit logging — real duplication, no redesign
Two independent mechanisms exist and don't talk to each other: 7 domain event tables (`EstimateApprovalEvent`, `WorkOrderStatusEvent`, `PartAllocationEvent`, `DiagnosticFindingEvent`, `InspectionEvent`, `ShopEvent`, `WorkflowGapEvent`) in 3 incompatible column shapes, plus `AuthLoginEvent` as a fourth, and a separate `log_security_event()`/`SecurityEventType` structured-logging path (35 call sites, all in `app/main.py`, none in store modules) with freeform, per-call-site-inconsistent kwargs. Concretely: `ShopEvent`'s 7 writer call sites across 4 modules populate its actor columns inconsistently (some use `.display_name`, one uses `.username`, `subscription_store.py`'s `trial_started` omits actor identity entirely); `log_security_event`'s 5 `SQUARE_API_FAILED` call sites omit `request=`, silently losing `http_path`/`client_host` that every other call site gets. **Decision for Phase 1: do not touch the 7 domain event tables' schemas** (they're working, tested, business-process audit trails, not a security log — redesigning them would be exactly the "broad rewrite" this phase must avoid). Instead: (a) add one `record_shop_event()` helper all `ShopEvent` writers converge on, same table/columns, consistent actor population — this is duplication removal within an existing schema, not a redesign; (b) hardened `log_security_event()` with a per-event-type expected-field contract and a `request` parameter that's required (not optional-and-often-forgotten), fixing the 5 Square call sites as part of the same change.

### 2.3 Rate limiting — real duplication, real test gap
7 (not 6) separate `RedisSlidingWindowRateLimiter` instances (general/estimate, login, signup, email-verification, email-verification-resend, password-reset, invitation-acceptance), each wired via a near-verbatim copy-pasted singleton/guard pair in `app/main.py` (~260 lines, `:522-784`), with limits correctly centralized in `app/config.py` but the wiring boilerplate duplicated 7×. Three of the seven have **no test proving they actually return 429** when exceeded (general/estimate, password-reset, invitation-acceptance) — the password-reset/invitation-acceptance limiters are exercised in `test_account_security_api.py` but only once per test run, never enough to breach the limit. **Phase 1 work: write the 3 missing 429-trigger tests first (locking in current behavior), then extract the 7 wiring blocks into one parameterized factory — never the other order.**

### 2.4 API keys — one static key, no lifecycle model exists
`app/openai_key_info.py` (fingerprint/mask/shape-validate) is unused by the running server — only 3 offline CLI scripts import it; `Settings.openai_api_key` is read directly from env with no rotation, scoping, expiration, or revocation mechanism, and no usage tracking. Square's token has the identical bare-env pattern with no equivalent tooling at all. **Scope tension, flagged explicitly rather than silently resolved:** the Phase 1 request to "harden API-key storage, scopes, expiration, revocation, usage tracking" describes a fuller key-lifecycle model than exists today for this single static key. Building scopes/expiration/revocation/per-key-usage-tracking from scratch would be new functionality, not extraction-and-hardening of existing code, and conflicts with this phase's "do not redesign" constraint. **Recommendation: Phase 1 hardens what exists** (wire `validate_key_text`'s shape-checking into the new startup check, §2.5, so the one key that exists is validated at boot instead of only via a CLI script nobody runs automatically) **and this document explicitly recommends scopes/expiration/revocation/usage-tracking be its own later, separately-approved sub-phase** — bundling it into Phase 1 would mean inventing a data model (an api_keys table, most likely) that doesn't exist, which is a real design decision deserving its own review, not a rider on a consolidation phase.

### 2.5 Startup/config validation — a real, HIGH-priority gap
No cross-field or startup assertion exists anywhere (`app/config.py`, `app/main.py`) — the app boots fully "ready" with a blank `OPENAI_API_KEY`, blank/placeholder owner credentials, or any string in `app_env` (not even a `Literal`). Two scripts (`scripts/validate_runtime.py`, `scripts/check_config.py`) already contain this exact validation logic but are never invoked by `docker-compose.yml`, the `Dockerfile`, or `app/main.py` — they are manual/CI-only today. **Phase 1 work: reuse this existing logic in one importable function called at app startup, so an unsafe production config is a boot failure, not a runtime surprise** — this directly satisfies "fail startup on unsafe production config" and mirrors the Laravel PoC's `DatabaseEnvironmentGuard` pattern (ADR-018) without inventing anything new.

### 2.6 CRITICAL: an unauthenticated, unscoped bypass of the entire security kernel exists in the repo
`integration/optimus_adapter.py`'s `OptimusInternetSkill` wraps `OptimusChatService.chat()` and `OptimusResearchOrchestrator.estimate_job()` directly, with **no auth, no rate limiting, and no tenant context of any kind** — it just constructs `Settings()` and calls the service. It has **zero callers anywhere in the repo** (confirmed by grep across `app/`, `scripts/`, `tests/`, and docs) — described in its own docstring as an adapter "for an existing Optimus host" that, as far as this inventory can determine, was never finished or wired up. This is dead code today, but it is the single clearest existing violation of the product principle "the AI must never have a separate uncontrolled path for changing application data" — if anything ever imports and calls it, every control this phase is building (auth, rate limits, tenant scoping, audit) is bypassed in one step. **This is ranked CRITICAL despite having zero current callers, because the blast radius of it silently being wired up later is total, and the fix is cheap.**

### 2.7 Secret redaction — no shared utility, single-purpose today
`app/context_store.py`'s 5-pattern regex blocklist (`_SECRET_PATTERNS`) is an input-*rejection* filter used only by `context_store.py` itself — it is not a redact-in-place transform, and nothing else in the codebase (notably `app/observability.py`'s JSON log formatter) uses it or anything like it. Structured logging currently relies entirely on caller discipline never to log a secret. **Phase 1 work: extract the pattern list into a shared utility and apply it as a defense-in-depth scrubbing pass in the logging formatter, in addition to (not instead of) `context_store.py`'s existing rejection behavior.**

### 2.8 Structured error capture — mostly consistent, three fragile spots
Domain exception → HTTP status mapping is consistent for the overwhelming majority of the ~90 `try/except` blocks in `app/main.py` (`*StoreError` → 422, `*NotFoundError` → 404, `*ConflictError` → 409). Found: one exception-naming lie (`SyntheticOwnerNotFoundError` → 422 not 404, but it's a test-support-only path, low real-world impact); three places where the HTTP status is decided by sniffing the exception's message string rather than its type (`ContextStoreError`, `WorkOrderStoreError`, `EstimateStoreError`) — fragile, since an unrelated message-text edit could silently change the API contract; one inconsistent response-body shape for the same 409 category (`SchedulingConflictError.as_detail()` returns a structured dict, other `*ConflictError`s return a plain string). No central `@app.exception_handler` exists — every mapping is hand-written per route. **Phase 1 work: add tests locking in current status codes for all three message-sniffing cases before touching them, then replace the string-sniffing with an explicit exception attribute/subtype (no behavior change, just a more robust check).**

### 2.9 Correlation IDs — usable today, one gap worth flagging for Sentinel later
`app/observability.py`'s per-request `request_id` (a `ContextVar`) already propagates through `asyncio.to_thread` into store/service code and appears on every JSON log line. A second, unrelated "request_id" exists inside `OpenAIWebResearchService.research()` (`app/services/openai_web.py:968`) scoped only to that single call and never logged — a naming collision that could confuse an incident responder, not a functional bug. There is no single ID tying together a whole multi-specialist chat turn (`optimus_chat.py`'s consultations + final synthesis). **Low priority for Phase 1 itself — noted here because ADR-021 (Sentinel) will need an "agent run" ID, and this is the place that ID should eventually attach.**

### 2.10 Input validation — no gap found
All 87 write endpoints sampled/grepped across `app/main.py` use a dedicated Pydantic request model; zero raw `dict`/`Any` body parameters found anywhere. **No Phase 1 work needed here.**

### 2.11 Background jobs — no gap found
`scripts/optimus_worker.py` is confirmed to touch no tenant data at all (a 60-second TCP-reachability heartbeat only) — there is no background code path in the repo that reads/writes shop-scoped data without a tenant context, because there is no data-touching background job at all today. **No Phase 1 work needed here beyond a regression test locking in that the worker never opens a business-data DB session, so this stays true if the worker is ever extended.**

---

## 3. Gaps ranked

| Rank | Gap | Where |
|---|---|---|
| **CRITICAL** | `OptimusInternetSkill` bypasses all auth/rate-limit/tenant controls; zero callers today but a total bypass if ever wired up | `integration/optimus_adapter.py` |
| **HIGH** | No startup/config validation — server boots fine with blank secrets, placeholder owner credentials, any `app_env` value | `app/config.py`, `app/main.py` |
| **HIGH** | 4 incompatible audit-event shapes; `ShopEvent`'s 7 writers populate actor identity inconsistently, one site omits it entirely | `app/db_models.py`, 7 writer modules |
| **HIGH** | 3 of 7 rate limiters have no test proving they actually 429 | `app/main.py`, `tests/` |
| **MEDIUM** | No shared secret-redaction utility outside `context_store.py`; logging relies purely on caller discipline | `app/observability.py`, `app/context_store.py` |
| **MEDIUM** | `log_security_event`'s freeform kwargs vary per call site; 5 Square call sites silently drop `http_path`/`client_host` | `app/security_events.py`, `app/main.py` |
| **MEDIUM** | 3 status-code decisions made by message-string-sniffing instead of exception type/attribute | `app/main.py` (Context/WorkOrder/Estimate error handlers) |
| **MEDIUM** | Rate-limiter wiring duplicated 7× with copy-pasted boilerplate | `app/main.py:522-784` |
| **LOW** | `openai_key_info.py` unused by the running server; Square has no equivalent tooling at all (asymmetric, not itself a vulnerability) | `app/openai_key_info.py` |
| **LOW** | One exception-naming lie (`SyntheticOwnerNotFoundError` → 422 not 404), test-support-only path | `app/main.py:1727-1730` |
| **LOW** | Two unrelated "request_id" concepts could be confused during an incident; no single ID for a multi-step AI turn | `app/observability.py`, `app/services/openai_web.py` |
| **OUT OF SCOPE (flagged, not resolved here)** | Full API-key lifecycle (scopes/expiration/revocation/usage-tracking) does not exist for the one static OpenAI key | recommend a separate, later, explicitly-approved sub-phase |

---

## 4. Files to change

| File | Change |
|---|---|
| `integration/optimus_adapter.py` | Delete, or gate behind the same `CurrentUserDep`/`OwnerAuthContextDep` + rate limiter + tenant context the real endpoints use — decision requested as part of approval (§8 asks for this explicitly). |
| `app/startup_checks.py` (new) | `validate_runtime_config(settings)`, ported from `scripts/validate_runtime.py`/`scripts/check_config.py`'s existing logic; raises on unsafe production config. |
| `app/main.py` | Call `validate_runtime_config` at startup (module import or FastAPI startup event); extract the 7 rate-limiter wiring blocks into one factory (behavior-preserving); replace the 3 message-sniffing status-code decisions with explicit type/attribute checks; fix the 5 `SQUARE_API_FAILED` call sites to always pass `request=`. |
| `app/security_events.py` | Add a per-event-type expected-field contract (or at minimum a typed wrapper) to `log_security_event`; extend `SecurityEventType` to cover sensitive-read/write/approval/API-key-use/support-access/security-setting-change categories. |
| `app/shop_store.py` (or a new small shared module) | Add `record_shop_event()` helper; migrate the 7 existing `ShopEvent`-writing call sites in `account_security_store.py`, `auth.py`, `shop_store.py`, `subscription_store.py`, `support_store.py` onto it — same table, consistent actor population. |
| `app/security/redaction.py` (new) | Extract `context_store.py`'s `_SECRET_PATTERNS` into a shared scrub utility; `context_store.py` keeps its existing rejection behavior calling into the shared list; `app/observability.py`'s `JsonLogFormatter` gains a scrubbing pass using the same utility. |
| `app/errors.py` or `app/main.py` | Fix `SyntheticOwnerNotFoundError` → 404; add explicit type/attribute checks replacing message-sniffing for `ContextStoreError`/`WorkOrderStoreError`/`EstimateStoreError`. |
| `app/openai_key_info.py` | Wire `validate_key_text()` into `app/startup_checks.py` so the running server, not just CLI scripts, benefits from it. |
| `tests/test_rate_limit_endpoints.py` (new) | The 3 missing 429-trigger tests (general/estimate, password-reset, invitation-acceptance), written **before** the rate-limiter refactor. |
| `tests/test_startup_checks.py` (new) | Unsafe-production-config tests (§7). |
| `tests/test_security_events.py` (new or extended) | Field-contract tests per `SecurityEventType`; `ShopEvent` actor-consistency tests across all 7 former call sites. |
| `tests/test_redaction.py` (new) | Known secret-shaped strings never appear in rendered log output. |
| `tests/test_membership_tenant_boundary.py` | Extend the existing AST test to positively assert every store's owner-query helper calls `effective_shop_id()` (closing the "scoped on neither" blind spot), not just forbid the legacy pattern. |
| `tests/e2e/test_optimus_adapter_bypass.py` (new, if the adapter is gated rather than deleted) | Proves the adapter cannot execute a write without the same auth/rate-limit/tenant context as the real endpoints. |
| `docs/architecture/adr/ADR-022-api-key-lifecycle-deferred.md` (new, if approved) | Records the API-key-lifecycle scope decision (§2.4) as its own dated ADR rather than silently expanding Phase 1. |

---

## 5. Database/API impact

- **Migrations required: zero.** No new tables, no column changes. `ShopEvent`'s existing columns already support consistent actor population — the fix is call-site discipline via a shared helper, not schema change. Vehicle ownership history (ADR-015) remains explicitly deferred and is not touched.
- **API surface changes: none required.** No new endpoints. `GET /ready`'s optional `database_driver` field extension (ADR-018) is a small, separately-schedulable addition — not required for Phase 1's own acceptance gate, listed here only because it can be folded in cheaply if approved.
- **Behavioral changes to existing endpoints: none intended.** Every change in §4 is either (a) a new startup-time check that only fires on genuinely unsafe config (does not affect a correctly-configured server), (b) internal refactors proven behavior-preserving by tests written first, or (c) closing the one dead-code bypass (§2.6), which by definition has no current callers to break.

---

## 6. Commit sequence

Each item is one reviewable PR. No item starts before the previous one merges and passes CI.

1. **Characterization tests, no production code changes**: the 3 missing rate-limiter 429 tests, the `ShopEvent` actor-consistency tests (documenting current inconsistent behavior as a known-bad baseline to fix in commit 4), tests locking in the 3 current message-sniffing status-code outcomes, and the extended tenant-scoping AST test. This commit can only add tests and must leave 100% of the existing suite green.
2. **Startup config validation**: `app/startup_checks.py` (ported from the two existing scripts), wired into `app/main.py`, `tests/test_startup_checks.py`. Includes the OpenAI key shape-check via `openai_key_info.validate_key_text()`.
3. **`OptimusInternetSkill` decision**: delete `integration/optimus_adapter.py`, or gate it — whichever is approved in §8 — plus `tests/e2e/test_optimus_adapter_bypass.py` if gated.
4. **Audit-event hardening**: `record_shop_event()` helper + migrate all 7 call sites; `log_security_event` field-contract + fix the 5 Square call sites; extended `SecurityEventType` taxonomy; tests updated from commit 1's baseline to assert the *fixed* consistent behavior.
5. **Secret-redaction utility**: `app/security/redaction.py`, wired into `app/observability.py`; `tests/test_redaction.py`.
6. **Error-handling standardization**: fix `SyntheticOwnerNotFoundError`, replace the 3 message-sniffing checks with explicit type/attribute checks, using commit 1's characterization tests to prove no status code changed.
7. **Rate-limiter wiring consolidation**: extract the 7 copy-pasted blocks into one parameterized factory, using commit 1's 429 tests (now covering all 7) to prove behavior is unchanged.
8. **Full-suite regression pass + `docs/context/CURRENT_STATE.md`/`SESSION_HANDOFF.md` update** recording Phase 1 complete, before any Phase 2 (deployment simplification, ADR-014) or later work begins.

### Rollback points
Every commit above is independently revertible: commits 1, 5, and 6 add code/tests without removing any existing path; commit 2 is a pure addition (revert = server behaves exactly as it does today, i.e., no startup check); commit 3 is either a deletion (revert = restore the file, still with zero callers, from git history) or an additive gate (revert = remove the gate); commit 4 changes call sites but not the underlying table schema (revert = call sites go back to their old, inconsistent-but-working form); commit 7 is pure code movement (revert = the 7 original blocks, still correct, come back).

---

## 7. Test and rollback plan

**Required test categories, mapped to what's actually being written (per §4/§6):**

- **Unit — permissions/tenant context**: extension to `tests/test_membership_tenant_boundary.py` (positive `effective_shop_id()` assertion); no new permission model exists to unit-test beyond what `test_role_isolation.py` already covers, which remains green throughout.
- **Unit — audit**: `tests/test_security_events.py` (field-contract per `SecurityEventType`; `ShopEvent` actor-consistency across all 7 call sites).
- **Unit — rate limits**: `tests/test_rate_limit_endpoints.py` (3 new 429 tests) plus the existing `tests/test_rate_limit.py` (unit tests of the underlying limiter class) remaining green.
- **Unit — redaction**: `tests/test_redaction.py`.
- **Integration — protected endpoints**: existing per-domain functional test files (`test_customers_api.py`, `test_vehicles_api.py`, etc.) remain green, unmodified by this phase.
- **Integration — background jobs**: a new small test asserting `scripts/optimus_worker.py`'s loop never opens a session against any business table (locks in the current, correct "heartbeat only" behavior).
- **Cross-tenant tests**: the existing `tests/e2e/test_isolation_sweep.py` (`test_second_owner_isolation_sweep_across_full_record_chain`) must remain green; no new business endpoints are added in this phase, so no new sweep coverage is required except confirming the adapter decision (§8) doesn't introduce one.
- **Approval-bypass tests, AI and manual paths**: the manual/customer path is already thoroughly covered (`tests/test_estimate_approval_api.py::test_invalid_expired_and_reused_tokens_fail_safely`, `::test_token_reuse_and_revision_mismatch`, `::test_cross_user_access_isolated` — all pre-existing, must remain green). The AI path has no execution capability today (`app/orchestrator.py` is read-only), so the only "AI approval-bypass" surface is `OptimusInternetSkill` itself — covered by `tests/e2e/test_optimus_adapter_bypass.py` if gated, or moot if deleted.
- **API-key tests**: `tests/test_startup_checks.py` covers shape/presence validation for the one static key that exists. Scope/expiration/revocation/throttling tests are **not written in this phase** per the §2.4/§8 scope decision — flagged, not silently skipped.
- **Unsafe production-config startup tests**: `tests/test_startup_checks.py` (blank secret, placeholder owner credentials, non-postgres driver in production — mirroring the Laravel PoC's `DatabaseEnvironmentGuardTest` pattern from ADR-018).
- **Existing regression suite remains green**: full `pytest` run (currently 51 unit + 23 e2e files) required before each commit in §6 merges, not just at the end.
- **PostgreSQL requirement**: all new integration/cross-tenant tests are added under `tests/e2e/` (which already always runs against a real Postgres container per `tests/e2e/conftest.py`), not the fast SQLite unit suite — SQLite-only success is not treated as sufficient for anything touching tenant isolation or migrations, consistent with the explicit instruction.

**Rollback plan**: see per-commit rollback points in §6. No commit in this phase touches a database migration, so no migration rollback procedure is needed. If any commit's tests fail post-merge in a way not caught by CI, the standard `optimusctl.sh rollback` mechanism (already CI-rehearsed, per `docs/architecture/STACK-DECISION.md` §2) applies at the deployment level.

---

## 8. Definition of done

Phase 1 is complete when, and only when:

1. Every gap ranked CRITICAL or HIGH in §3 has a corresponding merged commit from §6.
2. Every capability in scope (§2) has exactly one implementation location, with a test proving other call sites use it rather than re-implementing it.
3. No existing endpoint's actual authorization, rate-limit, or validation outcome has changed — proven by the full existing regression suite (51 unit + 23 e2e files) passing unchanged before and after this phase.
4. The `OptimusInternetSkill` decision (delete or gate) is resolved and verified by a passing test (§4, §6 commit 3).
5. A startup-config validation exists and is proven, via test, to actually block an unsafe production boot (§7).
6. The API-key-lifecycle scope decision is recorded as its own ADR (`ADR-022`, if approved) rather than left ambiguous.
7. `docs/context/CURRENT_STATE.md` and `docs/context/SESSION_HANDOFF.md` are updated to record Phase 1 complete, per `AGENTS.md`'s standing context-update rule.
8. No Phase 2 work (deployment simplification, vehicle ownership, prompt/manual execution, or any Sentinel event emission) has started — those remain gated on this phase's completion per the approved roadmap ordering.

---

## Approval requested for two specific decisions before implementation begins

1. **`integration/optimus_adapter.py`**: delete outright, or gate behind the same auth/rate-limit/tenant dependencies as the real endpoints? (Recommendation: delete — zero callers, zero tests, zero documented invocation path; gating dead code adds maintenance surface for a feature nobody uses today.)
2. **API-key lifecycle** (§2.4): confirmed out of scope for Phase 1, deferred to a separate later ADR/sub-phase? (Recommendation: yes — building scopes/expiration/revocation/usage-tracking from nothing is new development, not extraction of existing code.)

No implementation proceeds until this plan and the two decisions above are approved.
