# claude-codex-meight

**English** | [한국어](./docs/README.ko.md)

> **Claude Code plans, Codex builds.** Meight is the harness in between: Claude hands a task to a Codex worker with one command, keeps working, and gets the result back when it's done — just like using one of its own subagents. Built on the official `openai-codex` Python SDK. CLI: `meight`.

Most Claude↔Codex bridges are built for *a human watching a terminal* — tmux panes to attach to, dashboards to click. Meight is built for the agent doing the orchestration. In practice that means:

- **Fire and forget.** One command sends a task to a worker. When it finishes, the full result arrives in the completion notification. No polling, no copy-paste.
- **Cheap to watch.** Workers write progress to small files on disk. Claude peeks only when it wants to (`meight status`) — nothing streams into its context window.
- **Fixable mid-flight.** Going the wrong way? `meight steer` tells the running worker to change course — without killing it or losing the work done so far.
- **Workers ask instead of guessing.** A blocked worker stops and asks a question. Claude answers with `meight reply`, and the worker continues with everything it already knew.

```
Claude Code (orchestrator)
   │  one background Bash call
   ▼
meight dispatch impl-1 --brief-file - --cwd ~/repo <<'EOF'
<task brief>
EOF
   │                                  ▲
   ▼                                  │ completion notification
per-repo daemon ──── official openai-codex SDK ──── codex app-server (1 process, N threads)
   │
   └─ disk digests: status.json / events.log / result.md   ← orchestrator pulls on demand
```

## Why split the work this way

Anthropic's new Mythos-class models (**Claude Fable 5**) are remarkably good at planning and judgment — seeing the whole picture, breaking work down, making the right call when things are ambiguous. They are also expensive to run. Codex (**GPT-5.5**) costs much less per unit of work and is very good at the details: race conditions, type drift, missed edge cases, contract violations.

Meight pairs them so you get higher quality at lower cost: Claude does the thinking (*what and why*), Codex workers do the building (*how*), and each reviews the other's output — cross-model review catches what self-review misses. A side benefit: the workload spreads across two subscriptions. The full policy ships as [`CLAUDE.md`](./CLAUDE.md).

## Why this exists

As of June 2026, every public Claude↔Codex project we could find drives Codex through its **CLI** — spawning `codex exec` subprocesses or typing into tmux. Tools built that way share the same limits: to redirect a running worker you have to kill it (and lose its work), to see progress you have to pipe everything into the orchestrator's context, and a stuck worker has no way to ask for help.

OpenAI's official **`openai-codex` Python SDK** (released May 2026) removed those limits: it talks to `codex app-server` directly and exposes steering, interrupting, and streaming as real APIs, with a single Codex process running many workers at once. **Meight is — to our knowledge — the first public harness built on it.** Side by side:

| | tmux/exec bridges | MCP wrappers | **Meight** |
|---|---|---|---|
| Parallel workers | 1 process per worker | blocking tool calls | N threads, 1 codex process |
| Mid-turn steering | attach & type (human) or kill+resume (loses work) | ✗ | **`meight steer` — programmatic, no work lost** |
| Progress observation | scrape stdout / stream into context | ✗ | **disk digest, pull on demand (~0 tokens)** |
| Worker asks a question | ✗ (guesses or stalls) | ✗ | **`QUESTION:` protocol → exit 3 → `meight reply`** |
| Result delivery | scrape | tool return | **exit-code contract + result on stdout** |
| Session continuity | fragile | threadId | **same-thread `follow`/`reply` turns** |

## Quick start

Requirements: [Codex CLI](https://developers.openai.com/codex) installed & authenticated, Python ≥ 3.10.

```bash
git clone https://github.com/keepitmello/claude-codex-meight
cd claude-codex-meight && ./install.sh   # creates .venv + ~/.local/bin/meight
```

Dispatch a worker (from any git repo — state is isolated per repo under `.meight/`):

```bash
meight dispatch impl-1 --brief-file - --cwd ~/my-repo --sandbox ws <<'EOF'
Implement X in src/foo.py. Existing pattern: see src/bar.py:42.
Verify with: pytest tests/test_foo.py. Report changed files + test output.
EOF
# Daemon auto-starts. Blocks until the worker finishes, then prints the result.
# exit 0=completed · 2=failed/interrupted · 3=worker asked a question · 4=daemon dead · 1=timeout
```

The worker asked a question (exit 3)? The question is in the printed result. Answer in one shot, same thread:

```bash
meight reply impl-1 --brief "Use config-a.json, and keep the legacy field."
```

Observe and steer while it runs:

```bash
meight status            # one-line table: state, elapsed, files changed, tokens, current activity
meight status impl-1     # detail: current command, plan, last reasoning tail
meight steer impl-1 "Stop refactoring the helper — only fix the bug."   # mid-turn, no work lost
meight interrupt impl-1
```

## Using it from Claude Code

This is the intended consumer. Run dispatch as a **background Bash call** — Claude gets a completion notification with the full result, exactly like a native subagent finishing:

```
Bash(command: "meight dispatch review-1 --sandbox ro --effort high --brief-file - <<'EOF' ... EOF",
     run_in_background: true)
→ ... Claude keeps working ...
→ <task-notification> exit 0, output contains the worker's full report
```

Every brief is automatically prefixed with a harness preamble that (a) forbids `git commit`/`push` — git stays owned by the orchestrator — and (b) instructs the worker to end with a `QUESTION:` paragraph instead of guessing when blocked. Disable with `--no-preamble`.

A drop-in orchestrator prompt (role split, routing table, dispatch protocol, cross-model review rules) ships as [`CLAUDE.md`](./CLAUDE.md) — copy it into your project or global Claude Code memory. A self-contained Claude Code **skill** ships at [`skills/meight/`](./skills/meight/SKILL.md) — copy it into `~/.claude/skills/` for trigger-based JIT loading.

## What "easy for an agent" actually means

Small decisions everywhere assume the user is an LLM agent, not a person at a terminal:

- **Exit codes are the API.** `0` done, `2` failed, `3` question, `4` daemon gone. The agent branches on a number instead of reading prose and guessing whether things worked. Unknown outcomes map to *failed*, never to *completed* — exit 0 can be trusted.
- **One call per intent.** `dispatch` bundles daemon startup, launch, waiting, and result delivery into a single background shell call — the same shape as the agent's native async tools. No polling loops burning turns.
- **Names, not session IDs.** Workers are addressed as `review-1`, follow-ups included. No UUID bookkeeping to get wrong.
- **Results survive on disk.** `result.md` stays re-readable — if the agent's context gets compacted mid-session, nothing is lost.
- **Status is pre-digested.** Instead of raw logs, `status` returns what a decision needs: what the worker is doing now, which files changed, its last thought. Exactly enough to choose between wait, steer, and interrupt.
- **Policy can't be forgotten.** The no-commit rule and the QUESTION protocol are injected into every brief by the harness, not remembered by the agent.
- **Briefs go through stdin.** Long multi-line briefs avoid shell-quoting traps entirely.

## Command reference

| Command | What it does |
|---|---|
| `meight dispatch <name> [opts]` | One-shot: auto-start daemon → start worker → wait → print result. The default workflow. |
| `meight reply <name> --brief ...` | One-shot answer to a worker question: follow + wait + print last-turn result |
| `meight status [name]` | Pull digest (table or detail). Reads disk — works without the daemon |
| `meight steer <name> "text"` | Inject instruction into the running turn (no work lost) |
| `meight interrupt <name>` | Cancel the running turn (idempotent) |
| `meight follow <name> --brief ...` | Low-level: new turn on the same thread (context preserved) |
| `meight start / wait / result / list / daemon / ping / shutdown` | Low-level building blocks of dispatch |

Options: `--cwd` (worker workdir — use separate git worktrees for overlapping file scopes), `--sandbox ws|ro|full` (default `ws` = workspace-write; reviews run `ro`), `--effort low|medium|high|xhigh` (default `medium`; raise by task complexity), `--model`, `--timeout`.

Worker state lives in `<repo>/.meight/workers/<name>/`: `brief.md`, `status.json` (state machine + tokens + files changed + last activity), `events.log` (one line per meaningful event), `result.md` (final message per turn). Add `.meight/` to your global gitignore.

## Good to know

- Meight inherits your `~/.codex/config.toml` as-is (model, MCP servers, auth) — under the hood the SDK runs a standard `codex app-server`. If `codex` works in your terminal, `meight` works.
- `openai-codex` is pinned (`0.1.0b3`, beta). When bumping, re-run the verification suite in [`SPEC.md`](./SPEC.md).
- Design details — the concurrency model, state machine, and orchestration policy — live in [`ARCHITECTURE.md`](./ARCHITECTURE.md).

## License

MIT
