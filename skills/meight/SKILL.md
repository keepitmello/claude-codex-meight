---
name: meight
description: "Codex worker dispatch harness (global CLI: meight, repo: claude-codex-meight). Delegate implementation/review/runtime, browser QA, visual QA, computer-use, and image generation/editing work to N parallel Codex workers with explicit --mode collab|delegate, start/status/result supervision by default, one-shot dispatch for trivial safe tasks, structured QUESTION routing, and decision-surface reports. Use whenever a dispatcher delegates work to Codex. TRIGGERS: -코덱스 -meight -메이트 -mate -코덱스위임"
---

# meight (claude-codex-meight)

Harness for driving Codex workers in parallel from an orchestrating agent. It is
usable from any repo via the `meight` CLI. One global daemon is shared across
repos; worker state is isolated per invoking repo under
`<daemon-home>/repos/<repo-key>/`.

Codex worker-facing details live in
[`skills/meight-worker/SKILL.md`](../meight-worker/SKILL.md). The harness
preamble resolves that skill path relative to the `meight.py` location so any
clone can load the right worker contract. This skill is the dispatcher-facing
SSOT for how to supervise workers.

## Operating Model

- The dispatcher owns WHAT, WHY, priority, scope, UX, user-visible behavior,
  risk appetite, acceptance criteria, final approval, user communication,
  integration, and git coordination.
- Codex workers own HOW: technical judgment, technical design, implementation,
  verification, review-loop handling, and local technical choices.
- Workers are teammates, not silent executors. They can push back with a
  structured `QUESTION:` when they see a better direction, a wrong assumption,
  or a decision outside their ownership.
- Verification owns the outcome. A worker's "done" is a claim; relevant tests
  or runtime checks plus dispatcher sign-off make it a fact. When risk warrants
  independent review, a reviewer verdict is required too.
- Workers may commit/push completed verified work when the brief allows it, but
  the dispatcher still owns final integration and approval.

## Modes Are Required

`start` and `dispatch` require `--mode collab|delegate`. Aliases
`collaborative` and `delegated` are accepted. There is no default; omitting the
flag is an error with a teaching message. The consumer is an LLM agent, so
policy cannot be forgotten or left to memory.

- `--mode collab`: use for consult, design, diagnosis, architecture,
  alternatives, tradeoffs, planning, and direction-setting reads. The worker
  exposes options and reasoning.
- `--mode delegate`: use for bounded implementation, fixes, verification, and
  review. The worker owns the technical loop and reports a decision surface.
- `follow` and `reply` take no mode flag. They inherit the worker's recorded
  mode and receive only a one-line harness reminder instead of the full
  preamble.

Mode is recorded in `status.json` as `mode` and shown in status tables as the
`MODE` column.

## Default: Start, Then Check Status

For anything beyond trivial, short, low-risk work, use `start` instead of one
blocking `dispatch`. After starting, keep working and use `status`, `steer`,
`result`, and `reply` when the session is revisited or the host surfaces the
background work. Do not keep a long-running background checkpoint shell as the
normal Claude Code supervision loop.

```bash
meight start <name> --mode delegate --report decision --brief-file - --cwd <dir> \
  [--sandbox ws|ro|full, default full] [--effort low|medium|high|xhigh, default medium] <<'EOF'
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
Routing principle: **failure cost picks the model.** Code work that misses
forces an extra review/fix round, so a slower-but-smarter model wins on total
time. Step-heavy automation is latency-dominated with simple per-step
decisions, so a faster model wins.

| Model | Use for | Typical effort |
|-------|---------|----------------|
| `sol` | Implementation, fixes, verification (default for code work) | medium |
| `sol` | Design, consult, architecture, adversarial review | high |
| `terra` | Computer use, browser QA, runtime automation, step-heavy flows | medium |
| `luna` | One-shot trivial checks (`dispatch tiny-*`), lookups, screenshot reads | low–medium |

Benchmark rumor "sol medium ≈ terra high" is unverified for our workloads —
when in doubt on code quality, prefer `sol`. Revisit this table after A/B
comparisons on real briefs (record findings in `notes/lessons.md`).

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
meight dispatch tiny-1 --mode delegate --report decision --sandbox ro \
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

Decision schema fields:

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

`outcome=needs_decision` routes to `needs_input` / exit `3` using the first
entry in `decisions[]`.

Recommended pairing: `--mode delegate --report decision` for bounded
implementation, so dispatcher context stays clean for user communication.

## Structured QUESTION Routing

Workers use this exact final-paragraph shape:

```text
QUESTION:
TARGET: dispatcher | user
KIND: scope | ux | priority | risk | irreversible | acceptance | missing-info | better-direction | technical
<question + options + recommendation>
```

`TARGET` says who must decide:

- `dispatcher`: the orchestrating agent can answer via `reply`.
- `user`: the human above the dispatcher must decide.

`KIND` says why the question is being routed. Scope, UX, priority, risk
appetite, irreversible action, and acceptance criteria usually belong to the
user unless the brief explicitly grants that authority to the dispatcher.

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

At most two `follow`/`reply` turns per thread is a good default. If daemon
restart or GC expired the same-thread session, `status` shows
`runtime_lost_detail`; start a fresh worker instead of replying.

## Consult Doctrine

Use consults for direction-setting forks and for genuine uncertainty.

### Blind Consult (Default For Direction Forks)

Analyze first and keep your own analysis out of the brief. Send only the
problem, constraints, relevant files, and neutral option labels. Ask for the
best-supported design and the strongest case against it, not agreement.

```bash
meight start consult-auth --mode collab --sandbox ro --effort high --cwd <repo root> --brief-file - <<'EOF'
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
meight start consult-refine --mode collab --sandbox ro --effort high --cwd <repo root> \
  --brief "Direction is Option B. Pressure-test it: what am I missing, and what edge cases should the implementation cover?"
```

### Disagreement Protocol

1. Compare the two reads.
2. Split disagreements into evidence questions vs value judgments.
3. Evidence questions get one targeted verification worker.
4. User-owned value judgments (scope, UX, priority, risk appetite,
   irreversible action, acceptance criteria) escalate to the human.
5. Max two rounds. Then prefer the reversible/lower-risk option or escalate.

Do not run worker-vs-worker debate loops. Do not feed one read into the other
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
READ B (worker, blind|anchored): <one-paragraph position>
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

Operational lessons about running workers — recurring review-finding classes,
brief-writing gaps, harness interference patterns — get one line each. When a
lesson recurs, promote it into the brief template's Constraints or into this
skill. Repo-specific code patterns belong in that repo's own docs, not here.

## Review Worker Pattern

Use an independent read when risk warrants it: security-sensitive,
irreversible, broad, genuinely uncertain, or high-impact work. For a routine
bounded and reversible change, relevant verification plus dispatcher sign-off
is sufficient; do not spend a second worker merely as proof that ordinary work
is complete.

```bash
meight start review-X --mode delegate --report decision --sandbox ro --effort high --cwd <repo root> --brief-file - <<'EOF'
Adversarial review. Target: <files>. Contract: <spec / PR description>.
Hunt for real defects: correctness, regressions, missing verification,
security/data risk, edge cases, races. For each finding: severity P1/P2/P3,
file:line, why, fix direction. End with GO or NO-GO.
EOF
```

Default to a fresh Codex review worker for riskier work. For important
architecture, high-stakes, or irreversible work, add another independent read
when available (for example a Claude agent) because critical work deserves more
than one perspective. Independent context matters when review is warranted.

For bounded implementation, you can push the implement/review/fix loop inside
the worker by requiring it to spawn an independent reviewer and report only the
decision surface. Guardrails:

- At most two review rounds.
- Fix P1 blockers only unless the brief says otherwise.
- Record P2/P3 without broadening scope.
- Put detailed review logs in `<worker-name>-evidence.md`.

## Writing Briefs

Use the smallest brief that gives the worker the right contract:

- Goal
- Scope
- Existing patterns (required; use file:line)
- Constraints
- Verification
- Report

Do not paste mode, report, and QUESTION policy into every brief; the harness
preamble injects those. Domain rules and task-specific constraints belong in
the brief.

## Status, Steer, Interrupt

```bash
meight status            # one-line table for this repo, includes MODE
meight list --all-repos  # global table across repo namespaces
meight status <name>     # detail, including mode/report/needs_input target+kind
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
