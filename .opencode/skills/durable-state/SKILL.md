---
name: durable-state
description: Model a 采析绘 lifecycle (run, node, AI turn, skill recipe, workspace view) as a persisted state machine with checkpoint, interrupt and resume. Use when work can be paused by a human, a crash, a page reload or a conversation switch, or when status flags are scattered across ifs.
---

# Durable state

Read `AGENTS.md` and `docs/architecture/ADR-003-durable-state.md` first. The ADR owns the decision;
this skill is the implementation recipe.

## When to use

- A turn can wait for a user answer or an approval.
- A run can be stopped, resumed, promoted after a crash or queued.
- A recipe/skill has ordered steps that must not be skipped.
- The UI can close, switch conversation or reload while work is in flight.
- The code has several booleans (`running`, `stopping`, `waiting`, `interrupted`) that can disagree.

## The four machines

| machine | states | resume key |
|---|---|---|
| RunFSM | queued/starting/running/stopping/settling/completed/failed/interrupted/stopped | run_id |
| NodeFSM | pending/blocked/ready/running/done/partial/failed/skipped/stopped/restored | run_id + node_id |
| TurnFSM | new/context/streaming/tool/awaiting_user/settled/interrupted | turn_id |
| RecipeFSM | created/step_i/done/aborted | recipe_run_id |

A view state machine (closed/docked/full/settings/studio/skills) is allowed for UI, but it must not
own the transcript; switching views must not destroy the chat DOM.

## Turn runner

The HTTP request is a subscriber, not the driver:

1. `POST /chat` creates a turn and enqueues it; returns `turn_id`.
2. A runner thread executes the FSM and appends each event to `ai_events` with a monotonic `seq`.
3. `GET /turns/<id>/events?after=<seq>` streams from the log; disconnect does not stop the runner.
4. `answer`/`stop`/`steer` are commands in a table, consumed by the runner.
5. A reload re-subscribes from the last seen seq.

## Interrupt is a checkpoint

- Store `pending_call` with conversation, turn, call id, kind, payload, status, created_at.
- Answer by `call_id`/`question_id`; derive the message row on the server; never trust a DOM id.
- A new user message does not silently cancel a pending question. Default: queue it; a second
  "steer" action injects at a safe boundary. Explicit cancel is the only cancel.
- Rehydrate pending calls at boot; an expired/answered one returns a named refusal, not 404.

## Recipe guards

```json
{"id":"create_node","tool":"workflow_node_create","requires":["pick_column"],
 "args_schema":{"type":"object","required":["type","params"]},
 "produces":"node_id","check":"node_exists"}
```

- Offer only the current step's tool + read-only evidence tools + control tools.
- Refuse a step whose `requires` is not done; name the next step.
- A step is done only when its `check` sees evidence (tool result id, artifact id, validation id).
- The user may skip; record it as a user skip and show it in the final report.

## Event log rules

- Events are facts: `run.node.finished`, `ai.turn.settled`, `ai.question.answered`.
- Commands are direct calls: start, stop, answer, steer. Never implement control flow as events.
- A listener failure is logged and isolated; it must not kill a crawl or a turn.
- Events carry ids/status/counts, never crawled text.

## Acceptance

- Kill the process mid-turn; restart; the turn is `interrupted`, not vanished.
- Close the panel, switch conversation, reload; the same turn is still running and reattaches.
- Answer a question after a reload with only its `question_id`.
- Replay the transition table; every illegal transition is refused by name.
