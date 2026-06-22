# Architecture

For users: see [`README.md`](./README.md). This document is for people (or agents) modifying the harness: why it is shaped this way, where the sharp edges are.

## Design premise: the consumer is an agent

Every design decision optimizes for the orchestrating agent's economics, not human ergonomics:

1. **Observation is pull, completion is push.** Streaming worker events into the orchestrator's context would burn tokens linearly with worker runtime. Instead the daemon reduces the event stream to disk digests (`status.json`, `events.log`, `result.md`); the orchestrator polls only when it cares, and a blocking `wait`/`dispatch` (run as a background shell) delivers a push — the completion notification with the result attached, or a checkpoint wake-up when `wait --timeout` elapses while the worker keeps running. Supervised dispatch leans on that second case: a `wait --timeout` set near the expected duration is a sparse checkpoint, letting the orchestrator read one `status` and `steer` mid-run without ever streaming.
2. **Exit codes are the API.** `0` done, `2` failed/interrupted, `3` worker has a question, `4` daemon dead, `1` timeout. An agent branches on these without parsing prose.
3. **One call per intent (one-shot), or a supervised loop.** `dispatch` = (ensure daemon → start → wait → print result) and `reply` = (follow → wait → print last-turn result) are symmetric single background calls — one-shot driving costs the same tool calls as a native subagent, which suits trivial work. For substantial work the orchestrator instead uses `start` plus `wait`, so the door to `status`/`steer` stays open mid-run; how often it actually checks is its judgment, not a fixed cadence. Same pull/push primitives — just sampled when it matters instead of a single fire-and-forget.
4. **Two-way by protocol, not plumbing.** A preamble (auto-prepended to every brief) frames the worker as a teammate: never commit; and rather than guessing or silently complying, end with a `QUESTION:` paragraph — when blocked, or to flag a better approach, a wrong assumption, or a tradeoff before a direction locks in. The daemon promotes that to `needs_input` → exit 3 → the orchestrator answers or discusses with `reply` on the same thread. The same primitives run the other way: the orchestrator can dispatch a read-only `consult` brief to think a problem through with a worker, not just hand off work.

## Process topology

```
meight (CLI, ~/.local/bin)  ──── Unix socket, JSON-lines ────  global daemon
                                                                │ openai-codex SDK (1 client)
   status/result/wait read disk directly                        ▼
   (work without the daemon)                              codex app-server (1 process)
                                                                │ N threads multiplexed
~/.meight/repos/<repo-key>/workers/<name>/              ▼
   brief.md · status.json · events.log · result.md   ◀── per-worker consumer thread
```

- **Daemon home** = `$MEIGHT_HOME` if set, otherwise `$XDG_STATE_HOME/meight` or `~/.meight` → one daemon shared across repos.
- **Repo state home** = `<daemon-home>/repos/<repo-key>/`, where `<repo-key>` is a stable slug plus hash of the invoking repo root. `--cwd` still controls the worker execution directory; it does not change the repo namespace for status/result lookup.
- The SDK spawns `codex app-server --listen stdio://` and speaks JSON-RPC; per-turn notifications are routed by the SDK's internal MessageRouter, which is what allows N concurrent turns over one process.
- The daemon holds `Thread`/`TurnHandle` objects in a registry keyed by `(repo_key, worker_name)`. `steer` and `interrupt` require the live handle; `follow` can resume a completed/question worker from disk after a daemon restart through `thread_resume`.
- Workers start with `thread_source=ThreadSource.subagent` by default so they stay out of Codex Desktop's main user-thread list. `--main-thread` is the explicit opt-in to `ThreadSource.user` for tools that need a visible/main thread.
- Lifecycle is explicit: `MEIGHT_IDLE_TIMEOUT_SEC` controls daemon idle shutdown (default 1800s, `0` disables), and `MEIGHT_WORKER_GC_TTL_SEC` controls how long terminal workers stay in daemon memory (default 3600s, disk artifacts remain).

## State machine

`starting → running → {completed | failed | interrupted | needs_input}`

- Transition priority: **preserve failed/interrupted > QUESTION promotion > completed**. A non-retryable `error` event marks the worker failed and a later `turn/completed(status=completed)` must not overwrite it.
- Unknown/missing terminal turn status maps to `failed`, never `completed` (the wait contract depends on it).
- `needs_input` carries a **source**: `"question"` (final-paragraph `QUESTION:` detected after a completed turn — a real, final state) vs `"tool"` (mid-turn tool/approval wait — transient). `classify_wait_state()` returns exit 3 **only for source=question**; a tool-wait that survives to stream-end is converted to `failed`. This distinction exists because an early review showed tool-waits masquerading as final states.
- Non-question terminal transitions clear `needs_input_detail`/`source` (stale-question bug, found in review).

## Concurrency design

Three locks, one direction — **adding any reverse acquisition is a deadlock**:

| Lock | Protects | Order |
|---|---|---|
| `reg_lock` | worker registry (copy, then release) | outermost, never held into worker calls |
| `ctl_lock` (per worker) | all `TurnHandle` control calls: steer / interrupt / force-shutdown | acquired before… |
| `w.lock` (per worker) | status dict + digest writes | …innermost. Consumer threads take only this |

- **Turn generation ids**: each `follow` bumps `worker.generation`; the consumer thread carries its generation and every event/stream-end/exception handler drops work from stale generations. This is the mechanism that makes follow safe against a previous turn's late events.
- **Daemon singleton**: `flock(LOCK_EX|LOCK_NB)` on `daemon.lock`, plus a live-socket ping probe before ever unlinking an existing socket. Two concurrent cold dispatches may both spawn — flock guarantees one survives.
- **Liveness**: never trust `pid_alive` alone (pid reuse); socket ping is the primary signal, with a 2-strike policy in `wait`.
- `status.json` writes: temp name includes pid+thread-id, then `os.replace` (a fixed temp name lets concurrent writers steal each other's files).
- **Namespace isolation**: worker names only need to be unique inside the invoking repo namespace. `list --all-repos` reads every repo namespace when a global view is needed.

## Orchestration policy

The routing we run in production with Claude Code as the orchestrator; adapt to taste.

| Work | Route |
|---|---|
| Bounded implementation with a clear spec; code review; browser/runtime checks | Codex worker via `meight` |
| Exploration fan-out; fresh-context verification; anything needing the orchestrator's own tooling | Claude subagents |
| High-stakes or irreversible paths | Either — but runtime evidence + explicit orchestrator sign-off regardless |

- **Cross-model review is mandatory**: Codex implements → a fresh-context Claude agent verifies; Claude implements → Codex reviews (`--sandbox ro --effort high`, re-review via `follow` on the same worker). Same-model self-review is not accepted.
- Workers never commit; git belongs to the orchestrator (enforced by the preamble).
- Briefs must point at *existing patterns* relevant to the task — detail-oriented reviewers flag absent context as defects otherwise.
- `follow` at most ~2 times per thread, then reset with a fresh brief (long Codex sessions degrade).
- Effort by complexity: `medium` default, `high` for tricky implementation/review/debugging, `xhigh` for precision verification (concurrency, critical paths).

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

State-machine changes should re-run the fake-event scenarios (tool-wait→stream-end, question persistence, failed-preservation, multi-line question, wait classification) plus the live checks in `SPEC.md`.

## Operational notes

- **Editing `meight.py` does not affect a running daemon** — restart it (`meight shutdown`, next dispatch auto-starts). Easy to forget.
- Optional LaunchAgent support lives behind `meight launchd install --load`; `KeepAlive` stays off so launchd does not fight the daemon's idle shutdown policy.
- Beta SDK (`openai-codex==0.1.0b3`, pinned): before bumping, re-introspect the API surface (`inspect.signature`), dump real event payloads (`MEIGHT_DEBUG=1` → per-worker `debug-events.log`), and re-run the verification suite.
- Approval requests arrive as SDK server-requests (auto-accepted by the SDK's default handler), not stream notifications — the `needs_input` tool path is defensive.
- Per-turn `cwd`/`sandbox`/`model`/`effort` come from the SDK's `Thread.turn()` — worktree isolation is just `--cwd`.

## Deliberate non-features (v1)

Custom approval handling; structured worker output via `output_schema` (SDK supports it — natural extension for machine-readable reports); automatic worktree creation; launchd KeepAlive supervision; active-turn recovery across daemon crashes.
