# claude-codex-meight SPEC

`claude-codex-meight` is a harness that lets an orchestrator run multiple Codex
workers in parallel.

Core design goals:

- Observation is pull-based through compact disk digests to save tokens.
- Steering uses mid-turn input so active work is not discarded.
- Push-style waiting is reserved for completion or blocker boundaries through
  `wait` and background daemon execution.

This document is the implementation contract and verification record for
`meight.py`. It is not a usage tutorial.

## Stack

- Python 3.13 with a repository-local `.venv/`.
- `openai-codex==0.1.0b3` beta SDK. Keep the version pinned.
- SDK internals: the client spawns `codex app-server --listen stdio://` and
  talks JSON-RPC over stdio. One process multiplexes multiple threads through
  `MessageRouter`.
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
    effort="low|medium|high|xhigh",
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
- `mode` is required on `start`/`dispatch`: `collab` or `delegate` after alias
  normalization. `follow`/`reply` inherit it from status.
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
| `ping` | Check daemon health over `meight.sock` and print `pong` with the daemon pid and runtime `idle_timeout_sec`. |
| `launchd install [--load]` / `launchd status` / `launchd uninstall` | Manage an optional macOS LaunchAgent for the global daemon. The plist uses `RunAtLoad` and `KeepAlive=false`; CLI auto-start remains the on-demand path. |
| `start <name> --mode collab\|delegate (--brief-file F\|- \| --brief TEXT) [--report text\|decision] [--cwd DIR] [--sandbox ws\|workspace_write\|workspace-write\|ro\|read_only\|read-only\|full\|full_access\|full-access] [--model M] [--effort low\|medium\|high\|xhigh] [--fast \| --no-fast] [--no-preamble] [--main-thread]` | Start a new hidden worker thread with `thread_start(ephemeral=True, thread_source=ThreadSource.subagent)` plus one turn in the invoking repo namespace. `--mode` is required; aliases `collaborative` and `delegated` normalize to `collab` and `delegate`. Defaults: `report=text`, `sandbox=full`, `effort=medium`, `cwd=current directory`, `thread_source=subagent`, `thread_ephemeral=true`, `service_tier=default` so workers run non-Fast unless `--fast` is passed. `--report decision` supplies the SDK `output_schema` and writes `decision.json` plus `decision.md`. `--main-thread` intentionally uses `thread_start(ephemeral=False, thread_source=ThreadSource.user)` for tools that require a visible/main thread. `--fast` maps the SDK turn's `service_tier` to `priority`; omitted or `--no-fast` maps it to `default`. Reject duplicate active worker names inside the same repo namespace. `--brief-file -` reads the brief from stdin. |
| `dispatch <name> --mode collab\|delegate (--brief-file F\|- \| --brief TEXT) [--report text\|decision] [--cwd DIR] [--sandbox ws\|workspace_write\|workspace-write\|ro\|read_only\|read-only\|full\|full_access\|full-access] [--model M] [--effort low\|medium\|high\|xhigh] [--fast \| --no-fast] [--no-preamble] [--timeout SEC] [--shutdown-when-idle]` | One-shot command: auto-start daemon if needed, `start`, `wait`, then print `decision.md` when present or `result.md` otherwise. `--mode` is required with the same aliases as `start`. Default timeout is `1800` seconds. Exit code matches `wait`. `--shutdown-when-idle` asks the global daemon to stop after a terminal result if no workers are active. |
| `follow <name> (--brief-file F\|- \| --brief TEXT) [--no-preamble]` | Start a new turn on the same thread only for a worker waiting on a final `QUESTION:` while that worker remains attached to the current daemon. It takes no mode flag; it inherits the worker's recorded `mode` and `report` and receives a one-line harness reminder instead of the full preamble. Terminal workers release their SDK runtime immediately after stream end, so follow-up work should start a new worker. Hidden ephemeral workers are not resumed from disk after daemon restart; in that case `follow` fails clearly and the orchestrator must start a new worker. Reset status, increment `turns`, and append to `result.md`, `decision.json`/`decision.md` when applicable, and `events.log` with a separator. |
| `reply <name> (--brief-file F\|- \| --brief TEXT) [--no-preamble] [--timeout SEC] [--shutdown-when-idle]` | One-shot answer path for `QUESTION:` blockers: `follow`, `wait`, then print the latest `decision.md` when present or latest raw result otherwise. It takes no mode flag and inherits `mode`/`report`. Default timeout is `1800` seconds. |
| `steer <name> TEXT` | Inject mid-turn text into a running turn. Return an error unless the worker is currently running. |
| `interrupt <name>` | Interrupt the active turn. |
| `status [name] [--json] [--all-repos]` | Does not require the daemon. Read repo-scoped `status.json` directly. With no name, print a one-line table for workers in the invoking repo, including a `MODE` column; `--all-repos` reads every repo namespace. With a name, print details. `--json` prints JSON. |
| `list [--json] [--all-repos]` | Alias for `status` with no worker name. |
| `result <name> [--raw]` | Print `decision.md` when present. `--raw` prints `result.md`. |
| `wait <name> [--timeout SEC]` | Poll `status.json` once per second. Terminal states return `completed=0`, `failed=2`, `interrupted=2`. Final `QUESTION:` returns `3` only while the worker is still attached to the live daemon and can accept `reply`. Daemon death returns `4`. Timeout returns `1`. Print one final status summary line to stdout. |
| `shutdown [--force]` | Refuse shutdown while active workers exist. With `--force`, interrupt live turns, mark final `QUESTION:` waits interrupted, and then shut down. |

## Harness Preamble, Mode, and QUESTION Protocol

By default, `start`, `dispatch`, `follow`, and `reply` prepend the harness
protocol preamble to the brief. `--no-preamble` disables this.

`start` and `dispatch` build a mode-specific preamble at dispatch time:

- `collab` / `collaborative`: collaborative consult/design/diagnosis posture.
- `delegate` / `delegated`: delegated implementation/review/verification
  posture.

The preamble includes the normalized mode, allows workers to `git commit` and
`git push` their completed, verified work while the orchestrator still owns
integration and final sign-off, and points workers at
`skills/meight-worker/SKILL.md` as the worker-side contract. That path resolves
relative to the `meight.py` location, not the invoking cwd.

`follow` and `reply` do not accept a mode flag. They inherit the existing
worker's mode and use a one-line harness reminder instead of the full preamble.

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

If `outcome=needs_decision`, `decisions[]` must contain at least one entry.
The daemon routes the worker to `needs_input` / exit `3` using the first
decision's `target` and `kind`.

## Daemon Internals

- One synchronous `Codex` client per active worker.
- One Python `threading.Thread` per worker to consume the SDK stream and write
  digests.
- Socket protocol: one JSON request line and one JSON response line.
  Example: `{"cmd":"start",...}` -> `{"ok":true}` or
  `{"ok":false,"error":"..."}`.
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
  - Automatic approval or tool-response handling is out of scope.
- `error` notifications or stream exceptions set the worker state to `failed`
  and write the reason to `events.log`.
- `SIGTERM` and `SIGINT` attempt to interrupt all handles, close the Codex
  client, and clean up pid/socket files.
- Agent-message deltas are accumulated in memory and finalized on
  `item/completed`.
- `result.md` is written at `turn/completed` with the last agent message.
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

1. Start `daemon` in the background with a temporary `MEIGHT_HOME`, then confirm
   `ping` returns ok and the socket lives under that global home.
2. Run:
   `start t1 --mode delegate --brief "create /tmp/fleet-test/hello.txt with content 'hi', then reply DONE" --cwd /tmp/fleet-test --sandbox ws`
   Then `wait t1` must exit `0`; the file must exist; repo-scoped `status.json`,
   `events.log`, and `result.md` must agree.
3. Steering test:
   `start t2 --mode delegate --brief "Count from 1 to 50 slowly, one number per line, pausing to think between each"`
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

## Scope-Outs

- Automatic responses to approval requests or SDK tool input requests.
- Automatic worktree creation. The orchestrator controls worktrees through
  `cwd`.
- Active-turn recovery after daemon process death.
