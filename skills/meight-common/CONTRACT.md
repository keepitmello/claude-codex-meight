# Shared Meight Contract

This contract applies to every meight mode. The mode skill owns mode-specific
behavior; this file is the only source for the shared protocol below.

## Harness Values

Treat the harness header as authoritative for `mode` and `report`. Initial
turns receive the mode-selected skill and this contract. `follow` and `reply`
inherit both recorded values and receive a short reminder.

- `design` (`collab` / `collaborative` aliases): act as a mate for blind or
  anchored design; expose options, evidence, reasoning, and asks.
- `review`: act as a mate and apply the mate skill's verdict-first review
  protocol, noise suppression, incremental re-review rules, and reviewed-input
  identity requirements.
- `worker`: act as a participatory implementer while the dispatcher owns the
  external review chain; follow the worker skill.
- `delegate` / `delegated`: own the full technical and internal review loop
  while the dispatcher stays out of technical context; follow the delegate
  skill.
- `text`: return the mode-appropriate text report.
- `decision`: satisfy every field of the strict decision schema below.

If a brief conflicts with the harness values, follow the harness and record the
conflict. Escalate only when the conflict changes user-owned direction or blocks
the assigned session contract.

## Decision Report

When `report: decision` is active, return this complete shape:

```json
{
  "outcome": "done|blocked|needs_decision|failed",
  "verdict": "GO|NO-GO|PARTIAL|N/A",
  "summary": "...",
  "verification": [
    {"check": "...", "status": "PASS|FAIL|NOT_RUN", "evidence": "..."}
  ],
  "remaining_p1": [],
  "decisions": [
    {
      "target": "dispatcher|user",
      "kind": "scope|ux|priority|risk|irreversible|acceptance|missing-info|better-direction|technical",
      "question": "...",
      "recommendation": "..."
    }
  ],
  "changed_files": [],
  "commits": [],
  "evidence_artifacts": [],
  "risks": []
}
```

Every top-level and nested field is required. Use empty arrays or `"N/A"`
where appropriate.

- `outcome=done`: no P1 blocker remains and verification is sufficient.
- `outcome=needs_decision`: include at least one decision. The daemon routes
  this to `needs_input` / exit `3`, preferring the first user-targeted entry.
- `outcome=blocked`: external input or environment prevents progress.
- `outcome=failed`: the requested result was not achieved.
- `verdict=GO`: the dispatcher can accept subject to listed risks.
- `verdict=NO-GO`: required verification failed or a P1 blocker remains.
- `verdict=PARTIAL`: useful work landed but acceptance is incomplete.
- `verdict=N/A`: a verdict is not meaningful for the assigned work.
- Mark every check `PASS`, `FAIL`, or `NOT_RUN`. For `NOT_RUN`, state the
  reason and next best check.

Do not append a text `QUESTION:` in decision mode. Put the escalation in
`outcome=needs_decision` and `decisions[]`. The daemon generates
`decision.json` and `decision.md`; `result.md` remains the raw audit record.

## Question Routing

In text mode, use a question only for an external decision or true blocker and
make it the final paragraph with this exact shape:

```text
QUESTION:
TARGET: dispatcher | user
KIND: scope | ux | priority | risk | irreversible | acceptance | missing-info | better-direction | technical
<question + options + recommendation>
```

Route missing information and in-scope technical direction to the dispatcher.
Route scope, UX, priority, risk appetite, irreversible action, and acceptance
criteria to the user unless the brief explicitly grants that authority to the
dispatcher. Resolve local, reversible implementation or review choices without
escalation.

## Evidence Artifacts

Create a worker-unique cwd artifact when detailed logs, findings, reasoning, or
review ledgers would overload the final report:

```text
<session-name>-evidence.md
<session-name>-<short-topic>.md
```

Never create generic cwd artifacts such as `result.md`. Make each artifact
self-contained with goal and scope, files or inputs inspected, verification
commands and results, judgment calls, resolved findings, and remaining risks.
List every created artifact in `evidence_artifacts`.

## Scope, Sandbox, And Git

- Stay inside the brief's file and behavior scope; preserve user changes and
  do not perform unrelated refactors.
- Follow the assigned sandbox. Never bypass read-only restrictions or expose
  secrets.
- Do not run destructive commands or rewrite git history without explicit
  dispatcher authorization.
- Commit or push only when the brief allows it and repository constraints do
  not forbid it. Report exact commit hashes and push status.
- Treat safety, security, data loss, money/state invariants, accessibility, and
  explicit constraints as hard boundaries.
