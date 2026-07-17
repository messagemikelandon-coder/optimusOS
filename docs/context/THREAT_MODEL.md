# Threat Model

Purpose: enumerate OptimusOS's trust boundaries, the threats against each, current mitigations with exact code citations, and open/accepted risk — the Phase 6 Part H deliverable.
Information owner: repository maintainers and the owner responsible for production decisions.
Read when: changing auth, session handling, approval links, rate limiting, Square integration, document generation, or any cross-tenant data access; before any production deployment decision.
Update when: a trust boundary changes, a new public endpoint is added, a mitigation is added or removed, or a new gap is discovered.
Last verified date: 2026-07-17.
Relevant sources: `app/auth.py`, `app/estimate_store.py`, `app/rate_limit.py`, `app/config.py`, `app/invoice_store.py`, `app/main.py`, `app/square_store.py`, `app/observability.py`, `docs/context/SECURITY.md`, `docs/context/KNOWN_ISSUES.md`.

## Scope and method

OptimusOS is a single-process FastAPI app behind Nginx, backed by Postgres and Redis, serving one shop owner's business (Landon Motor Works) plus that owner's technicians and, via unauthenticated tokenized links, that owner's customers. There is currently exactly one production tenant; the owner/technician/customer trust model below is written to hold even as more shops are onboarded, since the data model already scopes everything by `owner_user_id`.

Each section below covers one trust boundary: what crosses it, who can reach it, what could go wrong, what currently stops that, and what's still open. Findings are graded:
- **Mitigated** — a real, verified control exists (cited file:line).
- **Accepted gap** — a real limitation, deliberately not fixed, with a stated reason and a revisit condition.
- **Open** — a real limitation with no accepted-gap reasoning yet; should be fixed or explicitly accepted by the owner.

## 1. Customer approval links

**What crosses the boundary**: an anonymous, unauthenticated party (the customer, or anyone who obtains the link) can view and act on an estimate — approve or decline a real financial commitment — without a login.

**Threats**: link guessing/brute-forcing; link reuse after the customer already acted; a stale link still working after the estimate changed; the public view leaking owner-internal data (supplier cost, markup, raw AI research reasoning); a leaked or forwarded link being usable indefinitely.

**Mitigations**:
- Token is `secrets.token_urlsafe(32)` (256 bits of randomness) — not guessable (`app/estimate_store.py:768`).
- Token is never stored in plaintext; only its SHA-256 hash is persisted (`app/estimate_store.py:773`, hash fn at `:99-100`) — a database read alone cannot recover a usable token.
- Expires on a timer (`expires_in_hours`, `app/estimate_store.py:775`) and is auto-marked `expired` past that point (`:889-890`).
- Single-use: approving or declining sets `status="used"` (`:954-955`); a second attempt on the same token is rejected.
- Explicitly revocable by the owner (`revoke_estimate_approval_request()`, `app/estimate_store.py:820-877`), which also frees the estimate back to `ready` so a corrected link can be sent — added specifically so a mis-sent or outdated link can be killed without waiting for it to be used or expire.
- The public view (`_revision_to_approval_view()`, `app/estimate_store.py:360-397`) is a deliberately narrow projection: it drops the internal `estimate_request_payload` (labor rate, mobile fee %, shop supplies %, parts tax overrides) and only includes customer-facing prices, never supplier cost or markup (`:374-384`).
- All three public routes (`view`/`approve`/`decline`, `app/main.py:2498,2523,2557`) are rate-limited per source IP (see §9).

**Status**: **Mitigated.** No new gap found. This is the most-hardened surface in the app, appropriately, since it's the only one a stranger can reach with a live financial action attached.

## 2. Session cookies (owner and technician login)

**What crosses the boundary**: a browser holding a valid `optimus_session` cookie is trusted as the authenticated user for every subsequent request.

**Threats**: session token theft via XSS or network sniffing; session fixation; a stolen cookie remaining valid indefinitely; logout not actually invalidating the session server-side (cookie deleted client-side but token still accepted if replayed).

**Mitigations**:
- Token is `secrets.token_urlsafe(48)` (384 bits), stored only as a SHA-256 hash (`app/auth.py:117,120`; hash fn `:38-39`; `AuthSession.token_hash`, `app/db_models.py:99`).
- Cookie is `HttpOnly` (not readable by JS, so a same-origin XSS can't directly exfiltrate the raw token via `document.cookie`) and `SameSite=Lax` (`app/auth.py:144,146`).
- `Secure` is set whenever `frontend_origin` is configured as `https://` (`app/auth.py:138`) — correctly forces the cookie off plaintext HTTP once staging/production is on TLS.
- Fixed TTL, default 12 hours (`session_ttl_hours`, `app/config.py:67`), enforced on every read (`app/auth.py:184`, `expires_at > now()` check).
- **Logout genuinely revokes the session server-side**, not just clearing the client cookie: `app/main.py:631` sets `auth.session.revoked_at` and commits before clearing the cookie (`:634`) — a replayed post-logout token is rejected by the same `revoked_at IS NULL` check every other request uses (`app/auth.py:184`).
- DB errors during session validation are caught and sanitized to a `503`, never leaking internals (`app/auth.py:220-225`).

**Accepted gap**: `Secure` gating trusts the static `frontend_origin` setting rather than a per-request TLS signal (no `X-Forwarded-Proto` trust), because nothing today confirms that header is stripped from untrusted clients at the actual proxy layer. Documented previously in `KNOWN_ISSUES.md`; revisit once staging's real proxy topology (Nginx → app, or a cloud LB in front of that) is finalized and its header-stripping behavior is confirmed.

**Accepted gap**: no idle timeout, only a fixed 12-hour TTL — a session left open on a shared/public device stays valid for up to 12 hours of inactivity. Acceptable for a single-owner mobile-mechanic tool used on the owner's own devices today; revisit if technician accounts are issued more broadly on shared shop-floor devices.

**Status**: **Mitigated**, with two accepted gaps above.

## 3. Owner vs. technician authorization

**What crosses the boundary**: every authenticated request is scoped to either the full data of one owner (`role="owner"`) or a narrower technician view of that same owner's data (`role="technician"`, `shop_owner_id` pointing at the owner).

**Threats**: a technician reading or writing another owner's data; a technician reading or writing a peer technician's assigned work; a route added later that forgets to gate itself at all (defaults to world-readable).

**Mitigations**:
- `effective_owner_id(auth)` (`app/auth.py:234-250`) is the single choke point every store module uses to scope a query: owners get their own id, technicians get their linked `shop_owner_id`. A technician with no linked owner is rejected with `403` rather than silently scoped to nothing or everything (`:245-249`).
- Every business-data route depends on `OwnerAuthContextDep` or `OwnerOrTechnicianAuthContextDep` (`app/main.py:405-408`), and the technician-accessible subset (own profile, own clock in/out, own-assigned work orders) is further scoped inside the store layer, not just at the route (`work_order_store.py` query-building, confirmed technician-scoped to `assigned_technician_id == own id`).
- `tests/test_role_isolation.py::test_every_business_route_is_role_gated_as_expected` is a **static audit**, not a spot-check: it inspects the live FastAPI route table and asserts every route not on an explicit allowlist requires owner auth. A new route that forgets its auth dependency fails this test automatically, by construction — this is the strongest guarantee in the codebase against the "forgot to gate a new route" class of bug, and it has run against every route added this entire session.
- Defense-in-depth already exercised once: `effective_owner_id` originally trusted `shop_owner_id` without confirming it points at a real `role="owner"` row; closed by `technician_store.py::provision_login()` re-validating that at account-creation time, independent of the route already being owner-gated (`KNOWN_ISSUES.md`, Phase 5.6 sub-phase 2 entry).

**Status**: **Mitigated.** The static route-gate audit is the load-bearing control here and should never be weakened or skipped in future sessions.

## 4. Public (unauthenticated) endpoints

**Enumerated** (everything reachable with zero session and zero approval token):
- `GET /`, `GET /login`, `GET /approval` — static marketing/login/approval-shell HTML, no data.
- `GET /health`, `GET /ready` — liveness/readiness status, no business data (see §11).
- `POST /api/auth/login` — credential check; rate-limited, see §9 for detail.
- `POST /api/estimate-approval/{view,approve,decline}` — token-authenticated, covered in §1.

**Threats**: any of these being abused for enumeration, DoS, or credential stuffing; `/health`/`/ready` leaking anything beyond liveness.

**Mitigations**: `/health`/`/ready` return only status booleans and non-sensitive build metadata (version, migration head, git commit — all already public via the repo itself); no customer or owner data. Static pages serve fixed HTML with no per-request data. Approval endpoints are rate-limited (§1, §9). `POST /api/auth/login` is now rate-limited too (`app/main.py::enforce_login_rate_limit`, `max_login_attempts_per_minute`, default 10/min, Redis-backed via the same multi-instance-safe limiter class as the approval endpoints) — every failed and successful attempt also emits a structured `auth.login_failed`/`auth.login_succeeded` security event (`app/security_events.py`), with the attempted username logged only as a truncated SHA-256 hash, never in plaintext, specifically so a user who mistypes their password into the username field can never have it captured in a log line.

**Status**: **Mitigated.** Login rate limiting was the one real open finding this document surfaced; it shipped in this same Part H pass (see §9 for the accepted residual-risk discussion of IP-only keying).

## 5. PDF/HTML document generation (customer-facing invoices)

**What crosses the boundary**: an owner-authenticated request renders a document (HTML view or PDF) that is designed to eventually be handed to or viewed by a customer.

**Threats**: supplier cost, markup, or internal research/reasoning leaking into a document a customer could see; injected content in a generated document (XSS-equivalent, since these are served as real HTML responses); CSP not applying to these routes.

**Mitigations**:
- `render_invoice_html()`/`render_invoice_pdf()` (`app/invoice_store.py:496-573`, `:598-665`) build their output exclusively from an explicit field list — customer/vehicle snapshot, complaint/title, line items, and totals — with no code path that reads `unit_cost`, `markup`, `hourly_cost`, or the raw AI research object. This mirrors the identical exclusion discipline already verified for the estimate-approval public view (§1).
- Both document routes still require `OwnerAuthContextDep` (`app/main.py:2862-2884,2887-2908`) — today a customer receives these documents via the owner (email/download/print), not by fetching them directly; there is no unauthenticated document-fetch route.
- The global CSP middleware (`app/main.py:467-491`) applies to every response including these, and the invoice HTML's one external reference (`/static/invoice.css`) is same-origin, so it's `style-src 'self'`-compliant. Two real CSP violations were caught and fixed earlier in this project's history precisely by live-testing this surface (`KNOWN_ISSUES.md`), not by static review alone.
- The PDF renderer is a hand-built, text-only structure (`app/invoice_store.py:636-665`) with no embedded external resources or scripting surface of any kind — there is no PDF-embedded-JS risk class here because the format doesn't support it in this implementation.

**Status**: **Mitigated.** No new gap found; this remains a good example of the "disclose, never fabricate, never leak internal cost" discipline applied consistently across the codebase.

## 6. Square integration

**What crosses the boundary**: the app pushes real invoice/payment-schedule data to Square's API using a server-held API token, and — if ever enabled — could receive webhook callbacks back from Square.

**Threats**: the Square token leaking (browser exposure, logs, `.env` mishandling); production Square calls firing unintentionally; a forged webhook being trusted as if it came from Square.

**Mitigations**:
- `square_access_token` is `repr=False` (`app/config.py:73`) and only ever read server-side in `app/square_store.py`; never returned in any API response.
- `square_configured` (`app/config.py:156-162`) is a hard structural gate: it's `False` unless the token, location id, **and** environment are all set, and — critically — it requires `square_environment == "sandbox"`. **A production Square call is structurally unreachable from this codebase today**, not just discouraged by convention.
- No webhook receiver exists at all. The integration is push-only (owner-initiated `push_invoice_to_square_record`, `app/main.py:2961-3002`) — there is no incoming endpoint, so "forged webhook" is not a live threat class for this app as currently built.

**Accepted gap**: no production Square credentials have ever been configured or exercised (`KNOWN_ISSUES.md`); email-TLD and phone-format validation gaps found during sandbox smoke-testing are non-blocking and un-fixed by owner decision.

**Open, low-severity, forward-looking**: because there is no webhook receiver today, there is also no webhook-signature-verification code today. This is correctly "not applicable" right now, but must be added **before** any future webhook receiver is built — noted here so that future work doesn't ship a webhook endpoint without signature verification from day one.

**Status**: **Mitigated** for the integration as it exists today; one forward-looking note for future webhook work.

## 7. File and static-asset exposure

**What crosses the boundary**: `/static/*` serves the compiled frontend (HTML/CSS/JS/vendor libraries) to anyone, authenticated or not.

**Threats**: path traversal reading files outside the intended directory; accidentally serving a non-public file (e.g., a stray `.env` or backup file) if one were ever placed under `app/static/`.

**Mitigations**: served via FastAPI's built-in `StaticFiles` mount (`app/main.py:423`), which is traversal-safe by construction (normalizes and bounds-checks paths). There are no file-upload endpoints anywhere in the app and no user-controlled path parameters used for file serving — there is no code path where a request parameter selects which file to read.

**Status**: **Mitigated.** Ongoing discipline required, not code: never place secrets or non-public files under `app/static/`.

## 8. Cross-tenant (cross-owner) data isolation

**What crosses the boundary**: every business-data query must return rows for exactly one owner's data, never another's, regardless of which table is queried or how many joins deep the ownership check is.

**Threats**: a query that filters on a child table's `owner_user_id` correctly but joins in a parent/sibling row that isn't independently checked; a foreign-key reference (e.g., `work_order_id` on a diagnostic finding) accepted without confirming it belongs to the same owner as the request.

**Mitigations**:
- The `owner_user_id` + `effective_owner_id(auth)` pattern is applied uniformly across every store module (confirmed present in `estimate_store.py`, `customer_store.py`, `work_order_store.py`, and every report/dashboard query added this session).
- Every business module has an explicit, standing-required cross-owner-isolation regression test (a hard rule already enforced throughout this project's history, not just this session — every one of the 6 Part G report slices this session included one).
- A **real cross-tenant bug was previously found and fixed**, not just theorized: Diagnostics/Inspections originally accepted a `work_order_id` without confirming it belonged to the request's own owner, closed by adding `_validate_work_order()` to both stores plus regression tests (`KNOWN_ISSUES.md`, Phase 5.6 sub-phases 3/4/6/7 entry) — evidence the isolation discipline here is actively tested, not just assumed.

**Accepted gap**: SQLite (the fast unit-test engine) does not enforce foreign keys or `ON DELETE CASCADE` without an explicit per-connection pragma, which this codebase does not enable (breaking ~100 existing tests when tried, per `KNOWN_ISSUES.md`). Every cascade relationship is verified correct against real Postgres in live-proof sessions, but the automated unit-test suite does not itself exercise real FK enforcement. This is a verification-coverage gap, not a known-broken cascade — revisit as a dedicated task (enable the pragma, fix the ~100 tests whose fixtures assumed lax ordering) before treating cascade behavior as fully proven by CI alone.

**Status**: **Mitigated**, with one verification-coverage gap noted above (not a live defect).

## 9. Rate limiting

**What's currently limited**: `POST /api/estimate-approval/{view,approve,decline}` — Redis-backed sliding window, per source IP + endpoint path, default 20/minute (`app/main.py:2505,2530,2564`; `app/rate_limit.py:55-101`; `app/config.py:65`). `POST /api/auth/login` — same limiter class, its own separate instance and configured limit (`max_login_attempts_per_minute`, default 10/min), keyed by source IP only (`app/main.py::enforce_login_rate_limit`).

**What's not**: all other authenticated endpoints (no per-user throttling on expensive operations like estimate generation or chat), static pages, health checks (correctly unthrottled by design, since monitoring needs to reach them unconditionally).

**Mitigations already proven**: the Redis-backed limiter is multi-instance-safe (atomic sorted-set check via a Redis pipeline, so concurrent app instances share one true count — verified live against a real multi-client scenario, per `PLANS.md`'s Part H structured-logging/rate-limiting entry) and fails open to a best-effort in-process limiter (not fails-closed to an outage) if Redis itself is unreachable, logging a warning when it does (`app/rate_limit.py:88-94`) — a deliberate choice so a Redis blip degrades rate-limit precision rather than taking down the public approval flow entirely.

**Accepted gap**: the login limiter is keyed by source IP only, not also by the attempted username. This has two real, named consequences, not just a theoretical caveat: (1) several legitimate users sharing one IP (a shop's staff on the same WiFi/cellular NAT) would all be throttled together if any one of them is retried enough times, and (2) an attacker who controls multiple source IPs (trivial and free via any rotating-proxy service) can bypass the per-IP ceiling entirely by spreading attempts across IPs, since there is no account-level lockout backing it up. Accepted for now because this is a single-shop deployment with a small, known set of real client IPs — the realistic false-positive risk (staff locking each other out) is low, and account-level lockout has its own downside (an attacker can deliberately lock a real owner out of their own account by repeatedly guessing, a denial-of-service vector this app doesn't have today specifically because it wasn't added). Revisit if usage grows to include multiple shops/locations behind shared NAT egress, or if login abuse is ever actually observed in production logs (the new `auth.login_failed` security event, correlatable by its hashed-username field even without the raw value, is exactly the signal that would show this).

**Second accepted gap, found by an independent `optimus-security-reviewer` pass (2026-07-17), not this document's original authoring session**: the login limiter's Redis-outage fallback is the same in-process, single-process `SlidingWindowRateLimiter` used by the public approval/chat endpoints (`app/rate_limit.py:88-95`), with no special-casing for login. That fail-open tradeoff is reasonable for the public endpoints (a Redis blip shouldn't take down customer-facing approval links), but it's a materially different risk for a credential-guessing surface: on a future multi-instance deployment, a Redis outage would silently give an attacker distributing attempts across instances up to *N × the configured limit* (N = instance count) for the outage's duration, since each instance would fall back to its own independent counter instead of sharing one. Accepted for now because the current deployment is single-instance, making the gap moot in practice today. Revisit before any multi-instance deployment: either fail closed specifically for the login limiter (a different tradeoff than the public endpoints warrant), or emit a dedicated security event when the Redis fallback activates so a monitor can correlate an outage window against any login-failure spike — neither is implemented today.

**Status**: **Mitigated**, with the accepted IP-only-keying gap and the Redis-outage-during-login gap above.

## 10. Secrets handling

Covered in full by `docs/context/SECURITY.md`; not re-derived here except to note the two real prior incidents (`docker compose config` dumping `.env` to a session transcript; a staging password mistyped into a stuck terminal) are both documented with their resolutions in `KNOWN_ISSUES.md`, and the concrete process fix from each (never run a full `docker compose config` dump; build multi-line remote files via sequential single-line `echo` commands, not `nano`/heredocs) should be treated as durable operating rules, not one-time fixes.

**Status**: see `docs/context/SECURITY.md` — **Mitigated**, with incident history as the evidence base.

## Summary: accepted gaps and forward-looking items

Login brute-force protection (§4, §9) was the one genuinely open finding this document surfaced on its first pass — it shipped in this same Part H work (Redis-backed rate limiting on `/api/auth/login`, plus hashed-not-raw security-event logging of failed attempts) and is no longer open, though its IP-only-keying tradeoff is now an explicitly accepted gap rather than an unstated one (§9). Everything below is an accepted gap or a forward-looking note, not a currently-open defect:

1. **Login rate limiter keyed by IP only, not also by attempted username** (§9) — accepted for the current single-shop deployment; revisit if usage grows to multiple locations behind shared NAT, or if real login abuse is observed via the new `auth.login_failed` security event.
2. **Login rate limiter's Redis-outage fallback loses its multi-instance guarantee specifically for login** (§9) — accepted because the current deployment is single-instance, making the gap moot today; revisit before any multi-instance deployment (see §9 for the two remediation options).
3. **Webhook signature verification** (§6) — not applicable today (no webhook receiver exists), but must ship alongside any future Square webhook endpoint, not after.
4. **`Secure`-cookie gating trusts a static setting, not a live TLS signal** (§2) — accepted, revisit once staging's real proxy topology (and header-stripping guarantees) are confirmed.
5. **SQLite FK-cascade verification gap** (§8) — accepted, revisit as a dedicated task; not a known-broken cascade, just unproven by the fast unit-test suite specifically.
6. **No idle session timeout** (§2) — accepted for current single-owner, own-device usage; revisit if technician accounts spread to shared devices.

Everything else in this document is a verified, currently-correct mitigation, not an open item.
