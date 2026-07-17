# Data Retention, Export, and Deletion

Purpose: the Phase 6 Part H deliverable for customer-data retention, export, and deletion — what's actually implemented today, what's a documented policy default pending owner/accountant confirmation, and what's an explicitly open gap.
Information owner: Landon Motor Works owner (business/legal decisions), repository maintainers (technical implementation).
Read when: a customer or regulator asks about their data; before building any customer-facing "download my data" or "delete my account" feature; before changing archive/delete behavior on `Customer`, `Vehicle`, `Estimate`, `WorkOrder`, or `Invoice`.
Update when: the owner confirms or changes a retention period, a real export/deletion request is handled, or new technical export/deletion capability ships.
Last verified date: 2026-07-17.
Relevant sources: `app/db_models.py`, `app/customer_store.py`, `app/customer_history_store.py`, `app/main.py`, `docs/context/BUSINESS_RULES.md`, `docs/context/SECURITY.md`.

## Scope and jurisdiction

OptimusOS serves one business (Landon Motor Works, a US-based mobile mechanic shop) and that business's own customers. This is not a GDPR-scoped consumer platform; the relevant framework is US small-business record-keeping practice (IRS guidance on business/tax records) plus ordinary customer-privacy courtesy, not EU-style "right to erasure" law, unless the owner's jurisdiction imposes something stricter — **the retention periods below are a defensible starting default, not a legal opinion, and should be confirmed with the owner's accountant/attorney before being treated as final**, matching how this codebase already flags other business-policy defaults (e.g. the payment-schedule installment split in `docs/context/BUSINESS_RULES.md`) as owner-confirmable rather than authoritative.

## What personal data OptimusOS stores

- **Customers**: name, email, phone, address (`app/db_models.py`'s `Customer` table).
- **Vehicles**: owner-of-record is the customer; VIN, plate, year/make/model — not personal data on its own, but linked to a customer.
- **Estimates, work orders, invoices, payments**: contain a point-in-time snapshot of customer/vehicle info (`customer_snapshot`, `vehicle_snapshot` fields) plus the actual financial transaction — these are the real financial records.
- **Technicians**: employment data for the owner's own staff, not customers; out of scope for this document (a separate employment-record retention question, not addressed here).

## Retention

**Financial records (estimates that became invoices, invoices, payments): retain for 7 years from the transaction date.** This is a conservative, defensible default based on common US small-business tax record-keeping guidance (bank/audit records are often recommended at 7 years, aligned with typical statute-of-limitations windows for tax audits) — the owner's accountant should confirm the exact period required for Landon Motor Works' specific situation. **Not yet enforced by any automated process** — there is no code today that purges records after 7 years; this is a stated target, not a running job.

**Non-financial customer data (a customer record with no completed invoice — e.g. a lead that never converted, or a declined estimate): no fixed retention period is set today.** Recommended default: retain for as long as the business relationship is active or being pursued, and honor a deletion request (see below) once there's no live financial record tying the customer to a retained transaction.

**Archived (soft-deleted) records**: `Customer.is_archived` (and the equivalent flag on `Vehicle`, `Estimate`, etc.) already exists and is used throughout the app — archiving hides a record from active owner-facing lists but does **not** delete or anonymize any data. Archiving is not a substitute for a real deletion process; it's a UI/workflow concern (declutter the active list), not a privacy control.

## Export

**Implemented today, owner-only, no new code needed**: `GET /api/customers/{customer_id}/history` (`app/customer_history_store.py::get_customer_history`, wired in `app/main.py`) already aggregates a customer's estimates (with approval status), work orders, and invoices (with live balance/overdue status) into one response. Combined with the existing `GET /api/customers/{id}` and `GET /api/vehicles?customer_id=...` endpoints, an owner can retrieve everything OptimusOS holds about a given customer today, entirely through existing, already-tested, owner-authenticated API routes — no new endpoint was required to satisfy "can the owner export a customer's data."

**Not implemented**: a single one-click "download this customer's complete data as a file" button, and no customer-initiated self-service export (a customer cannot log in and request their own data — there is no customer account/login concept in this app at all, only owner/technician accounts and unauthenticated tokenized approval links). If a customer asks Landon Motor Works for their data, the owner today would manually compile it from the endpoints above rather than clicking one button. **This is an accepted, documented gap**, not a hidden one: building a polished export UI is a reasonable future feature, not a blocker for correctly handling a real request today via the existing API.

## Deletion

**Not implemented.** There is no hard-delete or PII-anonymization path for a `Customer` record anywhere in this codebase today — only the archive/soft-delete flag described above, which does not remove any data.

This is deliberately left unbuilt rather than shipped as a guess, for the same reason the Comeback Rate report's auto-detection logic was left unbuilt earlier in this project's history: **building it correctly requires a real business/legal decision the owner hasn't made**, specifically:

1. When a customer has financial records (invoices/payments) that must be retained per the policy above, should a deletion request **anonymize** the PII fields on those records (replace name/email/phone with a redacted placeholder while keeping the financial transaction itself intact) or be **refused** with an explanation that the record must be retained? Both are legitimate approaches used by real businesses; the choice affects what gets built.
2. For a customer with **no** retained financial record (a pure lead/never-converted case), should deletion be a real hard `DELETE` (matching the existing `CASCADE` FK behavior already verified elsewhere in this codebase) or a special "purged" archive state that keeps a minimal audit trail that a deletion happened, without keeping any PII?
3. Who is authorized to execute a deletion — is it always the owner (matching every other action in this single-owner app), or does this need its own audit trail distinct from a normal archive action?

**Recommendation, not yet built**: once the owner answers the three questions above, the correct implementation is a new owner-only route (e.g. `POST /api/customers/{id}/erase`) that either (a) anonymizes PII on the customer record and any `*_snapshot` JSON fields on their financial records while leaving the financial transaction rows themselves intact, or (b) hard-deletes the customer and cascades per the existing FK relationships, depending on the owner's answer to question 1 — plus a regression test proving financial totals/history remain internally consistent after the operation either way. This is scoped as a dedicated future task, not attempted here, since AGENTS.md explicitly requires owner sign-off before any irreversible database operation, and guessing at the anonymize-vs-refuse policy would risk building the wrong thing.

## Summary

| Capability | Status |
|---|---|
| Retention policy documented | Done (this document) — periods are a default pending owner/accountant confirmation |
| Retention automatically enforced | Not implemented — no purge job exists |
| Export (via existing API, owner-executed) | Available today, no new code needed |
| Export (one-click UI / customer self-service) | Not implemented |
| Deletion (soft-archive) | Available today (pre-existing `is_archived` pattern), not a real privacy control |
| Deletion (real erasure/anonymization) | Not implemented — blocked on an owner decision (see above), not a technical gap |
