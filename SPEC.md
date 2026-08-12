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
- `openai-codex==0.144.4`. Keep the SDK version pinned.
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
    service_tier=None,
)                                      # -> TurnHandle
h.steer("text")
h.interrupt()
h.stream()                            # -> Iterator[Notification]
h.run()
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
The daemon recomputes the repo root/key/home and verifies the client fields;
request-controlled paths never select a state directory. The daemon home and
state directories are real owner-only directories (`0700`), worker-state
symlinks are rejected, and `meight.sock` is `0600`. Do not set a daemon or
LaunchAgent umask: worker subprocess repository file modes must not change.

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
      messages.log   # append-only full agent message text, streamed live
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
  "state": "target_preparing|starting|running|needs_input|completed|failed|interrupted",
  "started_at": "ISO8601 KST",
  "updated_at": "ISO8601 KST",
  "terminal_at": "ISO8601 KST|null",
  "repo_root": "/abs/path/to/repo",
  "repo_key": "repo-0123456789abcdef",
  "daemon_pid": 12345,
  "cwd": "...",
  "sandbox": "workspace-write",
  "mode": "mate|worker",
  "target": "mac|desktop",
  "runtime": "codex",
  "host_id": null,
  "dispatch_id": null,
  "remote_state": null,
  "remote_event_seq": 0,
  "attempt_id": null,
  "lease_epoch": null,
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
- Set `terminal_at` once on each new terminal transition; later status writes
  must not move it. A follow turn resets it for the next transition. Legacy
  terminal rows without the field may use `updated_at` for retention.
- Update status at event granularity, but throttle high-volume delta updates to
  once every two seconds.
- `needs_input_source` is the public source of truth for `needs_input`:
  `"question"` means a final `QUESTION:` blocker; `wait` exits `3` only when
  the worker is still attached to the live daemon and can accept `reply`;
  `"tool"` means an SDK tool or approval wait — `wait` treats it as active
  during a grace window (`TOOL_WAIT_GRACE_SEC`, 15s) and then surfaces it as
  exit `3` so an unanswerable wait is not invisible until timeout.
- `mode` is required on `dispatch` and on the `start` request it sends:
  canonical `mate` or `worker` after
  alias normalization. Legacy names `design`, `collab`, `collaborative`, and
  `review` normalize to `mate`; `delegate` and `delegated` normalize to
  `worker`. `follow`/`reply` inherit mode.
  Legacy rows with a `role` field or old long-form mode values must render
  without crashing.
- `needs_input_target` is `dispatcher|user|null`; missing `TARGET` in a parsed
  question defaults to `dispatcher`.
- `needs_input_kind` is
  `scope|ux|priority|risk|irreversible|acceptance|missing-info|better-direction|technical|null`.
- `events.log` line format:
  `2026-06-12T20:01:02+09:00 [item/completed] commandExecution: pnpm typecheck:be -> exit 0`.
- Do not write delta events to `events.log`.
- Truncate each event line to at most 300 characters.
- `messages.log` holds the full text of every agent message. `agentMessage`
  deltas are appended and flushed as they arrive, without the status throttle,
  because a live reader's whole value is seeing the worker speak as it writes.
  Each message opens with a `── <iso timestamp> ──` header line and a follow
  turn opens with `=== turn N (<iso timestamp>) ===`; the body is the worker's
  own prose, unmodified. Reasoning and command output deltas are still never
  recorded. A message completing with text the deltas did not carry appends
  only the missing remainder. `status.json` `last_message_tail` (500
  characters) and the `events.log` summary keep their existing truncation.

## CLI Contract

The command table must match the `python3 meight.py --help` subcommand list exactly.

| Command | Behavior |
|---|---|
| `daemon [--idle-timeout-sec SEC]` | Run the foreground global daemon. The orchestrator starts it in the background. If a live daemon already exists, return exit `1`. `0` disables idle shutdown. |
| `ping` | Check daemon health over `meight.sock` and print `pong` with the daemon pid, runtime `idle_timeout_sec`, `session_retention_sec`, and advertised `capabilities=["desktop1"]`. |
| `launchd install [--load]` / `launchd status` / `launchd uninstall` | Manage the optional macOS LaunchAgent. The plist uses `RunAtLoad=true` and crash-only `KeepAlive={SuccessfulExit=false}`. `install --load` non-force drains a live daemon, waits boundedly for its acknowledged PID/socket exit, runs `launchctl bootout --wait` with a subprocess timeout for a loaded job, writes/bootstraps the plist, and requires a fresh ping/PID. Active sessions or timeouts refuse transfer. |
| `dispatch <name> --mode mate\|worker (--brief-file F\|- \| --brief TEXT) [--target mac\|desktop] [--cwd DIR] [--sandbox ws\|workspace_write\|workspace-write\|ro\|read_only\|read-only\|full\|full_access\|full-access] [--model M] [--effort low\|medium\|high\|xhigh\|ultra\|max] [--fast \| --no-fast] [--no-preamble] [--timeout SEC] [--progress SEC] [--narrate] [--shutdown-when-idle]` | One-shot command and the only CLI path that opens a session. `target=mac` is the compatibility default and retains the local SDK path. `target=desktop` requires a clean Git checkout, an explicit repo mapping, and the versioned `wy-server` node contract; it never silently falls back to Mac. Remote result and change bundles are hash-verified into worker artifacts and are not auto-applied. The CLI requires capability `desktop1`; start success atomically echoes normalized mode, target, runtime, and epoch. All existing wait/result behavior remains the same. |
| `follow <name> (--brief-file F\|- \| --brief TEXT) [--model M] [--effort low\|medium\|high\|xhigh\|ultra\|max] [--fast \| --no-fast] [--no-preamble]` | Continue a terminal session or one waiting on a final `QUESTION:`. It inherits recorded mode and omitted turn settings. Every completed stream releases its SDK runtime; follow restores metadata, starts a fresh ephemeral thread, and injects a bounded handoff from saved brief, result, and recent events. |
| `reply <name> (--brief-file F\|- \| --brief TEXT) [--model M] [--effort low\|medium\|high\|xhigh\|ultra\|max] [--fast \| --no-fast] [--no-preamble] [--timeout SEC] [--progress SEC] [--narrate] [--shutdown-when-idle]` | One-shot answer path: `follow`, wait, then print `result.md`. It inherits mode and per-turn setting overrides from `follow`, and shares the blocking wait, heartbeat options, and exit codes described under `dispatch`. Default timeout is `1800` seconds. |
| `steer <name> TEXT` | Inject mid-turn text into a running turn. Return an error unless the worker is currently running. |
| `interrupt <name>` | Interrupt the active turn. For `ACTIVE` workers without a live `TurnHandle` yet, including the initial starting/SDK phase and follow/reply SDK phase, set `interrupt_requested`, return ok with a recorded-interrupt note, and let the atomic post-SDK commit abort the turn. |
| `status [name] [--json] [--all-repos] [--archived \| --all]` | Does not require the daemon. Read repo-scoped `status.json` directly. With no name, the default view includes active workers and terminal workers from the last 6 hours; `--archived` selects older terminal rows and `--all` combines both views. `--all-repos` reads every repo namespace. Legacy rows with a role field or long-form mode values remain readable. |
| `list [--json] [--all-repos] [--archived \| --all]` | Alias for `status` with no worker name. |
| `result <name>` | Print `result.md`. |
| `watch [name] [--all] [--include-archived] [--from-start] [--tail N]` | Does not require the daemon and writes nothing. Stream a worker's `messages.log` verbatim for a human in a second terminal while `dispatch` blocks elsewhere. Show the last `N` characters (default `2000`, resumed at a line boundary; `--from-start` replays everything) and then follow, waiting for a worker that has not spoken yet. `--all` interleaves every active worker, prefixing each line with its name. On a TTY, a footer shows the current item and advances its elapsed seconds on the viewer's clock, and it is suppressed mid-line so it cannot land inside a sentence. Print the final status summary when every watched worker stops: exit `0`, `1` for a selection error, `130` for Ctrl-C. |
| `watch` with no name | Select without knowing any name. Exactly one active worker attaches directly. Otherwise, on a TTY, print a numbered menu grouped as active, then idle (terminal or holding a final `QUESTION:`, questions first), then archived only under `--include-archived`, using the same recent/archived split as `status`; read a number from stdin, reject anything else without redrawing, and treat an empty line, EOF, or Ctrl-C as leaving with exit `0`. Without a TTY the menu is printed and the command exits `1`, since no choice can be read. |
| `shutdown [--force]` | Refuse shutdown while active workers exist. With `--force`, interrupt live turns, mark final `QUESTION:` waits interrupted, and then shut down. |

"The blocking wait" above and below names the shared polling loop inside
`dispatch` and `reply`. There is no separate `wait` command; `status` reads the
same digest without blocking.

## Harness Preamble, Mode, and QUESTION Protocol

By default, `dispatch`, `follow`, and `reply` prepend runtime contract context
to the brief. `--no-preamble` disables this.

`dispatch` builds a mode-specific preamble when it opens a session. Mode
selects the session contract and skill (protocol epoch `desktop1`):

- `mate` (legacy aliases `design` / `collab` / `collaborative` / `review`):
  `skills/meight-mate/SKILL.md` — thinking partner for blind or anchored
  design, diagnosis, and independent artifact review. A review brief names the
  decision and surface without restricting the mate to findings or suggestions;
  a dispatcher may add a second independent read when it can change the decision.
- `worker` (legacy aliases `delegate` / `delegated`):
  `skills/meight-worker/SKILL.md` — team implementer owning implementation,
  verification, and self-review; escalates dispatcher-sign-off gates
  (security-sensitive, public API contract, data migration, money path,
  frozen review chain) before acting.

Both preambles also inject `skills/meight-common/CONTRACT.md`, the sole shared
source for question routing, evidence artifacts, sandbox, and commit discipline.

The preamble includes normalized mode. All skill paths resolve relative to
`meight.py`, not the invoking cwd.

`follow` and `reply` do not accept a mode flag. They inherit the existing
session's mode and use a one-line reminder. Their model, effort, and
service tier are inherited only when the corresponding CLI option is omitted.
The CLI omits those request keys rather than sending defaults. The daemon
validates any raw override before resetting the worker, passes the selected
values to `Thread.turn()`, and records them only after successful turn creation.

Structured final questions use this exact format:

```text
QUESTION:
TARGET: dispatcher | user
KIND: scope | ux | priority | risk | irreversible | acceptance | missing-info | better-direction | technical
<question + options + recommendation>
```

The harness records the declared target and kind; the orchestrating agent owns
impact-based triage. A reply that would authorize a new worker, phase,
plan/addendum, review identity beyond the initial round's optional fresh read
or a preauthorized re-review, expensive
rerun, materially different method, or campaign-cap extension must be
escalated to the user even when the producer declared `TARGET: dispatcher` or
`KIND: technical`. This is dispatcher policy, not a daemon-side semantic
rewrite.

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

`wait` returns exit `3` for this durable state without requiring a live worker
runtime. `follow` and `reply` continue on the same Codex thread after runtime
release, registry GC, daemon restart, or interruption.

## Daemon Internals

- One synchronous `Codex` client per active worker.
- One Python `threading.Thread` per worker to consume the SDK stream and write
  digests.
- Post-SDK commit is atomic under the per-worker `ctl_lock`: re-check guards,
  generation, and consumer start happen as one success tail. SDK calls run
  outside `reg_lock` with a name-reserving `starting` placeholder.
- Socket protocol: one JSON request line (maximum 1 MiB) and one JSON response line.
  Example: `{"cmd":"start",...}` -> `{"ok":true}` or
  `{"ok":false,"error":"..."}`.
- `ping` and `runtime_status` responses advertise only
  `"capabilities": ["desktop1"]`. Start/follow requests carry
  `"protocol_epoch": "desktop1"`.
- The daemon validates epoch before imports, path resolution or creation,
  registry reservation, SDK startup, turn start, or any other start/follow
  side effect. It then validates start mode before start side effects.
- Successful `start` and `follow` responses atomically echo canonical mode and
  epoch. The CLI validates both and fails closed with a best-effort interrupt
  if a swapped daemon accepts the request under another contract, including a
  same-token stale-epoch downgrade.
- Every name-bearing CLI/socket command accepts only a 1-128 character worker
  name made from ASCII letters/digits/`._-`, starting with a letter or digit.
  The daemon derives and verifies repo context before selecting state and
  refuses symlink worker directories.
- Socket-dispatched commands: `start`, `follow`, `steer`, `interrupt`,
  `shutdown`, `ping`, `runtime_status`.
- Worker registry: `(repo_key, name) -> {thread, handle, state}`.
- `steer` and `interrupt` operate through the stored `TurnHandle`.
- Completed, failed, and interrupted workers keep their disk state but release
  their SDK runtime after the stream ends. This closes the worker-owned
  `codex app-server`, its MCP subprocesses, and stdio file descriptors.
- Final `QUESTION:` workers release the completed turn's `TurnHandle`, `Thread`,
  and worker-owned SDK runtime. Their disk row and correlation `thread_id`
  remain dormant; `reply`/`follow` starts a fresh ephemeral thread and injects
  a bounded artifact handoff before the next turn.
- Terminal workers are removed from daemon memory after
  `MEIGHT_WORKER_GC_TTL_SEC` (default `3600`; `0` disables). Foreground
  `meight daemon` exits after `MEIGHT_IDLE_TIMEOUT_SEC` seconds with no active
  workers (default `1800`; `0` disables), unless `--idle-timeout-sec`
  overrides it. Managed daemon starts (`dispatch` auto-start and LaunchAgent)
  set both
  `MEIGHT_IDLE_TIMEOUT_SEC=0` and `daemon --idle-timeout-sec 0`; LaunchAgent
  jobs also infer managed mode from `XPC_SERVICE_NAME=com.keepitmello.meight`
  if an older loaded job is missing the env override. `meight ping` exposes the
  runtime `idle_timeout_sec` and `session_retention_sec` for verification.
- Terminal disk artifacts are pruned after `MEIGHT_SESSION_RETENTION_SEC`
  (default 30 days; `0` disables). Cleanup is off the accept loop and scheduled
  at most hourly. Only real non-symlink terminal directories with a valid
  expired immutable `terminal_at` are eligible; legacy rows may use
  `updated_at`. Invalid/missing timestamps, active states, symlinks, and
  registry-owned names are skipped. Under `reg_lock`, eligibility/ownership is
  rechecked and the directory is atomically renamed to a tombstone; recursive
  deletion is outside the lock, and later passes recover leftover tombstones
  only after revalidating terminal state, expiry, and registry non-ownership.
  The internal prefix alone is never deletion authority because legacy worker
  names could collide with it.
- After singleton ownership is secured and before accepting requests, startup
  reconciliation preserves final-question rows with a valid `thread_id` and
  marks orphaned `starting`, `running`, and tool-wait rows `failed` with
  `runtime_lost_detail` and `terminal_at`.
- `follow` rehydrates terminal and final-question workers from disk after daemon
  restart or registry GC, then starts a fresh ephemeral thread with a bounded
  handoff from saved brief, result, and recent events.
  Low-level follow-up work after a terminal result may continue only
  inside a still-valid approved campaign and remaining worker/repair cap.
  Otherwise the orchestrator returns to the user instead of dispatching.
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
- Intentional acknowledged shutdown is the only zero-exit accept-loop close.
  Unexpected accept/socket ownership failure, including published pathname
  deletion or replacement, exits nonzero. Loaded LaunchAgent
  auto-start uses `launchctl kickstart` without `-k`; detached direct startup is
  permitted only when the explicit service-not-found result proves no job is
  loaded. If `launchctl print` otherwise cannot determine
  ownership, auto-start/install fails closed instead of spawning a competing
  unmanaged daemon. An unhealthy owner is stale only when its recorded PID is
  dead (if present) and the singleton lock can be acquired; bootstrap readiness
  requires a fresh PID/socket identity and that the ping PID equals launchd's
  running job PID.
- Agent-message deltas are accumulated in memory and finalized on
  `item/completed`.
- `result.md` is written once per turn with the last agent message, or with a
  terminal error when no agent message exists.

## SDK Boundary Defenses

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

It covers both posture-to-skill mappings, legacy aliases, missing/invalid mode
and missing/stale epoch rejection before side effects, follow/reply mode
inheritance, start resolution output, the `MODE` status cell, legacy rows with
role or old mode values, negative capability handshake with no start request or
state creation, mode+epoch fail-closed cleanup (including swapped same-token
stale-epoch), positive handshake with canonical mode in status,
private state/socket permissions, path/name/symlink rejection, request bounds,
immutable terminal timestamps, orphan reconciliation, retention safety/races,
launchd payload/routing/ownership transfer, and accept-loop exit classification.

1. Start `daemon` in the background with a temporary `MEIGHT_HOME`, then confirm
   `ping` returns capability `desktop1` and the socket lives under that global home.
2. Run:
   `start t1 --mode worker --brief "create /tmp/fleet-test/hello.txt with content 'hi', then reply DONE" --cwd /tmp/fleet-test --sandbox ws`
   Then `wait t1` must exit `0`; the file must exist; repo-scoped `status.json`,
   `events.log`, and `result.md` must agree.
3. Steering test:
   `start t2 --mode worker --brief "Count from 1 to 50 slowly, one number per line, pausing to think between each"`
   While running, send `steer t2 "Stop counting, just reply STEERED"` and
   confirm the result reflects the steer.
4. Interrupt test: interrupt a long-running task and confirm
   `state=interrupted`.
5. Multi-repo namespace test: run same-name workers from two git repos with the
   same `MEIGHT_HOME`; confirm one daemon pid and separate repo-scoped
   `status.json` files.
6. Reply test: create a final-`QUESTION` worker, confirm its app-server exits,
   restart the daemon, answer it, and confirm a new ephemeral `thread_id`,
   `continued_from_thread_id`, `turns=2`, and a separator in `result.md`.
7. Runtime release test: complete a non-question worker and confirm its worker
   runtime is no longer attached while disk artifacts remain readable.
8. Lifecycle test: with small `MEIGHT_IDLE_TIMEOUT_SEC` and
   `MEIGHT_WORKER_GC_TTL_SEC`, confirm terminal workers are GC'd from daemon
   memory while disk result files remain and the daemon exits when idle.
9. Restart/lost-worker test: restart during a running worker and confirm it
   becomes failed with `runtime_lost_detail`; restart after a final `QUESTION`
   and confirm it remains dormant and handoff-capable.
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
14. Trust-boundary tests: verify `0700` state, `0600` socket, CLI+daemon name
    rejection, daemon-derived repo context, symlink refusal, and 1 MiB request
    rejection.
15. Retention tests: cover exact threshold, disabled mode, invalid/missing and
    legacy timestamps, active/registered/symlink skips, immutable
    `terminal_at`, startup orphan conversion, atomic tombstone rename/recovery,
    deletion outside `reg_lock`, and off-loop hourly scheduling.
16. Launchd unit tests: assert `SuccessfulExit=false`, launchd-owned kickstart
    without `-k`, detached fallback only when unloaded, drain acknowledgement
    before waits, active refusal/timeouts before bootout/bootstrap, bounded
    first-load/reload order, and fresh-PID requirement.
17. Accept-loop unit test: intentional close returns zero; unexpected accept
    failure returns nonzero for crash supervision.

### Safe Ephemeral3 Migration Checklist

This is operator-run after the old daemon finishes serving current sessions;
implementation must not restart it.

1. Run `meight list --all-repos --json` and drain every `starting`, `running`,
   and tool/approval `needs_input` row across all repo namespaces. Final
   `QUESTION:` rows are dormant and do not block shutdown.
2. Run non-force `meight shutdown`. Its daemon-wide active-session guard is the
   enforcement backstop; do not use `--force` for migration.
3. Branch on LaunchAgent state. Loaded uses `meight launchd install --load` and
   verifies bounded `bootout --wait` ownership transfer; unloaded uses normal
   daemon startup.
4. Require `meight ping` to advertise `capabilities=desktop1` and verify the
   fresh daemon PID and socket identity.
5. Run a throwaway worker smoke (brief-directed read-only) and verify status
   mode plus `meight-worker` and common preamble paths.
6. Run a throwaway mate smoke and verify `mode=mate` plus `meight-mate` and
   common preamble paths before real dispatches resume.

## Scope-Outs

- Automatic responses to approval requests or SDK tool input requests, except
  per-worker Computer Use app-access elicitations. They are enabled by default,
  accept only `connector_id="computer-use"` requests, and apply only to the
  worker session.
- Automatic worktree creation. The orchestrator controls worktrees through
  `cwd`.
- Active-turn recovery after daemon process death.
- Count/size-based artifact eviction or deletion of malformed/unknown state.
