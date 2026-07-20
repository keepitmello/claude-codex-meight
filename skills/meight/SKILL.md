---
name: meight
description: "Codex dispatch harness (global CLI: meight, repo: claude-codex-meight). Route blind and anchored design to design, verdict-first plan/diff review to review, participatory bounded implementation to worker, and dispatcher-free full delegation to delegate; require explicit --mode and choose supervised or one-shot dispatch per task. Use whenever a dispatcher routes work to Codex. TRIGGERS: -코덱스 -meight -메이트 -mate -코덱스위임"
---

# meight (claude-codex-meight)

Harness for driving Codex sessions in parallel from an orchestrating agent. It is
usable from any repo via the `meight` CLI. One global daemon is shared across
repos; session state is isolated per invoking repo under
`<daemon-home>/repos/<repo-key>/`.

The default dispatcher is a Claude Code session. A Codex app/CLI session can
also act as dispatcher through the thin `~/.codex/skills/meight` binding that
points back to this file. Prefer the Claude dispatcher for long multi-phase or
direction-sensitive work: a cross-model dispatcher decorrelates blind spots
with the Codex workers it supervises.

Contract details live in [`skills/meight-mate/SKILL.md`](../meight-mate/SKILL.md),
[`skills/meight-worker/SKILL.md`](../meight-worker/SKILL.md), and
[`skills/meight-delegate/SKILL.md`](../meight-delegate/SKILL.md). Their shared protocol lives in
[`skills/meight-common/CONTRACT.md`](../meight-common/CONTRACT.md). The harness
preamble injects the mode-selected skill plus the common contract. This skill
is the dispatcher-facing SSOT for routing and supervision.

## Operating Model

- The user owns WHAT, WHY, priority, scope, UX, user-visible behavior, risk
  appetite, acceptance criteria, and approval to enter a new phase.
- The dispatcher preserves those decisions and owns technical choices inside
  the currently approved phase, user communication, integration, verification,
  and git coordination. The dispatcher does not approve expanded work on the
  user's behalf.
- A Codex worker owns participatory bounded technical design, implementation,
  verification, and local execution choices while the dispatcher owns the
  choice and handling of any external review. A delegate owns implementation and internal review
  end to end while the dispatcher stays outside technical context. A Codex
  mate independently challenges plans, direction, code, and doctrine.
- Mate, worker, and delegate name the session contract, not the model: `--mode` picks
  the contract and `--model` picks the brain.
- All three contracts are teammate contracts, not silent executors. They can push back with a
  structured `QUESTION:` when they see a better direction, a wrong assumption,
  or a decision outside their ownership.
- Verification owns the outcome. A worker's "done" is a claim; relevant tests
  or runtime checks plus dispatcher sign-off make it a fact. For work the
  dispatcher judges to warrant review, sign-off combines the review verdict
  with verification evidence. The dispatcher records its gate choice in one
  line; there is no default delivery chain.
- Sessions may commit/push completed verified work when the brief allows it, but
  the dispatcher still owns final integration and approval.

## Phase Approval And Campaign Identity

A user approval is bound to the named phase, method, expected cost envelope,
and acceptance path. It expires when a required gate fails, the next action
materially changes the method or expected cost, or the work shifts from
advancing the outcome to strengthening records.

Count attempts, repair rounds, and review rounds by the user outcome and
decision being pursued. The campaign identity survives renamed workers, fresh
threads, plan/addendum revisions, branches, and artifact or review identities.
Starting a new session does not reset a cap.

Inside one approved phase, at most one bounded repair and one re-review may be
preauthorized. A second NO-GO, a new blocker after that re-review, or a reroute
outside the approved phase stops automatic work. The dispatcher may gather the
cheapest trustworthy failure record, then must return the failure, options, and
recommendation to the user before dispatching more implementation or review.

## Modes Are Required

`start` and `dispatch` require `--mode design|review|worker|delegate`. `collab`,
`collaborative`, and `delegated` are accepted aliases. There is no default; omitting the
flag is an error with a teaching message. The consumer is an LLM agent, so
policy cannot be forgotten or left to memory.

- `--mode design`: use for blind or anchored design,
  diagnosis, architecture, alternatives, tradeoffs, planning, and direction
  setting. The session is a mate and exposes options and reasoning.
- `--mode review`: use for verdict-first plan, diff, adversarial, and doctrine
  review. The session is a mate with explicit review duties.
- `--mode worker`: use for bounded implementation, fixes, tests, verification,
  runtime/browser QA, computer use, and exploration while the dispatcher
  decides whether a separate review session is warranted.
- `--mode delegate`: use only for full delegation when the dispatcher should
  leave technical context. The delegate owns internal fresh-context read-only
  review and fails closed to worker for hard gates, money paths, or frozen
  dispatcher review chains.
- `follow` and `reply` take no mode flag. They inherit the session's recorded
  mode/report and receive only a one-line harness reminder instead of the full
  preamble. They also inherit model, effort, and Fast tier when those flags are
  omitted. Explicit `--model`, `--effort`, or `--fast`/`--no-fast` values apply
  to the new turn and become the values inherited by later turns.

Design and review use the mate contract; worker is participatory implementation;
delegate is full delegation. Canonical mode is recorded in `status.json` and
shown in the `MODE` column.

Omitted start/dispatch settings resolve from the mode in the CLI before the
wire request is built:

| Mode | Model | Effort | Fast | Report | Sandbox |
|---|---|---|---|---|---|
| `design` | `sol` | `high` | off | `text` | `ro` |
| `review` | `sol` | `high` | off | `decision` | `ro` |
| `worker` | `luna` | `xhigh` | on | `decision` | `full` |
| `delegate` | `sol` | `high` | off | `decision` | `full` |

Standard is silent: only deviations need explicit flags, and every explicit
flag wins over its mode default. This table is deliberately code-only operator
policy in `meight.py`; there is no config-file or environment override layer.
The start echo shows every resolved value with `(default)` or `(set)` provenance.
The CLI performs a capability handshake before sending `start`. If the live
daemon does not advertise capability `mode4`, start fails closed. Every
start/follow carries epoch `mode4`; success must atomically echo normalized mode
and epoch or the CLI best-effort interrupts and exits nonzero.

## Supervision Interface

`start` opens a supervised session. `status`, `steer`, `result`, and `reply`
let the dispatcher revisit it without prescribing how often it must do so.

```bash
meight start <name> --mode worker --brief-file - --cwd <dir> <<'EOF'
## Goal       <what this enables + success criteria>
## Decision   <the user decision this phase must close>
## Approval   <approved phase/method/cost envelope; campaign + round number>
## Scope      <file/dir boundary; do not exceed>
## Existing patterns  <file:line pointers; required for good review>
## Constraints <domain rules only; mode/QUESTION/report policy is injected>
## Stop / Escalate <failed gate, cap, or phase-change conditions>
## Verification <commands to run + expected outcome>
## Report     <decision surface; details in a worker-unique evidence artifact>
EOF
```

## Model Selection (GPT-5.6: sol / terra / luna)

Omit `--model` for the mode default above; pass it explicitly only for a
deviation. The short names are real aliases: `sol`, `terra`, and `luna` resolve
to the current ChatGPT-account slugs `gpt-5.6-sol`, `gpt-5.6-terra`, and
`gpt-5.6-luna`. Full or custom model strings pass through unchanged.
Routing principle: **failure cost picks the model.** The default is broad on
purpose: bounded work goes to `luna` at `xhigh`, with `--fast` when the account
and service make Fast available.

| Model | Use for | Typical effort |
|-------|---------|----------------|
| `luna` | Default model for worker-mode implementation, fixes, tests, verification, read-only log digging, browser/runtime QA, computer use, exploration | `xhigh` + `--fast` when available |
| `sol` | Default model for design/review direction and verdict work, plus hard-gated worker-mode implementation | `high`; reserve `xhigh` for genuinely hard problems — the dispatcher judges what qualifies |
| `terra` | No default ownership; capability-specific fallback when measured evidence supports it | task-specific |

`high` is the sol default, not a floor: `high` can overthink, so the dispatcher
may drop to `medium` at its discretion for lighter mate work. One caution from
measurement: `medium` has shown severity over-promotion in adversarial reviews,
so prefer the drop for design thinking and scoping design over verdict-bearing reviews.

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
meight follow <name> --effort xhigh --fast --brief "Continue with more reasoning."
meight reply <name> --effort high --no-fast --brief "Use the approved option."
```

Long-running checkpoint shells are not the default orchestration path. Treat a
stopped background shell as a shell lifecycle event, not a worker failure.

## One-Shot Dispatch

`dispatch` is the blocking one-shot form when the dispatcher does not need a
separately supervised session.

```bash
meight dispatch tiny-1 --mode worker --sandbox ro \
  --brief "Check whether README mentions LICENSE."
```

`dispatch` auto-starts the daemon if needed, starts the worker, waits, and
prints the preferred result (`decision.md` when present, otherwise `result.md`).
Add `--shutdown-when-idle` when the daemon should exit after a terminal result
and no other workers are active.

## Report Modes

Report mode defaults by session mode: design uses `text`; review, worker, and
delegate use `decision`. Explicit `--report` always overrides that default.
Text reports write the final message to `result.md`.

Use `--report decision` for bounded worker or delegate work:

- The SDK turn uses `output_schema`.
- The daemon writes `decision.json` and rendered `decision.md` for each turn.
- `meight result`, `dispatch`, and `reply` prefer `decision.md`.
- `meight result --raw` prints raw `result.md`.
- `result.md` remains the audit record.

The exact schema and field semantics live only in the
[shared contract](../meight-common/CONTRACT.md). `outcome=needs_decision`
routes to `needs_input` / exit `3`, prioritizing the first user-targeted entry.

Recommended pairing: `--mode worker` for bounded implementation. Use
`--mode delegate` only when intentionally
removing the dispatcher from technical context under the delegate contract.

## Structured QUESTION Routing

The exact text and decision-mode question formats live in the
[shared contract](../meight-common/CONTRACT.md). Dispatcher-targeted technical
or missing-information questions can be answered with `reply`; user-owned
scope, UX, priority, risk, irreversible, and acceptance decisions go to the
human.

Classify a question by the effect of answering it, not by the worker's label.
If the answer authorizes a new worker, phase, plan/addendum, review identity
beyond a preauthorized re-review, expensive rerun, materially different method,
or additional repair after the campaign cap, it is user-owned scope, priority,
or acceptance. Do not answer it with `meight reply` even when
`TARGET: dispatcher` or `KIND: technical` was declared.

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

If daemon restart or GC expired the same-thread session, `status` shows
`runtime_lost_detail`. Start a fresh worker instead of replying only when the
same campaign approval is still valid and its worker/repair cap has room.
Otherwise preserve the failure record and return to the user before dispatch.

## Design Doctrine

Use design with a mate for direction-setting forks and genuine uncertainty.

### Blind Design (For Unanchored Input)

Analyze first and keep your own analysis out of the brief. Send only the
problem, constraints, relevant files, and neutral option labels. Ask for the
best-supported design and the strongest case against it, not agreement.

```bash
meight start design-auth --mode design --cwd <repo root> --brief-file - <<'EOF'
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

### Anchored Design (For A Set Direction)

Use anchored design to refine an already-set direction:

```bash
meight start design-refine --mode design --cwd <repo root> \
  --brief "Direction is Option B. Pressure-test it: what am I missing, and what edge cases should the implementation cover?"
```

### Plan Review (Available Pattern)

Plan review is useful when a verdict can still change direction or materially
reduce failure cost. It is not a prerequisite for implementation. The
dispatcher decides whether to use it, records that choice in one line, and may
keep the review thread alive with `reply` while new evidence is still changing
the decision.

Use `--mode review` for a schema-validated decision report by default.
The reviewer leads with `APPROVE` or `REVISE`. The strict decision schema has no
literal APPROVE/REVISE values, so the interface encoding is:

- `APPROVE` => `outcome=done`, `verdict=GO`, summary starting
  `"APPROVE — <plan identity>"`.
- `REVISE` => `outcome=needs_decision`, `verdict=NO-GO`, summary starting
  `"REVISE — <plan identity>"`, with the dispatcher-owned revision decision as
  the only `decisions[]` entry only when the bounded revision round was already
  approved. A new phase, method, cost envelope, or cap extension is user-owned.

In text mode, `REVISE` ends as a dispatcher-targeted structured `QUESTION:`.
Either report mode preserves the thread for `reply`; `APPROVE` is terminal.
Reviewers suppress naming/style preferences, impossible edge cases,
out-of-scope hypotheticals, and findings already resolved by the current plan
or evidence. When the dispatcher freezes an approved versioned `PLAN.md`, scope
change reopens that decision.

### Disagreement Protocol

1. Compare the two designs.
2. Split disagreements into evidence questions vs value judgments.
3. Evidence questions get one targeted verification session.
4. User-owned value judgments (scope, UX, priority, risk appetite,
   irreversible action, acceptance criteria) escalate to the human.
5. Stop when more debate cannot change the decision; prefer a reversible,
   lower-risk option or escalate the user-owned judgment.

Do not run mate-vs-mate debate loops. Do not feed one design into the other
before both exist.

## Learning Loop: Decision Records, Preferences, Lessons

The harness gets better with use only if decisions and answers accumulate
somewhere agents actually read. Three ledgers, all plain files:

### Decision Records (`<repo>/decisions/`)

For a consequential direction-setting fork worth preserving, write
`decisions/YYYY-MM-DD-<slug>.md` in the working repo:

```md
# <the question>
DATE: <date> · FORK: two-design
ANALYSIS A (dispatcher): <one-paragraph position>
DESIGN B (mate, blind|anchored): <one-paragraph position>
DISAGREEMENT: <where they split, or "none">
RESOLUTION: evidence|value-judgment — <what settled it>
DECISION: <what was chosen>
STATUS: adopted
```

This is the durable output of a two-design fork: it survives context compaction,
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

For this operating model, record enough structured data to learn from actual
outcomes: mode, the one-line gate choice, reroutes or escalations and why they
happened, and false approvals found after sign-off. Do not turn measurement
into a mandatory ceremony.

Use baseline evidence before changing escalation rules.

## Mate Review (Available Pattern)

In worker mode, the dispatcher may spawn a separate read-only `--mode review`
session when failure cost warrants it. In delegate mode, the delegate contract
owns its internal fresh-context reviewer. Review is an independent evidence
source, not a fixed implementation stage.

```bash
meight start review-X --mode review --cwd <repo root> --brief-file - <<'EOF'
Adversarial review. Target: <files>. Contract: <versioned PLAN.md>.
Hunt for real defects: correctness, regressions, missing verification,
security/data risk, edge cases, races. For each finding: severity P1/P2/P3,
file:line, why, fix direction. End with GO or NO-GO.
EOF
```

Every review verdict names the exact input reviewed: the `PLAN.md` version
for plan reviews, or a commit hash/diff identity for code reviews. Before acting
on a verdict, the dispatcher compares that identity with the current artifact
and discards the verdict as stale if they no longer match.

The dispatcher arbitrates findings. `NO-GO` means blockers were found. If the
current user-approved phase explicitly includes its one bounded repair round,
route valid blockers to an implementer, verify the correction, and obtain one
verdict on the new review identity. Otherwise stop and ask the user before
repair. A second NO-GO or a new blocker after re-review ends the campaign; do
not create another worker or review identity to reset it. For reviewed work,
sign-off is the review verdict plus verification evidence; reading the entire
diff is never a sign-off gate. A change that alters frozen-plan scope, method,
cost envelope, or acceptance path reopens that decision.

Delegate-mode implementation reports from `luna` must map the approved-plan rationale onto
the existing decision schema:

- `summary`: name the plan version and state every deviation plus rationale;
- `verification`: show the evidence that the implementation satisfies the
  frozen plan;
- `risks`: state what was deliberately not done and why (use an empty list only
  when there truly is nothing to record);
- `changed_files` and `commits`: identify the review surface exactly.

Set the review's severity threshold and scope in its brief. Put detailed logs in
`<worker-name>-evidence.md` when they would overload the decision report.

### Fresh-Eyes UI Review (frontend dispatches)

When a frontend worker reports `IMPLEMENTED, FRESH-EYES PENDING`, dispatch an
independent comprehension reviewer before accepting `VERIFIED`. Protocol and
verbatim reviewer prompt: `~/.codex/skills/frontend-ux-router/references/fresh-eyes-review.md`.

- One-shot `--mode worker` (a comprehension check, not a verdict
  review) with only: the persona line, screenshot paths (or route),
  and the reviewer prompt. Zero implementation context — no brief, no diff,
  no explanations. Contamination invalidates the review.
- FAIL → route the reviewer's raw answers back to the implementer as redesign
  input (path-card recomposition, not copy patches). The dispatcher judges
  whether another fresh-eyes pass can still change the decision.

Use the smallest brief that gives the worker the right contract:

- Goal
- Decision
- Approval and campaign/round
- Scope
- Existing patterns (required; use file:line)
- Constraints
- Stop / Escalate
- Verification
- Report

Do not paste mode, report, and QUESTION policy into every brief; the
harness preamble injects those. Domain rules and task-specific constraints
belong in the brief.

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

### Mode4 Migration And Post-Restart Smoke

Do not restart while any repo namespace has an active or `needs_input` session.
The operator performs this checklist manually:

1. Run `meight list --all-repos --json` and confirm no row is `starting`,
   `running`, or `needs_input`.
2. Run non-force `meight shutdown`. Its daemon-wide active-session guard must
   refuse shutdown if the drain check missed anything; do not use `--force` for
   this migration.
3. Branch on LaunchAgent state. When loaded, use `meight launchd install
   --load` and verify its bounded `bootout --wait` ownership transfer. When not
   loaded, start the daemon normally.
4. Run `meight ping`, confirm `capabilities=mode4`, and verify the new daemon PID
   plus socket identity.
5. Run a throwaway read-only `--mode worker` smoke. Confirm status mode and the
   `meight-worker` plus common preamble paths.
6. Run two throwaway read-only delegate smokes: (a) an intentionally
   non-trivial brief whose evidence records the internal reviewer invocation,
   fresh-context/read-only posture, verdict, round count, and final decision
   surface; (b) a trivial brief that explicitly waives review and records the
   exemption. Confirm both status modes and `meight-delegate` plus common
   preamble paths.
7. Only then dispatch real work. Remove or retain the throwaway disk artifacts
   according to the normal operator policy; no forced cleanup is required.

The implementation worker must document this procedure but must not execute it
against the old daemon during the mode4 rollout.

Useful checks:

```bash
MEIGHT_HOME="${MEIGHT_HOME:-$HOME/.meight}" meight ping
ps eww -axo pid,ppid,command | rg 'meight.py daemon|MEIGHT_IDLE_TIMEOUT_SEC|XPC_SERVICE_NAME=com.keepitmello.meight'
launchctl print "gui/$(id -u)/com.keepitmello.meight"  # if LaunchAgent is installed
meight list --all-repos --json
```

`meight ping` also exposes `session_retention_sec`. Worker names are restricted
at both CLI and daemon boundaries to 1-128 ASCII letters/digits/`._-`, starting
with a letter or digit. The daemon independently derives/verifies repo state,
uses owner-only state directories plus a `0600` socket, rejects worker-state
symlinks, and bounds one socket request to 1 MiB. It intentionally does not set
a process-wide umask because that would change repository file modes created by
Codex workers.

When the LaunchAgent is loaded, on-demand start uses `launchctl kickstart`
without `-k`; direct detached start is only the unloaded-job fallback.
`meight launchd install --load` owns the safe transfer: it requests non-force
drain, refuses active sessions, waits boundedly for the acknowledged old
PID/socket to disappear, runs `launchctl bootout --wait` with a subprocess
timeout for a loaded job, bootstraps the new
plist, and requires a fresh ping/PID plus socket identity with a PID matching
launchd's running job. Ambiguous
`launchctl` ownership or an unhealthy owner that still holds the singleton
lock fails closed. Published socket deletion/replacement makes the daemon exit
nonzero for launchd recovery. Do not manually bootout before drain.

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
- LaunchAgent supervision is crash-only (`RunAtLoad=true`,
  `KeepAlive={SuccessfulExit=false}`): unexpected accept failure exits nonzero
  and restarts; acknowledged clean shutdown exits zero and stays stopped.
- Terminal workers release their SDK runtime immediately after stream end.
  `MEIGHT_WORKER_GC_TTL_SEC` (default 3600s) only removes terminal worker
  status from daemon memory. Disk artifacts use
  `MEIGHT_SESSION_RETENTION_SEC` (default 30 days; `0` disables). Off-loop
  hourly cleanup prunes only valid expired terminal rows using immutable
  `terminal_at` (legacy fallback `updated_at`), atomically tombstones under the
  registry lock, and deletes outside it. Recovery never trusts the tombstone
  prefix alone; it rechecks terminal state, expiry, and registry ownership.
  Active/replyable, malformed, symlinked, or registered sessions are skipped. Startup converts orphaned
  active rows to `failed`/`runtime_lost_detail`; hidden turns are not resumed.
- Beta SDK (`openai-codex==0.1.0b3`, pinned): re-run the SPEC.md verification
  suite when upgrading.
- Source and docs: README.md, SPEC.md, ARCHITECTURE.md.
