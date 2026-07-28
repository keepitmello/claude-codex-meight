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
left on the table. So meight exposes two postures — two Codex session
contracts:

- A **mate** (`--mode mate`) is an independent thinking partner. It joins
  blind/anchored design, diagnoses, reviews plans with a real verdict, and
  hunts defects adversarially — its contract says *challenge the dispatcher,
  agreement is not the goal*. The brief selects which protocol applies.
- A **worker** (`--mode worker`) is a team implementer. It owns code, tests,
  verification, and self-review, surfaces observations and better directions
  instead of executing silently, and escalates dispatcher-sign-off gates
  (security-sensitive, public API contracts, data migration, money paths,
  frozen review chains) before acting. The dispatcher decides whether to run a
  separate external review.

Mate and worker name the session contract, not the model; the mode picks the
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

## Judgment Before Process

Meight provides two session postures, not a mandatory development pipeline.
Avoiding overengineering comes first: the dispatcher chooses only the design,
review, implementation, and verification gates justified by the task's failure
cost, then records that choice in one line.

Blind or anchored design can clarify a real direction fork. Plan review and
adversarial code review are available verdict tools, not default stages. The
worker self-reviews by contract (spawning an internal fresh-context reviewer
when warranted), and the dispatcher spawns a separate external review session
when failure cost justifies it. A worker's `done` is still only a claim. For reviewed work, sign-off combines the review
verdict with verification evidence; unreviewed work still requires verification
evidence. Reading the entire diff is never a sign-off gate.

The included operator-policy template routes bounded work to `luna` and gates on
failure cost: raise the brain when failure can damage money or data, cannot be
undone, or spreads across production. When
work is hard, the template adds a stage instead of a bigger worker — a `sol`
mate plan handed to a `luna` worker — and reserves `sol` in worker mode for
implementation that stays hard with a plan in hand. Those model and money-path gates
are explicitly adjustable operator policy, not meight interface requirements.

Effort follows the same economics: `luna` runs `xhigh` because it is cheap,
`sol` defaults to `medium` for mate work (raise to `high` for verdict-bearing
review) and stops at `high`, which is reserved for genuinely hard problems —
the dispatcher judges what qualifies, and `sol high` takes one user
confirmation before launch because it is the costliest combination.

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
| Session contracts | no | no | `--mode mate\|worker`, harness-injected |

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
meight start impl-1 --mode worker \
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

Blind design goes to a mate instead — advisory and collaborative:

```bash
meight start design-auth --mode mate \
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

One-shot dispatch is available when a separately supervised session adds no
value:

```bash
meight dispatch tiny-1 --mode worker --sandbox ro \
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
Routing is impact-based: an answer that starts a new worker, phase,
plan/addendum, review identity beyond a preauthorized re-review, expensive
rerun, materially different method, or additional repair after the campaign
cap is user-owned even when labeled `technical`. Worker names and fresh review
identities do not reset the cap.

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
  templates when they repeat. Per-run records can carry the mode, one-line gate
  choice, reroute reason, and post-sign-off defects — enough to tune routing
  from outcomes without turning measurement into ceremony.

None of this is a new subsystem — just files plus doctrine, defined in
[`skills/meight/SKILL.md`](./skills/meight/SKILL.md#learning-loop-decision-records-preferences-lessons).
Judgments persist on disk rather than in model memory, so the personalization
survives context compaction, fresh sessions, and even model swaps.

## Using It From Claude Code Or Codex

For real work, run `wait --timeout` as the background shell call. The agent
wakes at completion, question, failure, daemon death, or checkpoint timeout.

```text
Bash(command: "meight start review-1 --mode mate --report decision --brief-file - <<'EOF' ... EOF")
Bash(command: "meight wait review-1 --timeout 300", run_in_background: true)
-> checkpoint exit 1
-> meight status review-1
-> healthy: wait again · drifting: meight steer review-1 "..."
```

A drop-in Claude orchestrator prompt ships as [`CLAUDE.md`](./CLAUDE.md). A
Codex-as-orchestrator prompt ships as [`AGENTS.md`](./AGENTS.md). The full
dispatcher-facing skill is [`skills/meight/`](./skills/meight/SKILL.md). The
session contracts are [`skills/meight-mate/`](./skills/meight-mate/SKILL.md)
and [`skills/meight-worker/`](./skills/meight-worker/SKILL.md), with their
shared protocol in
[`skills/meight-common/`](./skills/meight-common/CONTRACT.md).

The default dispatcher is a Claude Code session. A Codex app/CLI session can
dispatch through the same protocol via a thin `~/.codex/skills/meight` binding
that points at [`skills/meight/SKILL.md`](./skills/meight/SKILL.md) — one
protocol, two dispatcher runtimes.

## What "Easy For An Agent" Means

- **Exit codes are the API.** `0` done, `2` failed/interrupted/runtime-lost, `3`
  question, `4` daemon gone, `1` checkpoint timeout.
- **Names, not session IDs.** Sessions are addressed as `review-1`, including
  follow-ups. Names are 1-128 ASCII letters/digits/`._-`, starting with a
  letter or digit; the CLI and daemon both reject path syntax.
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
| `meight start <name> --mode mate\|worker [opts]` | Start a session and return immediately with the thread id plus resolved mode/model/effort/Fast/report/sandbox values and their default/set provenance. Supervised workflow entry point. |
| `meight wait <name> --timeout SEC` | Checkpoint wait: return on terminal state, replyable QUESTION, daemon death, or timeout. Timeout leaves the worker running. |
| `meight dispatch <name> --mode mate\|worker [opts]` | One-shot: auto-start daemon -> capability check -> start -> wait -> print preferred result. |
| `meight reply <name> --brief ... [--model M] [--effort E] [--fast\|--no-fast]` | One-shot answer to a replyable question; inherits mode/report and omitted turn settings, applies explicit turn overrides, and prints the latest result. |
| `meight follow <name> --brief ... [--model M] [--effort E] [--fast\|--no-fast]` | Low-level: new turn on the same live thread; inherits mode/report and omitted turn settings, while explicit overrides become the defaults for later turns. |
| `meight result <name> [--raw]` | Print `decision.md` when present; `--raw` prints raw `result.md`. |
| `meight status [name] [--json] [--all-repos]` | Pull digest. Table includes `MODE`; legacy rows with old role or long-form mode values remain readable. Reads disk. |
| `meight steer <name> "text"` | Inject instruction into the running turn. |
| `meight interrupt <name>` | Cancel the turn. An interrupt that arrives while a worker is still starting — or while a reply turn is being opened — is recorded, and aborts the turn the moment it would commit. |
| `meight list / daemon / ping / shutdown / launchd` | Low-level support commands. |

Common options:

- `--mode mate|worker` is required on `start` and `dispatch`. Legacy names
  `design`, `collab`, `collaborative`, `review` (→ mate) and `delegate`,
  `delegated` (→ worker) are accepted aliases. Mate is the thinking-partner
  contract; worker is team implementation with self-review and a
  dispatcher-owned external-review choice.
- `--report text|decision` uses the mode default below; `decision` writes
  `decision.json`/`decision.md`. Explicit flags always override.
- `--cwd` sets the worker workdir. Use separate git worktrees for overlapping
  file scopes.
- `--sandbox ws|ro|full` uses the mode default below.
- `--model luna|sol|terra` accepts the short aliases; full model strings pass
  through unchanged.
- `--effort low|medium|high|xhigh|ultra|max` uses the mode default below.
- `--fast` selects priority service tier and `--no-fast` disables it.
  On `follow`/`reply`, omitting `--model`, `--effort`, and Fast flags inherits
  the worker's current values; an explicit override applies to that new turn
  and becomes the value inherited by later turns.
- `--main-thread` uses a visible user thread for tools that need one. Default
  workers use persistent subagent threads, which remain hidden but resumable.

Omitted `start`/`dispatch` settings resolve in the CLI before the request is
sent:

| Mode | Model | Effort | Fast | Report | Sandbox |
|---|---|---|---|---|---|
| `mate` | `sol` | `medium` | off | `text` | `full` |
| `worker` | `luna` | `xhigh` | off | `decision` | `full` |

Neither posture enforces a sandbox: read-only is brief-driven policy (the mate
contract defaults to not modifying repository files), and `--sandbox` remains
for manual selection.

Standard is silent: specify only deviations. The table lives in `meight.py` as
deliberately simple code-only operator policy; there is no config-file or
environment override layer. Start output echoes every resolved value with
`(default)` or `(set)` provenance.

Worker state lives in
`<daemon-home>/repos/<repo-key>/workers/<name>/`: `brief.md`, `status.json`,
`events.log`, `result.md`, and, in decision mode, `decision.json` and
`decision.md`. Terminal workers keep disk artifacts but release their SDK
runtime immediately. A final structured `QUESTION:` also releases its runtime
and remains as a dormant disk row. `reply`/`follow` opens a fresh app-server,
resumes the stored `thread_id`, and continues the same thread even after daemon
restart or in-memory worker GC.

The daemon derives and verifies the repo key and state home instead of trusting
socket request paths. Its home, `repos/`, and repo/worker state directories are
owner-only (`0700`), worker state paths may not be symlinks, and `meight.sock`
is `0600`. Socket requests are bounded to 1 MiB. No process-wide umask is set,
so worker-created repository files keep the worker process's normal modes.

Terminal artifacts are retained for 30 days by default. Set
`MEIGHT_SESSION_RETENTION_SEC` to another non-negative number of seconds, or
`0` to disable disk pruning. Cleanup runs off the accept loop at most hourly,
never removes active, replyable, malformed, symlinked, or currently registered
workers, and uses immutable `terminal_at` (`updated_at` only for legacy rows).
After a daemon crash/restart, orphaned active rows become
`failed`/`runtime_lost_detail`. Final questions and terminal workers remain
resumable. Legacy ephemeral workers continue in a new persistent subagent
thread with a bounded handoff built from their saved brief, result, and events.

## Upgrading An Old Daemon To A New Protocol Epoch

The CLI fails closed before `start` when `meight ping` does not advertise the
current capability (`posture2`). Every start/follow request carries the epoch,
and every successful response atomically echoes normalized mode plus epoch. The
CLI validates both, so even a same-token daemon swapped mid-handshake cannot
silently use an old contract. Drain and restart manually:

1. Inspect `meight list --all-repos --json`; wait until no session across any
   repo is `starting`, `running`, or `needs_input`.
2. Run non-force `meight shutdown`. If it refuses, finish draining; do not use
   `--force` for this migration.
3. Branch on LaunchAgent state. If loaded, run `meight launchd install --load`
   and verify its bounded `bootout --wait` transfer selects the fresh daemon;
   if not loaded, start the daemon normally.
4. Confirm `meight ping` shows `capabilities=posture2`, then verify the new
   daemon PID and socket identity.
5. Run a throwaway `--mode worker` smoke (brief-directed read-only) and verify
   status mode plus `meight-worker` and common preamble paths.
6. Run a throwaway `--mode mate` smoke and verify `mode=mate` plus
   `meight-mate` and common preamble paths.
7. Resume real dispatches only after every smoke passes.

## Good To Know

- Meight inherits your `~/.codex/config.toml` for model, MCP servers, and auth.
  If `codex` works in your terminal, `meight` works.
- Meight uses the current system `codex` executable rather than the SDK's
  bundled runtime. Set `MEIGHT_CODEX_BIN` only when an explicit executable
  override is needed.
- Sessions start as hidden persistent Codex subagent threads by default:
  `thread_source=subagent`, `thread_ephemeral=false`.
- Foreground `meight daemon` exits after `MEIGHT_IDLE_TIMEOUT_SEC` seconds with
  no active workers by default. Managed `dispatch` auto-start and LaunchAgent
  starts disable idle shutdown; verify idle and retention values with
  `meight ping`.
- The LaunchAgent uses crash-only supervision (`SuccessfulExit=false`). A clean
  shutdown stays stopped. Auto-start uses `launchctl kickstart` when the job is
  loaded and never `kickstart -k`; direct detached startup is only the fallback
  when no job is loaded. `launchd install --load` drains the old daemon without
  force, waits for its acknowledged PID/socket exit, runs bounded
  `launchctl bootout --wait` on a loaded job,
  bootstraps the plist, and requires a fresh daemon PID/socket identity whose
  PID also matches the running job reported by launchd.
  Ambiguous `launchctl` results or an unhealthy daemon that still holds the
  singleton lock fail closed. If the published socket is deleted or replaced,
  the daemon exits nonzero so launchd can recreate it.
- `openai-codex` is pinned (`0.1.0b3`, beta). When bumping the SDK or Codex
  CLI, re-run the verification suite in [`SPEC.md`](./SPEC.md).
- Design details, state machine, hardening history, and lifecycle caveats live
  in [`ARCHITECTURE.md`](./ARCHITECTURE.md). Full dispatcher protocol lives in
  [`skills/meight/SKILL.md`](./skills/meight/SKILL.md). The earlier pipeline
  design retrospective — including the day it was designed by running itself — is in
  [`docs/2026-07-14-v3-pipeline-retrospective.md`](./docs/2026-07-14-v3-pipeline-retrospective.md).

## License

MIT
