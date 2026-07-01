# UI Control Matrix

Date: 2026-07-01

Status meanings:

- `Pass`: exercised in the live browser and observed working as intended for its available scope.
- `Fail`: exercised in the live browser or API and observed not completing the intended workflow.
- `Source-only`: wiring is present in the current frontend source, but this specific control was not separately exercised in the browser.
- `Not reachable`: control exists but its success state could not be reached from the current baseline.
- `Missing`: requested workflow/control is not present in the current frontend.

| Control | Selector or label | Intended action | Backend dependency | Auth required | Observed result | Status |
| --- | --- | --- | --- | --- | --- | --- |
| Primary nav `Command deck` | `button[data-view="dashboard"]` | Show dashboard | None | No | Dashboard is the default active view | Pass |
| Primary nav `Talk to Optimus` | `button[data-view="chat"]` | Show chat view | None | No | Chat view opens in browser audit | Pass |
| Primary nav `Job estimator` | `button[data-view="estimate"]` | Show estimate view | None | No | Estimate view opens in browser audit | Pass |
| Primary nav `System bay` | `button[data-view="system"]` | Show system view | None | No | System view opens in browser audit | Pass |
| Hero `Talk to Optimus` | button label `Talk to Optimus` | Navigate to chat | None | No | Chat view became active | Pass |
| Hero `Build an estimate` | button label `Build an estimate` | Navigate to estimate | None | No | Estimate view became active | Pass |
| Topbar location chip | `button.location-chip` | Navigate to system settings | None | No | System view became active | Pass |
| Mobile menu | `#mobile-menu` | Toggle sidebar on mobile | None | No | `aria-expanded` changed to `true`, sidebar opened | Pass |
| Dashboard prompt `Decode VIN` | button label `Decode VIN` | Navigate to chat and prefill prompt | None until submit | No | Chat opened and prompt text was filled | Pass |
| Dashboard prompt `Diagnose a fault` | button label `Diagnose a fault` | Navigate to chat and prefill prompt | None until submit | No | Source wiring present; not separately exercised | Source-only |
| Dashboard prompt `Find parts` | button label `Find parts` | Navigate to chat and prefill prompt | None until submit | No | Source wiring present; not separately exercised | Source-only |
| Dashboard prompt `Price a job` | button label `Price a job` | Navigate to estimate | None | No | Source wiring present; same handler pattern as other view buttons | Source-only |
| Dashboard `Run command` | `#dashboard-send` | Submit chat request | `POST /api/chat` | Yes | Browser showed visible `Command failed` state after `401` | Fail |
| Chat `Send` | `#chat-submit` | Submit chat request | `POST /api/chat` | Yes | Browser showed visible `Command failed` state after `401` | Fail |
| Chat quick command `Parts search` | `.context-action.quick-prompt` | Prefill chat prompt | None until submit | No | Source wiring present; not separately exercised | Source-only |
| Chat quick command `Labor research` | `.context-action.quick-prompt` | Prefill chat prompt | None until submit | No | Source wiring present; not separately exercised | Source-only |
| Chat quick command `Diagnostic plan` | `.context-action.quick-prompt` | Prefill chat prompt | None until submit | No | Source wiring present; not separately exercised | Source-only |
| Chat quick command `Structured estimate` | `.context-action[data-view="estimate"]` | Navigate to estimate | None | No | Source wiring present; same handler pattern as other view buttons | Source-only |
| Estimate submit `Research and estimate` | `#submit` | Submit estimate request | `POST /api/estimate` | Yes | With ZIP set, browser showed visible estimate error after `401` | Fail |
| Estimate result `Copy estimate` | `#copy-estimate` | Copy rendered estimate text | Successful estimate render first | No | Result actions never rendered because estimate flow failed before success | Not reachable |
| Estimate result `Print estimate` | `#print-estimate` | Print rendered estimate | Successful estimate render first | No | Result actions never rendered because estimate flow failed before success | Not reachable |
| Estimate result `Start another` | `#new-estimate` | Reset form and hide result | Successful estimate render first | No | Result actions never rendered because estimate flow failed before success | Not reachable |
| System `Show/Hide` token | `#toggle-token` | Toggle token field visibility | None | No | Source wiring present; not separately exercised | Source-only |
| System `Use current location` | `#use-location` | Request geolocation and persist coordinates | Browser geolocation only | Browser permission | Not exercised in this audit run | Not reachable |
| System `Refresh` | `#refresh-health` | Refresh health status from dashboard panel | `GET /health` | No | Health endpoint healthy; same `loadHealth()` handler as system check | Source-only |
| System `Run check` | `#system-refresh-health` | Refresh health status from system view | `GET /health` | No | Browser showed `Online` backend state | Pass |
| Location resolution API path | frontend helper only | Resolve ZIP/city to structured location | `POST /api/location/resolve` | Yes | Direct API probe returned `401` without token | Fail |
| Login control | none found | Acquire or establish access token | Expected auth route/UI | Yes | No login control found in current UI | Missing |
| Customer module | none found | Customer CRUD workflow | Expected `/api/customers` | Likely | No frontend screen or backend route found | Missing |
| Vehicle module | none found | Vehicle CRUD workflow | Expected `/api/vehicles` | Likely | No frontend screen or backend route found | Missing |
| Work-order module | none found | Work-order workflow | Expected `/api/work-orders` | Likely | No frontend screen or backend route found | Missing |
| Approval queue module | none found | Approval workflow | Expected `/api/approvals` | Likely | No frontend screen or backend route found | Missing |

## Notes

- The current frontend stores a bearer token in `sessionStorage` and attaches it to protected requests when the system token field is populated.
- The backend currently exposes protected chat, estimate, and location endpoints, but no login endpoint was found for obtaining a token from the UI.
- Protected flows fail visibly. They are not silent, but they are still failed user workflows in the current baseline.
