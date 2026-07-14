# claude-codex-meight SPEC

`claude-codex-meight` is a harness that lets an orchestrator run multiple Codex
mate and worker sessions in parallel.

Core design goals:

- Observation is pull-based through compact disk digests to save tokens.
- Steering uses mid-turn input so active work is not discarded.
- Push-style waiting is reserved for completion or blocker boundaries through
  `wait` and background daemon execution.

This document is the implementation contract and verification record for
`meight.py`. It is not a usage tutorial.

## Stack

- Python 3.13 with a repository-local `.venv/`.
- `openai-codex==0.1.0b3` beta SDK. Keep the SDK version pinned.
- SDK internals: the client spawns the current system
  `codex app-server --listen stdio://` selected by `system_codex_bin()` and
  talks JSON-RPC over stdio. `MEIGHT_CODEX_BIN` can explicitly select another
  executable. One process multiplexes multiple threads through `MessageRouter`.
- The SDK inherits the user's Codex config, including model, MCP servers, and
  authentication.

### Verified SDK API Surface

```python
from openai_codex import Codex, Sandbox, ApprovalMode

codex = Codex()                       # supports context-manager use
th = codex.thread_start()             # th.id = "019e..."
h = th.turn(
    input,
    *,
    cwd=str,
    sandbox=Sandbox.workspace_write,
    model=None,
    effort="low|medium|high|xhigh|ultra|max",
    approval_mode=None,
    output_schema=None,
    service_tier=None,
)                                      # -> TurnHandle
h.steer("text")
h.interrupt()
h.stream()                            # -> Iterator[Notification]
h.run()
codex.thread_resume(thread_id)        # exists, but hidden ephemeral workers are not treated as resumable
```

- `Notification` objects expose `.method` as a string and `.payload` as a
  pydantic object. Use `.model_dump()` before reading payload fields.
- `Sandbox` values: `read_only`, `workspace_write`, `full_access`.
- `ApprovalMode` values: `deny_all`, `auto_review`. `None` inherits config.
- Observed event sequence:
  `turn/started -> item/started -> item/agentMessage/delta* -> item/completed -> thread/tokenUsage/updated -> turn/completed`.
- Other important events:
  `turn/diff/updated`, `turn/plan/updated`,
  `item/commandExecution/outputDelta`, `tool/requestUserInput`,
  `item/*/requestApproval`, `thread/status/changed`, `error`.

## Deliverables

- `meight.py`: single-file implementation using only the Python standard library
  plus `openai-codex`.
- `meight`: CLI shim for invoking `meight.py`.
- Supported invocation shape: `meight <cmd>` or `.venv/bin/python meight.py <cmd>`.

## State Directory

If `$MEIGHT_HOME` is set, use it as the global daemon home. Otherwise use
`$XDG_STATE_HOME/meight` when `$XDG_STATE_HOME` is set, falling back to
`~/.meight/`. The daemon home is shared across repositories.

Each CLI invocation also resolves a repository namespace from the invoking cwd:
`git -C <cwd> rev-parse --show-toplevel` when available, otherwise `<cwd>`.
The repo key is a stable slug plus hash of that root. `--cwd` controls the
worker execution directory only; it does not change the status/result namespace.

```text
~/.meight/
  meight.sock          # Unix domain socket
  daemon.pid
  daemon.log         # daemon lifecycle log only; do not dump raw events
  launchd.out.log
  launchd.err.log
  repos/<repo-key>/
    workers/<name>/
      brief.md       # original dispatched prompt
      status.json    # digest; schema below
      events.log     # append-only meaningful event lines
      result.md      # final agent message at turn completion
      decision.json   # structured decision report when --report decision is used
      decision.md     # rendered decision surface when --report decision is used
```

The repository `.gitignore` should ignore `.venv/`. Historical repo-local
`.meight/` directories are no longer used by default.

### status.json Schema

```json
{
  "name": "worker-a",
  "thread_id": "...",
  "turn_id": "...",
  "state": "starting|running|needs_input|completed|failed|interrupted",
  "started_at": "ISO8601 KST",
  "updated_at": "ISO8601 KST",
  "repo_root": "/abs/path/to/repo",
  "repo_key": "repo-0123456789abcdef",
  "daemon_pid": 12345,
  "cwd": "...",
  "sandbox": "workspace-write",
  "role": "mate|worker",
  "mode": "delegate",
  "report": "decision",
  "model": null,
  "effort": "medium",
  "thread_source": "subagent",
  "thread_ephemeral": true,
  "current_item": "commandExecution: pnpm typecheck:be (12s)",
  "plan": ["[done] step1", "[active] step2"],
  "files_changed": ["src/x.ts"],
  "tokens": {"input": 0, "cached": 0, "output": 0},
  "last_message_tail": "last 500 chars of the agent message",
  "needs_input_detail": null,
  "needs_input_source": null,
  "needs_input_target": null,
  "needs_input_kind": null,
  "runtime_lost_detail": null,
  "error_detail": null,
  "turns": 1
}
```

- Write `status.json` atomically with a temporary file followed by `os.replace`.
- Update status at event granularity, but throttle high-volume delta updates to
  once every two seconds.
- `needs_input_source` is the public source of truth for `needs_input`:
  `"question"` means a final `QUESTION:` blocker; `wait` exits `3` only when
  the worker is still attached to the live daemon and can accept `reply`;
  `"tool"` means an SDK tool or approval wait and is treated as active until
  stream-end cleanup.
- `role` is required on `start`/`dispatch`: exactly `mate` or `worker`.
  `follow`/`reply` inherit it from status. Legacy rows may omit `role`; status
  rendering displays `-` and must not crash.
- `mode` is also required on `start`/`dispatch`: `collab` or `delegate` after
  alias normalization. `follow`/`reply` inherit it from status.
- `report` is `text` or `decision`.
- `needs_input_target` is `dispatcher|user|null`; missing `TARGET` in a parsed
  question defaults to `dispatcher`.
- `needs_input_kind` is
  `scope|ux|priority|risk|irreversible|acceptance|missing-info|better-direction|technical|null`.
- `events.log` line format:
  `2026-06-12T20:01:02+09:00 [item/completed] commandExecution: pnpm typecheck:be -> exit 0`.
- Do not write delta events to `events.log`.
- Truncate each event line to at most 300 characters.

## CLI Contract

The command table must match the `python3 meight.py --help` subcommand list exactly.

| Command | Behavior |
|---|---|
| `daemon [--idle-timeout-sec SEC]` | Run the foreground global daemon. The orchestrator starts it in the background. If a live daemon already exists, return exit `1`. `0` disables idle shutdown. |
| `ping` | Check daemon health over `meight.sock` and print `pong` with the daemon pid, runtime `idle_timeout_sec`, and advertised `capabilities` including `role`. |
| `launchd install [--load]` / `launchd status` / `launchd uninstall` | Manage an optional macOS LaunchAgent for the global daemon. The plist uses `RunAtLoad` and `KeepAlive=false`; CLI auto-start remains the on-demand path. |
| `start <name> --role mate\|worker --mode collab\|delegate (--brief-file F\|- \| --brief TEXT) [--report text\|decision] [--cwd DIR] [--sandbox ws\|workspace_write\|workspace-write\|ro\|read_only\|read-only\|full\|full_access\|full-access] [--model M] [--effort low\|medium\|high\|xhigh\|ultra\|max] [--fast \| --no-fast] [--no-preamble] [--main-thread]` | Start a new hidden Codex session with `thread_start(ephemeral=True, thread_source=ThreadSource.subagent)` plus one turn in the invoking repo namespace. `--role` is required as `mate` or `worker`; `--mode` is independently required, with `collaborative` and `delegated` aliases. Before sending `start`, the CLI pings the daemon and requires capability `role`; absence fails closed with `daemon predates --role; restart required`. Model aliases `sol`, `terra`, and `luna` normalize to `gpt-5.6-sol`, `gpt-5.6-terra`, and `gpt-5.6-luna`; other strings pass through. Defaults: `report=text`, `sandbox=full`, `effort=medium`, `cwd=current directory`, `thread_source=subagent`, `thread_ephemeral=true`, `service_tier=default`. `--report decision` supplies `output_schema`. `--main-thread` opts into a visible persistent user thread. `--fast` maps to service tier `priority`. Reject duplicate active names inside the same repo namespace. |
| `dispatch <name> --role mate\|worker --mode collab\|delegate (--brief-file F\|- \| --brief TEXT) [start opts] [--timeout SEC] [--shutdown-when-idle]` | One-shot command: auto-start daemon if needed, capability-check, `start`, `wait`, then print `decision.md` or `result.md`. Both role and mode are required. Default timeout is `1800` seconds. Exit code matches `wait`. |
| `follow <name> (--brief-file F\|- \| --brief TEXT) [--no-preamble]` | Start a new turn on the same thread only for a session waiting on a final `QUESTION:` while attached to the current daemon. It takes no role or mode flag; it inherits recorded `role`, `mode`, and `report` and receives a one-line reminder. Terminal sessions release their SDK runtime, and hidden sessions are not resumed from disk after restart. |
| `reply <name> (--brief-file F\|- \| --brief TEXT) [--no-preamble] [--timeout SEC] [--shutdown-when-idle]` | One-shot answer path: `follow`, `wait`, then print the latest preferred result. It inherits `role`/`mode`/`report`. Default timeout is `1800` seconds. |
| `steer <name> TEXT` | Inject mid-turn text into a running turn. Return an error unless the worker is currently running. |
| `interrupt <name>` | Interrupt the active turn. For `ACTIVE` workers without a live `TurnHandle` yet, including the initial starting/SDK phase and follow/reply SDK phase, set `interrupt_requested`, return ok with a recorded-interrupt note, and let the atomic post-SDK commit abort the turn. |
| `status [name] [--json] [--all-repos]` | Does not require the daemon. Read repo-scoped `status.json` directly. With no name, print a table including `ROLE` and `MODE`; `--all-repos` reads every repo namespace. Legacy rows without role render `-`. |
| `list [--json] [--all-repos]` | Alias for `status` with no worker name. |
| `result <name> [--raw]` | Print `decision.md` when present. `--raw` prints `result.md`. |
| `wait <name> [--timeout SEC]` | Poll `status.json` once per second. Terminal states return `completed=0`, `failed=2`, `interrupted=2`. Final `QUESTION:` returns `3` only while the worker is still attached to the live daemon and can accept `reply`. Daemon death returns `4`. Timeout returns `1`. Print one final status summary line to stdout. |
| `shutdown [--force]` | Refuse shutdown while active workers exist. With `--force`, interrupt live turns, mark final `QUESTION:` waits interrupted, and then shut down. |

## Harness Preamble, Role, Mode, and QUESTION Protocol

By default, `start`, `dispatch`, `follow`, and `reply` prepend the harness
protocol preamble to the brief. `--no-preamble` disables this.

`start` and `dispatch` build a role- and mode-specific preamble at dispatch
time. Role selects the contract:

- `mate`: `skills/meight-mate/SKILL.md` for consult, plan review, and
  adversarial review.
- `worker`: `skills/meight-worker/SKILL.md` for bounded implementation and
  verification.

Both preambles also inject `skills/meight-common/CONTRACT.md`, the sole shared
source for decision fields, question routing, evidence artifacts, sandbox, and
commit discipline. Mode independently selects posture:

- `collab` / `collaborative`: collaborative consult/design/diagnosis posture.
- `delegate` / `delegated`: delegated execution or verdict posture.

The preamble includes role, normalized mode, and report type. All skill paths
resolve relative to `meight.py`, not the invoking cwd.

`follow` and `reply` do not accept role or mode flags. They inherit the existing
session's role, mode, and report and use a one-line reminder.

Structured final questions use this exact format:

```text
QUESTION:
TARGET: dispatcher | user
KIND: scope | ux | priority | risk | irreversible | acceptance | missing-info | better-direction | technical
<question + options + recommendation>
```

When a completed turn's last paragraph starts with `QUESTION:`, the daemon
promotes the worker to:

```json
{
  "state": "needs_input",
  "needs_input_source": "question",
  "needs_input_target": "dispatcher",
  "needs_input_kind": "missing-info",
  "needs_input_detail": "QUESTION: ..."
}
```

Parsing is lenient: a missing `TARGET` defaults to `dispatcher`. Missing or
unknown `KIND` leaves `needs_input_kind=null` while preserving the raw
`needs_input_detail`.

`wait` returns exit `3` for this state only while the worker is still attached
to the live daemon. `follow` and `reply` are allowed to continue from this state
on the same Codex thread before daemon restart or interruption.

## Decision Report Schema

`--report decision` asks the SDK to constrain the final worker message through
`output_schema`. The daemon writes raw `result.md`, parsed `decision.json`, and
rendered `decision.md`. `meight result`, `dispatch`, and `reply` prefer
`decision.md`; `meight result --raw` prints `result.md`.

Required fields:

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

The schema is strict (`additionalProperties: false` on every object): every
field above is required on every object, nested objects included. Workers use
empty arrays or `"N/A"` where a field does not apply; omitting a field fails
SDK schema validation and the turn.

If `outcome=needs_decision`, `decisions[]` must contain at least one entry.
The daemon routes the worker to `needs_input` / exit `3` using the first
decision's `target` and `kind`. Decision-report workers cannot emit a text
`QUESTION:` paragraph; `outcome=needs_decision` + `decisions[]` is their
escalation channel, and the harness preamble teaches whichever channel matches
the worker's report mode.

## Daemon Internals

- One synchronous `Codex` client per active worker.
- One Python `threading.Thread` per worker to consume the SDK stream and write
  digests.
- Post-SDK commit is atomic under the per-worker `ctl_lock`: re-check guards,
  generation, and consumer start happen as one success tail. SDK calls run
  outside `reg_lock` with a name-reserving `starting` placeholder.
- Socket protocol: one JSON request line and one JSON response line.
  Example: `{"cmd":"start",...}` -> `{"ok":true}` or
  `{"ok":false,"error":"..."}`.
- `ping` and `runtime_status` responses advertise
  `"capabilities": ["role"]`. The CLI must observe that capability before it
  sends a role-aware start request.
- The daemon validates missing or unknown role before imports, directory
  creation, registry reservation, SDK startup, or any other start side effect.
  Direct socket clients cannot bypass this boundary or receive an implicit
  worker role.
- Socket-dispatched commands: `start`, `follow`, `steer`, `interrupt`,
  `shutdown`, `ping`, `runtime_status`.
- Worker registry: `(repo_key, name) -> {thread, handle, state}`.
- `steer` and `interrupt` operate through the stored `TurnHandle`.
- Completed, failed, and interrupted workers keep their disk state but release
  their SDK runtime after the stream ends. This closes the worker-owned
  `codex app-server`, its MCP subprocesses, and stdio file descriptors.
- Final `QUESTION:` workers detach the completed turn's `TurnHandle` but keep
  the worker-owned SDK runtime and `Thread` so `reply` can start the next turn
  on the same thread. If the question is interrupted, that runtime is released.
  Disk `thread_id` is an audit pointer, not a same-thread recovery mechanism for
  hidden ephemeral workers.
- Terminal workers are removed from daemon memory after
  `MEIGHT_WORKER_GC_TTL_SEC` (default `3600`; `0` disables). Foreground
  `meight daemon` exits after `MEIGHT_IDLE_TIMEOUT_SEC` seconds with no active
  workers (default `1800`; `0` disables), unless `--idle-timeout-sec`
  overrides it. Managed daemon starts (`dispatch` auto-start and LaunchAgent)
  set both
  `MEIGHT_IDLE_TIMEOUT_SEC=0` and `daemon --idle-timeout-sec 0`; LaunchAgent
  jobs also infer managed mode from `XPC_SERVICE_NAME=com.keepitmello.meight`
  if an older loaded job is missing the env override. `meight ping` exposes the
  runtime `idle_timeout_sec` for process-level verification.
- `follow` does not rehydrate hidden ephemeral workers after daemon restart.
  Same-daemon follow is the supported path for final `QUESTION:` replies only;
  low-level follow-up work after a terminal result should start a new worker.
- `wait` checks daemon `runtime_status` for active disk states, including final
  `QUESTION:` waits. If a new daemon is alive but does not know that worker,
  `wait` marks the worker failed with `runtime_lost_detail` instead of polling
  forever or returning a misleading exit `3`.
- `needs_input` handling:
  - `tool/requestUserInput` or `item/*/requestApproval` records a summarized
    payload in `needs_input_detail` with `needs_input_source="tool"`.
  - A final `QUESTION:` paragraph records the question in `needs_input_detail`
    with `needs_input_source="question"`.
  - Automatic approval or tool-response handling is out of scope, except the
    default Computer Use app-access bridge described below.
- Non-retry `error` notifications set the worker state to `failed`, preserve the
  allow-listed provider `message`, HTTP `status`, and error `type` in
  `error_detail`, and write the failure to both `events.log` and `result.md`.
  A later `turn/completed` does not duplicate or overwrite that result.
- `SIGTERM` and `SIGINT` attempt to interrupt all handles, close the Codex
  client, and clean up pid/socket files.
- Agent-message deltas are accumulated in memory and finalized on
  `item/completed`.
- `result.md` is written once per turn with the last agent message, or with a
  structured terminal error when no agent message exists.
  In decision report mode, `decision.json` and `decision.md` are written for
  the same turn after schema validation/rendering.

## Beta SDK Defenses

- Always read payload fields through `model_dump()` followed by `dict.get()`
  chains. Missing fields must not crash a worker.
- Unknown events are ignored except for optional debug logging.
- SDK exceptions, including `CodexRpcError`, fail only the affected worker. The
  daemon must stay alive.
- Unknown or missing terminal turn statuses must not be silently mapped to
  `completed`; classify them as `failed` unless an interrupt was requested.

## Verification Suite

Run these checks after implementation and attach the evidence.

The automated suite is:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -v
```

It covers role-to-skill mapping, missing/invalid role rejection at the daemon
boundary before side effects, follow/reply role inheritance, the `ROLE` status
column, legacy status rows without role, negative capability handshake with no
start request or state creation, and positive handshake with requested role in
status.

1. Start `daemon` in the background with a temporary `MEIGHT_HOME`, then confirm
   `ping` returns capability `role` and the socket lives under that global home.
2. Run:
   `start t1 --role worker --mode delegate --brief "create /tmp/fleet-test/hello.txt with content 'hi', then reply DONE" --cwd /tmp/fleet-test --sandbox ws`
   Then `wait t1` must exit `0`; the file must exist; repo-scoped `status.json`,
   `events.log`, and `result.md` must agree.
3. Steering test:
   `start t2 --role worker --mode delegate --brief "Count from 1 to 50 slowly, one number per line, pausing to think between each"`
   While running, send `steer t2 "Stop counting, just reply STEERED"` and
   confirm the result reflects the steer.
4. Interrupt test: interrupt a long-running task and confirm
   `state=interrupted`.
5. Multi-repo namespace test: run same-name workers from two git repos with the
   same `MEIGHT_HOME`; confirm one daemon pid and separate repo-scoped
   `status.json` files.
6. Reply test: create a final-`QUESTION` worker, answer it before daemon
   restart, and confirm `turns=2` with a separator in `result.md`.
7. Runtime release test: complete a non-question worker and confirm its worker
   runtime is no longer attached while disk artifacts remain readable.
8. Lifecycle test: with small `MEIGHT_IDLE_TIMEOUT_SEC` and
   `MEIGHT_WORKER_GC_TTL_SEC`, confirm terminal workers are GC'd from daemon
   memory while disk result files remain and the daemon exits when idle.
9. Restart/lost-worker test: create a running or final-`QUESTION` worker,
   restart the daemon, then confirm `wait` marks the active disk state failed
   with `runtime_lost_detail` instead of polling forever or returning stale
   `QUESTION`.
10. Force-shutdown test: create a final-`QUESTION` worker, run
    `shutdown --force`, and confirm the worker state becomes `interrupted`.
11. Shutdown/post-SDK race test: cover both orderings around the post-SDK
    success tail. If shutdown wins before commit, the turn aborts before
    consumer start; if commit wins first, shutdown interrupts the live handle and
    joins cleanup.
12. SDK-phase interrupt test: interrupt while the worker is still in the
    starting/SDK phase, confirm the interrupt is recorded, and confirm the
    atomic post-SDK commit aborts the turn.
13. Computer Use approval bridge test: with a fake SDK client, confirm a valid
    `mcpServer/elicitation/request` for `connector_id="computer-use"` accepts,
    while a different connector, method, or malformed metadata reaches the
    original handler.

### Safe Role Migration Checklist

This is operator-run after the old daemon finishes serving current sessions;
implementation must not restart it.

1. Run `meight list --all-repos --json` and drain every `starting`, `running`,
   and `needs_input` row across all repo namespaces.
2. Run non-force `meight shutdown`. Its daemon-wide active-session guard is the
   enforcement backstop; do not use `--force` for migration.
3. Start the new daemon normally and require `meight ping` to advertise
   `capabilities=role`.
4. Start a throwaway `--role mate --mode delegate --sandbox ro` session.
5. Verify its status records `"role": "mate"` and its saved `brief.md`
   preamble names `skills/meight-mate/SKILL.md` and
   `skills/meight-common/CONTRACT.md` before real dispatches resume.

## Scope-Outs

- Automatic responses to approval requests or SDK tool input requests, except
  per-worker Computer Use app-access elicitations. They are enabled by default,
  accept only `connector_id="computer-use"` requests, and apply only to the
  worker session.
- Automatic worktree creation. The orchestrator controls worktrees through
  `cwd`.
- Active-turn recovery after daemon process death.
