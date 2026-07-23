# Session Handoff

Purpose: replaceable handoff for the next substantial Codex/Claude session.
Information owner: the active session author.
Read when: starting or resuming work.
Update when: a substantial task completes or context needs to be handed forward.
Last verified date: 2026-07-23.

## Identity

- Agent/task owner: Claude — Diagnostic Evidence Engine slice: enrich the existing `diagnostic_findings` domain with structured, evidence-oriented fields (complaint, safety severity, diagnosis confidence, recommended next test) and a read-layer guarantee that an un-evidenced diagnosis is never presented as fact (`/goal` core-workflow order item 3).
- Branch/HEAD: `agent/claude/diagnostic-evidence-engine`, off `main` at `af653d7` (the merge of PR #85, VIN-decode intake). Migration head advances to `036_diagnostic_evidence`.
- Working directory: primary repo checkout (`origin` = the optimusOS GitHub repository).

## Context

Earlier this session, two `/goal` slices merged to `main`: Phase 2B runtime observability (PR #84) and the vehicle-first VIN-decode intake endpoint (PR #85, `af653d7`). This slice is the next one — the Diagnostic Evidence Engine. The `diagnostic_findings` table already existed (vehicle-scoped, owner/technician-gated CRUD, append-only `diagnostic_finding_events`) with `codes`, `symptoms`, `tests_performed`, `conclusion`. It lacked the evidence structure the `/goal` target calls for: a distinct operator complaint, a safety-severity signal, a diagnosis-confidence signal, a recommended next test, and a guarantee that an unsupported diagnosis is not stated as fact. This slice adds exactly those, additively.

## Active task (implemented, verified locally, awaiting review/merge)

Diagnostic Evidence Engine enrichment. Surface and files:

- `app/models.py` — new enums `DiagnosticConfidence` (`theory`/`probable`/`confirmed`) and `DiagnosticSeverity` (`informational`/`advisory`/`service_soon`/`unsafe`); new fields `complaint`, `confidence`, `severity`, `recommended_next_test` on `DiagnosticFindingBase` (so `Create`/`Read` inherit them) and on `DiagnosticFindingUpdate`; strip-validators extended; new derived read-only `diagnosis_unverified: bool` on `DiagnosticFindingRead`.
- `app/db_models.py` — four nullable columns on `diagnostic_findings` (`complaint` Text, `confidence` String(20), `severity` String(20), `recommended_next_test` Text) plus two CHECK constraints (`ck_diagnostic_findings_confidence`, `ck_diagnostic_findings_severity`) allowing NULL or the enum values.
- `alembic/versions/036_diagnostic_evidence.py` — additive migration adding the columns + constraints; `downgrade()` drops them. down_revision `035_operating_mode_confirmed_at`.
- `app/diagnostics_store.py` — persists/reads the new fields on create/update; `_diagnosis_is_unverified(conclusion, confidence)` helper drives the derived `diagnosis_unverified` flag; enum columns stored as `.value`, read back coerced to the enums.
- `app/static/index.html`/`app.js`/`styles.css` — complaint/severity/confidence/recommended-next-test form controls; detail view renders severity + confidence badges and tags a conclusion **"Unverified working theory"** when `diagnosis_unverified` is true; badge/tag CSS.
- `tests/test_diagnostics_and_inspections_api.py` — +4 tests: evidence-field round-trip, unverified-flag set when conclusion has no confidence and cleared when one is added, no-conclusion is not flagged, invalid-enum rejection at the model boundary.
- `tests/e2e/test_diagnostic_evidence_migration.py` — real-Postgres migration round-trip (035→head column/constraint presence, downgrade removal, re-upgrade).

Out of scope (deliberately not done): a write-time 422 requiring confidence-with-conclusion (rejected in favor of the non-breaking read-layer guarantee — see Evidence); measurements as a separate structured/numeric sub-record (kept inside the free-text `tests_performed`); any change to the append-only event granularity; the Job Compiler (findings→services→estimate lines, `/goal` slice 4) and customer-less vehicles (`/goal` slice 2 remainder) — each its own future slice.

## Verified baseline

- `git diff --check` clean; `ruff format --check app tests alembic`, `ruff check app tests alembic`, `pyright` — all clean (0 errors).
- `node --check app/static/app.js` — clean.
- `pytest --ignore=tests/e2e` — **806 passed, 2 skipped** (+4 net-new tests; no pre-existing test weakened). `tests/test_role_isolation.py`, `tests/test_capability_gate_safeguards.py`, `tests/test_migration_compat.py` green.
- `alembic heads` — single head `036_diagnostic_evidence`; offline `--sql` render for 035→036 verified.
- `pytest tests/e2e/test_diagnostic_evidence_migration.py` — **passed on real Postgres** (docker `postgres:16-alpine`): confirms upgrade adds the columns + constraints, downgrade removes them, re-upgrade restores head.

## Evidence

- Backward compatibility: the "no unsupported diagnosis stated as fact" rule is enforced at the **read/presentation** layer, not by a write block. `DiagnosticFindingRead.diagnosis_unverified` is true when a `conclusion` exists with no `confidence`, and the UI tags such a conclusion "Unverified working theory." This keeps the write API unchanged — a conclusion may still be saved without a confidence, so the four pre-existing conclusion-without-confidence tests (`test_diagnostics_and_inspections_api.py`, `test_reports_api.py`) stay green and no external client breaks.
- Round-trip + derivation: `test_diagnostic_evidence_fields_round_trip` persists/read-backs all four fields and asserts `diagnosis_unverified is False` when confidence is set; `test_conclusion_without_confidence_is_flagged_unverified` asserts the flag is true without confidence and flips to false once a confidence is added via update; `test_no_conclusion_is_not_flagged_unverified` asserts nothing-asserted is never flagged.
- Input safety: `DiagnosticFindingCreate.model_validate` rejects out-of-range `severity`/`confidence` values; the DB CHECK constraints reject them at the storage layer too (NULL always allowed, so existing rows satisfy them).
- Isolation unchanged: the endpoints and store keep the existing owner/technician tenant-scoped queries and append-only event trail; no route gating changed (`test_role_isolation.py` green).

## Unverified

- Full Docker/Playwright authenticated E2E suite not run locally beyond the new migration test; CI's job. The new fields are exercised through the store/API tests and the migration round-trip, not through a browser flow here.
- No live-data migration was run against staging/production; the migration was exercised only against a throwaway local Postgres container.

## Unrelated preexisting changes

- None functional. Every code change is scoped to this Diagnostic Evidence Engine slice. `CURRENT_STATE.md` was updated to record that PRs #84 and #85 are merged (correcting prior staleness that still described them as pending) and to add this slice's section — documentation only, no behavior change.

## Blockers and risks

- No engineering blocker. Additive and revert-safe: revert the single commit and `alembic downgrade 035_operating_mode_confirmed_at`.
- Migration `036` adds columns + CHECK constraints via `ALTER TABLE ADD CONSTRAINT` (Postgres). Unit tests build the schema via `Base.metadata.create_all` (SQLite, inline CHECK) and do not run migrations; the migration path is covered on real Postgres by the new E2E test and by CI's Alembic-integrity job.
- Merge coordination: `main` has several concurrent agent worktrees; sync `main` and re-run gates before merge.

## Exact next task

1. Review the branch/diff; push, open PR, confirm CI green (including the new E2E migration test and the Alembic-integrity job), then merge and sync `main`.
2. Natural follow-ups (each its own slice, none started here): the Job Compiler MVP (`/goal` slice 4) turning an evidenced finding into estimate lines/work-order tasks through one shared service path; surfacing `severity`/`confidence` in the diagnostics list rows and reports; optional structured numeric measurements as a child record; customer-less (vehicle-first) estimate/diagnostic entry (`/goal` slice 2 remainder).
