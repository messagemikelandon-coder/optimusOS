# OptimusOS Operating Modes Architecture Bridge

Purpose: design bridge for supporting three operating modes (Solo, Mobile Field, Shop) plus a Technician role workspace, and subscription tiers, on the existing one-codebase FastAPI/JavaScript stack — without duplicated business logic, and without shipping any code change in this document.
Information owner: repository maintainers and Dejake (owner approval required for the unresolved decisions in §11).
Read when: planning or reviewing any future mode/tier/capability work.
Status: **design/docs only.** No schema, runtime, frontend, API, permission, entitlement, navigation, or behavior change ships with this document. See [ADR-022](adr/ADR-022-operating-mode-tier-separation.md) for the accepted decision this document elaborates.
Last verified date: 2026-07-20.
Verification method: direct source inspection this session (`app/db_models.py`, `app/auth.py`, `app/api/deps.py`, `app/main.py`, `app/api/routers/*.py`, `app/static/{index.html,app.js}`, `app/*_store.py`), not carried forward from prior docs. Where an existing doc (`ARCHITECTURE.md`, `PRODUCT.md`) was found stale relative to code, this document defers to code and flags the doc lag in §12.

## How to read this document

Per task instruction, facts, recommendations, unresolved owner decisions, and risks are kept visually separate throughout:

- **Fact** — directly verified from source, file:line cited.
- **Recommendation** — this session's proposed direction; not yet approved.
- **Unresolved decision** — requires an explicit owner call before implementation; collected in §11.
- **Risk** — collected in §12.

---

## 1. Current inventory

### 1.1 Tenant/shop model (Fact)

| Table | Purpose | Key fields |
|---|---|---|
| `Shop` (`app/db_models.py:2011`) | Tenant identity. Docstring calls it "the tenant boundary." | `display_name`, address fields, `timezone` (default `America/Chicago`), `currency` (default `USD`), `status` (`pilot\|active\|suspended\|cancelled`) |
| `ShopSettings` (`:2094`) | 1:1 operational config, deliberately separate from identity because it changes more often. | `labor_rate`, `mobile_service_fee`, `shop_supplies_percent`, `parts_tax_rate`, `operating_hours` (JSON, unused), `service_area` (JSON, unused), `estimate_terms_text`, `invoice_terms_text`, `payment_plan_settings` (JSON), `branding_reference` |
| `ShopMembership` (`:2134`) | Links `UserAccount` ↔ `Shop` with a role. Exactly one active membership per user (partial unique index) — no shop-switcher exists. | `role` (`owner\|manager\|technician`), `is_active` |
| `ShopInvitation` (`:2182`) | Hash-only, expiring, single-use, revocable invitations. | `role`, `token_hash`, `expires_at` |
| `ShopEvent` (`:2232`) | Append-only audit trail for shop-level admin actions. Precedent this document reuses for capability/mode-change audit (§4, §5). | — |
| `ShopSubscription` (`:2339`) | One row per shop, OptimusOS's own platform billing (distinct from `square_store.py`'s customer-invoice integration). | `tier` (`solo\|team\|shop`), `billing_status` (`trialing\|active\|past_due\|canceled`), `seat_limit`, trial/period timestamps |

**No `mode`/`plan` column exists on `Shop` or `ShopSettings` today.** The closest thing is comment-only: four Phase 2C router docstrings (`app/api/routers/bays.py:13-15`, `working_hours.py:17-22`, `schedule_blocks.py:17-25`, `appointments.py:27-33`, all dated 2026-07-20) already classify their routes against "Solo Mode"/"Shop Mode"/"Mobile Field Mode"/a future "Technician Mode," explicitly noting "routing only, no gating added here." This document formalizes that vocabulary rather than inventing new terms — see ADR-022.

### 1.2 Roles (Fact)

Source of truth: `UserAccount.role` check constraint (`app/db_models.py:31`): `owner | manager | technician | support`. (`ShopMembership.role`/`ShopInvitation.role` allow only `owner | manager | technician` — `support` is shop-less and platform-level, per `app/auth.py:689`.)

| Auth dependency (`app/api/deps.py:33-44`) | Roles admitted | Underlying function |
|---|---|---|
| `AuthContextDep` | any authenticated user | `get_current_auth_context` |
| `VerifiedAuthContextDep` | any authenticated, email-verified user | `require_verified_auth_context` |
| `OwnerAuthContextDep` | `owner`, `manager` (name is legacy; actually owner-or-manager) | `require_owner_context` — also requires active shop billing access |
| `OwnerOrTechnicianAuthContextDep` | `owner`, `manager`, `technician` | `require_owner_or_technician_context` |
| `BillingAuthContextDep` | `owner`, `manager` | `require_billing_context` — deliberately skips the active-billing check so a suspended shop can still pay to restore access |
| `SupportAuthContextDep` | `support` only | `require_support_context` |

The named example pattern — six owner-only + three self-service technician routes on `/api/technicians*` (`app/api/routers/technicians.py:10-17`) — is the precedent this document's role-vs-mode boundary section (§6) generalizes from.

### 1.3 Routes (Fact — module-level; full endpoint table available via `git log` grep of `app/main.py`/`app/api/routers/*.py`)

| Module | Base path(s) | Auth | Extracted router? |
|---|---|---|---|
| Auth (pre-auth) | `/api/auth/login`, `/api/signup`, `/api/auth/verify-email*`, `/api/auth/password/reset-*`, `/api/invitations/accept` | none | no |
| Auth (self-service) | `/api/auth/me`, `/password/change`, `/sessions*`, `/login-history`, `/security` | `AuthContextDep` | no |
| Shop membership | `/api/shop/invitations*`, `/api/shop/members*` | `OwnerAuthContextDep` | no |
| Billing | `/api/billing/*` (7 routes) | `BillingAuthContextDep` | no |
| Support | `/api/support/*` | `SupportAuthContextDep` | no |
| Test-support (synthetic accounts) | `/api/test-support/*` | none (gated by `provisioning_enabled(settings)`) | no |
| Customers | `/api/customers*` | `OwnerAuthContextDep` | no |
| Vehicles | `/api/vehicles*` | `OwnerAuthContextDep` | no |
| Purchase orders | `/api/purchase-orders*` | `OwnerAuthContextDep` | no |
| Part allocations | `/api/work-orders/{id}/part-allocations`, `/api/part-allocations/*` | `OwnerOrTechnicianAuthContextDep` (events endpoint owner-only) | no |
| Workflow gaps | `/api/workflow-gaps*` | `OwnerAuthContextDep` | no |
| Intake requests | `/api/intake-requests*` | `OwnerAuthContextDep` | no |
| Diagnostic findings | `/api/diagnostic-findings*` | `OwnerOrTechnicianAuthContextDep` (delete/events owner-only) | no |
| Inspections | `/api/inspections*` | `OwnerOrTechnicianAuthContextDep` (delete/events owner-only) | no |
| Location/chat (Optimus) | `/api/location/resolve`, `/api/chat` | none today | no |
| Estimates | `/api/estimates*` | `OwnerAuthContextDep` | no |
| Estimate approval | `/api/estimate-approval/*` | none (public token) | no |
| Work orders | `/api/work-orders*` | mixed: owner-only (patch, assign-technician), owner-or-technician (list/get/status/notes) | no |
| Invoices | `/api/invoices*` | `OwnerAuthContextDep` | no |
| Dashboard | `/api/dashboard/summary` | `OwnerAuthContextDep` | no |
| Reports | `/api/reports/*` (6 report types) | `OwnerAuthContextDep` | no |
| Availability | `/api/availability` | `OwnerAuthContextDep` | no |
| Notifications | `/api/notifications*` | `OwnerAuthContextDep` | `app/api/routers/notifications.py` |
| Context (agent memory) | `/api/context/{project_key}*` | `VerifiedAuthContextDep` | `app/api/routers/context.py` |
| Parts | `/api/parts*` | `OwnerAuthContextDep` | `app/api/routers/parts.py` |
| Vendors | `/api/vendors*` | `OwnerAuthContextDep` | `app/api/routers/vendors.py` |
| Appointments | `/api/appointments*` | `OwnerAuthContextDep`, all 6 — **no technician-facing route exists** | `app/api/routers/appointments.py` |
| Bays | `/api/bays*` | `OwnerAuthContextDep` | `app/api/routers/bays.py` |
| Working hours | `/api/working-hours*` | `OwnerAuthContextDep` | `app/api/routers/working_hours.py` |
| Schedule blocks | `/api/schedule-blocks*` | `OwnerAuthContextDep` | `app/api/routers/schedule_blocks.py` |
| Technicians | `/api/technicians*` | mixed (6 owner / 3 self-service) | `app/api/routers/technicians.py` (this session's PR #75) |

### 1.4 Navigation (Fact)

`app/static/index.html` sidebar (`#sidebar`) + a mirrored `.mobile-bottom-nav`, visibility computed by `applyRoleNavVisibility()` (`app/static/app.js:316-337`) from three data attributes:

- `data-owner-only="true"` — hidden for technician or support sessions. Applied to 15 nav items (dashboard, technicians, customers, vehicles, service-desk, estimate, approval-queue, scheduling, parts, vendors, purchase-orders, invoices, square, reports, notifications, workflow-gaps).
- `data-technician-only="true" hidden` — shown only for technician sessions (`my-day`).
- `data-support-only="true" hidden` — shown only for support sessions (`support-directory`); a support session additionally force-hides every other nav item.
- Unmarked items (`diagnostics`, `inspections`, `work-orders`, `chat`, `system`) are visible to owner, manager, and technician alike, consistent with those routes' `OwnerOrTechnicianAuthContextDep` gating.

**This is role-based only.** No shop-settings-driven or mode/tier-driven nav gating exists today (e.g., nothing hides "Bays" based on bay count, mode, or tier).

### 1.5 Services/stores (Fact)

28 `app/*_store.py` modules, one business domain each (customer, vehicle, estimate, work order, invoice, payment, purchase order, part, part allocation, vendor, technician, scheduling [bays/working-hours/schedule-blocks/appointments], diagnostics, inspection, intake, notification, report, dashboard, workflow gap, account security, subscription, support, shop, square, test-support, context, customer-history, email-verification). Plus `app/services/*` (email, estimator, http, location, openai_web, optimus_chat, square, vin) and `app/orchestrator.py` (read-only research — no mutating actions today) / `app/control.py` (chat agent-delegation routing).

### 1.6 Existing feature controls (Fact)

No feature-flag/entitlement/capability mechanism exists anywhere (`grep -rniE "feature_flag|entitlement|capability" app/` — zero hits). The only tier machinery:

- `SUBSCRIPTION_TIERS` dict (`app/subscription_store.py:46-50`): `solo` ($49/mo, 1 seat), `team` ($99/mo, 5 seats), `shop` ($199/mo, unlimited).
- `enforce_technician_seat_limit()` (`app/technician_store.py:271-297`) — the only place tier actually gates behavior today, capping technician-roster size.
- `Shop.status` + `sync_shop_access_status()` (`app/auth.py:535-591`) — derived access suspension on trial/grace-period expiry, recomputed per-request, not cached.

### 1.7 Bays/technicians/scheduling relationships (Fact)

- `Bay` (`app/db_models.py:1824`) is a plain shop-scoped table with no count cap anywhere — a shop can have zero bays with no special-cased flag.
- `ScheduleBlock.bay_id`/`technician_id` are both nullable (a block with neither is a shop-wide closure).
- `Appointment.technician_id` is **required**; `Appointment.bay_id` is **optional**; `Appointment.service_location` is `shop | mobile`.
- Appointments are owner/manager-only today (§1.3) — the router docstring states this explicitly as a gap, not an oversight.
- Technician seat count is capped by subscription tier, independent of bay count — nothing cross-validates the two (e.g., a `team`-tier shop with 5 technician seats and 0 bays is valid today).

---

## 2. Capability matrix

Rows are the domains named in the task; columns are the three **operating modes** (workflow shape) and the **Technician role** (workspace, orthogonal to mode — see §6). This matrix describes mode-driven *workflow relevance*, not tier — tier is a separate overlay noted in §2.1.

`Full` = primary workflow surface. `Limited` = present but reduced/simplified. `Hidden (data preserved)` = not surfaced in that mode's default navigation, but never deleted and always owner-reachable (§5). `N/A` = domain doesn't apply to that mode's default shape but the underlying table/route is unaffected.

| Domain | Solo | Mobile Field | Shop | Technician role |
|---|---|---|---|---|
| Customers | Full | Full | Full | Full (read; write per existing role gate) |
| Vehicles | Full | Full | Full | Full (read; write per existing role gate) |
| Estimates | Full | Full | Full | Hidden (owner-only today, Fact §1.3) |
| Diagnostics | Full | Full | Full | Full (already owner-or-technician, Fact) |
| Work orders | Full | Full | Full | Full (already owner-or-technician, Fact) |
| Invoices | Full | Full | Full | Hidden (owner-only today, Fact) |
| Scheduling (appointments) | Limited (owner is own technician; no bay assignment) | Full (service_location=mobile is the primary case, Fact) | Full | Hidden today (Fact — no technician-facing route exists) |
| Bays | Hidden (data preserved) | Hidden (data preserved) | Full | N/A |
| Technicians (roster) | Hidden (data preserved; owner is sole operator) | Limited (small field roster) | Full | Self-service only (existing 3-route pattern, Fact) |
| Parts | Full | Limited (parts pickup/on-hand, not full warehouse flow) | Full | Read (existing part-allocation owner-or-technician gate) |
| Reports | Limited (owner-only, personal performance) | Limited | Full (management reporting) | Hidden (owner-only today, Fact) |
| Field functions (travel, service radius, drive-out fee, offline, media — see §8) | N/A | Full (this mode's differentiator) | Limited (only if a shop also dispatches mobile jobs) | Proposed: field technician's own view |
| Optimus actions (chat today; plan-executor per ADR-017, future) | Full | Full | Full | Scoped to the technician's own active capabilities (§7) |

### 2.1 Tier overlay (Fact + Recommendation)

Tier (`solo`/`team`/`shop`, existing, unchanged) grants *capacity and depth* independent of mode: seat count (existing, Fact), and — **Recommendation**, not yet built — report depth (e.g., management reporting reserved for `team`/`shop` tier regardless of mode) and multi-location support (future). A Solo-mode shop on the `shop` tier is valid (e.g., a solo operator who pays for extra seats to onboard a part-time helper without changing mode); a Shop-mode shop on the `solo` tier is valid but seat-limited to 1, which the existing `enforce_technician_seat_limit()` already blocks correctly today, independent of any mode work.

---

## 3. Domain model

### 3.1 Operating mode (Recommendation)

- New column: `Shop.operating_mode` — proposed values `solo | mobile_field | shop`, nullable at migration time, backfilled to `shop` for every existing shop (matches the one real pilot shop's actual usage: bays, technicians, and shop-based scheduling are already in active use — see `docs/context/GOAL_EVIDENCE_MATRIX.md` Part A). Not-null after backfill, mirroring the established `shop_id` nullable-then-backfill-then-not-null migration shape already used four times in this codebase (migrations 023-025).
- New signups (self-service, `POST /api/signup`) choose a mode explicitly at signup time — **Unresolved decision #2** (§11): is mode choice a required signup step, or a post-signup settings change with a sensible default?

### 3.2 Tier/entitlements (Fact, unchanged)

`ShopSubscription.tier` stays exactly as it is (`solo | team | shop`). No schema change proposed here.

### 3.3 Capability resolution (Recommendation)

One function, modeled directly on `effective_shop_id(db, auth)` (ADR-019's precedent):

```
resolve_capabilities(db, auth) -> ShopCapabilities
```

`ShopCapabilities` is a frozen, per-request-resolved object (not a live table read on every check) combining: `Shop.operating_mode`, `ShopSubscription.tier`, the caller's `ShopMembership.role`, and any per-shop override (§3.4). Exposed to routes via a `CapabilitiesDep` FastAPI dependency (analogous to the existing `OwnerAuthContextDep` shape), to store functions as a plain parameter (matching every existing store function's `auth: AuthContext` parameter shape — no new calling convention introduced), and to the frontend via `GET /api/capabilities` (§4).

### 3.4 Defaults and tenant overrides (Recommendation)

- Defaults come from `(operating_mode, tier)` — a lookup table, not per-shop data, so most shops need zero override rows.
- `ShopCapabilityOverride` (new table, proposed) — sparse, one row per shop per overridden capability key, for the genuine edge case (e.g., a Mobile Field shop that also wants bay-tracking for a small home garage). Mirrors `ShopSettings`'s "operational config that changes more often than identity" precedent.
- Overrides are owner/manager-settable only, never AI-settable (§7).

### 3.5 Audit history (Recommendation)

Reuse the existing `ShopEvent` append-only pattern (`app/db_models.py:2232`, Fact) for every mode change, tier change, and override change — no new audit-log mechanism invented. This is the same precedent already used for membership/status/invitation/settings changes.

---

## 4. One backend capability service

**Rule (per task instruction): UI hiding alone is forbidden.** Every mode/tier-conditional nav item or form control must correspond to a route/store call that independently enforces the same restriction — exactly the discipline the existing `data-owner-only` nav pattern already satisfies today only because every such item happens to map to an owner-gated route (§1.4, Fact).

Single call site, four consumers (Recommendation, modeled on ADR-016's "one write path" discipline):

1. **Routes** — a `CapabilitiesDep` dependency, checked alongside the existing `OwnerAuthContextDep`/`OwnerOrTechnicianAuthContextDep` (mode/tier gating is additive to role gating, never a replacement for it).
2. **Store functions** — defense in depth; a store function receiving a capabilities object it doesn't have never proceeds, even if a future caller forgets the route-level check (same belt-and-suspenders reasoning already applied to `effective_shop_id()`).
3. **Manual UI** — `GET /api/capabilities` returns the resolved snapshot; `app/static/app.js`'s nav visibility logic (§1.4) extends to read this snapshot instead of (or alongside) role alone, but the route-level enforcement in (1) is what actually prevents the action, not the nav's hidden attribute.
4. **AI tools** (ADR-017's future plan-executor, and today's `app/orchestrator.py`/`app/control.py` chat path once it gains any mutating action) — must call the same `resolve_capabilities()` and the same store functions manual UI calls, per ADR-016's existing mandate, extended to this axis (§7).

---

## 5. Safe transitions

- **Mode changes never delete data.** Switching Shop → Solo hides bays/roster from default navigation (§2, "Hidden (data preserved)") but every row remains queryable — Recommendation: an explicit owner-facing "show all shop data regardless of mode" toggle or export path, not a silent disappearance.
- **Switching Solo → Shop** requires no backfill — bays/technicians tables already exist and are simply empty; the shop starts creating rows through the now-visible Shop-mode workflows.
- **Migration shape** for `Shop.operating_mode` follows the exact nullable → backfill → not-null pattern already proven four times in this codebase (migrations 023-025, Fact) — no new migration pattern invented.
- **Rollback**: because hidden ≠ deleted, rolling back a mode change (or the mode feature itself) is a column drop / dependency revert with zero data loss, consistent with the "reversible slices" requirement in §9.

---

## 6. Role vs. mode boundaries

**Mode is a `Shop`-level property. Role is a per-`ShopMembership` property. They are orthogonal axes** (Fact — already true structurally today: `ShopMembership.role` lives on a different table than any shop-level config, and the task instruction states this explicitly for Technician Mode: "a role workspace, not a tenant mode or separate product").

- A Solo-mode shop still has exactly one `ShopMembership` with role `owner` — mode does not create or remove roles.
- Today's owner-only appointments (Fact, §1.3/§1.7, `app/api/routers/appointments.py:9-14`) is a **role** gap (`OwnerAuthContextDep` only, no `OwnerOrTechnicianAuthContextDep` variant), not a mode gap — it exists identically regardless of which mode a shop is in.
- **Unresolved decision #3** (§11): should future technician appointment access be gated by mode (e.g., only in Shop mode, where a technician has an employer relationship worth surfacing a schedule to), by role alone (any mode, once the route exists), or by both (mode determines *what* a technician sees — e.g., only their own assigned jobs in Mobile Field vs. the shop's full board in Shop mode)? This document takes no position; it flags the question because the capability service (§4) needs an answer before the technician-facing appointment route is built.
- The existing six-owner/three-self-service technician pattern (Fact, §1.2) is the template for how any future technician-facing route should split: full management stays role-gated to owner/manager, self-scoped actions get an explicit `OwnerOrTechnicianAuthContextDep`-shaped route, never a blanket "technicians see everything owners see."

---

## 7. Prompt-first rules

**Fact:** `app/orchestrator.py` is read-only research today (no database writes); `app/services/optimus_chat.py`'s chat endpoint never touches the database either. ADR-017 (accepted design, not yet implemented) is the only planned path for Optimus to take a mutating action, and it already commits to "execution calls the same store functions a manual UI click would call" (ADR-017, Decision).

This document adds one requirement to that existing plan, consistent with ADR-016's "no separate AI-only write path" principle:

- The plan-generator step must filter proposed actions against the caller's **active** capabilities (§3.3) before presenting a plan — an action outside the shop's mode/tier/role must never even be proposed.
- `execute_plan()` must **re-check** capabilities at execution time, not rely on the plan-generation-time check alone — closing the same class of time-of-check/time-of-use gap the impersonation security review already found and fixed elsewhere in this codebase (`docs/context/GOAL_EVIDENCE_MATRIX.md` Part C, support-admin entry: "a concurrent double-submit race on ending impersonation"). This is a documented precedent for exactly this risk shape, not a hypothetical.
- Optimus can never: approve its own plan (ADR-017's existing "one explicit approval action" requirement already covers this), operate outside `effective_shop_id()` tenant scope (ADR-019, unchanged), or invoke a capability the shop's tier doesn't grant, even if a user's prompt asks for it directly.
- These rules extend, and do not replace, ADR-017 §"Consequences": "its acceptance tests must include an approval-bypass test proving execution cannot occur without a prior, matching approval" — the same test category must be extended to cover a capability-bypass attempt.

---

## 8. Mobile Field gaps — current vs. proposed

| Concern | Current (Fact) | Proposed (Recommendation) |
|---|---|---|
| Travel time | No field anywhere (`Appointment`, `WorkOrder` schemas have no travel/duration-to-site field). | New nullable field on `Appointment` or a `field_visit` concept; out of scope to design fully here — flagged for its own implementation slice (§9). |
| Service radius | `ShopSettings.service_area` (JSON) column exists but is **unused** — no route reads or writes it beyond copying it through `shop_store.py:222-223` at signup. | Define its shape and enforce it at scheduling/estimate time. |
| Drive-out fees | `ShopSettings.mobile_service_fee` exists as a **numeric field copied from the app-level static `Settings.mobile_service_fee` config** (`app/config.py`) at signup — effectively one flat fee, not a dynamic per-distance or per-zone fee. | Per-shop configurable drive-out fee logic, tied to `service_area` above. |
| Offline / limited-connectivity | None — no service worker, no offline cache, no sync-on-reconnect logic anywhere in `app/static/`. | Explicitly named in the task as **future** scope ("future limited-connectivity support") — this document flags it only; no design proposed here. |
| Photos / voice notes | **None** — a repo-wide search for photo/attachment/voice-note/media-url handling in `app/` returned zero hits. No upload route, no media table. | New capability, scoped to its own slice; likely needs object storage decision (out of scope for this bridge). |
| Route/location context | `app/services/location.py`'s `LocationService` does one-off ZIP/city geocoding for estimate research only — not technician routing, not live location. | Deferred; flagged only. |
| Minimum-click field workflows | Current nav (§1.4) is desktop/owner-oriented; no mobile-first simplified flow exists beyond the existing responsive `.mobile-bottom-nav` (a layout adaptation, not a workflow simplification). | Mode-driven simplified nav/workflow for `mobile_field`, built on the capability service (§4) once it exists. |

None of the above ship in this document — they are named to satisfy the task's explicit "mark current versus proposed" requirement, not designed in detail.

---

## 9. Reversible implementation slices

Each slice is independently shippable, additive, and rollback-safe (drop column / revert PR, no data loss per §5). Ordering follows the same "extract and prove one thing at a time" discipline already used for the Phase 2C router-extraction series (9 steps, one PR each, this session's PR #75 being the ninth).

| Slice | Scope | Migration/backfill/defaults | Tests | Rollout | Rollback |
|---|---|---|---|---|---|
| 0 | This document + ADR-022 | none | doc/link validation (§13) | merge as draft PR | revert commit |
| 1 | `Shop.operating_mode` column | nullable → backfill all existing shops to `shop` → not-null (mirrors migrations 023-025 shape) | migration rehearsal against real Postgres (existing e2e pattern, `tests/e2e/test_shop_tenant_migration_backfill.py` precedent) | column unused by any route yet — zero behavior change | drop column |
| 2 | `resolve_capabilities()` service + `GET /api/capabilities` (owner/manager-only read) | none (reads existing columns) | unit tests on resolution logic per (mode, tier, role) combination | additive-only; no existing route calls it yet | delete the module/route |
| 3 | Wire capability checks into **one** low-risk route group (e.g., `bays`, already Shop-mode-exclusive per its own docstring, §1) | none | route-level capability-bypass tests (mirrors ADR-017's required bypass-test category, §7) | ship in **observe/log-only mode** first (log would-be-denials without enforcing) before flipping to enforce, matching this codebase's existing incremental-rollout discipline (e.g., Phase 1's `asyncio.to_thread` fix was verified, then Phase 2 added the CI rehearsal) | revert PR; enforcement flag off |
| 4 | Extend to remaining mode-shaped route groups (`technicians`, `working_hours`, `schedule_blocks`, `appointments`) one PR per group | none | per-group tests, same shape as slice 3 | same observe-then-enforce pattern | per-PR revert |
| 5 | Frontend nav consumes `GET /api/capabilities` instead of role-only logic | none | Playwright test per mode showing correct nav (extends existing real-browser e2e pattern) | behind existing nav logic until parity confirmed | revert to role-only nav function |
| 6 | `ShopCapabilityOverride` table + owner/manager settings UI | new table, empty by default | override-precedence tests | additive | drop table |
| 7 | Wire ADR-017's plan-executor (when built) through the same service from day one | n/a — new feature, not a retrofit | capability-bypass test extended to the AI path (§7) | ships as part of ADR-017's own rollout, not separately | n/a (ADR-017 not yet built) |

Telemetry: each enforcing slice (3, 4) should log capability-denial events the same way `security_events.py` already logs auth denials (Fact — existing precedent, not a new logging mechanism).

---

## 10. Route/module classification

| Classification | Modules |
|---|---|
| **Shared** (identical across all modes/roles) | Customers, Vehicles, Diagnostics, Work orders, Notifications, Context, Auth, Estimate approval (public), Chat |
| **Mode-shaped** (same route, different relevance/defaults per mode) | Scheduling (appointments, working hours, schedule blocks), Reports, Parts, Optimus actions (future plan-executor) |
| **Shop-only** (Shop mode primary use; hidden-not-deleted elsewhere) | Bays, Technicians (roster management routes), Purchase orders (multi-vendor inventory flow) |
| **Mobile-specific** (Mobile Field mode differentiator; mostly proposed, not built — §8) | Field functions (travel, service radius, drive-out fee, media, offline) |
| **Technician-role-specific** (self-service, any mode) | `/api/technicians/me*` (existing 3-route pattern), future technician appointment view (§6, unresolved) |

---

## 11. Unresolved owner decisions

1. **Solo/Shop naming collision.** "Solo" and "Shop" each name both a proposed operating mode and an existing subscription tier (§2.1, ADR-022 Decision §1). The schema-level disambiguation (`operating_mode` vs `tier` columns) is sufficient at the code level; the open question is whether product copy/UI needs its own disambiguating language (e.g., "Solo mode" vs "Solo plan" spelled out everywhere) or whether context makes the collision harmless. Needs an explicit owner call before any user-facing copy is written.
2. **Mode selection at signup.** Is operating mode a required signup step, or a post-signup settings change with a default (§3.1)? Affects the self-service signup flow (`POST /api/signup`, already shipped) and whether it needs a new field.
3. **Technician appointment-access gating shape.** Mode-gated, role-gated, or both (§6)? Blocks designing the technician-facing appointment route.
4. **`ShopCapabilityOverride` approval scope.** Should per-shop capability overrides require support/platform approval (like impersonation) or be fully owner/manager self-service (like existing `ShopSettings` edits)? Affects §3.4's design and the support-admin domain's existing scope boundary ("platform-side only, read-only" per `GOAL_EVIDENCE_MATRIX.md` — an override-approval flow would be the first *write* capability granted to support, a scope expansion worth its own decision).
5. **Field-functions data model** (§8) — travel time, service radius enforcement, drive-out fee calculation, and media storage each need their own design pass; this document intentionally does not propose schemas for them.

---

## 12. Risks

- **Doc staleness precedent.** `docs/context/ARCHITECTURE.md` and `PRODUCT.md` (last verified 2026-07-08) are measurably behind current code (they don't mention Shop/tenant model, technicians, subscriptions, or support role at all) — this document was built from source, not those docs, to avoid propagating the same staleness. Risk: without a refresh discipline, this document could suffer the same fate. Mitigation: this document cites file:line for every Fact, so future re-verification is mechanical.
- **Naming collision risk** (§11.1) — shipping user-facing copy that conflates mode and tier could confuse owners evaluating pricing vs. workflow fit. Not yet a real defect since neither concept has UI copy yet.
- **Capability-service becomes a second tenant-boundary-style single point of enforcement** — exactly like `effective_shop_id()`, a missed call site is a silent security gap, not a loud error. Mitigation proposed in ADR-022 Consequences: extend the existing AST regression-test pattern (already proven for ADR-019) to this axis at implementation time, before writing the routes that need it — not after.
- **Scope creep into implementation.** Because the capability model touches nearly every route in the app (§10), there is a real risk that "Phase 1" of implementation balloons into a full rewrite. The slice plan (§9) is deliberately ordered to start with one already-mode-exclusive, low-traffic route group (`bays`) specifically to bound first-slice risk.
- **Mobile Field is the least-built mode today** (§8 — almost everything is "proposed," not "current") — of the three modes, it carries the most net-new work, which affects sequencing/estimation for whichever slice tackles it first.
- **Concurrent work in this repository.** Other active branches/worktrees (`agent/codex/phase3-tenant-boundary`, `agent/claude/goal-phase7-subscription-billing`, `agent/claude/goal-phase8-support-admin`, `agent/claude/goal-phase9-observability`, observed as active worktrees at the time this document was written) touch adjacent territory (tenant boundary, subscription billing, support admin) — implementation slices in §9 should be sequenced against those phases' actual merge state at the time, not against this document's snapshot.

---

## 13. Documentation/link/checksum validation performed

- Verified every file:line citation in this document against the current `main` branch (post-PR-#75 merge, commit `1ff6bad`) at the time of writing.
- Verified `sha256sum -c docs/architecture/CHECKSUMS.txt` still reports every preserved file (`STACK-DECISION.md`, ADR-014 through ADR-021) as `OK` — this document and ADR-022 do not modify any preserved file.
- Verified every internal markdown link in this document and in ADR-022 resolves to an existing file in this repository.
- Verified `docs/architecture/README.md`'s ADR index table now includes ADR-022, and `docs/context/DECISIONS.md` has a short pointer entry per that directory's own rule 3.

## See also

- [ADR-022](adr/ADR-022-operating-mode-tier-separation.md) — the accepted decision this document elaborates.
- [ADR-016](adr/ADR-016-shared-business-service-layer.md), [ADR-017](adr/ADR-017-prompt-manual-shared-execution.md), [ADR-019](adr/ADR-019-tenant-boundary.md) — the precedents this design extends.
- [`docs/architecture/README.md`](README.md) — architecture decision index.
- [`docs/context/GOAL_EVIDENCE_MATRIX.md`](../context/GOAL_EVIDENCE_MATRIX.md) — the current, verified state of the broader multi-shop pilot work this document's inventory (§1) drew on.
- [`docs/context/DECISIONS.md`](../context/DECISIONS.md) — lightweight decisions log, pointer entry added.
