# Session Handoff

Purpose: replaceable handoff for the next substantial Codex/Claude session.
Information owner: the active session author.
Read when: starting or resuming work.
Update when: a substantial task completes or context needs to be handed forward.
Last verified date: 2026-07-19.

## Identity

- Agent/task owner: Codex, remaining `/goal` multi-shop pilot phases.
- Synced `main`: `506aff5e58e22ab2118b64420e9700092d58001b` (PR #61, membership-derived tenant authorization).
- Active worktree: `/home/dejake/optimus-server/.claude/worktrees/account-lifecycle`.
- Active branch/HEAD: `agent/codex/phase5-account-lifecycle` at `506aff5`; the worktree is intentionally dirty with the Phase 5 account-lifecycle implementation listed below.

## Active task

Publish the now-complete Phase 5 account-security slice, merge it after CI, sync `main`, and continue Phase 6 without pausing between safe development steps. Password change/reset, session inventory/revocation, user-facing login history, persistent account lockout, owner/manager/technician invitations, disabled/suspended behavior, and MFA-ready metadata are implemented and locally verified.

Current implementation:

- New migration `029_account_lifecycle` adds account status/lockout state, hash-only single-use password-reset tokens, login events, provider-neutral MFA factor metadata with no raw secret field, and normalized/pending-unique invitation email state.
- New `app/account_security_store.py` implements persistent generic-response lockout, password change/reset, session controls, login history, invitation create/list/revoke/accept for all three roles, technician-profile creation on technician acceptance, member listing, and suspension/reactivation with session revocation.
- `app/main.py` exposes the account/session/reset/invitation/member APIs, applies Redis-backed public reset/invitation throttling, and emits structured lifecycle security events. Reset request, reset confirmation, and invitation acceptance now use separate limiter keys/domains after UI review caught cross-flow exhaustion.
- `UserAccount.account_status` is enforced during login and every authenticated request; disabled/suspended accounts cannot retain usable sessions.
- `app/static/index.html`/`app.js` now provide public forgot/reset/invitation views and System-bay password, session, login-history, invitation, and member-status controls. Account-security loads use an auth-generation guard and explicit clearing so logout/account changes cannot leave stale prior-user data.
- New fast coverage in `tests/test_account_security_api.py` exercises lifecycle/security scenarios including HTTP routes, Manager permissions, legacy privileged-invitation rejection, and cross-Shop isolation. Real-Postgres migration, successful-login metadata, reset/provisioning concurrency, and real-browser workflows are committed tests.
- Reviewer remediation now also bounds both login-event and successful-session metadata, lets correct credentials clear a defensive lockout cooldown, revokes reset tokens on password/status/archive changes, cancels a suspended inviter's pending grants, limits Managers to technician invitations at creation and acceptance, translates invitation uniqueness races, serializes invitation acceptance/direct provisioning on the same Technician row, links existing unassigned technician profiles, rejects reactivation of archived profiles, and deterministically revokes duplicate normalized legacy invitations during migration.

Out of scope for this slice: real email/SMS provider integration, production credentials, staging/production deployment, actual MFA enrollment/challenge UX, owner ownership-transfer/offboarding policy, and all later Phase 6-17 domains.

## Verified baseline

- PR #61 merged with all six GitHub checks green: handoff contract, Alembic integrity, lint/type/unit/JS, authenticated E2E, backup/restore/rollback, and Docker boot/secret scan.
- Root `main` was fast-forwarded to `506aff5`; the long-standing untracked root `optimusOS/` clone remains untouched.
- Complete fast suite: **449 passed, 2 skipped**.
- Complete real-Postgres/Chromium E2E suite: **26 passed**. The session-scoped E2E server uses a test-only 240-login allowance because all synthetic clients share `127.0.0.1`; production defaults and limiter tests are unchanged.
- Focused account/technician/role/UI suite: **50 passed**; focused migration/concurrency suite: **4 passed**.
- Migration 029 passed a real-Postgres upgrade from 028, normalized-duplicate remediation and constraint assertions, downgrade, and re-upgrade.
- Real PostgreSQL proves successful long-User-Agent login metadata is bounded, reset request/confirmation completes without deadlock, and concurrent invitation acceptance/direct provisioning yields exactly one account linked to the Technician profile.
- The expanded Chromium workflow proves owner password change, second-session revocation, Manager and Technician invitations/acceptance, Manager invitation restrictions and suspension invalidation, invitation revocation, Technician self-service/current-session revoke, password reset, all-session revocation, and relogin.
- Independent UI, correctness/migration, and security re-reviews all returned **PASS** on the stabilized diff.
- Final repo-wide gates are green after the documentation edits: `ruff format --check .` (162 files), `ruff check .`, `pyright` (0 errors), `node --check app/static/app.js`, `git diff --check`, and `python3 scripts/check_ai_handoff.py`.
- The new worktree dependency download stalled; its `.venv` was safely populated from the already-locked sibling tenant worktree without changing project dependencies or lockfiles.

## Evidence

- Password reset and invitations store only SHA-256 token hashes; raw codes exist only in the injected non-sending email adapter and are not returned by APIs or logged.
- Password change preserves the current session and revokes all others; password reset revokes every session and is single-use.
- Lockout is per account and persists in PostgreSQL while the external login response remains the same generic 401.
- Invitation acceptance creates exactly one role-matching Shop membership; technician acceptance also creates the linked same-shop Technician profile.
- Suspension/disable updates account and membership together and revokes active sessions; reactivation restores both without bypassing membership validation.
- MFA schema contains provider references and lifecycle metadata only, not TOTP/shared secrets.

## Unverified

- GitHub CI has not yet run on the account-lifecycle branch, and the branch is not yet committed/pushed/merged.
- No real email was sent, no billable API was called, and no staging/production change was attempted.

## Unrelated preexisting changes

- Root worktree `/home/dejake/optimus-server` remains on clean `main` except the pre-existing untracked nested `optimusOS/` clone.
- Older tenant-boundary and release-process worktrees remain separate and are not being edited.

## Blockers and risks

- No external blocker. Local implementation, runtime proof, and independent reviews are complete; only publication/CI remains for this slice.
- Real email delivery, actual MFA provider enrollment, production deployment, owner ownership-transfer semantics, and real-data retention decisions remain owner/vendor/infrastructure gated.
- Current invitation acceptance is intentionally for a new platform account; joining a second Shop with an existing account remains unsupported while sessions have no Shop selector.

## Exact next task

1. Inspect the staged diff, commit, push, and open the Phase 5 account-lifecycle PR.
2. Wait for all CI, merge, and sync `main`.
3. Cut the next isolated Phase 6 branch from the verified merged baseline and continue the `/goal` roadmap.
