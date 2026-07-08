# Known Issues

Purpose: confirmed defects, environment blockers, and their repair status.
Information owner: repository maintainers.
Read when: assessing current risk or planning repairs.
Update when: a defect is discovered, repaired, or reclassified.
Last verified date: 2026-07-08.
Relevant sources: `git status`, `git diff --stat`, `env UV_CACHE_DIR=/tmp/uv-cache uv run pytest -q`, `docker compose logs --tail=80 backend worker`, `docker compose exec -T backend alembic current`.

## Confirmed Open Issues

- None currently confirmed in the Work Order, Invoice, Payment Tracking, or Phase 4 hardening source implementation, automated verification path, or non-billable live proof path.
- Payment-schedule installment percentage split (Phase 3) is an explicitly flagged placeholder (owner-confirmed even default split) pending real business-rule confirmation — see `docs/context/BUSINESS_RULES.md` and `docs/context/CURRENT_STATE.md`'s Payment Tracking Slice section. Not a defect, but a known open decision.
- No permanent, repeatable, committed automated test exists yet for Phase 4's fresh-volume E2E flow or its three failure drills (Redis down, Postgres down, full restart) — only a one-time manual live-proof run on 2026-07-08. Not a defect, but an open scope decision: build a permanent version before Phase 5, or accept the one-time proof as sufficient.

## Historical Resolved Issues

- Phase 4 (Full Local MVP Hardening) review items resolved on 2026-07-08:
  - independent review found `scripts/scan_logs_for_secrets.py`'s credentialed-connection-URL pattern only matched `postgresql://`, missing a leaked `redis://user:pass@host` even though Redis is a default-scanned service; fixed by broadening the pattern to match any `scheme://user:pass@` URL, and added `bearer`/`client_secret`/`auth_token` to the generic secret-label pattern
  - independent review found two new test docstrings (`tests/test_document_exposure_scan.py`, one test in `tests/test_idempotency_audit.py`) claimed Phase-4-deliverable status without acknowledging they substantially overlap existing per-slice tests; fixed by naming the overlapping test directly in each docstring and stating plainly they're kept for the roadmap's consolidated-scan requirement, not new logic coverage
  - a suspected defect (unwrapped, unsanitized DB error path in `app/auth.py::get_current_auth_context` when Postgres is down) was investigated and ruled out — the function already wraps its DB access in `try/except SQLAlchemyError` returning a sanitized `503`; confirmed by code reading, a live Postgres-down drill, and independent + security review; no code change was needed
- Phase 3 (Payment Tracking) review items resolved on 2026-07-08:
  - security review found the overpayment check was not race-safe under concurrent requests to the same invoice (no row lock); fixed same-day by adding a `SELECT ... FOR UPDATE` lock on the invoice row in `app/payment_store.py::record_payment` before the check-then-insert; full gates re-ran green after the fix
  - independent review found two minor, accepted architecture-drift items (payment logic split into a new `app/payment_store.py` module; an added `le=1_000_000` bound on payment amount) — both documented in `docs/context/SESSION_HANDOFF.md`, neither required a code change
  - a test-only typing issue (`SimpleNamespace` passed where `Invoice` was annotated) and a test-only VIN collision (three fixture vehicles created under one owner in a single test reusing the same hardcoded VIN) were both fixed in `tests/test_payments_api.py`
- Phase 1 closure verification items are resolved:
  - non-billable live Work Order proof passed against the Docker stack
  - independent review findings around blocked transitions, uncached estimate reopening, and note-recency ordering were fixed
  - security review of the Work Order diff completed with no findings
- Phase 2 implementation and verification items completed so far:
  - invoice generation from completed work orders
  - issue action plus due-date stamping
  - customer-safe HTML/PDF document generation
  - forbidden-field exclusion checks for HTML/PDF output
  - Docker rebuild and Alembic head update to `008_invoices`
  - non-billable live invoice UI/API proof including restart persistence and cross-user isolation
  - independent review follow-up fixed completion-time invoice creation to roll back atomically on failure
  - independent review follow-up moved invoice document styling to `/static/invoice.css` so the HTML remains styled under the existing CSP
  - independent review follow-up fixed `fees_total` derivation to include non-canonical fee items
  - independent review follow-up widened invoice line-item descriptions from `String(240)` to `Text` before the uncommitted `008_invoices` migration is finalized
  - independent review follow-up fixed PDF long/multiline rendering by wrapping fragments instead of truncating raw text
  - independent review follow-up fixed invoice list selection rendering so the active-row highlight stays synchronized
- Estimate Approval runtime defects and the `estimator_output_invalid` schema mismatch were resolved before the Work Order slice and remain closed; see Git history and prior session context for the detailed repair record.
