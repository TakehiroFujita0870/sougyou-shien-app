---
name: ceo-decision-backlog
description: Record material product ambiguity as CEO decision Issues and enforce the ten-open-issue stop limit.
---

# CEO decision backlog

## Procedure

1. Read `docs/operations/ceo-decision-backlog.md`.
2. Query open Issues labeled `ceo-decision` before starting autonomous product work.
3. If the proposed question already exists, update that Issue instead of creating a duplicate.
4. For a material unresolved choice, create one Issue with `ceo-decision` and `blocked`. Include the decision, 2-3 mutually exclusive options, the exact stopped scope, and acceptance criteria after the decision.
5. If the open count is 10 or more, stop new autonomous implementation. Continue only safe validation, urgent security/data-loss fixes, and closure of already-reviewed work.
6. Never block unrelated reversible product work while the count is below 10.

## Exit Criteria

- The open decision count is known.
- Material ambiguity is linked to one non-duplicate Issue.
- The stopped scope is explicit and narrow.
- The ten-Issue stop rule has been applied.
