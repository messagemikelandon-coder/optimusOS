# ADR-016: Shared business-service layer

- ID: ADR-016
- Date: 2026-07-20
- Status: Accepted
- Context: The product principle requires prompt (AI) and manual interfaces to call the exact same application services, with no separate AI-only write path. optimus-server's `*_store.py` modules already implement this shape (one function per business operation, called identically from FastAPI routes regardless of caller). The Laravel PoC independently re-derived the identical pattern (`Domain/*Service.php`), which is evidence the pattern is a stack-independent architecture discipline, not a Laravel-specific technique.
- Decision: No structural change to the existing store-layer pattern. Going forward, enforce one discipline as new callers are added: the AI plan-executor (ADR-017) must call existing store functions (`create_estimate`, `convert_estimate_to_work_order`, etc.) and must never reimplement `effective_shop_id()`/`_owner_query()` tenant scoping itself. This is the single highest-risk duplication point identified for the upcoming prompt/manual work, not a currently-existing problem.
- Alternatives considered: introducing a new, separate "AI action" layer distinct from the existing stores (rejected — this is precisely the "AI must never have a separate uncontrolled path for changing application data" anti-pattern the product principle forbids); rewriting the store layer as part of adopting a new framework (rejected per ADR-014 — no framework change is happening).
- Consequences: the AST regression test that already fails the build on any raw `owner_user_id` comparison (ADR-019) should be extended to also fail on any new plan-executor code path that queries the database directly instead of calling an existing store function, before that code is written, not after.
- Files affected: none yet — this ADR is a standing constraint on work done under ADR-017, to be enforced by code review and the extended test in ADR-019/Phase 1.
- Revisit if: a genuinely new class of caller (e.g., a scheduled background job) needs a different invocation shape than "call the store function" — that should be evaluated against this ADR explicitly rather than silently diverging.
