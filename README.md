# claude-codex-meight

<p align="center">
  <img src="./docs/hero.jpg" alt="Claude Fable 5 + Codex" width="720">
</p>

**English** | [한국어](./docs/README.ko.md)

> **A two-way harness for Claude × Codex.** Not just dispatch-and-wait: Codex workers raise questions and flag better ideas mid-run, the Claude orchestrator consults them when it's stuck, and both sides review each other's work — a real collaboration loop, not one model bossing the other around. Built on the official `openai-codex` Python SDK. CLI: `meight`.

Most Claude↔Codex bridges are built for *a human watching a terminal* — tmux panes to attach to, dashboards to click. Meight is built for the agents themselves: a Claude orchestrator and Codex workers collaborating directly, with no human in the loop. In practice that means:

- **Both directions, same thread.** Codex isn't just an executor — a worker ends a turn with a `QUESTION:` to flag a better path or a shaky assumption (not only when it's blocked), and the orchestrator answers or adjusts the direction with it. Real back-and-forth, not fire-a-task-collect-a-result.
- **Consult, don't just delegate.** Stuck on a design? The orchestrator dispatches a read-only worker to think a problem through *with* it — the sibling of code review, applied to the thinking instead of the artifact.
- **Nothing ships self-reviewed.** Every worker output gets an independent read — never from the worker that produced it. By default that's a fresh-context Codex review worker (independent context is what catches defects; there's no evidence cross-model reviews better). For important architecture or high-stakes work, the orchestrator runs both — a Codex review worker and a cross-model Claude agent — for two independent perspectives instead of one.
- **Supervised, on your terms.** The `start`+`wait` split lets the orchestrator pull `status` and `steer` mid-run — how often, and whether at all, is its judgment, not a fixed cadence. Progress lives in small disk files, so watching costs ~0 context.
- **One-shot when it fits.** `meight dispatch` still gives fire-and-forget for trivial, short, low-risk tasks.

```
   Claude orchestrator   ⇄   Codex worker(s)
   (what & why)               (how)
        │                          ▲
        ├──  start + brief  ───────┘
        │
        │◀──  QUESTION:  better idea · wrong assumption · blocked · done
        │──▶  answer · steer · consult · review
        │            (either side can open the next turn, same thread)
        │
        ▼   orchestrator pulls disk digests on demand — ~0 context, never streamed
   global daemon ── official openai-codex SDK ── codex app-server (1 process, N threads)
        status.json · events.log · result.md
```

## Why two models, working together

Anthropic's new Mythos-class models (**Claude Fable 5**) are remarkably good at planning and judgment — seeing the whole picture, breaking work down, making the right call when things are ambiguous. They are also expensive to run. Codex (**GPT-5.5**) costs much less per unit of work and is very good at the details: race conditions, type drift, missed edge cases, contract violations.

Meight pairs them so you get higher quality at lower cost: Claude holds the *what and why*, Codex the *how*. But the division only pays off because the two work as **teammates, not boss and tool** — a worker pushes back when it sees a better path, the orchestrator consults a worker when it's stuck, and each reviews the other's output (cross-model review catches what same-model self-review misses). A side benefit: the workload spreads across two subscriptions. The full collaboration policy ships as [`CLAUDE.md`](./CLAUDE.md).

## Why this exists

As of June 2026, every public Claude↔Codex project we could find drives Codex through its **CLI** — spawning `codex exec` subprocesses or typing into tmux. Tools built that way share the same limits: to redirect a running worker you have to kill it (and lose its work), to see progress you have to pipe everything into the orchestrator's context, and a stuck worker has no way to ask for help.

OpenAI's official **`openai-codex` Python SDK** (released May 2026) removed those limits: it talks to `codex app-server` directly and exposes steering, interrupting, and streaming as real APIs, with a single Codex process running many workers at once. **Meight is — to our knowledge — the first public harness built on it.** Side by side:

| | tmux/exec bridges | MCP wrappers | **Meight** |
|---|---|---|---|
| Parallel workers | 1 process per worker | blocking tool calls | N threads, 1 codex process |
| Mid-turn steering | attach & type (human) or kill+resume (loses work) | ✗ | **`meight steer` — programmatic, no work lost** |
| Progress observation | scrape stdout / stream into context | ✗ | **disk digest, pull on demand (~0 tokens)** |
| Two-way conversation | ✗ (guesses or stalls) | ✗ | **worker raises `QUESTION:` (blocked *or* better idea) → exit 3 → `meight reply`; orchestrator can `consult` back** |
| Result delivery | scrape | tool return | **exit-code contract + result on stdout** |
| Session continuity | fragile | threadId | **same-thread `follow`/`reply` turns** |

## Quick start

Requirements: [Codex CLI](https://developers.openai.com/codex) installed & authenticated, Python ≥ 3.10.

```bash
git clone https://github.com/keepitmello/claude-codex-meight
cd claude-codex-meight && ./install.sh   # creates .venv + ~/.local/bin/meight
```

For substantial work, use supervised dispatch from any git repo. Meight uses one global daemon by default (`$MEIGHT_HOME`, `$XDG_STATE_HOME/meight`, or `~/.meight`) while keeping worker state isolated per invoking repo under `repos/<repo-key>/`. `start` expects the global daemon to be running; `dispatch` auto-starts it, and you can also start it once with `meight daemon` or install the optional LaunchAgent with `meight launchd install --load`.

```bash
meight start impl-1 --brief-file - --cwd ~/my-repo <<'EOF'
Implement X in src/foo.py. Existing pattern: see src/bar.py:42.
Verify with: pytest tests/test_foo.py. Report changed files + test output.
EOF

meight wait impl-1 --timeout 300
# exit 0=completed · 2=failed/interrupted · 3=worker asked a question · 4=daemon dead · 1=checkpoint timeout
```

On exit `1`, the worker is still running. Inspect once, then either wait again or steer:

```bash
meight status impl-1
meight steer impl-1 "Stop refactoring the helper — only fix the bug."
meight wait impl-1 --timeout 300
```

On exit `0`, `2`, or `3`, `wait` prints a status summary. Read the full message from disk:

```bash
meight result impl-1
```

The worker asked a question (exit 3)? The question is also visible in `meight status impl-1` as `needs_input_detail`. Answer in one shot, same thread:

```bash
meight reply impl-1 --brief "Use config-a.json, and keep the legacy field."
```

You're the one who's stuck? Run the loop the other way — dispatch a read-only worker to think a problem through *with* you, then `follow` to refine the direction together:

```bash
meight start consult-1 --sandbox ro --brief "My plan is X but I'm unsure about Y. Read src/ and tell me what I'm missing — and a better approach if you see one."
meight wait consult-1 --timeout 300
meight follow consult-1 --brief "Good point on Y. If we go that way, how does Z hold up?"
```

For trivial, short, low-risk tasks, one-shot dispatch is still available:

```bash
meight dispatch tiny-1 --brief "Check whether README mentions LICENSE." --sandbox ro
```

## Using it from Claude Code

This is the intended consumer. For real work, run `wait --timeout` as the **background Bash call**. Claude wakes at the checkpoint, reads one `status`, and either waits again or sends a targeted `steer`:

```
Bash(command: "meight start review-1 --sandbox ro --effort high --brief-file - <<'EOF' ... EOF")
Bash(command: "meight wait review-1 --timeout 300",
     run_in_background: true)
→ ... Claude keeps working ...
→ <task-notification> exit 1 checkpoint timeout
→ meight status review-1
→ healthy: wait again · drifting: meight steer review-1 "..."
```

When the worker reaches a terminal state, the notification is `0` (completed), `2` (failed/interrupted), or `3` (worker question). Use `meight result review-1` for the full report. On `0`, verify the work before accepting it. On `3`, answer with `meight reply`.

Every brief is automatically prefixed with a harness preamble that (a) forbids `git commit`/`push` — git stays owned by the orchestrator — and (b) frames the worker as a teammate: rather than guessing or silently complying, end with a `QUESTION:` paragraph when blocked *or* to flag a better approach, a wrong assumption, or a decision that could shift direction. Disable with `--no-preamble`.

A drop-in orchestrator prompt (role split, routing table, dispatch protocol, cross-model review rules) ships as [`CLAUDE.md`](./CLAUDE.md) — copy it into your project or global Claude Code memory. A self-contained Claude Code **skill** ships at [`skills/meight/`](./skills/meight/SKILL.md) — copy it into `~/.claude/skills/` for trigger-based JIT loading.

## What "easy for an agent" actually means

Small decisions everywhere assume the user is an LLM agent, not a person at a terminal:

- **Exit codes are the API.** `0` done, `2` failed, `3` question, `4` daemon gone. The agent branches on a number instead of reading prose and guessing whether things worked. Unknown outcomes map to *failed*, never to *completed* — exit 0 can be trusted.
- **Sparse checkpoints, not busy polling.** Set `wait --timeout` near the work's expected duration: finish in time and the orchestrator just gets the completion push; overrun and the timeout wakes it for one `status` look. A timeout returns exit `1` and leaves the worker running. No fixed interval, no obligation to check — `status` and `steer` stay available without tight polling loops that burn turns. A backgrounded `wait` also auto-prints a status heartbeat every 300s (`--progress N` to retune, `0` to disable) into its output, so you read mid-run progress without re-waiting — keep `--timeout` long for visibility, shorten it only to steer.
- **Names, not session IDs.** Workers are addressed as `review-1`, follow-ups included. No UUID bookkeeping to get wrong.
- **Results survive on disk.** `result.md` stays re-readable — if the agent's context gets compacted mid-session, nothing is lost.
- **Status is pre-digested.** Instead of raw logs, `status` returns what a decision needs: what the worker is doing now, which files changed, its last thought. Exactly enough to choose between wait, steer, and interrupt.
- **Policy can't be forgotten.** The no-commit rule and the QUESTION protocol are injected into every brief by the harness, not remembered by the agent.
- **Briefs go through stdin.** Long multi-line briefs avoid shell-quoting traps entirely.

## Command reference

| Command | What it does |
|---|---|
| `meight start <name> [opts]` | Start a worker and return immediately with the thread id. Supervised workflow entry point. |
| `meight wait <name> --timeout SEC` | Checkpoint wait: return on terminal state, QUESTION, daemon death, or timeout. Timeout leaves the worker running. |
| `meight dispatch <name> [opts]` | One-shot: auto-start daemon → start worker → wait → print result. Use for trivial, short, low-risk work. Add `--shutdown-when-idle` to stop the daemon after the result when no workers are active. |
| `meight reply <name> --brief ...` | One-shot answer to a worker question: follow + wait + print last-turn result |
| `meight status [name]` | Pull digest (table or detail). Reads disk — works without the daemon |
| `meight steer <name> "text"` | Inject instruction into the running turn (no work lost) |
| `meight interrupt <name>` | Cancel the running turn (idempotent) |
| `meight follow <name> --brief ...` | Low-level: new turn on the same thread (context preserved) |
| `meight result / list / daemon / ping / shutdown / launchd` | Low-level support commands |

Options: `--cwd` (worker workdir — use separate git worktrees for overlapping file scopes), `--sandbox ws|ro|full` (default `full` = no sandbox, so Codex can verify freely — builds, daemon restarts, writes outside cwd; `ws` = workspace-write scoped to cwd; reviews run `ro`), `--effort low|medium|high|xhigh` (default `medium`; raise by task complexity), `--model`, `--fast`/`--no-fast` (workers run non-Fast by default; pass `--fast` to use the codex Fast/priority tier), `--timeout`. Workers start as hidden ephemeral Codex subagent threads by default so they stay out of Codex Desktop's main user-thread list; use `--main-thread` only when a tool needs a visible/main thread.

Worker state lives in `<daemon-home>/repos/<repo-key>/workers/<name>/`: `brief.md`, `status.json` (state machine + tokens + files changed + last activity), `events.log` (one line per meaningful event), `result.md` (final message per turn). Use `meight list --all-repos` for a global view. Terminal workers stay in daemon memory for `MEIGHT_WORKER_GC_TTL_SEC` seconds by default, and the daemon exits after `MEIGHT_IDLE_TIMEOUT_SEC` seconds with no active workers; set either env var to `0` to disable that cleanup.

## Good to know

- Meight inherits your `~/.codex/config.toml` for model, MCP servers, and auth — under the hood the SDK runs a standard `codex app-server`. If `codex` works in your terminal, `meight` works. Meight deliberately overrides worker service tier to non-Fast by default; pass `--fast` when a specific worker should use the priority tier.
- `openai-codex` is pinned (`0.1.0b3`, beta). When bumping, re-run the verification suite in [`SPEC.md`](./SPEC.md).
- Design details — the concurrency model, state machine, and orchestration policy — live in [`ARCHITECTURE.md`](./ARCHITECTURE.md).

## License

MIT
