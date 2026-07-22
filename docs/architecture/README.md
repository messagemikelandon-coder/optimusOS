# Architecture decisions index

This directory holds the preserved record of the OptimusOS stack decision (FastAPI vs. Laravel) and the architecture decision records (ADRs) it produced. It is separate from `docs/context/DECISIONS.md` (the repo's lightweight, ongoing decisions log) because this decision was large enough to warrant a full report plus individually addressable ADRs; `docs/context/DECISIONS.md` gets a short pointer entry rather than a duplicate of this content.

## The decision

- **[STACK-DECISION.md](STACK-DECISION.md)** — the full, verified comparison report: raw and feature-normalized metrics, a weighted decision matrix, the recommendation, both architecture lessons the Laravel PoC surfaced (vehicle ownership, environment/database validation), the ordered roadmap, the first security-kernel phase scope, the commit sequence, and risks/rollback/acceptance tests. **Preserved verbatim — do not edit.** Amendments require a new dated ADR below.
- **Approved decision:** retain and simplify the existing FastAPI/JavaScript OptimusOS. Do not migrate to Laravel, begin a phased Laravel rewrite, or run two production applications.
- **Source of the report:** `/home/dejake/optimus-laravel-poc/docs/DECISION.md`, commit `c889e6d8ac81abf8962974bae734b0561e2c24e5`. The PoC repository is retained as research evidence and is not deleted.

## Architecture decision records (ADR-014 through ADR-021)

| ADR | Title | Status |
|---|---|---|
| [ADR-014](adr/ADR-014-final-stack-and-deployment.md) | Final stack and deployment | Accepted |
| [ADR-015](adr/ADR-015-vehicle-identity-and-ownership.md) | Vehicle identity and ownership | Accepted (design), not yet implemented |
| [ADR-016](adr/ADR-016-shared-business-service-layer.md) | Shared business-service layer | Accepted |
| [ADR-017](adr/ADR-017-prompt-manual-shared-execution.md) | Prompt/manual shared execution | Accepted (design), not yet implemented |
| [ADR-018](adr/ADR-018-environment-database-validation.md) | Environment/database validation | Accepted |
| [ADR-019](adr/ADR-019-tenant-boundary.md) | Tenant boundary | Accepted |
| [ADR-020](adr/ADR-020-security-kernel-integration.md) | Security-kernel integration | Accepted — Phase 1, in progress |
| [ADR-021](adr/ADR-021-sentinel-event-integration.md) | Sentinel event integration | Accepted (design), not yet implemented |
| [ADR-022](adr/ADR-022-operating-mode-tier-separation.md) | Operating mode and subscription tier as separate, service-resolved axes | Accepted — implemented (non-enforcing) |

These continue the numbering already used in `docs/context/DECISIONS.md` (which runs ADR-001 through ADR-013 as of this writing) rather than restarting at ADR-001, since they are part of the same project decision history.

## Roadmap and current phase

The ordered roadmap lives in `STACK-DECISION.md` §7. **Phase 1 — security and structural foundation (ADR-020) is complete.** Its inventory, gap ranking, files-to-change list, commit sequence, and test/rollback plan live in **[PHASE1-SECURITY-KERNEL-PLAN.md](PHASE1-SECURITY-KERNEL-PLAN.md)**; the completion record is in **[PHASE1-SECURITY-KERNEL-COMPLETION.md](PHASE1-SECURITY-KERNEL-COMPLETION.md)**. (ADR-020's own Status line still reads "Phase 1, in progress" because that ADR file is preserved under `CHECKSUMS.txt` and is not edited after preservation; this index reflects the current status.) **Next phase: Phase 2 — observability** (structured metrics, disk and Docker-volume monitoring first, alerts, and an operational summary); readiness notes in **[PHASE2-READINESS.md](PHASE2-READINESS.md)**.

Explicitly deferred, not part of Phase 1 or 2: vehicle ownership history (ADR-015) and prompt/manual shared execution (ADR-017) both wait until the earlier phases ship and pass their own acceptance tests.

## Operating modes and subscription tiers

**[OPERATING-MODES-ARCHITECTURE-BRIDGE.md](OPERATING-MODES-ARCHITECTURE-BRIDGE.md)** — design bridge for Solo/Mobile Field/Shop operating modes and the Technician role workspace, covering the current-state inventory, capability matrix, domain model, the single capability-resolution service, safe transitions, role-vs-mode boundaries, prompt-first rules for Optimus, Mobile Field gaps, reversible implementation slices, and route classification. Decision recorded in [ADR-022](adr/ADR-022-operating-mode-tier-separation.md). **Now implemented as non-enforcing slices** (capability service, OBSERVE-only Bays pilot, owner/manager settings-based operating-mode management, capability-shaped navigation, and owner-only non-blocking post-signup onboarding — PR #81, merge commit `7050bb8`, migration head `035_operating_mode_confirmed_at`); see amendments §12a–§12d. **No mode/tier enforcement has shipped** — Bays stays OBSERVE-only and an AST safeguard blocks any `CapabilityGateMode.ENFORCE` reference.

## Rules for this directory

1. `STACK-DECISION.md` is never edited after preservation. A correction or reversal is a new dated ADR, not a change to that file's body (a post-approval addendum section at its end records only the approval fact and pointers).
2. Each ADR file is a single decision; a superseding decision gets a new ADR number and file, with the old one's Status updated to `Superseded by ADR-0NN`.
3. `docs/context/DECISIONS.md` gets a short entry pointing here whenever a decision in this directory is made or changed, per `AGENTS.md`'s existing context-update rule — it does not duplicate the full text.
