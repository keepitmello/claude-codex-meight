# claude-codex-meight

<p align="center">
  <img src="./docs/hero.jpg" alt="Claude Fable 5 + Codex" width="720">
</p>

**English** | [한국어](./docs/README.ko.md)

> **A two-way harness where Codex mates challenge your plans and Codex workers
> build them.** Meight is built for an LLM agent that designs collaboratively, delegates,
> steers, reviews, and signs off with evidence. Official `openai-codex` Python
> SDK underneath. CLI: `meight`.

Most bridges are built for a human watching a terminal: tmux panes, dashboards,
stdout scraping. Meight is built for the agent itself — a dispatcher that
starts hidden Codex sessions, reads compact disk digests, steers a live turn,
answers structured questions, and keeps final reports small enough to make
user-facing decisions without drowning in implementation detail.

The core idea is that a frontier model wasted as a silent executor is capability
left on the table. So meight offers two Codex session contracts:

- A **mate** (`--mode design` or `--mode review`) is an independent challenger.
  It reviews plans with a real verdict, hunts defects adversarially, and joins blind design —
  its contract says *challenge the dispatcher, agreement is not the goal*.
- A **worker** (`--mode delegate`) is a bounded implementer. It owns the
  technical loop — code, tests, verification, runtime QA — and reports a
  decision surface, escalating real ambiguity instead of guessing.

Mate and worker name the session's contract, not the model; the mode picks the
contract, and `--model` picks the brain. The dispatcher keeps direction,
arbitration, integration, and final sign-off; nothing merges on a mate's or
worker's word alone.

```text
   dispatcher agent   <->   Codex mate(s) / worker(s)
   (what and why)           (challenge / implement)
        |                       ^
        |-- start + brief ------|
        |
        |<- QUESTION / decision report / result
        |-- reply / steer / design / review
        |
        v
   global daemon -- official openai-codex SDK -- per-worker codex app-server
        status.json · events.log · result.md · decision.json · decision.md
```

## The Pipeline

Meight ships an opinionated development loop, refined by running it on itself.
Every stage is doctrine (files the harness injects), not framework code:

1. **Blind design for direction forks.** Before a direction-setting decision,
   a read-only mate gets the problem and constraints only — no dispatcher lean
   to anchor on — and returns the best-supported design plus the strongest case
   against it.
2. **Plan-review loop.** Once direction is set, the dispatcher authors a plan
   and a `mate/sol` reviews it: verdict-first `APPROVE`/`REVISE`, at most three
   rounds, incremental re-review of prior findings, noise suppression (no style
   nits, no impossible edge cases). `REVISE` keeps the same thread alive through
   a structured question, so revisions stay in one conversation. Approval
   freezes the plan as versioned `PLAN.md` — the review contract everything
   downstream is judged against.
3. **Workers implement.** `worker/luna` at `xhigh` (plus `--fast` when
   available) is the cheap, capable default for bounded work. A failure-cost
   hard gate routes acceptance-critical work — concurrency, security, public
   API contract design, data migration, cross-cutting refactors, anything that
   can corrupt money/data or cause irreversible harm — to `worker/sol` instead.
   Implementation reports must state plan deviations, rationale, and what was
   deliberately not done.
4. **Review chain.** `mate/sol` adversarial review against the frozen plan
   (maximum two rounds, runtime cross-checked, verdicts name exactly what they
   reviewed so stale verdicts get discarded) → the dispatcher reads the full
   diff with plan and repo context, fixes valid defects directly, and owns the
   final sign-off.

**Gates scale with the work.** The full chain is the default for plan-governed
work, but the dispatcher may skip or shrink gates for small, low-risk,
reversible tasks — never silently: the user is told which gate was skipped and
why, or asked first when it is borderline. Failure-cost hard gates and
money-path sign-off are never skippable, and skips are recorded as metrics.

Effort follows the same economics: `luna` runs `xhigh` because it is cheap,
`sol` defaults to `high` (it can overthink; the dispatcher may drop light mate
work to `medium`) and reserves `xhigh` for genuinely hard problems — the
dispatcher judges what qualifies.

## Why This Exists

The official `openai-codex` Python SDK talks to `codex app-server` directly and
exposes steering, interrupting, streaming, output schemas, and thread control as
APIs. Meight uses one SDK runtime per active worker, then releases it when the
worker finishes so MCP subprocesses and file descriptors do not linger.

Compared with tmux/exec wrappers:

| | tmux/exec bridges | MCP wrappers | **Meight** |
|---|---|---|---|
| Parallel sessions | 1 process per worker | blocking tool calls | one SDK runtime per active worker |
| Mid-turn steering | attach/type or kill+resume | no | `meight steer` |
| Progress observation | scrape stdout | no | disk digest, pull on demand |
| Two-way conversation | no | no | structured `QUESTION:` -> exit 3 -> `reply` |
| Result delivery | scrape | tool return | exit-code contract + result files |
| Machine-readable reports | no | wrapper-specific | `--report decision` via `output_schema` |
| Session contracts | no | no | `--mode design\|review\|delegate`, harness-injected |

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
meight start impl-1 --mode delegate --report decision --model luna --effort xhigh --fast \
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

Blind design goes to a mate instead — read-only and collaborative:

```bash
meight start design-auth --mode design --sandbox ro --model sol --effort high \
  --cwd ~/my-repo --brief-file - <<'EOF'
We need to choose an auth-token refresh design.

Constraints:
- No user-visible logout regression.
- Existing token storage is in src/auth/store.ts.

Options:
- Option A: refresh before each protected request when expiry is near.
- Option B: centralize refresh in the API client on 401.

Give the best-supported design, the strongest case against it, and the evidence
that would settle remaining uncertainty. No code changes.
EOF
```

For trivial, short, low-risk tasks, one-shot dispatch is available:

```bash
meight dispatch tiny-1 --mode delegate --report decision --sandbox ro \
  --brief "Check whether README mentions LICENSE."
```

Computer Use app-access is enabled by default for each meight session. Other
MCP approvals remain unchanged.

## Structured Questions

Sessions do not guess and do not silently comply. When blocked — or when they
see a better direction — they end the turn with a structured question the
daemon promotes to exit `3`:

```text
QUESTION:
TARGET: dispatcher | user
KIND: scope | ux | priority | risk | irreversible | acceptance | missing-info | better-direction | technical
<question + options + recommendation>
```

`TARGET` says who must decide; `KIND` says why. A middle-layer agent answers
dispatcher-owned questions with `meight reply` and escalates user-owned ones
(scope, UX, risk appetite, irreversible actions) verbatim. In decision-report
mode the same routing runs through `outcome=needs_decision` in the schema.

## The Harness Learns

Three plain-file ledgers make the dispatch loop improve with use:

- **Decision records** (`<repo>/decisions/`). Every direction-setting fork
  resolved by two independent designs leaves a record: both positions, where
  they split, and what settled it. Later sessions audit the *why*; settled
  questions stay settled.
- **Preference ledger** (`<daemon-home>/notes/preferences.md`). When the human
  answers a `TARGET: user` question, the answer is recorded. The dispatcher
  checks the ledger before escalating, so each class of question reaches the
  human once — only irreversible and risk calls are always re-confirmed.
- **Lessons** (`<daemon-home>/notes/lessons.md`). Recurring review findings
  and operational mistakes become one-line lessons, promoted into brief
  templates when they repeat. Per-run records carry the mode, plan-review
  rounds and revise causes, escalation rates and which hard-gate clause fired,
  gate skips, and post-sign-off defects — the baseline that tunes the routing
  gates empirically instead of by vibe.

None of this is a new subsystem — just files plus doctrine, defined in
[`skills/meight/SKILL.md`](./skills/meight/SKILL.md#learning-loop-decision-records-preferences-lessons).
Judgments persist on disk rather than in model memory, so the personalization
survives context compaction, fresh sessions, and even model swaps.

## Using It From Claude Code Or Codex

For real work, run `wait --timeout` as the background shell call. The agent
wakes at completion, question, failure, daemon death, or checkpoint timeout.

```text
Bash(command: "meight start review-1 --mode review --report decision --sandbox ro --model sol --effort high --brief-file - <<'EOF' ... EOF")
Bash(command: "meight wait review-1 --timeout 300", run_in_background: true)
-> checkpoint exit 1
-> meight status review-1
-> healthy: wait again · drifting: meight steer review-1 "..."
```

A drop-in Claude orchestrator prompt ships as [`CLAUDE.md`](./CLAUDE.md). A
Codex-as-orchestrator prompt ships as [`AGENTS.md`](./AGENTS.md). The full
dispatcher-facing skill is [`skills/meight/`](./skills/meight/SKILL.md). The
session contracts are [`skills/meight-mate/`](./skills/meight-mate/SKILL.md) and
[`skills/meight-worker/`](./skills/meight-worker/SKILL.md), with their shared
protocol in [`skills/meight-common/`](./skills/meight-common/CONTRACT.md).

The default dispatcher is a Claude Code session. A Codex app/CLI session can
dispatch through the same protocol via a thin `~/.codex/skills/meight` binding
that points at [`skills/meight/SKILL.md`](./skills/meight/SKILL.md) — one
protocol, two dispatcher runtimes.

## What "Easy For An Agent" Means

- **Exit codes are the API.** `0` done, `2` failed/interrupted/runtime-lost, `3`
  question, `4` daemon gone, `1` checkpoint timeout.
- **Names, not session IDs.** Sessions are addressed as `review-1`, including
  follow-ups.
- **Sparse checkpoints, not busy polling.** `wait --timeout` is a wake-up dial;
  it does not kill the worker.
- **Status is pre-digested.** `status` returns mode, report type, current
  item, changed files, needs-input target/kind, and last-message tail.
- **Policy cannot be forgotten.** Mode, mode-skill loading, the shared
  contract, and report shape are injected by the harness — `--mode` is a
  required flag with a teaching error, validated at the daemon
  boundary too, so a stale CLI or a raw socket client gets the same contract.
- **Results survive on disk.** `result.md` remains the raw audit record;
  decision reports add `decision.json` and `decision.md`.
- **Briefs go through stdin.** Multi-line briefs avoid shell quoting traps.

## Command Reference

| Command | What it does |
|---|---|
| `meight start <name> --mode design\|review\|delegate [opts]` | Start a session and return immediately with the thread id. Supervised workflow entry point. |
| `meight wait <name> --timeout SEC` | Checkpoint wait: return on terminal state, replyable QUESTION, daemon death, or timeout. Timeout leaves the worker running. |
| `meight dispatch <name> --mode design\|review\|delegate [opts]` | One-shot: auto-start daemon -> capability check -> start -> wait -> print preferred result. Use only for trivial, short, low-risk work. |
| `meight reply <name> --brief ...` | One-shot answer to a replyable question; inherits mode/report and prints the latest result. |
| `meight follow <name> --brief ...` | Low-level: new turn on the same live thread; inherits mode/report. |
| `meight result <name> [--raw]` | Print `decision.md` when present; `--raw` prints raw `result.md`. |
| `meight status [name] [--json] [--all-repos]` | Pull digest. Table includes `MODE`; legacy rows with old role or long-form mode values remain readable. Reads disk. |
| `meight steer <name> "text"` | Inject instruction into the running turn. |
| `meight interrupt <name>` | Cancel the turn. An interrupt that arrives while a worker is still starting — or while a reply turn is being opened — is recorded, and aborts the turn the moment it would commit. |
| `meight list / daemon / ping / shutdown / launchd` | Low-level support commands. |

Common options:

- `--mode design|review|delegate` is required on `start` and `dispatch`.
  `collab`, `collaborative`, and `delegated` are accepted aliases. Design and
  review are the two collaborative modes (mate contract); delegate is the
  delegation mode (worker contract). Design is for blind/anchored design,
  review for verdict-first plan/diff review, and delegate for implementation.
- `--report text|decision` defaults to `text`; `decision` writes
  `decision.json`/`decision.md`.
- `--cwd` sets the worker workdir. Use separate git worktrees for overlapping
  file scopes.
- `--sandbox ws|ro|full` defaults to `full`; reads and reviews usually use
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

## Upgrading An Old Daemon To Mode3 Support

The new CLI fails closed before `start` when `meight ping` does not advertise
`capabilities=mode3` — and it verifies the normalized mode echo in start and
follow responses, so even a daemon swapped mid-handshake cannot silently use
the wrong contract. Drain and restart manually:

1. Inspect `meight list --all-repos --json`; wait until no session across any
   repo is `starting`, `running`, or `needs_input`.
2. Run non-force `meight shutdown`. If it refuses, finish draining; do not use
   `--force` for this migration.
3. Start the daemon normally and confirm `meight ping` shows
   `capabilities=mode3`.
4. Start a throwaway read-only `--mode review` session. Confirm status records
   `mode=review` and its saved preamble references both
   `skills/meight-mate/SKILL.md` and `skills/meight-common/CONTRACT.md`.
5. Resume real dispatches only after that smoke passes.

## Good To Know

- Meight inherits your `~/.codex/config.toml` for model, MCP servers, and auth.
  If `codex` works in your terminal, `meight` works.
- Meight uses the current system `codex` executable rather than the SDK's
  bundled runtime. Set `MEIGHT_CODEX_BIN` only when an explicit executable
  override is needed.
- Sessions start as hidden ephemeral Codex subagent threads by default:
  `thread_source=subagent`, `thread_ephemeral=true`.
- Foreground `meight daemon` exits after `MEIGHT_IDLE_TIMEOUT_SEC` seconds with
  no active workers by default. Managed `dispatch` auto-start and LaunchAgent
  starts disable idle shutdown; verify the live value with `meight ping`.
- `openai-codex` is pinned (`0.1.0b3`, beta). When bumping the SDK or Codex
  CLI, re-run the verification suite in [`SPEC.md`](./SPEC.md).
- Design details, state machine, hardening history, and lifecycle caveats live
  in [`ARCHITECTURE.md`](./ARCHITECTURE.md). Full dispatcher protocol lives in
  [`skills/meight/SKILL.md`](./skills/meight/SKILL.md). Why the pipeline looks
  like this — including the day it was designed by running itself — is in
  [`docs/2026-07-14-v3-pipeline-retrospective.md`](./docs/2026-07-14-v3-pipeline-retrospective.md).

## License

MIT
