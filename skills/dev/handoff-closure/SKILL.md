---
name: handoff-closure
description: Close cross-task delivery for PR_READY, PR_UPDATED, review decisions, MERGED, and DEPENDENCY_READY. Use whenever work has a successor task or an event must start review, revision, merge follow-up, or portfolio action.
---

# Handoff closure

1. Identify the successor task, event, and required receiver state before making the result final.
2. Put the 12-character SHA in normal payloads and final status. Keep the full idempotency key (`repository + issue_or_pr + full_head_or_merge_sha + event + target`) only for internal audit, rollback, collision, or delivery-failure records.
3. In the same turn, send the event with `send_message_to_thread`. Never send to yourself. Never substitute a final response or GitHub comment for task delivery.
4. Read or wait for the recipient. Require `HANDOFF_ACCEPTED` or an observable active review/work state.
5. Keep the sender incomplete until receipt is confirmed. On delivery failure or timeout, return `HANDOFF_FAILED` with target, event, 12-character SHA, and retry state; retain the full idempotency key internally.
6. On receipt, return `HANDOFF_ACCEPTED` in the same turn and enter work, review, or a concrete `BLOCKED` state.
7. For `REVIEW_CHANGES_REQUESTED`, the integration reviewer must relay the findings to the author in the same turn and confirm the author's receipt before ending review work.
8. Send normal PR and review events only to the next responsible department. Send CEO only `MERGED { org_health }` or a true CEO-boundary `BLOCKED`; preserve the GO_ON/CHANGE/BLOCK handshake.
9. In the final response, name the accepted target, event, and 12-character SHA reference. Do not report “complete” or “waiting” before receipt. Never put full receipt-key lists in CEO `MERGED { org_health }` payloads.
