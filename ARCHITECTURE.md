# Architecture

For users: see [`README.md`](./README.md). This document is for people (or agents) modifying the harness: why it is shaped this way, where the sharp edges are.

## Design premise: the consumer is an agent

Every design decision optimizes for the orchestrating agent's economics, not human ergonomics:

1. **Observation is pull, completion is push.** Streaming worker events into the orchestrator's context would burn tokens linearly with worker runtime. Instead the daemon reduces the event stream to disk digests (`status.json`, `events.log`, `result.md`); the orchestrator polls only when it cares, and a blocking `wait`/`dispatch` (run as a background shell) delivers a push — the completion notification with the result attached, or a checkpoint wake-up when `wait --timeout` elapses while the worker keeps running. Supervised dispatch leans on that second case: a `wait --timeout` set near the expected duration is a sparse checkpoint, letting the orchestrator read one `status` and `steer` mid-run without ever streaming.
2. **Exit codes are the API.** `0` done, `2` failed/interrupted, `3` worker has a question, `4` daemon dead, `1` timeout. An agent branches on these without parsing prose.
3. **One call per intent (one-shot), or a supervised loop.** `dispatch` = (ensure daemon → start → wait → print result) and `reply` = (follow → wait → print last-turn result) are symmetric single background calls — one-shot driving costs the same tool calls as a native subagent, which suits trivial work. For substantial work the orchestrator instead uses `start` plus `wait`, so the door to `status`/`steer` stays open mid-run; how often it actually checks is its judgment, not a fixed cadence. Same pull/push primitives — just sampled when it matters instead of a single fire-and-forget.
4. **Mode is harness policy, not memory.** `start` and `dispatch` require
   `--mode design|review|delegate`. Design and review are the two collaborative
   modes and select the independent
   challenger (`mate`) contract; delegate selects the implementer (`worker`)
   contract. The preamble injects the mode-selected skill plus
   `meight-common/CONTRACT.md`. `follow`/`reply` inherit mode and report. Model
   stays independent: `sol` can run as a worker for hard-gated implementation,
   while `luna` can be a mate for design or review.
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
6. **Decision reports contain technical context.** `--report decision` uses the
   SDK `output_schema` to produce `decision.json` and rendered `decision.md`.
   `result.md` remains the raw audit record, but `result`/`dispatch`/`reply`
   prefer the decision surface so the orchestrator can communicate with the user
   without absorbing every implementation detail.
7. **Plans are versioned review contracts.** Direction forks remain blind
   design. After direction is set, a bounded anchored `mate/sol` review loop
   freezes versioned `PLAN.md`; implementation, adversarial review, and
   dispatcher sign-off all evaluate the same contract.

## Process topology

```
meight (CLI, ~/.local/bin)  ──── Unix socket, JSON-lines ────  global daemon
                                                                │ openai-codex SDK (per active worker)
   status/result/wait read disk directly                        ▼
   (work without the daemon)                              codex app-server (worker-owned)
                                                                │ released after terminal turn
~/.meight/repos/<repo-key>/workers/<name>/              ▼
   brief.md · status.json · events.log · result.md
   decision.json · decision.md                    ◀── per-worker consumer thread
```

- **Daemon home** = `$MEIGHT_HOME` if set, otherwise `$XDG_STATE_HOME/meight` or `~/.meight` → one daemon shared across repos.
- **Repo state home** = `<daemon-home>/repos/<repo-key>/`, where `<repo-key>` is a stable slug plus hash of the invoking repo root. `--cwd` still controls the worker execution directory; it does not change the repo namespace for status/result lookup.
- **Mode3 capability boundary** = `ping` and `runtime_status` advertise
  `capabilities=["mode3"]`. A new CLI checks this before sending `start`; an old
  daemon therefore fails closed instead of silently loading the wrong skill.
  The daemon independently rejects missing or unknown mode before imports,
  directory creation, registry reservation, or SDK startup.
- **Mode contract path** = `design` and `review` map to
  `skills/meight-mate/SKILL.md`; `delegate` maps to
  `skills/meight-worker/SKILL.md`; all load `skills/meight-common/CONTRACT.md`.
  Status persists only the canonical mode. Legacy rows with a role field or
  long-form mode values remain renderable.
- The SDK spawns `codex app-server --listen stdio://` and speaks JSON-RPC. Meight owns one SDK runtime per active worker so terminal workers can close their app-server, MCP subprocesses, and stdio file descriptors without waiting for daemon shutdown.
- The daemon holds `Thread` objects in a registry keyed by `(repo_key, worker_name)` only while that worker is active or waiting on a final `QUESTION:`. It keeps a `TurnHandle` only while a stream is live. `steer` and `interrupt` require the live handle; terminal workers release the whole SDK runtime after stream end, while a final `QUESTION:` keeps the worker-owned thread so `reply` can start the next turn.
- Workers start with `ephemeral=True` and `thread_source=ThreadSource.subagent` by default so they stay out of Codex Desktop's main user-thread list. `--main-thread` is the explicit opt-in to `ephemeral=False` plus `ThreadSource.user` for tools that need a visible/main thread. Hidden ephemeral worker `thread_id`s are audit pointers, not daemon-restart recovery handles.
- Lifecycle is explicit: `MEIGHT_IDLE_TIMEOUT_SEC` controls daemon idle shutdown (foreground default 1800s, `0` disables; `daemon --idle-timeout-sec` overrides). Managed `dispatch`/LaunchAgent starts pass idle disable through both env and daemon args; LaunchAgent jobs also infer managed mode from `XPC_SERVICE_NAME` if an older loaded job lacks the env. `MEIGHT_WORKER_GC_TTL_SEC` controls how long terminal worker status remains in daemon memory for visibility (default 3600s, disk artifacts remain); terminal SDK runtimes are already released.

## State machine

`starting → running → {completed | failed | interrupted | needs_input}`

- Transition priority: **preserve failed/interrupted > QUESTION promotion > completed**. A non-retryable `error` event marks the worker failed and a later `turn/completed(status=completed)` must not overwrite it.
- Unknown/missing terminal turn status maps to `failed`, never `completed` (the wait contract depends on it).
- `needs_input` carries a **source**: `"question"` (final-paragraph structured `QUESTION:` or `outcome=needs_decision` detected after a completed turn — a real, final state) vs `"tool"` (mid-turn tool/approval wait — transient). `classify_wait_state()` returns exit 3 **only for source=question**; a tool-wait that survives to stream-end is converted to `failed`. This distinction exists because an early review showed tool-waits masquerading as final states.
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
- **FD hygiene**: terminal workers close their worker-owned SDK runtime immediately after stream end. Final `QUESTION:` is not a live stream; it keeps the same-daemon `Thread` and SDK runtime for reply, but must not keep the completed turn's `TurnHandle`.
- **Runtime ownership**: daemon registry, not disk `thread_id`, is the source of truth for live/followable sessions. `wait` asks the daemon for `runtime_status`; if a disk-active worker is not attached to the live daemon, it is marked failed/lost instead of being polled forever.
- `status.json` writes: temp name includes pid+thread-id, then `os.replace` (a fixed temp name lets concurrent writers steal each other's files).
- **Namespace isolation**: worker names only need to be unique inside the invoking repo namespace. `list --all-repos` reads every repo namespace when a global view is needed.

## Orchestration policy

The routing we run in production; adapt to taste for Claude or Codex as the
main orchestrator.

| Work | Route |
|---|---|
| Bounded implementation, fixes, tests, verification, read-only log digging, browser/runtime QA, computer use, exploration | `--mode delegate --model luna --effort xhigh`, plus Fast when available |
| Blind/anchored design and diagnosis | `--mode design --model sol --effort high` (`xhigh` only for genuinely hard problems) |
| Plan and adversarial review | `--mode review --model sol --effort high` (`xhigh` only for genuinely hard problems) |
| Hard-gated implementation | `--mode delegate --model sol --effort xhigh` |
| Capability-specific fallback | any mode with `terra`; no default ownership, re-promotable on measured evidence |

- **Failure cost is the hard gate**: route to `sol` when acceptance-critical
  behavior materially depends on concurrency, security, public schema/API
  contract design, persistent-data migration, or cross-cutting refactoring, or
  when failure can cause money/data damage, irreversible harm, or high-impact
  production damage. General endpoint implementation and read-only production
  log investigation remain `luna`; API contract design/evolution and
  production mutation/remediation do not. Money paths retain dispatcher
  sign-off.
- **Direction-setting forks use blind design by default**: the orchestrator
  writes its own analysis first, keeps it out of the brief, and asks a read-only
  mate for the best-supported design plus the strongest case against it.
  Anchored design is only for refining an already-set direction. Plan review
  is a bounded anchored loop after that direction is set.
- **Plan review is persistent and bounded**: `REVISE` keeps the thread alive
  for `reply` (text mode: a dispatcher-targeted structured `QUESTION:`;
  decision mode: the schema encoding defined in `skills/meight/SKILL.md`);
  `APPROVE` is terminal. Run at most three rounds, recording `new-risks` and
  `resolved-risks` separately. An unapproved third round returns control to the
  dispatcher for residual-risk sign-off, a targeted evidence check, or user
  escalation. Approval freezes versioned `PLAN.md`; scope changes reopen it.
- **The review chain is explicit**: `worker/luna` implementation → `mate/sol` adversarial
  review (maximum two rounds) → dispatcher full-diff read with plan and repo
  context → direct fixes and final sign-off. P1-fix-level corrections preserve
  the contract; beyond-plan fixes reopen approval. Harness/core surgery routes
  to `sol` and adds a Claude context-holding review at plan and final-diff
  stages.
- Sessions may commit/push completed verified work; the orchestrator still owns integration and final sign-off.
- Briefs must point at *existing patterns* relevant to the task — detail-oriented reviewers flag absent context as defects otherwise.
- `follow`/`reply` at most ~2 times per thread for ordinary work; the plan-review
  loop is the explicit three-round exception.
- The CLI retains `medium` as a compatibility default, but doctrine selects
  `luna xhigh` for bounded work and `sol high` for its ownership areas (`xhigh`
  reserved for genuinely hard problems). Pipeline gates scale with the work at
  the dispatcher's judgment — skips are announced to the user or asked first,
  and failure-cost hard gates plus money-path sign-off are never skippable.

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

- **Editing `meight.py` does not affect a running daemon.** For the mode3
  migration, first inspect `meight list --all-repos --json` and drain all
  active/`needs_input` sessions across every namespace. Then use non-force
  `meight shutdown`; its daemon-wide guard is the enforcement backstop. After
  restart, require `meight ping` capability `mode3`, then run a throwaway
  read-only `--mode review` start and verify both its status mode and saved
  mate/common preamble paths before real work. Do not use forced shutdown for
  this migration.
- Optional LaunchAgent support lives behind `meight launchd install --load`; `KeepAlive` stays off, and the LaunchAgent sets both `MEIGHT_IDLE_TIMEOUT_SEC=0` and `daemon --idle-timeout-sec 0` so live control channels stay attached until explicit shutdown. Verify the loaded job with `launchctl print`, not only the plist file.
- Beta SDK (`openai-codex==0.1.0b3`, pinned): meight deliberately supplies the current system `codex` executable instead of the SDK's older bundled runtime. `MEIGHT_CODEX_BIN` is the explicit override. Before bumping the SDK or Codex CLI, re-introspect the API surface (`inspect.signature`), dump real event payloads (`MEIGHT_DEBUG=1` → per-worker `debug-events.log`), and re-run the verification suite.
- Approval requests arrive as SDK server-requests (auto-accepted by the SDK's default handler), not stream notifications — the `needs_input` tool path is defensive.
- Per-turn `cwd`/`sandbox`/`model`/`effort`/`service_tier` come from the SDK's
  `Thread.turn()`. `--fast` maps to `service_tier="priority"`; it is not a
  separate model slug. Worktree isolation is just `--cwd`.

## Deliberate non-features (v1)

Custom approval handling; automatic worktree creation; launchd KeepAlive
supervision; active-turn recovery across daemon crashes.
