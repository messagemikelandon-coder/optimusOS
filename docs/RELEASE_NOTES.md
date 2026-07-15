# Release Notes

Purpose: human-readable summary of what changed per version, generated from merged PRs. This is the first version to have a formal entry — see `docs/context/PLANS.md` for the full historical phase-by-phase record of everything shipped before this doc existed.
Format: newest version first. Each entry lists the merged PRs it's built from and a short summary of user-visible or operationally relevant change. Internal review findings and full verification detail live in `docs/context/PLANS.md` and `docs/context/CURRENT_STATE.md`, not here.

## 7.1.0 (release candidate, not yet tagged or deployed)

Built from PRs #27–#31 (Phase 6 Parts A, B, C first increment, and H first three sub-items) plus this release-process infrastructure work (Phase 6 Part J).

- **CI enforcement** (#27): every PR and push to `main` now runs lint/typecheck/test, a real-Postgres migration round-trip check, and a full Docker Compose integration boot with health/readiness polling and a log secret scan — previously only the AI-coordination handoff doc was validated in CI.
- **Synthetic test-account provisioning + authenticated E2E suite, first increment** (#28): a double-gated (env flag + non-production) test-only path to mint and clean up synthetic owner/technician accounts, plus a real-browser Playwright suite driving the full customer → estimate → approval → work order → invoice → payment workflow through real logins and real API calls — the first genuine authenticated end-to-end proof in the project (prior "live proofs" used a frontend auth-state bypass).
- **Approval-token revocation** (#29): owners can now revoke an active estimate-approval link; the revoked token immediately 404s on the public approval view, the audit trail records the revocation and reason, and the estimate resets to `ready` so a fresh link can be sent without a new research call.
- **Multi-instance-safe rate limiting** (#30): estimate/chat rate limiting moved from an in-process counter (silently multiplied across load-balanced instances) to a Redis-backed sliding window shared correctly across instances, with a best-effort in-process fallback if Redis is briefly unreachable.
- **Structured JSON logging + request correlation** (#31): replaces plain-text `logging.basicConfig` with structured JSON log lines, a per-request correlation id (`X-Request-ID`) propagated to every log line emitted during that request, and an automated log-exposure test asserting passwords/API-key-shaped values never appear in logs.
- **Release process infrastructure** (this change, Phase 6 Part J): semantic versioning with a single source of truth and a drift-prevention test; `/health` and `/ready` now report `version`, `git_commit` (baked in at Docker build time), and `migration_head`; a new schema-compatibility check (`app/migration_compat.py`) prevents the app from reporting itself ready against a database schema it doesn't recognize, while correctly tolerating the normal deploy-order window where new app code briefly runs against old-but-compatible schema (see ADR-012); the System bay UI now displays the running build's migration head and commit; `docs/context/RELEASE_CHECKLIST.md` documents the release process, required gates, and rollback criteria.

**Not included in 7.1.0**: Phase 6 Parts D–G (Diagnostics/Inspections auditability, technician workflow for those modules, Purchase Orders, full Reports), the remainder of Part C (newer-module and security-behavior E2E coverage), the remainder of Part H (threat model, full security-event taxonomy, OpenAI cost logging, retention/export/deletion policy, monitoring/alerting), and Part I (staging verification). See `docs/context/PLANS.md` for current status of each.

## 7.0.1 and earlier

No formal release-notes entries exist for versions before 7.1.0. The complete history — every phase, sub-phase, and PR from the original Estimate Approval slice through Phase 5.6's eight sub-phases — is recorded in `docs/context/PLANS.md`.
