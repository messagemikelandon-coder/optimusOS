# Session Handoff

Purpose: replaceable handoff template for the next substantial Codex/Claude session.
Information owner: the active session author.
Read when: starting or resuming work.
Update when: a substantial task completes or context needs to be handed forward.
Last verified date: 2026-07-09.
Relevant sources: `docs/context/CURRENT_STATE.md`, `docs/context/PLANS.md`, `docs/context/KNOWN_ISSUES.md`, `docs/context/DECISIONS.md`, `git status`, `git log`, `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q`, local Docker rehearsals of `scripts/optimusctl.sh restore`/`rollback`/`migrate-down` run on 2026-07-09.

## Identity

- Updated UTC: 2026-07-09T02:00Z
- Agent: Claude
- Branch: `ops/staging` (branched from `main` at `c920891`)
- HEAD: `c920891` plus uncommitted Phase 5 local-prep work in the working tree
- Worktree: primary (`/home/dejake/optimus-server`)

## Active task

- Goal: **Phase 5 — Private Staging.**
- Status: Local-only code/process prep is done, independently reviewed, security-reviewed, and rehearsed against the real local dev stack. **Blocked on owner-performed real-world infrastructure setup** before any actual deployment/staging work can proceed — no agent can create cloud accounts, spend money, or register a domain.
- Important context discovered this session: Phase 3 (`feat/payment-tracking`) and Phase 4 (`harden/local-mvp`) were merged directly into `main` on GitHub by the owner (PR #7 `423192b`, PR #8 `c920891`) outside of any agent action, between sessions. Local `main` was fast-forwarded to match. Phase 4 was explicitly closed by the owner accepting its one-time live proof as sufficient (see `docs/context/KNOWN_ISSUES.md`/`PLANS.md`) — no permanent automated fresh-volume E2E/failure-drill artifact exists or is planned unless separately requested.
- Infrastructure decision made this session (ADR-011 in `docs/context/DECISIONS.md`, owner-confirmed via direct choice): staging will run on a **DigitalOcean** droplet; domain will be registered through **Cloudflare** (also solves HTTPS/HSTS termination via Cloudflare's edge proxy, no self-managed TLS certs needed).
- Out of scope, unchanged: Square/external payment or scheduling integration; live/billable OpenAI calls.

## Verified baseline

- No real cloud infrastructure exists yet. Everything below was built/rehearsed against the existing local Docker Compose dev stack only.
- `app/main.py`: added `Strict-Transport-Security: max-age=63072000; includeSubDomains` to the `security_headers` middleware, gated on `settings.frontend_origin.lower().startswith("https://")` — same pattern as the existing Secure-cookie check in `app/auth.py`. Deliberately does NOT trust a client-supplied `X-Forwarded-Proto` header (documented in code as a limitation to revisit once staging's real reverse-proxy topology exists — trusting that header today, with no confirmed trusted-proxy boundary, would let a client force a spoofed HSTS response).
- `scripts/optimusctl.sh`: added `restore <dump-file> [target-db]` (restores into a scratch database only — refuses if `target-db` matches the live `POSTGRES_DB` **read from `.env` directly**, not the invoking shell's ambient environment; refuses reserved Postgres names `postgres`/`template0`/`template1`; refuses non-plain-identifier names), `rollback` (retags `optimus-server-backend`/`optimus-server-worker` Docker images from `:previous` back to `:latest`, sudo-aware via a `DOCKER` array matching the script's existing `COMPOSE` convention), and `migrate-down <revision>` (runs `alembic downgrade` via the backend container). `update()` now tags current `:latest` images as `:previous` before rebuilding, so `rollback` has something to revert to.
- `tests/test_security_headers.py` (new): the only test file in this repo that does real ASGI/middleware testing via `fastapi.testclient.TestClient` against the actual `app.main.app`, rather than this suite's usual direct-route-function-call style. Confirmed reasoning: `monkeypatch.setattr(main, "get_settings", ...)` only affects the middleware's direct unqualified call, not the already-captured `Depends(get_settings)` used by route dependency injection — tests only assert on response headers, never on settings-derived response bodies, so this is safe.

## Evidence

- Gates (2026-07-09): `ruff format`/`ruff check .` clean repo-wide; `pyright` 0 errors; `pytest -q` **174 passed** (171 prior + 3 new in `tests/test_security_headers.py`).
- Independent review + security review both completed 2026-07-09 on all Phase 5 local-prep changes. Four real findings, all fixed same-day and re-verified:
  - **High**: `tag_current_as_previous()`/`rollback()` used bare `docker` commands instead of the script's existing sudo-detection convention, which would have broken `update()` (an existing, previously-working command) on any host needing `sudo docker`. Fixed by adding a `DOCKER` array mirroring the existing `COMPOSE` array.
  - **Medium**: `restore()`'s live-database guard read `POSTGRES_DB` from the invoking shell's ambient environment, not from `.env` (the file docker compose actually uses) — a staging `.env` with a non-default `POSTGRES_DB` could silently bypass the guard. Fixed with an `env_value()` helper that parses `.env` directly.
  - **Medium**: `restore()` had no denylist for PostgreSQL's own reserved/system database names (`template0`, `template1`). Fixed with an explicit denylist.
  - **Low**: `docs/context/CURRENT_STATE.md` mislabeled PR #7 as the Phase 2 merge (it's Phase 3; Phase 2 was PR #6, previously unmentioned in that doc). Fixed.
  - Also flagged, not fixed (documented instead): HSTS gating trusts a static setting rather than a per-request TLS signal — both reviewers independently raised this; deliberately not changed to trust `X-Forwarded-Proto` without a confirmed trusted-proxy boundary in front of the app (see code comment in `app/main.py`).
- Rehearsals against the real local dev stack (2026-07-09), re-run after all fixes with the same successful outcomes:
  - `backup` → `restore` into `optimus_os_restore_check`: row counts confirmed matching the live DB exactly across `user_accounts` (17), `customers` (132), `invoices` (6), `invoice_payments` (4).
  - Guard tests: `restore <dump> optimus_os` → refused (live DB name); `restore <dump> template1` → refused (reserved name); `restore <dump> 'evil"; DROP DATABASE optimus_os; --'` → refused (identifier-shape check) — all three dangerous inputs correctly blocked, legitimate default path still works.
  - `rollback`: tagged current images `:previous`, force-recreated backend onto a deliberately broken `busybox` image, confirmed `/health` failed completely, ran `rollback`, confirmed `/health` returned `200` again with the exact original image ID restored.
  - `migrate-down 008_invoices` then `migrate` (upgrade head): clean round-trip back to `009_payments (head)`, dev stack confirmed healthy throughout.
  - All rehearsal artifacts (scratch DB, `:previous` tags, the busybox image) cleaned up afterward.

## Unverified

- No real staging infrastructure exists — everything above is local-only prep and rehearsal, not a deployed staging environment.
- No droplet, domain, DNS, TLS, secrets-store, or external monitoring/alerting has been configured or tested against anything real.
- No browser/Playwright UI click-through was performed this session (no frontend changes were made).

## Unrelated preexisting changes

- None newly observed this session beyond what was already known (4 pre-existing `ruff format` drift files predating Phase 3, unrelated to any diff touched here).

## Blockers and risks

- **Owner action required before Phase 5 can proceed further**: create the DigitalOcean account, add a payment method, create a droplet; register the domain through Cloudflare. No agent can perform any of this (real credentials, spending money, cloud provider actions all require explicit owner action per `AGENTS.md`).
- Nothing on `ops/staging` is committed or pushed yet.
- Carried over: payment-schedule installment percentage split remains an owner-confirmed placeholder pending real business-rule confirmation (`docs/context/BUSINESS_RULES.md`).

## Exact next task

Once the owner has a DigitalOcean droplet and a Cloudflare-registered domain, the next agent-assisted work is: provision the droplet (Docker + Compose), configure Cloudflare DNS/proxy for HTTPS termination, set up separate staging PostgreSQL/Redis credentials, get secrets onto the host without committing them, and wire up `/health`+`/ready` external monitoring. Until then, this branch's local-prep work is ready to commit/push pending explicit approval, but real deployment work is blocked on the owner's account/domain setup.
