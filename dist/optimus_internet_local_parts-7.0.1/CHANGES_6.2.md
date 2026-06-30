# Changes in Optimus 6.2

- Added direct owner-to-Optimus chat at `POST /api/chat`.
- Added `direct`, `auto`, and `team` routing modes.
- Kept Optimus as the only owner-visible speaker.
- Added selective silent specialist consultation.
- Made current price, local availability, labor time, VIN, and estimate research native Optimus work.
- Expanded parts links beyond the original fixed retailer allowlist while retaining public-HTTPS and private-network protections.
- Preserved official links when retailer price is hidden; hidden prices no longer corrupt totals.
- Replaced blanket approval rules with single-confirmation owner authority.
- Added owner-full-control policy for reversible local work.
- Added current-turn confirmation for financial and destructive actions.
- Added manager-policy merge text in `OPTIMUS_MANAGER_PATCH.md`.
- Added an owner-facing browser chat interface.
- Added routing, chat, authority, pricing-link, API, and regression tests.
