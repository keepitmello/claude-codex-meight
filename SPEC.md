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
codex.thread_resume(thread_id)        # exists; introspect signature in code if needed
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
  "cwd": "...",
  "sandbox": "workspace-write",
  "model": null,
  "effort": "medium",
  "thread_source": "subagent",
  "current_item": "commandExecution: pnpm typecheck:be (12s)",
  "plan": ["[done] step1", "[active] step2"],
  "files_changed": ["src/x.ts"],
  "tokens": {"input": 0, "cached": 0, "output": 0},
  "last_message_tail": "last 500 chars of the agent message",
  "needs_input_detail": null,
  "needs_input_source": null,
  "turns": 1
}
```

- Write `status.json` atomically with a temporary file followed by `os.replace`.
- Update status at event granularity, but throttle high-volume delta updates to
  once every two seconds.
- `needs_input_source` is the public source of truth for `needs_input`:
  `"question"` means a final `QUESTION:` blocker and makes `wait` exit `3`;
  `"tool"` means an SDK tool or approval wait and is treated as active until
  stream-end cleanup.
- `events.log` line format:
  `2026-06-12T20:01:02+09:00 [item/completed] commandExecution: pnpm typecheck:be -> exit 0`.
- Do not write delta events to `events.log`.
- Truncate each event line to at most 300 characters.

## CLI Contract

The command table must match the `python3 meight.py --help` subcommand list exactly.

| Command | Behavior |
|---|---|
| `daemon` | Run the foreground global daemon. The orchestrator starts it in the background. If a live daemon already exists, return exit `1`. |
| `ping` | Check daemon health over `meight.sock` and print `pong` with the daemon pid. |
| `launchd install [--load]` / `launchd status` / `launchd uninstall` | Manage an optional macOS LaunchAgent for the global daemon. The plist uses `RunAtLoad` and `KeepAlive=false`; CLI auto-start remains the on-demand path. |
| `start <name> (--brief-file F\|- \| --brief TEXT) [--cwd DIR] [--sandbox ws\|workspace_write\|workspace-write\|ro\|read_only\|read-only\|full\|full_access\|full-access] [--model M] [--effort low\|medium\|high\|xhigh] [--fast \| --no-fast] [--no-preamble] [--main-thread]` | Start a new persistent worker thread with `thread_start(ephemeral=False, thread_source=ThreadSource.subagent)` plus one turn in the invoking repo namespace. Defaults: `sandbox=full`, `effort=medium`, `cwd=current directory`, `thread_source=subagent` so meight workers do not appear as main user threads in Codex Desktop. `--main-thread` intentionally uses `ThreadSource.user` for tools that require a visible/main thread. `--fast`/`--no-fast` toggles the codex Fast (priority) service tier for this worker — it maps to the SDK turn's `service_tier` (`priority` / `default` respectively); omitted = inherit `~/.codex/config.toml`. Reject duplicate active worker names inside the same repo namespace. `--brief-file -` reads the brief from stdin. |
| `dispatch <name> (--brief-file F\|- \| --brief TEXT) [--cwd DIR] [--sandbox ws\|workspace_write\|workspace-write\|ro\|read_only\|read-only\|full\|full_access\|full-access] [--model M] [--effort low\|medium\|high\|xhigh] [--fast \| --no-fast] [--no-preamble] [--timeout SEC] [--shutdown-when-idle]` | One-shot command: auto-start daemon if needed, `start`, `wait`, then print `result.md`. Default timeout is `1800` seconds. Exit code matches `wait`. `--shutdown-when-idle` asks the global daemon to stop after a terminal result if no workers are active. |
| `follow <name> (--brief-file F\|- \| --brief TEXT) [--no-preamble]` | Start a new turn on the same thread for a terminal worker or a worker waiting on a final `QUESTION:`. If the daemon restarted, resume the thread from the repo-scoped `status.json` via `thread_resume`. Reset status, increment `turns`, and append to `result.md` and `events.log` with a separator. |
| `reply <name> (--brief-file F\|- \| --brief TEXT) [--no-preamble] [--timeout SEC] [--shutdown-when-idle]` | One-shot answer path for `QUESTION:` blockers: `follow`, `wait`, then print only the latest turn result. Default timeout is `1800` seconds. |
| `steer <name> TEXT` | Inject mid-turn text into a running turn. Return an error unless the worker is currently running. |
| `interrupt <name>` | Interrupt the active turn. |
| `status [name] [--json] [--all-repos]` | Does not require the daemon. Read repo-scoped `status.json` directly. With no name, print a one-line table for workers in the invoking repo; `--all-repos` reads every repo namespace. With a name, print details. `--json` prints JSON. |
| `list [--json] [--all-repos]` | Alias for `status` with no worker name. |
| `result <name>` | Print `result.md`. |
| `wait <name> [--timeout SEC]` | Poll `status.json` once per second. Terminal states return `completed=0`, `failed=2`, `interrupted=2`. Final `QUESTION:` returns `3`. Daemon death returns `4`. Timeout returns `1`. Print one final status summary line to stdout. |
| `shutdown [--force]` | Refuse shutdown while active workers exist. With `--force`, interrupt all active workers and then shut down. |

## Harness Preamble and QUESTION Protocol

By default, `start`, `dispatch`, `follow`, and `reply` prepend the harness
protocol preamble to the brief. `--no-preamble` disables this.

The preamble requires workers to leave changes in the working tree and to avoid
`git commit` or `git push`. It also frames the worker as a teammate: rather than
guessing or silently complying, a worker ends its final response with a paragraph
starting with `QUESTION:` — either when blocked on information only the
orchestrator can provide, or to raise a better approach, a wrong assumption, or a
decision that could shift direction.

When a completed turn's last paragraph starts with `QUESTION:`, the daemon
promotes the worker to:

```json
{
  "state": "needs_input",
  "needs_input_source": "question",
  "needs_input_detail": "QUESTION: ..."
}
```

`wait` returns exit `3` for this state. `follow` and `reply` are allowed to
continue from this state on the same Codex thread.

## Daemon Internals

- One synchronous `Codex` client per global daemon.
- One Python `threading.Thread` per worker to consume the SDK stream and write
  digests.
- Socket protocol: one JSON request line and one JSON response line.
  Example: `{"cmd":"start",...}` -> `{"ok":true}` or
  `{"ok":false,"error":"..."}`.
- Socket-dispatched commands: `start`, `follow`, `steer`, `interrupt`,
  `shutdown`, `ping`.
- Worker registry: `(repo_key, name) -> {thread, handle, state}`.
- `steer` and `interrupt` operate through the stored `TurnHandle`.
- Terminal workers remain on disk and are removed from daemon memory after
  `MEIGHT_WORKER_GC_TTL_SEC` (default `3600`; `0` disables). The daemon exits
  after `MEIGHT_IDLE_TIMEOUT_SEC` seconds with no active workers (default
  `1800`; `0` disables).
- `follow` can rehydrate a terminal/question worker after daemon restart with
  `Codex.thread_resume(thread_id, cwd=..., sandbox=..., model=..., service_tier=...)`.
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
   `start t1 --brief "create /tmp/fleet-test/hello.txt with content 'hi', then reply DONE" --cwd /tmp/fleet-test --sandbox ws`
   Then `wait t1` must exit `0`; the file must exist; repo-scoped `status.json`,
   `events.log`, and `result.md` must agree.
3. Steering test:
   `start t2 --brief "Count from 1 to 50 slowly, one number per line, pausing to think between each"`
   While running, send `steer t2 "Stop counting, just reply STEERED"` and
   confirm the result reflects the steer.
4. Interrupt test: interrupt a long-running task and confirm
   `state=interrupted`.
5. Multi-repo namespace test: run same-name workers from two git repos with the
   same `MEIGHT_HOME`; confirm one daemon pid and separate repo-scoped
   `status.json` files.
6. Follow-up test: restart the daemon, send a follow-up instruction to completed
   `t1`, and confirm the new turn uses the same `thread_id`.
7. Lifecycle test: with small `MEIGHT_IDLE_TIMEOUT_SEC` and
   `MEIGHT_WORKER_GC_TTL_SEC`, confirm terminal workers are GC'd from daemon
   memory while disk result files remain, and the daemon exits when idle.

## Scope-Outs

- Automatic responses to approval requests or SDK tool input requests.
- `output_schema` support.
- Automatic worktree creation. The orchestrator controls worktrees through
  `cwd`.
- Active-turn recovery after daemon process death.
