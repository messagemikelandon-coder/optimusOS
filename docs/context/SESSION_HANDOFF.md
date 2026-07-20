# Session Handoff

Purpose: replaceable handoff for the next substantial Codex/Claude session.
Information owner: the active session author.
Read when: starting or resuming work.
Update when: a substantial task completes or context needs to be handed forward.
Last verified date: 2026-07-20.

## Identity

- Agent/task owner: Claude, `/goal` Phase 1 of the approved security-kernel roadmap.
- Branch/HEAD: `agent/claude/architecture-decision-preservation`, on top of `main` at `197907f` (Phase 8, already merged). Not pushed/PR'd/merged; `main` untouched.
- Working directory: the primary repo `/home/dejake/optimus-server` (not a worktree).

## Context

The Laravel-vs-FastAPI stack decision was made and preserved (retain and simplify FastAPI; no Laravel/PHP, ever). See `docs/architecture/STACK-DECISION.md`, the ADRs `ADR-014`..`ADR-021` in `docs/architecture/adr/`, and the index `docs/architecture/README.md`. The Laravel PoC at `/home/dejake/optimus-laravel-poc/` is retained as research evidence only — not deployed, not deleted.

## Active task — DONE this session, awaiting owner review

**Phase 1: extract, centralize, test, and harden the existing security kernel.** Full report: `docs/architecture/PHASE1-SECURITY-KERNEL-COMPLETION.md`. Inventory/plan: `docs/architecture/PHASE1-SECURITY-KERNEL-PLAN.md`.

Seven independently-revertible commits (`bc25e0f`, `ac5024e`, `a61c21e`, `a8ac217`, `7b049e5`, `e4843d9`, `01728b6`):

1. Deleted the unauthenticated / tenant-unscoped / un-rate-limited `OptimusInternetSkill` AI bypass (`integration/optimus_adapter.py`) + regression test.
2. Fail-closed production startup validation (`app/startup_checks.py`): blank/placeholder/short secrets or a sqlite prod `DATABASE_URL` refuse boot, with no value leakage.
3–5. Normalized security-audit contract (`SecurityAuditEvent`/`ActorType`/`EventResult` in `app/security_events.py`, backward compatible) + verified 429s for all seven rate limiters + centralized the seven copy-pasted limiter blocks into one `RateLimiterRegistry` with header/endpoint bypass tests.
6. Positive tenant-primitive AST assertion across every `*_store.py` + a background-job tenant-safety test.
7. Shared secret-redaction utility (`app/redaction.py`) wired into the JSON log formatter.

Deliberately **not** done (documented in the report, not defects): ShopEvent DB-writer actor retrofit (risk > gain; variance is largely legitimate), the three message-sniffing error handlers (already test-pinned), and any broad API-key lifecycle (out of scope by approval).

## Verified baseline (this session)

- `ruff format --check .`, `ruff check .`, `pyright` — all clean.
- `pytest --ignore=tests/e2e` — exit 0, 542 tests (+77 net-new Phase 1 tests; no pre-existing test's assertions weakened).
- Real-Postgres production-parity boot check: `/health` 200 with `APP_ENV=test`; fail-closed confirmed with `APP_ENV=production` + blank secrets. The full Docker/Playwright e2e suite is CI's job (expected green there — CI ships no `.env`, so the harness's `APP_ENV=test` makes the guard a no-op); it was not run in full locally because this sandbox's real `.env` is production-mode and the new guard correctly refuses that boot.

## Evidence

Full evidence is in `docs/architecture/PHASE1-SECURITY-KERNEL-COMPLETION.md` (§3 test commands/results, §4 controls consolidated, §5 gaps closed). Summary: `ruff format --check`, `ruff check`, `pyright` all clean; `pytest --ignore=tests/e2e` = 542 passed, 2 skipped (+77 net-new Phase 1 tests); real-Postgres boot verified both ways (safe config → `/health` 200; unsafe production config → fail-closed). Draft PR #66 (`Phase 1: Harden and centralize security kernel`) is open into `main` and not merged.

## Unverified

- The full Docker/Playwright `tests/e2e` suite was not run locally (CI's job; this sandbox's production-mode `.env` correctly trips the new startup guard). It runs in CI on PR #66.
- The deferred items in the completion report (§6: ShopEvent DB-writer actor consistency, message-sniffing error handlers, broad API-key lifecycle) are documented, not implemented, and not independently reviewed.

## Unrelated preexisting changes

- None. Every commit on this branch is scoped to Phase 1 (security-kernel hardening) plus a Phase-1 CI-compatibility fix. No unrelated feature or refactor is bundled in.

## Blockers and risks

- No engineering blocker. Risks are the three documented deferred items (none an active exploit) and the standard review/merge gate: publication beyond the pushed branch/draft PR (i.e. merge) needs explicit owner approval per this repo's git rules — not yet given.

## Exact next task

1. Owner reviews Phase 1 (`PHASE1-SECURITY-KERNEL-COMPLETION.md`) and draft PR #66; then decide on merge. Merge requires explicit current-turn owner approval per this repo's git rules — not yet given.
2. Do **not** start Phase 2 (deployment simplification, ADR-014) or any prompt/manual-execution (ADR-017), vehicle-ownership (ADR-015), or Sentinel (ADR-021) work without explicit approval. Recommended Phase 2 is the low-risk deployment simplification; rationale in the completion report §9 and the Phase 2 readiness note `docs/architecture/PHASE2-READINESS.md`.
