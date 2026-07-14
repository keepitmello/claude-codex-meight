# Orchestration Policy - Codex as Orchestrator, Codex as Mates and Workers

> Drop-in prompt for running meight from Codex. Copy this into a project's
> `AGENTS.md` or `~/.codex/AGENTS.md` and adjust to taste. Full command
> examples and protocol details live in
> [`skills/meight/SKILL.md`](./skills/meight/SKILL.md).

## Role Split

The main Codex session is the orchestrator. It owns direction, task
decomposition, arbitration, final integration/sign-off, user communication, and
git coordination. Codex workers, driven through `meight`, own bounded technical
design, implementation, verification, and local execution judgment. Codex
mates independently challenge direction, plans, code, and doctrine.

Same-model orchestration still works because context is independent. Treat
neither role as a clone of the main session. Let mates push back on wrong
assumptions, and use them for fresh reads when a decision or artifact needs
another technical pass.

## Routing

| Work | Route |
|---|---|
| Bounded implementation, fixes, tests, verification, read-only log digging, browser/runtime QA, computer use, exploration | `--role worker --model luna --effort xhigh`, plus Fast when available |
| Direction, plan review, adversarial review | `--role mate --model sol --effort high|xhigh` |
| Hard-gated implementation | `--role worker --model sol --effort xhigh` |
| Capability-specific fallback | either role with `terra` only when measured evidence supports it |

Failure cost is the gate. Hard-route to `sol` when acceptance-critical work
materially depends on concurrency, security, public schema/API contract design,
persistent-data migration, or a cross-cutting refactor, or when failure can
cause money/data damage, irreversible harm, or high-impact production damage.
General endpoint implementation and read-only production log investigation
remain `luna`; API contract design/evolution and production mutation or
remediation do not. Money paths retain dispatcher sign-off. `luna` can escalate
ambiguity with `QUESTION:`; `luna→terra` remains open as an evidence-backed
capability fallback.

## Compact Quick Reference

```bash
meight start <name> --role worker --mode delegate --report decision --model luna --effort xhigh \
  [--fast] --brief-file - --cwd <dir> [--sandbox ws|ro|full] <<'EOF'
## Goal
## Scope
## Existing patterns
## Constraints
## Verification
## Report
EOF

meight wait <name> --timeout 300
meight status <name>
meight steer <name> "correction"
meight result <name>          # prefers decision.md when present
meight result <name> --raw    # prints raw result.md
```

- `start` and `dispatch` require `--role mate|worker` with no default. Choose
  mate for consult/review and worker for implementation/verification. Role and
  model are independent.
- They also require `--mode collab|delegate`
  (`collaborative`/`delegated` aliases are accepted). There is no default:
  the consumer is an LLM agent, so policy cannot be left to memory.
- `follow` and `reply` take no role or mode flag. They inherit role/mode/report and
  receive only a one-line harness reminder.
- Use `--mode delegate --report decision` for bounded implementation. It keeps
  final reports machine-shaped as `decision.json` plus rendered `decision.md`,
  while raw `result.md` remains the audit record.
- Use `--role mate --mode collab` for consult/design/diagnosis. The mate should expose
  options, reasoning, recommendation, evidence, and asks.
- One-shot `dispatch` is for trivial, short, low-risk work only. Substantial
  work should use `start` + `wait` so `status`/`steer` remain available.

## Question Routing

Session questions are final paragraphs with this exact structure:

```text
QUESTION:
TARGET: dispatcher | user
KIND: scope | ux | priority | risk | irreversible | acceptance | missing-info | better-direction | technical
<question + options + recommendation>
```

`TARGET: user` or user-owned kinds such as scope, UX, priority, risk appetite,
irreversible action, or acceptance criteria should be escalated to the human
verbatim. Dispatcher-owned technical or missing-information questions can be
answered with `meight reply`.

## Consult Doctrine

Direction-setting forks get two reads. Analyze first, then send a blind consult:
problem and constraints only, no lean, no draft conclusion, neutral equal-length
Option A/B labels if options are given. Ask for the best-supported design and
the strongest case against it, not agreement.

Anchored consults (`my lean is X, what am I missing?`) are still valid only for
refining an already-set direction. Label blind vs anchored explicitly.

When reads disagree: split evidence questions from value judgments. Evidence
gets one targeted verification session. User-owned value judgments go to the
human. Stop after at most two rounds; then choose the reversible/lower-risk path
or escalate. Do not create mate-vs-mate debate loops.

## Plan-Review Loop

After direction is set, the dispatcher authors a plan and sends it to a
persistent `--role mate --model sol --effort high|xhigh` reviewer. This is bounded anchored refinement, not
a replacement for blind consult:

1. The reviewer leads with `APPROVE` or `REVISE`.
2. `REVISE` keeps the thread alive for `reply` (text mode: dispatcher-targeted
   structured `QUESTION:`; decision mode: the exact schema encoding in
   `skills/meight/SKILL.md`); `APPROVE` is terminal.
3. Run at most three rounds and record `new-risks` and `resolved-risks`
   separately each round.
4. After an unapproved round three, the dispatcher chooses residual-risk
   sign-off, a targeted evidence read, or user escalation; do not auto-reenter.
5. Freeze approval as versioned `PLAN.md`. Scope change reopens approval.

Implementation follows `worker/luna` → `mate/sol` adversarial review (maximum two rounds)
→ dispatcher full-diff read with plan and repo context → direct fixes and final
sign-off. P1-fix-level corrections keep the contract; fixes beyond plan scope
reopen approval. Harness/core surgery routes to `sol` and adds a Claude
context-holding review at both plan and final-diff stages.

## Daemon Role Migration

The CLI fails closed when the live daemon does not advertise capability
`role`. Drain `meight list --all-repos --json`, use non-force
`meight shutdown`, restart normally, confirm `meight ping` shows `role`, then
run a throwaway read-only mate and verify its status role plus mate/common
preamble paths before real dispatches. Never force-shutdown this migration.

## Safety Rules

1. The frozen `PLAN.md` is the review contract. Implementation reports must
   state plan deviations plus rationale and what was deliberately not done.
   The orchestrator reads the full diff and owns final sign-off.
2. NO-GO means blockers were found. Fix valid blockers, then re-review. Push
   back only with code or runtime evidence.
3. No completion claims without evidence. A worker's "done" is a claim;
   relevant tests or runtime checks and your sign-off make it a fact.
   Plan-governed implementation also requires the `mate/sol` review verdict.
4. Workers may commit/push completed verified work when allowed by the brief,
   but the main session still owns final integration and approval.
5. Parallel workers with overlapping file scopes need separate worktrees via
   `--cwd`.
