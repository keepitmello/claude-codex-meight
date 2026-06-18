---
name: meight
description: "Codex worker dispatch harness (global CLI: meight, repo: claude-codex-meight). Delegate implementation/review/runtime, browser QA, visual QA, computer-use, and image generation/editing work to N parallel Codex workers — supervised dispatch by default (start + sparse wait checkpoints + status/steer), one-shot dispatch for trivial safe tasks, bidirectional QUESTION protocol. Use whenever the orchestrator delegates work to Codex. TRIGGERS: -코덱스 -meight -메이트 -mate -코덱스위임"
---

# meight (claude-codex-meight)

Harness for driving Codex workers in parallel from a Claude orchestrator — usable from any repo via the `meight` CLI. Worker state is isolated per repo under `.meight/` (gitignored).

**Operating model (self-contained — works without any other prompt file):**
- **You (Claude) hold the direction**: task decomposition, integration, verification, user communication, and git. **Codex workers are teammates, not just executors**: strong on details (races, type drift, edge cases), often weaker on the big picture. So you own *what and why* and they own *how* — but run it two-way: pull a worker in to sounding-board a hard call or sketch the big picture together, and expect workers to push back when they spot a better path. Discuss and adjust more than you dictate. **And holding the direction is not deciding it alone**: when the work hits a fork that *sets* direction, you cross-read it with a Codex worker before committing (see "Direction is set by two reads, never one" below). "Teammates, not executors" means the hard calls are made together, not just the easy implementation handed off.
- **Routing**: bounded implementation with a clear spec / code review / browser, visual, desktop, and runtime QA work → Codex workers. Exploration fan-out / fresh-context verification / harness-tool work → Claude subagents.
- **Cross-model review is mandatory**: Codex implements → a Claude agent verifies; Claude implements → a Codex worker reviews. Same-model self-review doesn't count.
- **Direction is set by two reads, never one**: when the work reaches a fork that sets direction — which approach, a design tradeoff, an architecture or diagnosis call, scope/sequencing, anything genuinely ambiguous — it gets **two independent analyses before you commit**: yours first (you analyze it directly — analysis is never outsourced), then a mandatory read-only Codex analysis of the *same* question, and you set direction by comparing the two reads. This is the sibling of cross-model review — review checks a finished artifact, this shapes the direction before the build — and like review, one side alone doesn't count: your reasoning alone is a claim, the cross-read makes it a decision. The trap it closes: deciding a direction-setting branch solo, without ever calling a worker. Run the Codex half via the **Consult** pattern below. (Trivial, unambiguous, or already-agreed calls don't need this.)
- **Workers never commit** (the harness preamble enforces it) — review the working tree and commit yourself. A worker's "done" is a claim; your verification makes it a fact.

## Codex worker capabilities to use actively

Do not treat Codex workers as text-only coding agents. In this harness, a Codex worker can be a practical implementation, QA, research, and production teammate. The exact tools vary by active Codex environment, auth, and sandbox, so ask for a capability explicitly in the brief and require evidence if the worker used it.

Capability map:

- **Code implementation**: read the repo, edit files, follow existing patterns, run typechecks/tests/linters, and report exact files changed.
- **Code review / risk review**: inspect diffs or target files for real defects, edge cases, regressions, security risks, missing tests, and contract drift.
- **Debugging / root-cause analysis**: reproduce failures, inspect logs, trace source-to-sink paths, form hypotheses, and verify the primary fix path rather than only adding containment.
- **Terminal / filesystem work**: run local commands, inspect generated artifacts, compare diffs, create focused scripts when appropriate, and collect command output as evidence.
- **Vision / screenshots**: inspect uploaded or local images, compare screenshots, catch layout overlap, broken rendering, visual regressions, asset mismatches, text clipping, and visual polish issues.
- **Browser use**: open and exercise local web apps, click/type through flows, capture screenshots, verify responsive layouts, inspect browser-visible runtime behavior, and smoke-test localhost features.
- **Computer use**: operate desktop apps or OS UI when the task needs real application interaction rather than repository inspection.
- **Image generation / editing**: create or modify bitmap assets, mocks, sprites, visual references, product imagery, UI imagery, and other generated visuals when the task needs them.
- **Web / current-info research**: look up current docs, APIs, release notes, pricing, policies, or other time-sensitive facts when browsing is available or required.
- **Document / PDF / spreadsheet work**: inspect, create, edit, render, or verify docs, PDFs, CSV/XLSX files, and similar artifacts when the environment provides those tools.
- **Design / product QA**: review UX flows, frontend design quality, accessibility risks, responsive behavior, copy clarity, and whether the screen matches the product intent.
- **Connector-backed work**: use available apps/connectors such as GitHub, Google Drive, Figma, Canva, Hugging Face, Sentry, or similar tools when the user/session has enabled them.
- **Runtime QA**: combine terminal evidence with browser, screenshot, desktop, or artifact evidence before claiming UI, visual, end-to-end, or integration behavior is correct.

When delegating these tasks, say the modality explicitly in the brief: e.g. "use browser QA and screenshots", "inspect the attached image visually", "use computer-use if the desktop app must be operated", "generate/edit an image asset if needed", or "browse official docs for the current API contract". Also name the expected evidence: screenshot path, browser URL, visual comparison notes, terminal command, test output, source link, changed asset path, or artifact path.

Use Codex workers especially for:

- UI QA after frontend changes, including mobile/desktop screenshots, overlap checks, text clipping checks, and interactive smoke tests
- Localhost flows that require clicking through the app, not just running unit tests
- Visual regression checks against screenshots, mocks, screenshots from production, or a Figma/Canva reference
- Visual asset creation or polish when a mock, sprite, generated image, hero image, or product visual would unblock implementation
- Desktop-app verification where browser or CLI evidence is insufficient
- End-to-end verification that needs multiple evidence types, such as tests plus browser screenshots plus logs
- Cross-checking Claude's visual/layout/product assumptions with an independent Codex run
- Fresh-context code review after Claude implements, especially for edge cases, concurrency, money-path, auth, data migration, or external API changes
- Current-docs verification when an API, SDK, browser behavior, law, pricing, product feature, or public fact may have changed
- Artifact work such as PDFs, docs, spreadsheets, exported reports, generated images, or screenshots where visual/rendered output matters

## Default: supervised dispatch

For anything beyond trivial, short, low-risk work, drive the worker with `start` + `wait` instead of one blocking `dispatch`. The split is the whole point: while the worker runs you can pull `status` and `steer` it — one-shot `dispatch` shuts that door until the work is already done. *Whether* you check in, how often, and *whether* you steer are your judgment, not a fixed cadence — the aim is to keep the door open, not to micromanage.

```bash
# 1) Start only. This returns immediately after printing thread_id.
# If the daemon is not running, start the per-repo daemon separately first.
meight start <name> --brief-file - --cwd <dir> \
  [--sandbox ws|ro|full, default ws] [--effort low|medium|high|xhigh, default medium] <<'EOF'
<brief>
EOF

# 2) Wait as a checkpoint timer (set --timeout to roughly the expected duration). Timeout does NOT kill the worker.
meight wait <name> --timeout 300
# exit: 0=completed, 2=failed/interrupted, 3=needs_input (worker question),
#       4=daemon dead, 1=checkpoint timeout while worker continues

# 3) On exit 1, inspect once and decide.
meight status <name>
# Look at current_item / plan / files_changed / tokens / last_message_tail / needs_input_source.

# 4) If healthy, wait again. If drifting, steer once, then wait again.
meight steer <name> "correction"
meight wait <name> --timeout 300

# On terminal/question exits, read the full worker message from disk.
meight result <name>
```

Set `--timeout` to roughly how long you expect the work to take. Finishes inside that window → you get the completion push and never spend a turn checking. Overruns → the timeout wakes you, and an overrun is itself a signal worth one `status` look. There's no fixed interval and no obligation to check — a sparse wake-up, then your call: wait again, steer, or just let it run. Never busy-poll (checking every few seconds burns turns for nothing).

Steer when `status` shows the worker drifting from the goal — and not during healthy progress, since needless intervention breaks its flow. What counts as drift is your judgment, not a checklist.

When the worker reaches a terminal state, `wait` returns immediately with `0` (completed), `2` (failed/interrupted), or `3` (QUESTION). `wait` prints a status summary; use `meight result <name>` for the full report or question. On exit `0`, cross-model verify before accepting the work. On exit `3`, answer with `reply`.

## One-shot dispatch only for trivial safe work

```bash
# Run this single call via Bash run_in_background only when supervision is not worth it.
meight dispatch <name> --brief-file - --cwd <dir> \
  [--sandbox ws|ro|full, default ws] [--effort low|medium|high|xhigh, default medium] [--timeout 1800] <<'EOF'
<brief>
EOF
# exit: 0=completed, 2=failed/interrupted, 3=needs_input (worker question), 4=daemon dead, 1=timeout
```

- `dispatch` still exists and is useful for small, bounded work: it auto-starts the daemon, starts the worker, waits, and prints the result in one call
- Do not use one-shot dispatch for substantial work that may need observation or steering
- Implementation: omit `--sandbox` (ws is the default). Review & analysis: `--sandbox ro`
- Model: gpt-5.5 + Fast (priority tier, inherited from ~/.codex/config.toml). Toggle it per worker with `--fast`/`--no-fast` on `start`/`dispatch` (`--no-fast` = cheaper non-priority tier; omit to inherit config). **Pick effort by complexity**: medium (default, routine implementation) / high (tricky implementation, code review, debugging) / xhigh (precision verification — concurrency, irreversible or hard-to-verify changes — and hard design)
- N parallel workers OK. Overlapping file scopes → separate git worktrees via `--cwd`
- A harness preamble is auto-prepended to every brief: **no commit/push** + end with a `QUESTION:` paragraph when blocked

## Writing briefs (template in README.md)

Goal / Scope / **Existing patterns (REQUIRED — without pointers Codex misdiagnoses existing patterns as defects)** / Constraints (domain rules only) / Verification / Report.

## When a worker asks a question (exit 3)

A worker's `QUESTION:` isn't only "I'm blocked" — under the teammate preamble it's also how a worker flags a better approach, a shaky assumption, or a tradeoff that needs your call. Treat it as a discussion opener, not just an unblock request. In supervised mode, read it with `meight status <name>` (`needs_input_detail`) or `meight result <name>`; in one-shot `dispatch`/`reply` it's in the printed result. Answer — or discuss back — in one shot:

```bash
# via run_in_background → completion notification carries the last-turn result (same exit-code contract as dispatch)
meight reply <name> --brief "answer" [--timeout 1800]
```

For low-level control use follow (starts the turn only) + wait + result. At most ~2 follow/reply turns per thread, then reset with a fresh brief. After a daemon restart existing workers cannot be followed → start under a new name.

## Status / steer / interrupt

```bash
meight status            # one-line table for all workers (pull only — never stream)
meight status <name>     # current_item / plan / files_changed / tokens / last_message_tail / needs_input_source
meight steer <name> "instruction"   # mid-turn injection (no work lost; running turns only)
meight interrupt <name>             # cancel (idempotent)
```

`status` is part of the normal supervised loop, not a side channel. Use it at checkpoint wake-ups and after suspicious output. Running several workers at once? Pull the all-worker `status` table and only open up the ones that look off — don't wait on each one individually. `interrupt` is for clearly wrong or unsafe runs where steering is not enough.

## Consult a worker (sounding board, not just delegation)

The channel runs both ways. This is **also the Codex half of a decision fork** (see "Direction is set by two reads" above) — on a direction-setting branch it's not an optional when-you're-stuck move but the required second read. And whenever *you* are stuck, unsure of an approach, or want to pressure-test a design before committing, dispatch a read-only consult instead of a build order:

```bash
meight start consult-x --sandbox ro --effort high --cwd <repo root> --brief-file - <<'EOF'
Thinking through <problem>. My current lean is <A>, but <concern>. Read <files> and tell me: is <A> sound, what am I missing, is there a better approach? No code changes — just your read and reasoning.
EOF
meight wait consult-x --timeout <expected>
# Refine direction together on the same thread:
meight follow consult-x --brief "Good point on Y. If we go that way, how does Z hold up?"
```

This is the sibling of cross-model review: review checks a finished artifact, consult shapes the thinking before or during the work. Fold what comes back into the direction — that's what a teammate is for.

## Review worker pattern

```bash
meight start review-X --sandbox ro --effort high --cwd <repo root> --brief-file - <<'EOF'
Adversarial review. Target: <files>. Contract: <spec / PR description>.
Hunt for real defects ... For each finding: severity P1/P2/P3, file:line, why, fix direction.
End with verdict GO or NO-GO.
EOF
meight wait review-X --timeout 300
# After fixes, re-review on the same worker via follow/reply (context preserved)
```

## State / caveats

- Worker artifacts: `<repo>/.meight/workers/<name>/{brief.md,status.json,events.log,result.md}`
- Low-level commands: daemon / start / wait / result / list / shutdown [--force]
- High-stakes or irreversible work: never accept a worker's "done" on its word — require runtime evidence plus your own sign-off, always
- **Restart the daemon after editing meight.py** (a live daemon keeps running old code)
- Beta SDK (`openai-codex==0.1.0b3`, pinned): re-run the SPEC.md verification suite when upgrading
- Source & docs (README / SPEC / ARCHITECTURE): github.com/keepitmello/claude-codex-meight
