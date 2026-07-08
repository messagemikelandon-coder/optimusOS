---
name: review-diff
description: Runs an independent, context-isolated review of the current OptimusOS diff and handoff claims.
disable-model-invocation: true
context: fork
agent: optimus-reviewer
---
Review the current branch against its merge base with the intended base branch. Read `docs/context/SESSION_HANDOFF.md` and verify its claims against code and executable evidence.

Focus on correctness, architecture drift, regressions, missing tests, migration safety, ownership isolation, and unsupported completion statements. Do not modify files.
