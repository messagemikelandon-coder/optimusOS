# Session Handoff

Purpose: replaceable handoff for the next substantial Codex/Claude session.
Information owner: the active session author.
Read when: starting or resuming work.
Update when: a substantial task completes or context needs to be handed forward.
Last verified date: 2026-07-23.

## Identity

- Agent/task owner: Claude — vehicle-first foundation slice: standalone VIN-decode vehicle-intake endpoint with safe-failure states and automatic field population (`/goal` order item 2).
- Branch/HEAD: `agent/claude/vin-decode-intake`, one implementation commit on top of `main` at `e5ead03` (the merge of PR #84, Phase 2B). Branched from `origin/main`.
- Working directory: primary repo checkout (`origin` = the optimusOS GitHub repository).

## Context

The repository is already at/near the `/goal` 60–75% target: `docs/context/GOAL_EVIDENCE_MATRIX.md` (verified against source) shows the full Customer→Vehicle→Estimate→Owner/Customer-approval→Work-Order→Invoice→History workflow, the multi-tenant Shop model, billing, support-admin, and operating modes are all implemented, tested, and merged (migrations through `035`). Phase 2B (goal item 1) is already merged (PR #84). VIN *decode* logic existed but only inside the AI estimator orchestrator (`app/orchestrator.py`) — it was **not** exposed for standalone vehicle intake and had **no safe-failure surface**. This slice closes that specific gap.

## Active task (implemented, verified locally, awaiting review/merge approval)

Standalone VIN-decode vehicle intake. Surface and files:

- `app/models.py` — `VinDecodeStatus` (`decoded`/`partial`/`unavailable`), `VinDecodeRequest` (strict 17-char VIN, normalized/validated), `VinDecodeResponse` (`status`/`message`/`decoded`).
- `app/services/vin.py` — new `VinService.decode_intake(vin)`: wraps the existing `decode()`, catches `httpx.HTTPError`/`ValueError`/`KeyError`/`TypeError` and empty results, returns `unavailable` (never raises), classifies decoded vs. partial, logs a secret-free `vin_decode.unavailable` reliability event (error type only, never the VIN).
- `app/main.py` — `POST /api/vehicles/decode-vin`, owner/manager-gated (`OwnerAuthContextDep`), `enforce_vin_decode_rate_limit` (per-client), `Cache-Control: no-store`; `get_vin_service` dependency + `VinServiceDep` restricted to the `vpic.nhtsa.dot.gov` host allowlist; `Depends` added to the fastapi import.
- `app/config.py` — `max_vin_decode_requests_per_minute` (default 20, 1..240). `.env.example` documents it.
- `app/static/index.html`/`app.js`/`styles.css` — "Decode VIN" button + live status on the vehicle form; `decodeVehicleVin()` populates only empty identity fields (never clobbers hand-entered values), uppercases the VIN, disables the button while in flight, renders status via `textContent`.
- `tests/test_vin.py` — `decode_intake` decoded/unavailable-on-upstream-failure(×4)/empty-result units.
- `tests/test_vin_decode_api.py` — endpoint auth (401 unauthenticated), owner decoded happy path (+ VIN upper-cased before lookup, no-store header), safe-failure `unavailable` is HTTP 200, invalid-VIN → 422 (×3), per-client rate limit → 429.

Out of scope (deliberately not done): customer-less estimates/diagnostics (a large change across the multi-tenant boundary — high collision risk with the 10+ in-flight worktrees); any migration/schema change; any write path; wiring decode into vehicle create/update automatically; a paid/keyed VIN provider (vPIC is free/public); any capability enforcement (Bays stays OBSERVE-only, AST safeguard untouched).

## Verified baseline

- `ruff format --check app tests`, `ruff check app tests`, `pyright` — all clean (0 errors).
- `node --check app/static/app.js` — clean. `git diff --check` — clean.
- `pytest --ignore=tests/e2e` — **799 passed, 2 skipped** (was 786; +13 net-new tests; no pre-existing test weakened). `tests/test_role_isolation.py` and `tests/test_capability_gate_safeguards.py` green — new route correctly owner-gated, no `CapabilityGateMode.ENFORCE`.
- `alembic` head unchanged: `035_operating_mode_confirmed_at` (no migration).

## Unverified

- Full Docker/Playwright `tests/e2e` not run in this container (no Docker/Postgres/Redis) — CI's job. This slice adds no e2e test.
- No real outbound NHTSA call was made; the decode path is proven through injected boundaries plus the safe-failure design and the existing `VinService.decode` tests, not exercised against live vPIC here.

## Blockers and risks

- No engineering blocker. Additive and revert-safe (revert the single commit; no migration/schema/data).
- **Publishing/merge gate:** per `CLAUDE.md`/`AGENTS.md`, opening/merging the PR requires Dejake's explicit current-turn approval. Not merged autonomously. `main` currently has 10+ concurrent agent worktrees branching off it — sync `main` and re-run gates before merge.
- Egress to `origin` may be blocked by org policy in this container; if so, deliver via `git format-patch` and open the draft PR (title: `Vehicle-first: standalone VIN-decode intake endpoint`) once egress is available.

## Exact next task

1. Owner reviews the branch/diff and, if approved, merges (do not merge without explicit approval; sync `main` and re-run gates first).
2. Natural follow-ups (each its own slice, none started here): auto-decode on vehicle create when a VIN is entered; customer-less (vehicle-first) estimate/diagnostic entry across the tenant boundary; VIN check-digit validation; a cached/offline decode fallback.
