---
name: meight
description: Dispatch bounded or long-running work from Codex with native subagents while preserving the shared meight mate/worker contracts. Use for independent design, diagnosis, artifact review, implementation, verification, and supervised phase work in the Codex desktop app.
---

# meight — Codex native dispatcher binding

First resolve the physical path of this file, following the installation
symlink back into the repository checkout. The full dispatcher protocol is the
single source of truth at `../../../../skills/meight/SKILL.md` relative to that
physical location. Read it completely before dispatching. Also read the shared
contract and the selected posture contract before spawning:

- shared: `../../../../skills/meight-common/CONTRACT.md`
- mate: `../../../../skills/meight-mate/SKILL.md`
- worker: `../../../../skills/meight-worker/SKILL.md`

This binding changes the transport when the dispatcher is running in the Codex
desktop app. The shared
ownership, phase approval, campaign identity, stop rules, question routing,
review caps, and verification rules remain binding.

## Codex app transport — native only

When native collaboration tools are available in the Codex desktop app:

- Use native `spawn_agent`, `send_message`, `followup_task`, `interrupt_agent`,
  `list_agents`, and `wait_agent` tools.
- Do not invoke the `meight` CLI, daemon, worker registry, or disk result
  protocol.
- Native agent threads are the supervision and result surface. Receive their
  final reports as compressed packets and keep integration and sign-off in the
  main session.
- If native subagents are unavailable, report that limitation. Do not silently
  fall back to the external meight daemon unless the user explicitly requests
  that fallback.

The external `meight` CLI instructions in the shared skill apply only outside
this native-app route or when the user explicitly asks to operate the meight
daemon.

## You are the dispatcher

The main session owns brief authoring, mode selection, model/effort selection,
question triage, result arbitration, final verification, and integration. The
user still owns WHAT, WHY, scope, priority, risk appetite, acceptance criteria,
and approval to enter a new phase.

Use subagents only for bounded independent workstreams or an isolated quality
check that materially improves speed or quality. Prefer 2–3 agents over broad
fan-out. Do not send multiple writers into the same ownership area.

For work expected to exceed about one hour or containing a mid-run gate, keep
the main session at the steering level. Spawn only the current approved phase,
give it explicit stop rules, inspect its report at the decision boundary, and
obtain fresh user approval before a changed method, larger cost, new acceptance
path, or recovery phase.

## Native posture and review routing

Use the current global `AGENTS.md` routing contract and the live `spawn_agent`
schema for model and effort; this binding owns only the meight-to-native
transport mapping. Use `fork_turns="none"` with a short self-contained brief on
fresh spawns.

| Work | Native route |
|---|---|
| Mate design or diagnosis | one judgment-capable Sol agent; read-only unless the brief authorizes changes |
| Independent artifact review | one read-only `reviewer` |
| Additional independent read that can change the decision | a second read-only `reviewer` in parallel with the same neutral brief |
| Worker implementation or verification | the current AGENTS route selected from brief completeness and interpretive risk |

Give a reviewer the exact artifact, intended outcome, constraints, and decision
it must support. Leave the observations and emphasis to independent judgment.
The reviewer may surface useful evidence or a better direction that the brief
did not ask for. One reviewer is the default; add a second only when another
unanchored judgment can change the decision. Do not share conclusions between
independent reviewers.

After each successful spawn, tell the user which agent, model, and effort are
running. If the requested route is unavailable, report the routing failure
rather than substituting an unapproved model or external meight daemon.

## Native brief contract

Every spawn message contains only:

- `Outcome`: the decision or observable result and success condition
- `Scope`: owning boundary and write permissions
- `Constraints`: approval, repository, and safety boundaries
- `Evidence`: checks or artifacts required for acceptance
- `Stop`: escalation conditions and known dependencies

Tell the agent to read the shared contract plus the selected mate or worker
contract before acting. Review work is read-only unless the user also asks for
changes. For a worker, state whether commit or push is allowed; omission means
neither is allowed.

A review returns the evidence-backed judgment that matters: findings, better
directions, and a verdict when the decision calls for one. Worker and design
reports follow their selected contracts. Detailed evidence belongs in a
worker-unique artifact only when the final packet would otherwise become noisy.

## Supervision and questions

- Use `send_message` to steer an agent that is currently running.
- Use `followup_task` for another turn after an agent is idle or after it asks a
  dispatcher-owned technical or missing-information question.
- Use `interrupt_agent` only when the current work must stop.
- Use `list_agents` for a current snapshot and `wait_agent` when waiting is the
  useful next action. Do not busy-poll.

Classify questions by the effect of answering them. Answer in-scope technical
or missing-information questions in the main session and resume the same
native agent. Escalate scope, UX, priority, risk, irreversible action,
acceptance, new phase, materially different method/cost, expensive rerun, or a
campaign-cap extension to the user. A new agent name does not reset repair or
review limits.

## Completion

Treat a subagent's result as evidence, not completion. The main session checks
the compact packets against the brief, arbitrates conflicts, and signs off from
the implementation owner's verification plus any selected review verdict. It
does not repeat a full repository review; inspect only a claim whose conflict or
missing evidence can change the decision. A second NO-GO or a new blocker after
the one allowed re-review ends automatic work and returns the decision to the
user.
