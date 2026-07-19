# Session Handoff

Purpose: replaceable handoff for the next substantial Codex/Claude session.
Information owner: the active session author.
Read when: starting or resuming work.
Update when: a substantial task completes or context needs to be handed forward.
Last verified date: 2026-07-19.
Relevant sources: current Git state, `docs/context/GOAL_EVIDENCE_MATRIX.md`, full gates, real-Postgres migration rehearsal, real-browser E2E, and independent reviews.

## Identity

- Agent: Codex.
- Synced `main`: `2e99c7bddde83985729393bfa637fa96e5f67887` (PR #60, secure email verification).
- Active worktree: `/home/dejake/optimus-server/.claude/worktrees/tenant-boundary`.
- Active branch: `agent/codex/phase3-tenant-boundary`, based on merged `main` at `2e99c7b`.
- Slice state: final Phase 3 tenant authorization is fully verified and publication-ready on the active branch.

## Active task

Continue the owner-authorized `/goal` roadmap without pausing between safe phases. The current dependency-safe slice closes Phase 3 before the remainder of Phase 5 invitations/account lifecycle.

Implemented in this slice:

1. Migration `028_membership_tenant_boundary`: Manager becomes a valid account role; late real technician accounts missing memberships are backfilled; historical active memberships on already-inactive accounts are normalized inactive; the partial uniqueness rule now permits at most one active membership per account for every role; downgrade refuses rather than deleting Manager data.
2. `effective_shop_id(db, auth)` resolves exactly one active role-matching membership and ignores `UserAccount.shop_owner_id`. Every authenticated request validates this boundary, making membership deactivation and role mismatch immediately fail closed.
3. Every production business-store authorization query now filters its model's `shop_id`; no production store compares `owner_user_id` for authorization. Legacy owner ids remain only for compatibility/audit fields and record numbering.
4. Existing owner-gated operational routes admit Manager accounts. The browser treats Managers as shop operators rather than technicians, including navigation and notification refresh.
5. Technician login provisioning creates the matching Shop membership transactionally, closing the post-migration lifecycle gap.
6. A real frontend defect found during verification was fully corrected: background work-order list refreshes have no authority to replace or clear an active detail pane, because list rows are summaries and may omit the selected record due to paging/filtering/stale requests.

## Verified baseline

- Full fast test suite passed after the repository-wide query cutover (2 Redis-dependent skips remain expected).
- Focused Manager/membership/context boundary suite passed: 36 tests, including a real HTTP Manager session whose deliberately wrong legacy owner pointer cannot change its Shop boundary and corrupt technician-account links that fail closed before mutation.
- `ruff format`, `ruff check`, `pyright` (0 errors/warnings), JavaScript syntax, and `git diff --check` are clean.
- Both real-Postgres tenant migration suites passed (4 tests): the migration-022 historical path, inactive technician normalization, late-technician backfill, synthetic exclusion/pointer preservation, canonical active-owner repair, Manager constraint, downgrade to 027, and re-upgrade to head.
- The complete browser/real-service E2E suite passed: 21 tests, including the core repair workflow and both migration suites.
- Three independent final reviews returned PASS: tenant-scope, security/archive lifecycle, and correctness/migration safety. No blocking findings remain.

## Security invariants

- Membership, not `shop_owner_id`, is the tenant authorization source of truth.
- A session is valid for exactly one active membership and the membership role must match `UserAccount.role`.
- Manager is operationally equivalent to Owner for current shop workflows; future platform subscription-billing ownership changes must use a new explicit owner-only dependency.
- The static regression in `tests/test_membership_tenant_boundary.py` fails if a production store reintroduces an `owner_user_id` comparison.
- Context entries still use the canonical legacy owner id because that assistive-memory table has no `shop_id`; membership validation occurs before every context request. Revisit only if context gains its own multi-shop switching semantics.

## Unverified / owner-gated

- No real email was sent; production email provider selection/credentials remain owner-gated.
- No live/billable OpenAI request was made.
- No staging/production deployment was attempted.
- Real-data retention/deletion policy, production billing provider, production monitoring vendors, and payment-schedule policy remain owner decisions for the final consolidated report.

## Unrelated preexisting changes

- The root worktree still has the long-standing untracked nested `optimusOS/` clone. It was not touched.
- Older worktrees/branches remain outside this slice.

## Exact next task

1. Commit/push/open PR, wait for CI, and merge this fully verified tenant-boundary slice.
2. Sync `main`, create the next isolated branch, and finish the remaining Phase 5 account lifecycle: password change/reset, session list/revocation, login history/lockout, tokenized invitations for owner/manager/technician, disabled/suspended behavior, and MFA-ready architecture.
3. Continue through Phases 6-17 in dependency-safe reviewed slices, consolidating only the real owner/vendor/infrastructure decisions at the end.
