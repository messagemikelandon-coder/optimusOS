---
name: production-readiness
description: Audits OptimusOS local, staging, and production gates without modifying or deploying anything.
disable-model-invocation: true
context: fork
agent: optimus-release-auditor
---
Audit the current repository and evidence. Produce three separate verdicts:
1. local development ready
2. private staging ready
3. production ready

Evaluate application tests, Docker/runtime, migrations, data isolation, secrets, HTTPS, backups and restore, monitoring, alerting, rate limits, dependency failures, security review, rollback, deployment reproducibility, and customer-facing workflow proof.

Return a gate matrix and the next smallest task. Do not change files or deploy.
