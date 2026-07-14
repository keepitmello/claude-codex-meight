# claude-codex-meight

<p align="center">
  <img src="./docs/hero.jpg" alt="Claude Fable 5 + Codex" width="720">
</p>

**English** | [한국어](./docs/README.ko.md)

> **A two-way harness for orchestrating Codex mates and workers.** Meight is built for an
> LLM agent that delegates, consults, steers, reviews, and signs off with
> evidence. It runs on the official `openai-codex` Python SDK. CLI: `meight`.

Most bridges are built for a human watching a terminal: tmux panes, dashboards,
stdout scraping. Meight is built for agents. A dispatcher can start hidden Codex
sessions, read compact disk digests, steer a live turn, answer structured
questions, and keep final reports small enough to make user-facing decisions.

- **Explicit roles.** `--role mate` selects the independent consult/review
  contract; `--role worker` selects bounded implementation/verification. Role
  and model are independent, and there is no default.
- **Explicit modes.** `start` and `dispatch` require `--mode collab|delegate`.
  No default. The consumer is an LLM agent, so policy is harness-enforced rather
  than remembered.
- **Supervised by default.** `start` + `wait` keeps `status` and `steer`
  available. `dispatch` remains for trivial, short, low-risk work.
- **Structured questions.** A worker can end with `QUESTION:` plus
  `TARGET: dispatcher|user` and a `KIND`, so a middle-layer agent knows whether
  to answer or escalate.
- **Decision reports.** `--report decision` writes `decision.json` and rendered
  `decision.md`; raw `result.md` stays as the audit record. This keeps technical
  context contained.
- **Blind consults for forks.** Direction-setting decisions use an independent
  read-only consult with problem and constraints only, before debate or
  implementation.
- **Plan review before implementation.** After direction is set, a bounded
  `--role mate --model sol` loop approves and freezes versioned `PLAN.md`; `REVISE` stays on
  the same thread through a dispatcher-targeted question.
- **Worker/luna implements, mate/sol reviews.** `worker/luna xhigh` plus Fast
  when available is the default for bounded work. Failure-cost hard gates route
  critical implementation to `worker/sol`; `terra` has no default ownership.
- **It gets better with use.** Direction decisions, user preferences, and
  operational lessons persist as plain files the dispatcher reads before
  acting. Repeat questions stop reaching the human; settled directions stay
  settled.

```text
   dispatcher agent   <->   Codex mate(s) / worker(s)
   (what and why)           (challenge / implement)
        |                       ^
        |-- start + brief ------|
        |
        |<- QUESTION / decision report / result
        |-- reply / steer / consult / review
        |
        v
   global daemon -- official openai-codex SDK -- per-worker codex app-server
        status.json · events.log · result.md · decision.json · decision.md
```

## Why This Exists

The official `openai-codex` Python SDK talks to `codex app-server` directly and
exposes steering, interrupting, streaming, output schemas, and thread control as
APIs. Meight uses one SDK runtime per active worker, then releases it when the
worker finishes so MCP subprocesses and file descriptors do not linger.

Compared with tmux/exec wrappers:

| | tmux/exec bridges | MCP wrappers | **Meight** |
|---|---|---|---|
| Parallel workers | 1 process per worker | blocking tool calls | one SDK runtime per active worker |
| Mid-turn steering | attach/type or kill+resume | no | `meight steer` |
| Progress observation | scrape stdout | no | disk digest, pull on demand |
| Two-way conversation | no | no | structured `QUESTION:` -> exit 3 -> `reply` |
| Result delivery | scrape | tool return | exit-code contract + result files |
| Machine-readable reports | no | wrapper-specific | `--report decision` via `output_schema` |

And because every judgment lands on disk — digests, decisions, preferences,
lessons — the pairing gets more personal over time: the dispatcher learns
which questions its human wants to see, and which ones it is trusted to
answer itself.

## Quick Start

Requirements: [Codex CLI](https://developers.openai.com/codex) installed and
authenticated, Python >= 3.10.

```bash
git clone https://github.com/keepitmello/claude-codex-meight
cd claude-codex-meight
./install.sh   # creates .venv + ~/.local/bin/meight
```

For real work, use supervised dispatch from any git repo. Meight uses one global
daemon by default (`$MEIGHT_HOME`, `$XDG_STATE_HOME/meight`, or `~/.meight`)
while isolating worker state per repo under `repos/<repo-key>/`.

```bash
meight start impl-1 --role worker --mode delegate --report decision --model luna --effort xhigh --fast \
  --brief-file - --cwd ~/my-repo <<'EOF'
Implement X in src/foo.py. Existing pattern: see src/bar.py:42.
Verify with: pytest tests/test_foo.py.
Report changed files, verification, remaining P1s, risks, and evidence artifact.
EOF

meight wait impl-1 --timeout 300
# exit 0=completed · 2=failed/interrupted/runtime-lost · 3=replyable question · 4=daemon dead · 1=checkpoint timeout
```

On exit `1`, the worker is still running. Inspect once, then wait again or
steer:

```bash
meight status impl-1
meight steer impl-1 "Stop refactoring the helper; only fix the bug."
meight wait impl-1 --timeout 300
```

On terminal exits, read the preferred report. Use `--raw` only when you need the
audit message:

```bash
meight result impl-1
meight result impl-1 --raw
```

The worker asked a replyable question (exit `3`)? The same target/kind is also
visible in `status.json` and `meight status`.

```bash
meight reply impl-1 --brief "Use config-a.json and keep the legacy field."
```

For trivial, short, low-risk tasks, one-shot dispatch is available:

```bash
meight dispatch tiny-1 --role worker --mode delegate --report decision --sandbox ro \
  --brief "Check whether README mentions LICENSE."
```

Computer Use app-access is enabled by default for each meight worker session.
Other MCP approvals remain unchanged.

```bash
meight dispatch desktop-qa --role worker --mode delegate --sandbox ro --model luna --effort xhigh --fast \
  --brief "Use Computer Use to inspect Calculator. Do not change its state."
```

## Operating Model

| Role / model | Default ownership | Effort |
|---|---|---|
| `worker` / `luna` | Bounded implementation, fixes, tests, verification, read-only log digging, browser/runtime QA, computer use, exploration | `xhigh`, plus `--fast` when available |
| `mate` / `sol` | Direction, plan review, adversarial review | `high` or `xhigh` |
| `worker` / `sol` | Hard-gated implementation | `xhigh` |
| either / `terra` | Capability-specific fallback only; re-promotable on measured evidence | task-specific |

Failure cost is the routing gate. Use `sol` when acceptance-critical behavior
materially depends on concurrency, security, public schema/API contract design,
persistent-data migration, or cross-cutting refactoring, or when failure can
cause money/data damage, irreversible harm, or high-impact production damage.
General endpoint implementation and read-only production log investigation stay
with `luna`; API contract design/evolution and production mutation/remediation
do not. Money paths still require dispatcher sign-off.

The implementation chain is `worker/luna` → `mate/sol` adversarial review
(maximum two rounds) → dispatcher full-diff read against frozen `PLAN.md` and repository
context → direct fixes and final sign-off. A scope-changing fix reopens plan
approval; a P1-fix-level correction does not. Harness/core surgery routes to
`sol` and adds a Claude context-holding review at plan and final-diff stages.

## Consults

Direction-setting forks use blind consult by default: write your own analysis
first, keep it out of the brief, and ask a read-only mate for the
best-supported design and the strongest case against it.

```bash
meight start consult-auth --role mate --mode collab --sandbox ro --model sol --effort high --cwd ~/my-repo --brief-file - <<'EOF'
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

Anchored consults are still valid after direction is already set:

```bash
meight start consult-refine --role mate --mode collab --sandbox ro --model sol --brief \
  "Direction is Option B. Pressure-test it: what am I missing?"
```

Once direction is set, plan review is a separate bounded anchored loop:

1. The dispatcher authors the plan; `mate/sol high|xhigh` reviews it.
2. The reviewer leads with `APPROVE` or `REVISE`. `REVISE` keeps the thread
   alive for `reply` (text mode: a dispatcher-targeted structured `QUESTION:`;
   decision mode: the exact schema encoding in `skills/meight/SKILL.md`);
   `APPROVE` is terminal.
3. Run at most three rounds, recording `new-risks` and `resolved-risks`
   separately each round.
4. After an unapproved third round, choose residual-risk sign-off, a targeted
   evidence read, or user escalation. Do not auto-reenter.
5. Freeze approval as versioned `PLAN.md`; scope changes reopen approval.

When reads disagree, split evidence questions from value judgments. Evidence
gets one targeted verification session. User-owned value judgments (scope, UX,
priority, risk appetite, irreversible action, acceptance criteria) go to the
human. Stop after at most two rounds; choose the reversible/lower-risk path or
escalate.

## The Harness Learns

Three plain-file ledgers make the dispatch loop improve with use:

- **Decision records** (`<repo>/decisions/`). Every direction-setting fork
  resolved by two independent reads leaves a record: both positions, where
  they split, and what settled it. Later sessions audit the *why*; settled
  questions stay settled.
- **Preference ledger** (`<daemon-home>/notes/preferences.md`). When the human
  answers a `TARGET: user` question, the answer is recorded. The dispatcher
  checks the ledger before escalating, so each class of question reaches the
  human once — only irreversible and risk calls are always re-confirmed.
- **Lessons** (`<daemon-home>/notes/lessons.md`). Recurring review findings
  and operational mistakes become one-line lessons, promoted into brief
  templates when they repeat. Every run record includes its `mate|worker`
  role. The v3 baseline also records plan rounds and
  revise causes, reroutes divided by `luna` starts (ordinary questions tracked
  separately), `luna→sol|terra` plus the hard-gate clause, and false approvals
  within the same release window or a repo-defined fixed time fallback.

None of this is a new subsystem — just files plus doctrine, defined in
[`skills/meight/SKILL.md`](./skills/meight/SKILL.md#learning-loop-decision-records-preferences-lessons).
Judgments persist on disk rather than in model memory, so the personalization
survives context compaction, fresh sessions, and even model swaps.

## Using It From Claude Code Or Codex

For real work, run `wait --timeout` as the background shell call. The agent wakes
at completion, question, failure, daemon death, or checkpoint timeout.

```text
Bash(command: "meight start review-1 --role mate --mode delegate --report decision --sandbox ro --model sol --effort high --brief-file - <<'EOF' ... EOF")
Bash(command: "meight wait review-1 --timeout 300", run_in_background: true)
-> checkpoint exit 1
-> meight status review-1
-> healthy: wait again · drifting: meight steer review-1 "..."
```

A drop-in Claude orchestrator prompt ships as [`CLAUDE.md`](./CLAUDE.md). A
Codex-as-orchestrator prompt ships as [`AGENTS.md`](./AGENTS.md). The full
dispatcher-facing skill is [`skills/meight/`](./skills/meight/SKILL.md). The
role contracts are [`skills/meight-mate/`](./skills/meight-mate/SKILL.md) and
[`skills/meight-worker/`](./skills/meight-worker/SKILL.md), with their shared
protocol in [`skills/meight-common/`](./skills/meight-common/CONTRACT.md).

## What "Easy For An Agent" Means

- **Exit codes are the API.** `0` done, `2` failed/interrupted/runtime-lost, `3`
  question, `4` daemon gone, `1` checkpoint timeout.
- **Names, not session IDs.** Workers are addressed as `review-1`, including
  follow-ups.
- **Sparse checkpoints, not busy polling.** `wait --timeout` is a wake-up dial;
  it does not kill the worker.
- **Status is pre-digested.** `status` returns role, mode, report type, current item,
  changed files, needs-input target/kind, and last-message tail.
- **Policy cannot be forgotten.** Role, mode, role-skill loading, the shared
  contract, and report shape are injected by the harness.
- **Results survive on disk.** `result.md` remains the raw audit record;
  decision reports add `decision.json` and `decision.md`.
- **Briefs go through stdin.** Multi-line briefs avoid shell quoting traps.

## Command Reference

| Command | What it does |
|---|---|
| `meight start <name> --role mate\|worker --mode collab\|delegate [opts]` | Start a session and return immediately with the thread id. Supervised workflow entry point. |
| `meight wait <name> --timeout SEC` | Checkpoint wait: return on terminal state, replyable QUESTION, daemon death, or timeout. Timeout leaves the worker running. |
| `meight dispatch <name> --role mate\|worker --mode collab\|delegate [opts]` | One-shot: auto-start daemon -> capability check -> start -> wait -> print preferred result. Use only for trivial, short, low-risk work. |
| `meight reply <name> --brief ...` | One-shot answer to a replyable question; inherits role/mode/report and prints the latest result. |
| `meight follow <name> --brief ...` | Low-level: new turn on the same live thread; inherits role/mode/report. |
| `meight result <name> [--raw]` | Print `decision.md` when present; `--raw` prints raw `result.md`. |
| `meight status [name] [--json] [--all-repos]` | Pull digest. Table includes `ROLE` and `MODE`; legacy rows show `-` for role. Reads disk. |
| `meight steer <name> "text"` | Inject instruction into the running turn. |
| `meight interrupt <name>` | Cancel the turn. An interrupt that arrives while a worker is still starting — or while a reply turn is being opened — is recorded, and aborts the turn the moment it would commit. |
| `meight list / daemon / ping / shutdown / launchd` | Low-level support commands. |

Common options:

- `--role mate|worker` is required on `start` and `dispatch`; there is no
  default. `mate` is for consult/review, `worker` for implementation/verification.
- `--mode collab|delegate` is required on `start` and `dispatch`
  (`collaborative`/`delegated` aliases accepted).
- `--report text|decision` defaults to `text`; `decision` writes
  `decision.json`/`decision.md`.
- `--cwd` sets the worker workdir. Use separate git worktrees for overlapping
  file scopes.
- `--sandbox ws|ro|full` defaults to `full`; reviews and consults usually use
  `ro`.
- `--model luna|sol|terra` accepts the short aliases; full model strings pass
  through unchanged.
- `--effort low|medium|high|xhigh` defaults to `medium`.
- `--fast` opts a specific worker into priority service tier; omitted or
  `--no-fast` stays non-Fast.
- `--main-thread` opts out of hidden ephemeral subagent threads for tools that
  need a visible main thread.

Worker state lives in
`<daemon-home>/repos/<repo-key>/workers/<name>/`: `brief.md`, `status.json`,
`events.log`, `result.md`, and, in decision mode, `decision.json` and
`decision.md`. Terminal workers keep disk artifacts but release their SDK
runtime immediately. A final structured `QUESTION:` remains attached to the live
daemon so `reply` can answer on the same thread. After daemon restart, disk
artifacts remain but same-thread reply is expired; start a fresh worker.

## Upgrading An Old Daemon To Role Support

The new CLI fails closed before `start` when `meight ping` does not advertise
`capabilities=role`. Drain and restart manually:

1. Inspect `meight list --all-repos --json`; wait until no session across any
   repo is `starting`, `running`, or `needs_input`.
2. Run non-force `meight shutdown`. If it refuses, finish draining; do not use
   `--force` for this migration.
3. Start the daemon normally and confirm `meight ping` shows
   `capabilities=role`.
4. Start a throwaway read-only `--role mate --mode delegate` session. Confirm
   status records `role=mate` and its saved preamble references both
   `skills/meight-mate/SKILL.md` and `skills/meight-common/CONTRACT.md`.
5. Resume real dispatches only after that smoke passes.

## Good To Know

- Meight inherits your `~/.codex/config.toml` for model, MCP servers, and auth.
  If `codex` works in your terminal, `meight` works.
- Meight uses the current system `codex` executable rather than the SDK's
  bundled runtime. Set `MEIGHT_CODEX_BIN` only when an explicit executable
  override is needed.
- Workers start as hidden ephemeral Codex subagent threads by default:
  `thread_source=subagent`, `thread_ephemeral=true`.
- Foreground `meight daemon` exits after `MEIGHT_IDLE_TIMEOUT_SEC` seconds with
  no active workers by default. Managed `dispatch` auto-start and LaunchAgent
  starts disable idle shutdown; verify the live value with `meight ping`.
- `openai-codex` is pinned (`0.1.0b3`, beta). When bumping the SDK or Codex CLI, re-run the
  verification suite in [`SPEC.md`](./SPEC.md).
- Design details, state machine, hardening history, and lifecycle caveats live
  in [`ARCHITECTURE.md`](./ARCHITECTURE.md). Full dispatcher protocol lives in
  [`skills/meight/SKILL.md`](./skills/meight/SKILL.md).

## License

MIT
