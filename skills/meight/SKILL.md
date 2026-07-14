---
name: meight
description: "Codex dispatch harness (global CLI: meight, repo: claude-codex-meight). Route independent consult and review work to role mate, bounded implementation and verification to role worker, require explicit --role and --mode, supervise with start/status/result, and use one-shot dispatch only for trivial safe work. Use whenever a dispatcher delegates work to Codex. TRIGGERS: -코덱스 -meight -메이트 -mate -코덱스위임"
---

# meight (claude-codex-meight)

Harness for driving Codex sessions in parallel from an orchestrating agent. It is
usable from any repo via the `meight` CLI. One global daemon is shared across
repos; session state is isolated per invoking repo under
`<daemon-home>/repos/<repo-key>/`.

Role details live in [`skills/meight-mate/SKILL.md`](../meight-mate/SKILL.md)
and [`skills/meight-worker/SKILL.md`](../meight-worker/SKILL.md). Their shared
protocol lives in
[`skills/meight-common/CONTRACT.md`](../meight-common/CONTRACT.md). The harness
preamble injects the selected role skill plus the common contract. This skill
is the dispatcher-facing SSOT for routing and supervision.

## Operating Model

- The dispatcher owns WHAT, WHY, priority, scope, UX, user-visible behavior,
  risk appetite, acceptance criteria, final approval, user communication,
  integration, and git coordination.
- A Codex worker owns bounded technical design, implementation, verification,
  and local execution choices. A Codex mate independently challenges plans,
  direction, code, and doctrine.
- Both roles are teammates, not silent executors. They can push back with a
  structured `QUESTION:` when they see a better direction, a wrong assumption,
  or a decision outside their ownership.
- Verification owns the outcome. A worker's "done" is a claim; relevant tests
  or runtime checks plus dispatcher sign-off make it a fact. Plan-governed
  implementation additionally requires the `mate/sol` review verdict from the
  review chain below; verification plus dispatcher sign-off alone is
  sufficient only for work outside a plan-governed review chain.
- Sessions may commit/push completed verified work when the brief allows it, but
  the dispatcher still owns final integration and approval.

## Roles Are Required

`start` and `dispatch` require `--role mate|worker`. There is no default.
Omission or an unknown value produces a teaching error before start side
effects.

- `--role mate`: use for blind or anchored consults, plan review, adversarial
  review, and doctrine/contract challenge.
- `--role worker`: use for bounded implementation, fixes, tests, verification,
  runtime/browser QA, computer use, and exploration.

Role and model are independent. Hard-gated implementation by `sol` uses
`--role worker`; `--role mate --model luna` is valid but unusual. `follow` and
`reply` inherit the recorded role. Role is stored in `status.json` and shown in
the `ROLE` status column.

The CLI performs a capability handshake before sending `start`. If the live
daemon does not advertise capability `role`, start fails closed with
`daemon predates --role; restart required`; it never falls back to the worker
skill.

## Modes Are Required

`start` and `dispatch` require `--mode collab|delegate`. Aliases
`collaborative` and `delegated` are accepted. There is no default; omitting the
flag is an error with a teaching message. The consumer is an LLM agent, so
policy cannot be forgotten or left to memory.

- `--mode collab`: use for consult, design, diagnosis, architecture,
  alternatives, tradeoffs, planning, and direction-setting reads. The mate
  exposes options and reasoning.
- `--mode delegate`: use for bounded implementation, fixes, verification, and
  review. The worker owns the technical loop and reports a decision surface.
- `follow` and `reply` take no mode flag. They inherit the session's recorded
  mode and receive only a one-line harness reminder instead of the full
  preamble.

Mode is recorded in `status.json` as `mode` and shown in the `MODE` column.

## Default: Start, Then Check Status

For anything beyond trivial, short, low-risk work, use `start` instead of one
blocking `dispatch`. After starting, keep working and use `status`, `steer`,
`result`, and `reply` when the session is revisited or the host surfaces the
background work. Do not keep a long-running background checkpoint shell as the
normal Claude Code supervision loop.

```bash
meight start <name> --role worker --mode delegate --report decision --brief-file - --cwd <dir> \
  [--sandbox ws|ro|full, default full] [--effort low|medium|high|xhigh|ultra|max, default medium] <<'EOF'
## Goal       <what this enables + success criteria>
## Scope      <file/dir boundary; do not exceed>
## Existing patterns  <file:line pointers; required for good review>
## Constraints <domain rules only; mode/QUESTION/report policy is injected>
## Verification <commands to run + expected outcome>
## Report     <decision surface; details in a worker-unique evidence artifact>
EOF
```

## Model Selection (GPT-5.6: sol / terra / luna)

Pass `--model` explicitly; the flag already exists on `start` and `dispatch`.
The short names are real aliases: `sol`, `terra`, and `luna` resolve to the
current ChatGPT-account slugs `gpt-5.6-sol`, `gpt-5.6-terra`, and
`gpt-5.6-luna`. Full or custom model strings pass through unchanged.
Routing principle: **failure cost picks the model.** The default is broad on
purpose: bounded work goes to `luna` at `xhigh`, with `--fast` when the account
and service make Fast available.

| Model | Use for | Typical effort |
|-------|---------|----------------|
| `luna` | Default model for role-worker implementation, fixes, tests, verification, read-only log digging, browser/runtime QA, computer use, exploration | `xhigh` + `--fast` when available |
| `sol` | Default model for role-mate direction/plan/adversarial review, plus hard-gated role-worker implementation | `high` or `xhigh` |
| `terra` | No default ownership; capability-specific fallback when measured evidence supports it | task-specific |

Hard gate (verbatim contract wording): **acceptance-critical한 부분이 concurrency,
security, 공개 schema/API 계약 설계, 영속 데이터 마이그레이션, cross-cutting
리팩터에 materially 의존하거나 실패가 돈/데이터 손상·비가역·고임팩트 프로덕션
피해를 낳으면 sol로 하드 라우팅.** General endpoint implementation remains
`luna`; API contract design or evolution is `sol`. Read-only production log
investigation is `luna`; production mutation or incident remediation is not a
`luna` task, and money paths retain the existing dispatcher sign-off gate.
Ambiguity inside a `luna` task is handled with `QUESTION:` escalation.

`terra` can receive a `luna` escalation when a capability-specific reason and
measured evidence justify it. It can be promoted back into default ownership
after evidence accumulates, but no promotion rule is assumed before the
baseline exists. UX and user-visible-behavior judgment stays with the
dispatcher; briefs specify the accepted UX contract explicitly.

When you revisit the worker, inspect once and decide:

```bash
meight status <name>
meight steer <name> "correction"
```

When the worker reaches a terminal or question state:

```bash
meight result <name>        # prefers decision.md when present
meight result <name> --raw  # raw result.md audit record
meight reply <name> --brief "Use config-a.json and keep the legacy field."
```

Long-running checkpoint shells are not the default Claude Code orchestration
path. Treat a stopped background shell as a shell lifecycle event, not a worker
failure.

## One-Shot Dispatch

Use one-shot dispatch only when supervision is not worth it.

```bash
meight dispatch tiny-1 --role worker --mode delegate --report decision --sandbox ro \
  --brief "Check whether README mentions LICENSE."
```

`dispatch` auto-starts the daemon if needed, starts the worker, waits, and
prints the preferred result (`decision.md` when present, otherwise `result.md`).
Add `--shutdown-when-idle` when the daemon should exit after a terminal result
and no other workers are active.

## Report Modes

Default report mode is `--report text`: the final message is written to
`result.md`.

Use `--report decision` for bounded delegated work:

- The SDK turn uses `output_schema`.
- The daemon writes `decision.json` and rendered `decision.md` for each turn.
- `meight result`, `dispatch`, and `reply` prefer `decision.md`.
- `meight result --raw` prints raw `result.md`.
- `result.md` remains the audit record.

The exact schema and field semantics live only in the
[shared contract](../meight-common/CONTRACT.md). `outcome=needs_decision`
routes to `needs_input` / exit `3`, prioritizing the first user-targeted entry.

Recommended pairing: `--mode delegate --report decision` for bounded
implementation, so dispatcher context stays clean for user communication.

## Structured QUESTION Routing

The exact text and decision-mode question formats live in the
[shared contract](../meight-common/CONTRACT.md). Dispatcher-targeted technical
or missing-information questions can be answered with `reply`; user-owned
scope, UX, priority, risk, irreversible, and acceptance decisions go to the
human.

The daemon parses leniently. Missing `TARGET` defaults to `dispatcher`. Parsed
values are recorded as `needs_input_target` and `needs_input_kind` in
`status.json`. Exit codes do not change: final structured questions still exit
`3`. The middle layer triages: `TARGET: user` or user-owned kinds are escalated
to the human verbatim; other questions are answered with `meight reply`. Before
escalating, check the preference ledger (see Learning Loop below) — an already
answered class of question is answered from the ledger, not re-asked.

```bash
meight reply <name> --brief "Use config-a.json and keep the legacy field."
```

At most two `follow`/`reply` turns per thread is a good default for ordinary
work and for the implementation review loop. The plan-review loop below is the
explicit exception: it permits up to three total review rounds and uses
dispatcher-targeted `QUESTION:` plus `reply` to preserve the thread. If daemon
restart or GC expired the same-thread session, `status` shows
`runtime_lost_detail`; start a fresh worker instead of replying.

## Consult Doctrine

Use consults for direction-setting forks and for genuine uncertainty.

### Blind Consult (Default For Direction Forks)

Analyze first and keep your own analysis out of the brief. Send only the
problem, constraints, relevant files, and neutral option labels. Ask for the
best-supported design and the strongest case against it, not agreement.

```bash
meight start consult-auth --role mate --mode collab --sandbox ro --model sol --effort high --cwd <repo root> --brief-file - <<'EOF'
We need to choose an auth-token refresh design.

Constraints:
- No user-visible logout regression.
- Existing token storage is in src/auth/store.ts.
- Existing request retry code is in src/api/client.ts.

Options:
- Option A: refresh before each protected request when expiry is near.
- Option B: centralize refresh in the API client on 401.

Give the best-supported design, the strongest case against it, and the evidence
that would settle remaining uncertainty. No code changes.
EOF
```

### Anchored Consult (Only After Direction Is Set)

Use anchored consults to refine an already-set direction:

```bash
meight start consult-refine --role mate --mode collab --sandbox ro --model sol --effort high --cwd <repo root> \
  --brief "Direction is Option B. Pressure-test it: what am I missing, and what edge cases should the implementation cover?"
```

### Plan-Review Loop (Bounded Anchored Refinement)

Blind consult remains unchanged for direction-setting forks. Only after the
direction is set does the dispatcher author a plan and enter this bounded,
anchored refinement loop with `sol high` or `sol xhigh`:

1. The dispatcher authors the plan and sends it to a persistent `mate/sol` review
   mate thread. Run this bounded loop with `--role mate --mode delegate
   --report decision` so
   verdicts arrive schema-validated; `--report text` remains acceptable for
   collab-style exploratory reviews.
2. The reviewer leads with `APPROVE` or `REVISE`. In decision-report mode the
   strict schema has no APPROVE/REVISE values, so the exact encoding is:
   `APPROVE` ⇒ `outcome=done`, `verdict=GO`, summary starting
   `"APPROVE — <plan identity>"`; `REVISE` ⇒ `outcome=needs_decision`,
   `verdict=NO-GO`, summary starting `"REVISE — <plan identity>"`, with the
   dispatcher-owned revision decision as the only `decisions[]` entry unless a
   genuine user-owned decision exists. In text mode, `REVISE` ends as a
   dispatcher-targeted structured `QUESTION:`. Either way the thread survives
   for `meight reply`; `APPROVE` is terminal.
   Reviewers must not flag:
   - naming/style preferences in the plan document itself;
   - theoretical edge cases that cannot occur with real inputs;
   - out-of-scope “what about” hypotheticals; or
   - findings the plan text or a prior round already resolved.
3. Run at most three plan-review rounds. From round 2 onward, before raising
   new findings, the reviewer first dispositions every prior finding as
   `addressed`, `partially addressed`, or `not addressed`, citing the plan
   text/evidence that resolved it or explains why it remains open. Record that
   disposition with the `resolved-risks` half of the round ledger, while
   `new-risks` contains only new findings; keep the two separate. In
   decision-report mode the ledger lives in a worker-unique evidence artifact
   with separate `new-risks` and `resolved-risks` headings, listed in
   `evidence_artifacts` — the strict schema has no fields for it.
4. If round three does not approve, do not auto-reenter. The dispatcher chooses
   exactly one next step: residual-risk sign-off, a targeted evidence read, or
   user escalation.
5. Freeze the approved contract as versioned `PLAN.md`. Implementation and
   final review both use that exact plan. A scope change reopens plan approval.

Plan review is also the routing backstop: it records which hard-gate clause
fired, or explicitly records `none—luna eligible`.

### Disagreement Protocol

1. Compare the two reads.
2. Split disagreements into evidence questions vs value judgments.
3. Evidence questions get one targeted verification session.
4. User-owned value judgments (scope, UX, priority, risk appetite,
   irreversible action, acceptance criteria) escalate to the human.
5. Max two rounds. Then prefer the reversible/lower-risk option or escalate.

Do not run mate-vs-mate debate loops. Do not feed one read into the other
before both exist.

## Learning Loop: Decision Records, Preferences, Lessons

The harness gets better with use only if decisions and answers accumulate
somewhere agents actually read. Three ledgers, all plain files:

### Decision Records (`<repo>/decisions/`)

After any direction-setting fork resolved by two reads, write
`decisions/YYYY-MM-DD-<slug>.md` in the working repo:

```md
# <the question>
DATE: <date> · MODE: consensus|delegation
READ A (dispatcher): <one-paragraph position>
READ B (mate, blind|anchored): <one-paragraph position>
DISAGREEMENT: <where they split, or "none">
RESOLUTION: evidence|value-judgment — <what settled it>
DECISION: <what was chosen>
STATUS: adopted
```

This is the durable output of consensus mode: it survives context compaction,
lets any later session audit *why*, and accumulates the judgment patterns that
settle future forks faster. Supersede with `STATUS: superseded by <file>`
rather than deleting.

### Preference Ledger (`<daemon-home>/notes/preferences.md`)

Before escalating a `TARGET: user` question, check the ledger. If the user has
already answered the same class of question, answer via `reply` citing the
recorded preference instead of re-asking. After the user decides something new,
append one line: preference, one-clause rationale, date.

Exception: `KIND: irreversible` and `KIND: risk` questions are re-confirmed
with the user even when a recorded preference matches.

### Lessons (`<daemon-home>/notes/lessons.md`)

Operational lessons about running meight sessions — recurring review-finding classes,
brief-writing gaps, harness interference patterns — get one line each. When a
lesson recurs, promote it into the brief template's Constraints or into this
skill. Repo-specific code patterns belong in that repo's own docs, not here.

For this operating model, record enough structured data to measure:

- plan-review round count and the cause of each `REVISE`;
- role (`mate` or `worker`) for every run record;
- escalation rate as rerouted tasks divided by `luna`-started tasks, with
  ordinary `QUESTION:` events tracked separately;
- the escalation axis (`luna→sol` or `luna→terra`) and the hard-gate clause
  that fired;
- false approvals found after sign-off, measured within the same release
  window; repos without releases must define a fixed time-window fallback.

Do not harden escalation rules until this baseline exists.

## Mate Review Pattern

The normal implementation chain is `luna` implementation → `sol` adversarial
review → dispatcher full-diff read and final sign-off. The review contract is
the frozen, versioned `PLAN.md`, not a summary written after implementation.

```bash
meight start review-X --role mate --mode delegate --report decision --sandbox ro --model sol --effort high --cwd <repo root> --brief-file - <<'EOF'
Adversarial review. Target: <files>. Contract: <versioned PLAN.md>.
Hunt for real defects: correctness, regressions, missing verification,
security/data risk, edge cases, races. For each finding: severity P1/P2/P3,
file:line, why, fix direction. End with GO or NO-GO.
EOF
```

Every review verdict must name the exact input reviewed: the `PLAN.md` version
for plan reviews, or a commit hash/diff identity for code reviews. Before acting
on a verdict, the dispatcher compares that identity with the current artifact
and discards the verdict as stale if they no longer match.

The dispatcher reads the complete diff with both `PLAN.md` and repository
context, arbitrates findings, fixes valid defects directly, and owns the final
sign-off. A dispatcher fix that changes plan scope reopens plan approval; a
P1-fix-level correction keeps the frozen contract. The adversarial code-review
loop is capped at two rounds.

Harness-grade or core surgery routes to Codex `sol`, not a Claude implementation
fork. It also adds a Claude context-holding review at both the plan stage and
the final-diff stage. The dispatcher remains the orchestrator, arbitrator, and
final signer.

Role-worker implementation reports from `luna` must map the approved-plan rationale onto
the existing decision schema:

- `summary`: name the plan version and state every deviation plus rationale;
- `verification`: show the evidence that the implementation satisfies the
  frozen plan;
- `risks`: state what was deliberately not done and why (use an empty list only
  when there truly is nothing to record);
- `changed_files` and `commits`: identify the review surface exactly.

Review guardrails:

- At most two review rounds.
- Fix P1 blockers only unless the brief says otherwise.
- Record P2/P3 without broadening scope.
- Put detailed review logs in `<worker-name>-evidence.md`.

### Fresh-Eyes UI Review (frontend dispatches)

When a frontend worker reports `IMPLEMENTED, FRESH-EYES PENDING`, dispatch an
independent comprehension reviewer before accepting `VERIFIED`. Protocol and
verbatim reviewer prompt: `~/.codex/skills/frontend-ux-router/references/fresh-eyes-review.md`.

- One-shot `--role mate --model luna` with only: the persona line, screenshot paths (or route),
  and the reviewer prompt. Zero implementation context — no brief, no diff,
  no explanations. Contamination invalidates the review.
- FAIL → route the reviewer's raw answers back to the implementer as redesign
  input (path-card recomposition, not copy patches). One re-review; a second
  FAIL on the same question escalates to the user.

Use the smallest brief that gives the worker the right contract:

- Goal
- Scope
- Existing patterns (required; use file:line)
- Constraints
- Verification
- Report

Do not paste role, mode, report, and QUESTION policy into every brief; the
harness preamble injects those. Domain rules and task-specific constraints
belong in the brief.

## Status, Steer, Interrupt

```bash
meight status            # one-line table for this repo, includes ROLE and MODE
meight list --all-repos  # global table across repo namespaces
meight status <name>     # detail, including role/mode/report/needs_input target+kind
meight steer <name> "instruction"
meight interrupt <name>
```

`status` is pull-only and reads disk. `steer`, `interrupt`, `follow`, and active
runtime behavior require a live daemon.

## Codex Worker Capabilities

Ask for the modality explicitly in the brief and require evidence that it was
used:

- Browser use: open and click through localhost apps, responsive flows, smoke
  tests, screenshots.
- Computer use: operate desktop apps or OS UI.
- Vision/screenshots: inspect layout, text clipping, rendering, mocks, Figma,
  production captures.
- Asset/document work: images, PDFs, docs, CSV/XLSX.
- Research: current docs, APIs, release notes, pricing, policies when browsing
  is available.
- Connector-backed work: GitHub, Google Drive, Figma, Canva, Hugging Face,
  Sentry, and similar when enabled.

## Daemon Runtime Checks

Meight runtime code is loaded into the long-lived daemon process. After changing
`meight.py`, restart the daemon before trusting behavior from new workers.

### Role Migration And Post-Restart Smoke

Do not restart while any repo namespace has an active or `needs_input` session.
The operator performs this checklist manually:

1. Run `meight list --all-repos --json` and confirm no row is `starting`,
   `running`, or `needs_input`.
2. Run non-force `meight shutdown`. Its daemon-wide active-session guard must
   refuse shutdown if the drain check missed anything; do not use `--force` for
   this migration.
3. Start the new daemon by the installation's normal mechanism and run
   `meight ping`. Confirm `capabilities=role`.
4. Start a throwaway read-only session with `--role mate --mode delegate`.
5. Confirm `meight status <name> --json` records `"role": "mate"` and inspect
   its `brief.md` to verify the preamble names
   `skills/meight-mate/SKILL.md` plus `skills/meight-common/CONTRACT.md`.
6. Only then dispatch real work. Remove or retain the throwaway disk artifacts
   according to the normal operator policy; no forced cleanup is required.

The implementation worker must document this procedure but must not execute it
against the old daemon during the mate-split rollout.

Useful checks:

```bash
MEIGHT_HOME="${MEIGHT_HOME:-$HOME/.meight}" meight ping
ps eww -axo pid,ppid,command | rg 'meight.py daemon|MEIGHT_IDLE_TIMEOUT_SEC|XPC_SERVICE_NAME=com.keepitmello.meight'
launchctl print "gui/$(id -u)/com.keepitmello.meight"  # if LaunchAgent is installed
meight list --all-repos --json
```

Hidden-session invariant:

- Default workers must have `"thread_source": "subagent"` and
  `"thread_ephemeral": true` in `status.json` / `meight status <name> --json`.
- Only explicit `--main-thread` workers may have `"thread_source": "user"` and
  `"thread_ephemeral": false`.
- If Codex Desktop shows new meight workers unexpectedly, check for an old
  daemon running from another home or process.

## State / Caveats

- Worker artifacts:
  `<daemon-home>/repos/<repo-key>/workers/<name>/{brief.md,status.json,events.log,result.md,decision.json,decision.md}`
- Low-level commands: daemon / start / result / list / shutdown `[--force]` /
  launchd.
- Lifecycle: foreground `MEIGHT_IDLE_TIMEOUT_SEC` default is 1800s, while
  `daemon --idle-timeout-sec 0` disables it. Managed `dispatch`/LaunchAgent
  starts pass idle disable through both env and daemon args. LaunchAgent jobs
  infer managed mode from `XPC_SERVICE_NAME=com.keepitmello.meight` if an older
  loaded job lacks the env. Trust `meight ping`/startup log for the running
  value.
- Terminal workers release their SDK runtime immediately after stream end.
  `MEIGHT_WORKER_GC_TTL_SEC` (default 3600s) only removes terminal worker
  status from daemon memory while keeping disk artifacts.
- Beta SDK (`openai-codex==0.1.0b3`, pinned): re-run the SPEC.md verification
  suite when upgrading.
- Source and docs: README.md, SPEC.md, ARCHITECTURE.md.
