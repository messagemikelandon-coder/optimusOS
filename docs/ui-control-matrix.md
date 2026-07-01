# UI Control Matrix

Date: 2026-07-01

Status meanings:

- `Pass`: exercised live and completed the intended workflow.
- `Expected auth guard`: exercised live and intentionally returned the required `401` or login redirect.
- `Source-only`: present in source, not separately exercised beyond equivalent handlers.
- `Missing`: not part of the current frontend scope.

| Control | Selector or label | Intended action | Backend dependency | Auth required | Observed result | Status |
| --- | --- | --- | --- | --- | --- | --- |
| Login screen | `/login` | Render unauthenticated sign-in screen | `GET /api/auth/me` | No | Login view rendered correctly | Pass |
| Login submit | `#login-form` | Authenticate owner session | `POST /api/auth/login` | No | Invalid fixture login showed visible failure; valid login established session | Pass |
| Session restore | page reload | Restore server-side session from cookie | `GET /api/auth/me` | Yes | Reload kept the owner signed in | Pass |
| Logout | `#topbar-logout`, `#system-logout` | Revoke session and return to login | `POST /api/auth/logout` | Yes | Logout returned to login and revoked server-side session | Pass |
| Expired-session return | page reload after forced expiry | Reject expired session and return to login | `GET /api/auth/me` | Yes | Expired session returned browser to `/login` | Pass |
| Primary nav `Command deck` | `.nav-item[data-view="dashboard"]` | Show dashboard | None | No | Dashboard view active after login | Pass |
| Primary nav `Talk to Optimus` | `.nav-item[data-view="chat"]` | Show chat | None | No | Chat view opened and worked live | Pass |
| Primary nav `Job estimator` | `.nav-item[data-view="estimate"]` | Show estimate | None | No | Estimate view opened and rendered live results | Pass |
| Primary nav `System bay` | `.nav-item[data-view="system"]` | Show system | None | No | System view opened and location/auth state updated | Pass |
| Dashboard prompt `Decode VIN` | prompt chip | Navigate to chat and prefill prompt | None until submit | No | Handler pattern unchanged; not re-run separately | Source-only |
| Dashboard `Run command` | `#dashboard-send` | Submit owner chat request | `POST /api/chat` | Yes | Authenticated chat request succeeded with `200` | Pass |
| Chat submit | `#chat-submit` | Submit owner chat request | `POST /api/chat` | Yes | Authenticated chat request succeeded with `200` | Pass |
| System ZIP field | `#view-system #postal-code` | Persist location context for research | none until API call | Yes for protected flows | ZIP saved and used by estimate flow | Pass |
| Location resolution API path | frontend fetch helper | Resolve location for protected workflow | `POST /api/location/resolve` | Yes | Authenticated request returned `200` | Pass |
| Estimate submit | `#submit` | Run full estimate workflow | `POST /api/estimate` | Yes | Authenticated estimate request returned `200` and rendered result | Pass |
| Estimate `Copy estimate` | `#copy-estimate` | Copy rendered estimate text | successful estimate render | No | Available after live estimate render; not separately asserted | Source-only |
| Estimate `Print estimate` | `#print-estimate` | Print rendered estimate | successful estimate render | No | Available after live estimate render; not separately asserted | Source-only |
| Estimate `Start another` | `#new-estimate` | Reset estimate result | successful estimate render | No | Available after live estimate render; not separately asserted | Source-only |
| Runtime check | `#system-refresh-health` | Verify backend state | `GET /health` | No | Health check remained online during audit | Pass |
| HttpOnly session cookie | browser cookie store | Deliver browser session token securely | `Set-Cookie` from login | Yes | `optimus_session` received with `HttpOnly` and `SameSite=Lax` | Pass |
| Raw token storage prevention | database session storage | Store only token hash | `auth_sessions` | Yes | Raw session token not stored in DB | Pass |
| Browser token storage prevention | `localStorage`, `sessionStorage` | Avoid bearer-token storage | None | Yes | No bearer token or raw session token stored | Pass |
| Unauthenticated `GET /api/auth/me` | initial load | Reject anonymous session lookup | `GET /api/auth/me` | No | Returned `401` as expected | Expected auth guard |
| Invalid login | fixture credentials | Reject bad credentials | `POST /api/auth/login` | No | Returned `401` with visible failure feedback | Expected auth guard |
| Post-logout session check | after sign-out | Reject revoked session | `GET /api/auth/me` | No | Returned `401` as expected | Expected auth guard |
| Post-expiry session check | after forced expiry | Reject expired session | `GET /api/auth/me` | No | Returned `401` as expected | Expected auth guard |
| Customer module | none found | Customer CRUD workflow | expected future API | Likely | Not present in current frontend scope | Missing |
| Vehicle module | none found | Vehicle CRUD workflow | expected future API | Likely | Not present in current frontend scope | Missing |
| Work-order module | none found | Work-order workflow | expected future API | Likely | Not present in current frontend scope | Missing |
| Approval queue module | none found | Approval workflow | expected future API | Likely | Not present in current frontend scope | Missing |

## Notes

- The current live frontend uses server-side cookie auth and no browser-stored bearer token.
- Existing end-to-end scope now passes for login, chat, estimate, location, logout, and expired-session handling.
- Missing business modules remain out of scope for this branch and were not started here.
