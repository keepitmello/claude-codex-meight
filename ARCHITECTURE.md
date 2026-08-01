# Architecture

For users: see [`README.md`](./README.md). This document is for people (or agents) modifying the harness: why it is shaped this way, where the sharp edges are.

## Design premise: the consumer is an agent

Every design decision optimizes for the orchestrating agent's economics, not human ergonomics:

1. **Observation is pull, completion is push.** Streaming worker events into the orchestrator's context would burn tokens linearly with worker runtime. Instead the daemon reduces the event stream to disk digests (`status.json`, `events.log`, `result.md`); the orchestrator polls only when it cares, and a blocking `wait`/`dispatch` (run as a background shell) delivers a push — the completion notification with the result attached, or a checkpoint wake-up when `wait --timeout` elapses while the worker keeps running. Supervised dispatch leans on that second case: a `wait --timeout` set near the expected duration is a sparse checkpoint, letting the orchestrator read one `status` and `steer` mid-run without ever streaming.
2. **Exit codes are the API.** `0` done, `2` failed/interrupted, `3` worker has a question, `4` daemon dead, `1` timeout. An agent branches on these without parsing prose.
3. **One call per intent (one-shot), or a supervised session.** `dispatch` = (ensure daemon → start → wait → print result) and `reply` = (follow → wait → print last-turn result) are symmetric single background calls. `start` plus `wait` keeps the door to `status`/`steer` open mid-run. The orchestrator selects either interface by whether supervision can change the outcome, without a fixed cadence.
4. **Mode is harness policy, not memory.** `start` and `dispatch` require
   `--mode mate|worker`. Mate selects the thinking-partner contract (design,
   diagnosis, verdict-first review — the brief picks the protocol). Worker
   selects team implementation with self-review and a dispatcher-owned
   external-review choice. The preamble injects the mode-selected skill plus
   `meight-common/CONTRACT.md`. `follow`/`reply` inherit mode; they
   also inherit model/effort/service tier unless the caller overrides them at
   the new-turn boundary. Model stays independent: mate defaults to `sol`, while
   a worker defaults to `sol medium` for repository understanding. A complete
   brief may explicitly select `luna max` with Fast for execution; the selected
   model remains a dispatcher choice.
5. **Two-way by protocol, not plumbing.** A preamble frames either contract as a
   teammate: sessions may commit/push completed verified work while the
   orchestrator owns integration and final sign-off; and rather than guessing or
   silently complying, end with a structured `QUESTION:` paragraph when blocked,
   or to flag a better approach, a wrong assumption, or a tradeoff before a
   direction locks in. The daemon promotes that to `needs_input` -> exit 3 -> the
   orchestrator triages `TARGET: dispatcher|user` and replies or escalates. The
   same primitives run the other way: the orchestrator can dispatch a read-only
   blind design to think a problem through with a mate, not just hand off
   work.
6. **Results stay human-readable.** Every turn writes its final text to
   `result.md`. A final `QUESTION:` paragraph is the only special routing
   format; there is no second structured-result channel.
7. **Plans can be versioned review contracts.** When the dispatcher chooses to
   freeze an approved `PLAN.md`, later implementation and review evaluate that
   exact contract. A material scope, method, cost-envelope, or acceptance-path
   change reopens the user decision. Campaign identity follows that decision
   across renamed workers, plan revisions, and review identities, so a fresh
   session cannot reset repair or review caps.

## Process topology

```
meight (CLI, ~/.local/bin)  ──── Unix socket, JSON-lines ────  global daemon
                                                                │ openai-codex SDK (per active worker)
   status/result/wait read disk directly                        ▼
   (work without the daemon)                              codex app-server (worker-owned)
                                                                │ released after terminal turn
~/.meight/repos/<repo-key>/workers/<name>/              ▼
   brief.md · status.json · events.log · result.md
                                                 ◀── per-worker consumer thread
```

- **Daemon home** = `$MEIGHT_HOME` if set, otherwise `$XDG_STATE_HOME/meight` or `~/.meight` → one daemon shared across repos.
- **Repo state home** = `<daemon-home>/repos/<repo-key>/`, where `<repo-key>` is a stable slug plus hash of the invoking repo root. `--cwd` still controls the worker execution directory; it does not change the repo namespace for status/result lookup.
- **Protocol epoch boundary** = `ping` and `runtime_status` advertise only
  `capabilities=["ephemeral3"]`. Every start/follow request carries epoch
  `ephemeral3`; the daemon validates it before imports, path resolution or
  creation, registry reservation, SDK startup, or turn start. Successful
  responses echo normalized mode plus epoch atomically, and the CLI interrupts
  and fails on either mismatch.
- **Mode contract path** = `mate` maps to `skills/meight-mate/SKILL.md`;
  `worker` maps to `skills/meight-worker/SKILL.md`; both load
  `skills/meight-common/CONTRACT.md`. Legacy four-mode names normalize onto
  the two postures. Status persists only the canonical mode. Legacy rows with
  a role field or long-form mode values remain renderable.
- The SDK spawns `codex app-server --listen stdio://` and speaks JSON-RPC. Meight owns one SDK runtime per active worker so terminal workers can close their app-server, MCP subprocesses, and stdio file descriptors without waiting for daemon shutdown.
- The daemon holds `Thread` objects in a registry keyed by `(repo_key, worker_name)` only while a turn is starting or running. It keeps a `TurnHandle` only while a stream is live. Every completed stream, including a final `QUESTION:`, closes the worker-owned SDK runtime. `reply`/`follow` starts a fresh ephemeral thread and injects a bounded handoff from saved brief, result, and recent events.
- Workers always start with `ephemeral=True` and `thread_source=ThreadSource.subagent`. The SDK defines thread source as analytics metadata; it does not hide a persisted thread from Codex clients. Ephemeral threads are not materialized in stored thread listings, which prevents meight work from accumulating as Codex app tasks.
- Lifecycle is explicit: `MEIGHT_IDLE_TIMEOUT_SEC` controls daemon idle shutdown (foreground default 1800s, `0` disables; `daemon --idle-timeout-sec` overrides). Managed `dispatch`/LaunchAgent starts pass idle disable through both env and daemon args; LaunchAgent jobs also infer managed mode from `XPC_SERVICE_NAME` if an older loaded job lacks the env. `MEIGHT_WORKER_GC_TTL_SEC` controls how long terminal worker status remains in daemon memory (default 3600s). Disk artifacts use a separate `MEIGHT_SESSION_RETENTION_SEC` window (default 30 days, `0` disables); pruning runs off the accept loop no more than hourly.
- The daemon home and every state directory leaf are real owner-only directories (`0700`); worker state symlinks are rejected and the socket is `0600`. The daemon recomputes repo root/key/home and validates raw request fields, validates worker names at CLI and socket boundaries, and bounds one JSON request to 1 MiB. Privacy comes from parent/socket permissions, not a process-wide umask that would leak into Codex worker subprocesses.

## State machine

`starting → running → {completed | failed | interrupted | needs_input}`

- Transition priority: **preserve failed/interrupted > QUESTION promotion > completed**. A non-retryable `error` event marks the worker failed and a later `turn/completed(status=completed)` must not overwrite it.
- Unknown/missing terminal turn status maps to `failed`, never `completed` (the wait contract depends on it).
- `needs_input` carries a **source**: `"question"` (final-paragraph `QUESTION:` detected after a completed turn — a real, final state) vs `"tool"` (mid-turn tool/approval wait — transient). `classify_wait_state()` returns exit 3 **only for source=question**; a tool-wait that survives to stream-end is converted to `failed`. This distinction exists because an early review showed tool-waits masquerading as final states.
- Structured questions also carry `needs_input_target` (`dispatcher|user`) and
  `needs_input_kind` (`scope|ux|priority|risk|irreversible|acceptance|missing-info|better-direction|technical`) so a middle-layer agent can decide whether to answer or escalate.
- Non-question terminal transitions clear `needs_input_detail`/`source` (stale-question bug, found in review).

## Concurrency design

Three locks, one direction — **adding any reverse acquisition is a deadlock**:

| Lock | Protects | Order |
|---|---|---|
| `reg_lock` | worker registry (copy, then release) | outermost, never held into worker calls |
| `ctl_lock` (per worker) | all `TurnHandle` control calls: steer / interrupt / force-shutdown | acquired before… |
| `w.lock` (per worker) | status dict + digest writes | …innermost. Consumer threads take only this |

- **Control plane never waits on the data plane** — for SDK-scale or unbounded
  waits. The daemon control plane (accept loop, `ping`, registry lookups,
  `_maintenance`) must not hold `reg_lock` across worker data-plane operations
  whose duration it cannot bound: SDK calls (`Codex()`/`thread_start`/`turn`
  are seconds of subprocess+RPC), stream consumption, or open-ended consumer
  joins. Concretely: `cmd_start`/`cmd_follow` register a name-reserving
  placeholder under `reg_lock`, then run the SDK phase outside it, and
  `_maintenance` uses non-blocking `is_alive()` instead of joining consumers.
  The failure mode this prevents: a slow `thread_start` holding `reg_lock`
  starves `accept()` via `_maintenance`, and a concurrent `wait`'s socket
  probes time out twice — a false daemon-dead exit `4` plus a healthy worker
  wrongly marked runtime-lost. **Deliberate bounded residual**: the same-name
  reuse gates in `cmd_start`/`cmd_follow` may join a finishing consumer for up
  to 3s under `reg_lock` — load-bearing for file-reset safety (never unlink
  files a live stream still writes); acceptable because it is bounded and only
  triggers when a same-name reuse races a finishing stream. A per-worker
  directory lock could remove it later. The shutdown race left by the
  uncovered SDK phase is closed by the **atomic post-SDK commit**: the
  `shutting_down`/`interrupt_requested` re-check, generation bump, and
  `consumer.start()` happen under the worker's `ctl_lock`, which
  `_shutdown_now` and `cmd_interrupt` also take — either the abort flag is
  seen before commit, or the committed consumer/handle is visible to the
  interrupter. `cmd_interrupt` records interrupts that arrive during the SDK
  phase (`handle is None`, state active) instead of dropping them.

- **Turn generation ids**: each `follow` bumps `worker.generation`; the consumer thread carries its generation and every event/stream-end/exception handler drops work from stale generations. This is the mechanism that makes follow safe against a previous turn's late events.
- **Daemon singleton**: `flock(LOCK_EX|LOCK_NB)` on `daemon.lock`, plus a live-socket ping probe before ever unlinking an existing socket. Two concurrent cold dispatches may both spawn — flock guarantees one survives.
- **Liveness**: never trust `pid_alive` alone (pid reuse); socket ping is the primary signal, with a 2-strike policy in `wait`.
- **FD hygiene**: every completed stream closes its worker-owned SDK runtime immediately. A final `QUESTION:` is a durable dormant state: it keeps status and a correlation `thread_id`, not an app-server, `Thread`, or completed turn handle.
- **Runtime ownership**: the daemon registry is authoritative only for a live turn. A durable terminal or final-question row can be restored from disk, and `follow` continues it through a fresh ephemeral thread plus bounded artifact handoff.
- **Crash reconciliation**: only after the daemon wins the singleton flock, prior `starting`, `running`, and tool-wait rows are atomically marked `failed` with `runtime_lost_detail` and immutable `terminal_at`; their evidence remains. Final-question rows remain dormant and handoff-capable.
- **Disk retention**: only real, non-symlink terminal worker directories with a valid expired `terminal_at` are eligible (`updated_at` is a legacy-only fallback). Invalid/missing timestamps, active states, symlinks, and registry-owned names fail safe. Under `reg_lock`, the daemon rechecks eligibility/ownership and atomically renames to a cleanup tombstone; recursive deletion happens after releasing the lock. Later passes recover leftover tombstones only after the same terminal/expiry/registry checks—the prefix alone is not trusted because legacy worker names could collide with it.
- `status.json` writes: temp name includes pid+thread-id, then `os.replace` (a fixed temp name lets concurrent writers steal each other's files).
- **Namespace isolation**: worker names only need to be unique inside the invoking repo namespace. `list --all-repos` reads every repo namespace when a global view is needed.

## Orchestration policy

The routing we run in production; adapt to taste for Claude or Codex as the
main orchestrator.

| Work | Route |
|---|---|
| Implementation, fixes, tests, verification, log digging, browser/runtime QA, computer use, exploration, full delegation | `--mode worker` |
| Blind/anchored design and diagnosis | `--mode mate` (`high` only for genuinely hard problems; `sol` stops at `high`) |
| Plan and adversarial review | `--mode mate --effort high` (`sol high`; standing reviewer route) |
| Hard work of any kind | `--mode mate` for the plan first, then `--mode worker --model luna` on a frozen brief with complete contract, scope, and evidence |
| Implementation still hard with a complete brief | `--mode worker --model luna` (`max` with Fast for execution) |
| `sol high` | reviewer default; for non-review mate work, only genuinely hard design and confirm with the user before launching |
| Capability-specific fallback | either posture with `terra`; no default ownership, re-promotable on measured evidence |

- **Brief completeness is the worker's first routing axis**: a brief that fully
  states the acceptance contract, file/directory scope, and verification evidence
  may select `luna max` with Fast; a brief with remaining judgment starts at
  `sol medium` so hidden blockers can surface. Failure cost is an independent
  escalation axis: money, data loss, irreversibility, and production spread can
  justify a higher brain or an added gate. Money paths retain dispatcher
  sign-off, and the worker contract escalates its own do-not-decide-alone list
  before acting.
- **Difficulty is answered with a stage, not a bigger worker**: a `sol` mate
  plan is frozen, then handed to a worker with a complete brief for `luna max`
  with Fast. Worker `sol` stays at `medium`; `sol high` is the reviewer default.
  Non-review design takes one user confirmation before using it.
- **Avoiding overengineering comes first**: design and review modes are tools,
  not a default chain. The dispatcher selects gates by failure cost and records
  the choice in one line.
- **Design supports real uncertainty**: blind design avoids anchoring when an
  independent direction would add evidence; anchored design pressure-tests a
  direction already chosen.
- **Plan review is available anchored refinement**: `REVISE` keeps the thread
  alive for `reply` with a dispatcher-targeted `QUESTION:`, while `APPROVE` is
  terminal. If approval freezes a versioned `PLAN.md`, a material scope change
  reopens that decision.
- **Review is verdict evidence, not a pipeline stage**: the worker owns its
  self-review. When an independent internal read is warranted, it uses a
  fresh-context `sol high` reviewer. For reviewed work, sign-off combines the
  text verdict with verification evidence. Reading the entire diff is never a
  sign-off gate.
- Sessions may commit/push completed verified work; the orchestrator still owns integration and final sign-off.
- Briefs must point at *existing patterns* relevant to the task — detail-oriented reviewers flag absent context as defects otherwise.
- The CLI resolves omitted start/dispatch settings from the selected mode
  before building the wire request. Explicit flags always win:

  | Mode | Model | Effort | Fast | Sandbox |
  |---|---|---|---|---|
  | `mate` | `sol` | `medium` | off | `full` |
  | `worker` | `sol` | `medium` | off | `full` |

  Standard is silent and deviation is explicit. The table is deliberately
  code-only operator policy in `meight.py`; there is no config-file or
  environment override layer. An explicit `--model luna` reselects `max` and,
  when Fast is omitted, the model's Fast default; explicit `--fast`/`--no-fast`
  wins. Start output echoes each resolved value with `(default)` or `(set)`
  provenance.

## Hardening history

Built by a Claude orchestrator, adversarially reviewed by Codex across five rounds before v1 — 13 real defects found and fixed. Classes of bugs, as a checklist for future changes:

1. Daemon double-start via stale pid + socket unlink (→ flock + ping probe)
2. Follow racing a previous turn's stream thread (→ generation ids, consumer-finished gate)
3. SDK failure leaving zombie `starting` workers that block their name forever (→ mark-failed on turn-creation exception)
4. Concurrent control calls on a shared `TurnHandle`, including the force-shutdown path bypassing the lock (→ per-worker `ctl_lock` everywhere)
5. Same-name reuse unlinking files a live thread still writes (→ consumer-finished gate)
6. Fixed temp-file name corrupting `status.json` under concurrent writers (→ unique temp names)
7. Unknown turn status mapped to `completed`, violating the wait contract (→ completed-only mapping)
8. pid-reuse false-alive (→ ping-first liveness)
9. Tool-wait `needs_input` surfacing as exit 3 / masking failures; stale question detail after failure (→ `needs_input_source`, terminal-transition clears)
10. Enum-vs-string comparison silently broken by pydantic's default `model_dump()` (→ `mode="json"` everywhere)
11. `reg_lock` held across SDK calls / consumer joins starving the accept loop — head-of-line blocking that surfaced as false daemon-dead exit `4` under concurrent `wait` (→ placeholder registration + SDK phase outside the lock, non-blocking `_maintenance`, atomic post-SDK commit under `ctl_lock`, mid-SDK-phase interrupts recorded; "control plane never waits on the data plane")

State-machine changes should re-run the fake-event scenarios (tool-wait→stream-end, question persistence, failed-preservation, multi-line question, wait classification) plus the live checks in `SPEC.md`.

## Operational notes

- **Editing `meight.py` does not affect a running daemon.** For an epoch
  migration, first inspect `meight list --all-repos --json` and drain all
  active/`needs_input` sessions across every namespace. Then use non-force
  `meight shutdown`; its daemon-wide guard is the enforcement backstop. Branch
  on LaunchAgent state: loaded uses `meight launchd install --load` and its
  bounded `bootout --wait` transfer, unloaded uses normal startup. Require a
  fresh PID/socket identity and `meight ping` capability `ephemeral3`. Then run
  one worker smoke and one mate smoke and verify saved mode-specific/common
  preamble paths before real work. Do not use forced shutdown for this
  migration.
- Optional LaunchAgent support lives behind `meight launchd install --load`. It uses `RunAtLoad=true` plus crash-only `KeepAlive={SuccessfulExit=false}`: unexpected accept/socket failure exits nonzero and restarts, while acknowledged shutdown exits zero and stays stopped. The daemon also exits nonzero if the published socket pathname is deleted or replaced. Loaded-job auto-start uses `launchctl kickstart` without `-k`; direct detached startup is only used after the explicit service-not-found result proves no job is loaded. Other `launchctl` failures are unknown and fail closed. Install/reload shares one bounded ownership-transfer path: non-force drain (active sessions refuse), wait for the acknowledged old PID and socket to disappear, run `launchctl bootout --wait` with a subprocess timeout for an already-loaded job, write/bootstrap the plist, then require a fresh ping/PID and socket identity whose PID matches launchd's running job PID. This provenance check rejects a detached contender started during the transfer window. A ping failure is stale only when the recorded PID is dead (if present) and the singleton lock can be acquired; a held or unprobeable lock refuses transfer. No bootout occurs before drain completion.
- SDK (`openai-codex==0.144.4`, pinned): meight deliberately supplies the current system `codex` executable instead of the SDK's bundled runtime. `MEIGHT_CODEX_BIN` is the explicit override. The pinned SDK must understand every thread item emitted by that runtime, including nested-agent activity in a live turn. Before bumping the SDK or Codex CLI, re-introspect the API surface (`inspect.signature`), dump real event payloads (`MEIGHT_DEBUG=1` → per-worker `debug-events.log`), and re-run the verification suite.
- Approval requests arrive as SDK server-requests (auto-accepted by the SDK's default handler), not stream notifications — the `needs_input` tool path is defensive.
- Per-turn `cwd`/`sandbox`/`model`/`effort`/`service_tier` come from the SDK's
  `Thread.turn()`. `--fast` maps to `service_tier="priority"`; it is not a
  separate model slug. Follow/reply omit inherited setting keys on the wire;
  raw overrides are validated before reset, and a successfully created turn
  atomically makes its selected settings the worker/status defaults for the
  next turn. Worktree isolation is just `--cwd`.

## Deliberate non-features (v1)

Custom approval handling; automatic worktree creation; active-turn recovery
across daemon crashes; count/size-based artifact eviction.
