# Integrating Optimus 7.0.1 with the existing host

The original Optimus host repository was not available in the active workspace. This package is a tested drop-in control and research layer; the host still needs to register it.

## 1. Merge the manager policy

Merge `OPTIMUS_MANAGER_PATCH.md` into the existing `MANAGER.md`. Remove older rules that force every owner message through all agents or prohibit internet price research.

## 2. Register direct chat and estimate tools

```python
from integration.optimus_adapter import OptimusInternetSkill

optimus_skill = OptimusInternetSkill()

tool_registry.register(
    name="optimus_chat",
    handler=optimus_skill.chat,
    read_only=True,
    approval_required=False,
)

tool_registry.register(
    name="internet_local_parts_estimator",
    handler=optimus_skill.estimate_job,
    read_only=True,
    approval_required=False,
)
```

The authenticated owner-chat route should call `optimus_skill.chat` directly. Do not fan every message out to the agent registry first.

## 3. Pass owner context into action policy

For action tools registered elsewhere in the host:

```python
decision = optimus_skill.approval_policy(
    action_name,
    origin=call.origin,  # owner, agent, or system
    explicit_owner_instruction=call.requested_by_owner_in_current_turn,
    current_turn_confirmation=call.destructive_or_payment_confirmed_now,
    optimus_authorized=call.authorized_by_optimus,
)

if decision.required:
    return optimus.request_owner_approval(reason=decision.reason)
```

This removes repeated approval prompts while preserving a current-turn check for payments and destructive changes.

## 4. Local service option

Run the FastAPI application and call:

- `POST /api/chat`
- `POST /api/estimate`

Chat example:

```json
{
  "message": "Look up a starter near me for a 2020 Dodge Challenger 6.4L and give me price, availability, link, and labor time.",
  "mode": "auto",
  "location": {"postal_code": "95677"},
  "history": [],
  "requested_agents": []
}
```

Estimate example:

```json
{
  "vehicle": {"vin": "2C3CDXGJ6LH120446"},
  "job": "Replace starter",
  "location": {"postal_code": "95677"},
  "labor_rate": 100
}
```

## 5. Host capabilities still required

This package can research and decide policy, but the host must separately expose any real action tool Optimus should control, such as:

- File and code editing
- Email or customer messaging
- Calendar scheduling
- Store reservation or checkout
- Invoice persistence
- Shell commands

Register each tool with a clear action name so `approval_policy` can classify it.
