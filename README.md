# claude-codex-meight

**English** | [한국어](./docs/README.ko.md)

> **An agent-first harness that lets Claude Code drive OpenAI Codex workers like native subagents** — built directly on the official `openai-codex` Python SDK. CLI: `meight`.

Most Claude↔Codex bridges are built for *humans watching terminals*: tmux panes to attach to, kanban boards to click, stdout to scrape. **Meight is built for the orchestrating agent itself.** The design question was never "what looks nice in a terminal" — it was *"what does Claude need so that dispatching a Codex worker feels exactly like spawning one of its own subagents?"*

The answer: one-shot dispatch with an exit-code contract, pull-based progress digests that cost ~zero context tokens, programmatic mid-turn steering, and a worker→orchestrator question protocol. All of it native — no tmux, no screen-scraping, no MCP indirection.

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

## Why this exists

As of June 2026, every public Claude↔Codex orchestration project wraps the Codex **CLI** — `codex exec` subprocesses or tmux `send-keys`. That generation of tooling cannot steer a running worker without killing it, cannot observe progress without streaming everything into the orchestrator's context window, and cannot let a worker ask a question.

OpenAI's official **`openai-codex` Python SDK** (released 2026-05) changed the substrate: it speaks JSON-RPC to `codex app-server` and exposes `TurnHandle.steer()` / `.interrupt()` / `.stream()` as public APIs, with one Codex process multiplexing N concurrent threads. **Meight is — to our knowledge — the first public harness built on it.** Everything the tmux generation faked, this does natively:

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

## Hardening

The concurrency layer (daemon singleton via `flock` + socket probe, per-worker control locks, turn generation-ids that drop stale stream events, a `needs_input` source distinction so tool-waits can't masquerade as final states) survived **five rounds of adversarial review by Codex itself** — 13 real defects found and fixed before v1. The full defect ledger is in [`ARCHITECTURE.md`](./ARCHITECTURE.md#hardening-history). Inherits your `~/.codex/config.toml` (model, MCP servers, auth) — the SDK spawns a standard `codex app-server` under the hood.

> ⚠️ `openai-codex` is pinned (`0.1.0b3`, beta). When bumping, re-run the verification suite in [`SPEC.md`](./SPEC.md).

## License

MIT
