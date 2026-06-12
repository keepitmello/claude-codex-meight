---
name: meight
description: "Codex worker dispatch harness (global CLI: meight, repo: claude-codex-meight). Delegate implementation/review/runtime work to N parallel Codex workers — one-shot dispatch (auto-daemon + result push), disk-digest observation (status pull), mid-turn steer, bidirectional QUESTION protocol. Use whenever the orchestrator delegates work to Codex. TRIGGERS: -코덱스 -meight -메이트 -mate -코덱스위임"
---

# meight (claude-codex-meight)

Harness for driving Codex workers in parallel from a Claude orchestrator — usable from any repo via the `meight` CLI. Worker state is isolated per repo under `.meight/` (gitignored).

**Operating model (self-contained — works without any other prompt file):**
- **You (Claude) are the tech lead**: own direction, task decomposition, integration, verification, user communication, and git. **Codex workers are your implementers/reviewers**: strong on details (races, type drift, edge cases), weaker on big-picture — you decide *what and why*, workers execute *how*.
- **Routing**: bounded implementation with a clear spec / code review / browser & runtime work → Codex workers. Exploration fan-out / fresh-context verification / harness-tool work → Claude subagents.
- **Cross-model review is mandatory**: Codex implements → a Claude agent verifies; Claude implements → a Codex worker reviews. Same-model self-review doesn't count.
- **Workers never commit** (the harness preamble enforces it) — review the working tree and commit yourself. A worker's "done" is a claim; your verification makes it a fact.

## Default: one-shot dispatch

```bash
# Run this single call via Bash run_in_background → the completion notification carries the full result
meight dispatch <name> --brief-file - --cwd <dir> \
  [--sandbox ws|ro|full] [--effort low|medium|high|xhigh, default medium] [--timeout 1800] <<'EOF'
<brief>
EOF
# exit: 0=completed, 2=failed/interrupted, 3=needs_input (worker question), 4=daemon dead, 1=timeout
```

- The daemon auto-starts on dispatch — no lifecycle management (one independent daemon per repo)
- Implementation = `--sandbox ws` (default) / review & analysis = `--sandbox ro`
- Model: gpt-5.5 + Fast (priority tier, inherited from ~/.codex/config.toml). **Pick effort by complexity**: medium (default, routine implementation) / high (tricky implementation, code review, debugging) / xhigh (precision verification — concurrency, money-path — and hard design)
- N parallel workers OK. Overlapping file scopes → separate git worktrees via `--cwd`
- A harness preamble is auto-prepended to every brief: **no commit/push** + end with a `QUESTION:` paragraph when blocked

## Writing briefs (template in README.md)

Goal / Scope / **Existing patterns (REQUIRED — without pointers Codex misdiagnoses existing patterns as defects)** / Constraints (domain rules only) / Verification / Report.

## When a worker asks a question (exit 3)

The question is already in the dispatch output (result). Answer in one shot:

```bash
# via run_in_background → completion notification carries the last-turn result (same exit-code contract as dispatch)
meight reply <name> --brief "answer" [--timeout 1800]
```

For low-level control use follow (starts the turn only) + wait + result. At most ~2 follow/reply turns per thread, then reset with a fresh brief. After a daemon restart existing workers cannot be followed → start under a new name.

## Observe / steer

```bash
meight status            # one-line table for all workers (pull only — never stream)
meight status <name>     # current_item / plan / files_changed / tokens / last_message_tail / needs_input_source
meight steer <name> "instruction"   # mid-turn injection (no work lost; running turns only)
meight interrupt <name>             # cancel (idempotent)
```

## Review dispatch pattern

```bash
meight dispatch review-X --sandbox ro --effort high --cwd <repo root> --brief-file - <<'EOF'
Adversarial review. Target: <files>. Contract: <spec / PR description>.
Hunt for real defects ... For each finding: severity P1/P2/P3, file:line, why, fix direction.
End with verdict GO or NO-GO.
EOF
# After fixes, re-review on the same worker via follow/reply (context preserved)
```

## State / caveats

- Worker artifacts: `<repo>/.meight/workers/<name>/{brief.md,status.json,events.log,result.md}`
- Low-level commands: daemon / start / wait / result / list / shutdown [--force]
- Money-path work: worker result + runtime evidence + orchestrator sign-off, always
- **Restart the daemon after editing meight.py** (a live daemon keeps running old code)
- Beta SDK (`openai-codex==0.1.0b3`, pinned): re-run the SPEC.md verification suite when upgrading
- Source & docs (README / SPEC / ARCHITECTURE): github.com/keepitmello/claude-codex-meight
