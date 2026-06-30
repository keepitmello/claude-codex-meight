---
name: meight
description: "Codex worker dispatch harness (global CLI: meight, repo: claude-codex-meight). Delegate implementation/review/runtime, browser QA, visual QA, computer-use, and image generation/editing work to N parallel Codex workers — supervised dispatch by default (start + sparse wait checkpoints + status/steer), one-shot dispatch for trivial safe tasks, bidirectional QUESTION protocol. Use whenever 루/the dispatcher delegates work to Codex. TRIGGERS: -코덱스 -meight -메이트 -mate -코덱스위임"
---

# meight (claude-codex-meight)

Harness for driving Codex workers in parallel from a Claude-side dispatcher — usable from any repo via the `meight` CLI. One global daemon is shared across repos; worker state is isolated per invoking repo under `<daemon-home>/repos/<repo-key>/`.

Codex worker-facing details live in [`skills/meight-worker/SKILL.md`](../meight-worker/SKILL.md); the harness preamble points workers there before work starts, while this skill remains the dispatcher-facing guide for supervising workers.

**Operating model (self-contained — works without any other prompt file):**
- **The dispatcher is 루 / the companion**: task decomposition, final integration/sign-off, user communication, and git coordination stay with 루. **Codex workers are tech leads, not just executors**: strong on details (races, type drift, edge cases, contract violations) and responsible for *how* the work is done. 루 owns what to build, why it matters, priority, UX, user-visible behavior, risk appetite, and final approval. Codex owns technical judgment, design, implementation, verification, and review loops. Run it two-way: pull a worker in to sounding-board a hard call, and expect workers to push back when they spot a better path or a wrong assumption.
- **Routing**: bounded implementation with a clear spec / code review / browser, visual, desktop, and runtime QA work → Codex workers. Exploration fan-out / fresh-context verification / harness-tool work → Claude subagents.
- **Independent review before accepting is mandatory — default to a Codex review worker**: every worker output gets an independent read, and the one non-negotiable is that the implementer never reviews its own work. There's no evidence cross-model reviews *better* than a fresh same-model read — independent context is what does the work — so:
  - **Default (single review) — fresh Codex review worker**: a *separate* worker from the implementer, adversarial `--sandbox ro`. This is the standard independent review for most work, including verifying Codex implementations. Cheaper and faster than spinning up a Claude agent.
  - **Important architecture / high-stakes / irreversible work — run both (A/B)**: dispatch the Codex review worker *and* a cross-model Claude agent in parallel, so two independent perspectives land on it. Not because cross-model is higher quality — because critical work deserves two reads instead of one.
  The trap this still closes: accepting a worker's "done" with no independent read at all.
- **Direction is set by two reads, never one**: when the work reaches a direction-setting branch — which approach, a design tradeoff, an architecture or diagnosis call, scope/sequencing, anything genuinely ambiguous — it gets **two independent analyses before you commit**: yours first (you analyze it directly — analysis is never outsourced), then a mandatory read-only Codex analysis of the *same* question, and you set direction by comparing the two reads. This is the sibling of cross-model review — review checks a finished artifact, this shapes the direction before the build — and like review, one side alone doesn't count: your reasoning alone is a claim, the cross-read makes it a decision. The trap it closes: deciding a direction-setting branch solo, without ever calling a worker. Run the Codex half via the **Consult** pattern below. (Trivial, unambiguous, or already-agreed calls don't need this.)
- **Verification still owns the outcome (owns what/why, not how)** — a worker's "done" is a claim, your verification makes it a fact. Workers may now run `git commit`/`git push` for their completed, verified work and report what they committed; you still own integration and final sign-off.
- **Two modes — pick one up front, ask the user if unsure**: **Collaborative** — use it for design, diagnosis, architecture, alternatives, and direction discussion. 루 and Codex think together, so exposing technical options is useful. **Delegated** — use it for bounded implementation, fixes, verification, and review. Codex owns the technical loop and reports only what 루 needs to decide or sign off. Mixing them is the failure mode: asking 루 to choose local technical details, or hiding a scope/UX/risk decision inside implementation. If the mode is not obvious, ask before dispatching.

## Default: supervised dispatch

For anything beyond trivial, short, low-risk work, drive the worker with `start` + `wait` instead of one blocking `dispatch`. The split is the whole point: while the worker runs you can pull `status` and `steer` it — one-shot `dispatch` shuts that door until the work is already done. *Whether* you check in, how often, and *whether* you steer are your judgment, not a fixed cadence — the aim is to keep the door open, not to micromanage.

```bash
# 1) Start only. This returns immediately after printing thread_id.
# If the daemon is not running, use `meight dispatch` for a one-shot auto-start,
# install/load the LaunchAgent, or start `meight daemon` in a background process.
# Do not run a foreground daemon in the main Claude Code turn.
meight start <name> --brief-file - --cwd <dir> \
  [--sandbox ws|ro|full, default full] [--effort low|medium|high|xhigh, default medium] <<'EOF'
<brief>
EOF

# 2) Wait as a checkpoint timer (set --timeout to roughly the expected duration). Timeout does NOT kill the worker.
#    Run wait via run_in_background — the backgrounded wait IS the push (no standalone daemon channel): its
#    exit fires a task-notification that wakes you, no turn spent. While running it auto-prints a status
#    heartbeat every 300s (--progress N to retune, 0 to disable) into the .output, so you read mid-run
#    progress without re-waiting. Foreground works but blocks your turn = waste.
meight wait <name> --timeout 300
# exit: 0=completed, 2=failed/interrupted/runtime-lost,
#       3=needs_input (worker question still attached and replyable),
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

**Timeout length = your check-in dial.** Near the full duration → mostly run-to-completion, wake at the end; a fraction (≈⅓–½) → deliberate mid-run checkpoints, re-waited. Set it by how close you want to stay, not a default number. Since wait auto-heartbeats progress (above), you rarely need a short timeout just for *visibility* — keep it long and read the heartbeat; shorten it only when you mean to *steer* mid-run.

### Checkpoint design: markers by default, gates only when earned

Set in the brief how the worker reports mid-run:
- **Marker (default):** emit a one-line `CHECKPOINT: …` at each phase boundary and keep going — never blocks; you read it via `status` at your dialed cadence. Progress stays legible without stopping the worker.
- **Gate (exception):** stop for approval (`needs_input`) only at a direction-setting branch where a wrong turn wastes everything downstream. Costs a round-trip and blocks the worker — spend only when you can name the wrong-turn it prevents.

Steer when `status` shows the worker drifting from the goal — and not during healthy progress, since needless intervention breaks its flow. What counts as drift is your judgment, not a checklist.

When the worker reaches a terminal state, `wait` returns immediately with `0` (completed), `2` (failed/interrupted/runtime-lost), or `3` (QUESTION that is still attached and replyable). `wait` prints a status summary; use `meight result <name>` for the full report or question. On exit `0`, get an independent review before accepting the work — a fresh Codex review worker by default, or both that and a cross-model Claude agent for critical/architecture work (see the review rule above). On exit `3`, answer with `reply`. If daemon restart or GC expired the same-thread session, `wait` returns `2` with `runtime_lost_detail`; start a fresh worker.

## One-shot dispatch only for trivial safe work

```bash
# Run this single call via Bash run_in_background only when supervision is not worth it.
meight dispatch <name> --brief-file - --cwd <dir> \
  [--sandbox ws|ro|full, default full] [--effort low|medium|high|xhigh, default medium] [--timeout 1800] <<'EOF'
<brief>
EOF
# exit: 0=completed, 2=failed/interrupted/runtime-lost, 3=replyable worker question, 4=daemon dead, 1=timeout
```

- `dispatch` still exists and is useful for small, bounded work: it auto-starts the daemon, starts the worker, waits, and prints the result in one call
- Add `--shutdown-when-idle` when a one-shot worker should ask the daemon to exit after a terminal result if no workers are active
- Do not use one-shot dispatch for substantial work that may need observation or steering
- Implementation: omit `--sandbox` (full is the default — no sandbox, so Codex can actively verify: builds, daemon restarts, writes outside cwd). Drop to `--sandbox ws` for write-scoped-to-cwd. Review & analysis: `--sandbox ro`
- Model: gpt-5.5 with non-Fast service tier by default. Pass `--fast` on `start`/`dispatch` only when that specific worker should use the priority tier; omitted or `--no-fast` stays on the cheaper non-priority tier. **Pick effort by complexity**: medium (default, routine implementation) / high (tricky implementation, code review, debugging) / xhigh (precision verification — concurrency, irreversible or hard-to-verify changes — and hard design)
- Thread visibility: workers start with `ephemeral=True` and `thread_source=subagent` by default so they stay out of Codex Desktop's main user-thread list. Use `--main-thread` only for tools that require a visible/main thread.
- N parallel workers OK. Overlapping file scopes → separate git worktrees via `--cwd`
- A harness preamble is auto-prepended to every brief: **workers may commit/push their verified work** + end with a `QUESTION:` paragraph only for decisions 루/the dispatcher must make or true blocks

## Consult a worker (sounding board, not just delegation)

The channel runs both ways. This is **also the Codex half of a direction-setting decision** (see "Direction is set by two reads" above) — on a direction-setting branch it's not an optional when-you're-stuck move but the required second read. And whenever *you* are stuck, unsure of an approach, or want to pressure-test a design before committing, dispatch a read-only consult instead of a build order:

```bash
meight start consult-x --sandbox ro --effort high --cwd <repo root> --brief-file - <<'EOF'
Thinking through <problem>. My current lean is <A>, but <concern>. Read <files> and tell me: is <A> sound, what am I missing, is there a better approach? No code changes — just your read and reasoning.
EOF
meight wait consult-x --timeout <expected>
# Refine direction together on the same thread:
meight follow consult-x --brief "Good point on Y. If we go that way, how does Z hold up?"
```

This is the sibling of cross-model review: review checks a finished artifact, consult shapes the thinking before or during the work. Fold what comes back into the direction — that's what a teammate is for.

## When a worker asks a question (exit 3)

A worker's `QUESTION:` isn't only "I'm blocked" — under the teammate preamble it's also how a worker flags a better approach, a shaky assumption, or a tradeoff that needs your call. Keep that channel narrow: `QUESTION:` is for decisions 루/the dispatcher must make, such as scope, UX, user-visible behavior, priority, risk appetite, irreversible action, or acceptance-criteria conflict. Technical uncertainty should be resolved with evidence first; local implementation choices should be decided by the worker and recorded as judgment calls, not escalated as questions. In supervised mode, read it with `meight status <name>` (`needs_input_detail`) or `meight result <name>`; in one-shot `dispatch`/`reply` it's in the printed result. Answer — or discuss back — in one shot:

```bash
# via run_in_background → completion notification carries the last-turn result (same exit-code contract as dispatch)
meight reply <name> --brief "answer" [--timeout 1800]
```

For low-level control use follow (starts the turn only) + wait + result. At most ~2 follow/reply turns per thread, then reset with a fresh brief. Same-thread follow requires the worker to still be attached to the current daemon; after daemon restart or terminal-worker GC, disk artifacts remain but follow is expired, so start a new worker.

## Status / steer / interrupt

```bash
meight status            # one-line table for this repo's workers (pull only — never stream)
meight list --all-repos  # global table across repo namespaces
meight status <name>     # current_item / plan / files_changed / tokens / last_message_tail / needs_input_source
meight steer <name> "instruction"   # mid-turn injection (no work lost; running turns only)
meight interrupt <name>             # cancel (idempotent)
```

`status` is part of the normal supervised loop, not a side channel. Use it at checkpoint wake-ups and after suspicious output. Running several workers at once? Pull the all-worker `status` table and only open up the ones that look off — don't wait on each one individually. `interrupt` is for clearly wrong or unsafe runs where steering is not enough.

## Daemon runtime checks

Meight runtime code is loaded into the long-lived daemon process. After changing `meight.py`, restart the daemon before trusting behavior from new workers; otherwise the old Python code can keep creating sessions with the old contract.

Useful checks:

```bash
MEIGHT_HOME="${MEIGHT_HOME:-$HOME/.meight}" meight ping
ps eww -axo pid,ppid,command | rg 'meight.py daemon|MEIGHT_IDLE_TIMEOUT_SEC|XPC_SERVICE_NAME=com.keepitmello.meight'
launchctl print "gui/$(id -u)/com.keepitmello.meight"  # if LaunchAgent is installed
meight list --all-repos --json
```

Hidden-session invariant:

- Default workers must have `"thread_source": "subagent"` and `"thread_ephemeral": true` in `status.json` / `meight status <name> --json`.
- Only explicit `--main-thread` workers may have `"thread_source": "user"` and `"thread_ephemeral": false`; those are expected to appear in Codex Desktop.
- If Codex Desktop still shows new meight workers, first check whether an old daemon is still running from a repo-local `.meight` home or an older process. Shut down stale meight daemons, then let `dispatch` auto-start the global daemon again.
- `meight status` reads disk and can work without the daemon; `steer`, `interrupt`, `follow`, and active runtime behavior require a live daemon.

## Review worker pattern

This is the **fresh Codex review worker** form of the review rule — and also the Codex side of cross-model review when Claude implemented. Use a *different* worker name than the implementer so the reviewer reads with fresh, independent context (never re-use the implementing worker — that's self-review).

```bash
meight start review-X --sandbox ro --effort high --cwd <repo root> --brief-file - <<'EOF'
Adversarial review. Target: <files>. Contract: <spec / PR description>.
Hunt for real defects ... For each finding: severity P1/P2/P3, file:line, why, fix direction.
End with verdict GO or NO-GO.
EOF
meight wait review-X --timeout 300
# After fixes, re-review on the same worker via follow/reply (context preserved)
```

## Self-reviewing implementation worker (keeps 루 out of the technical ping-pong)

The pattern above has *you* dispatch the reviewer and relay findings back to the implementer — useful, but it drags 루 through every implement↔review↔fix round and pollutes the dispatcher context with technical detail. For bounded implementation work, push that whole loop *inside* the implementing worker: it spawns its own independent reviewer, fixes the real defects, and hands back only what 루 needs to decide or sign off. 루 stays out of the technical execution and ping-pong, then does final sign-off (+ commit) only.

The implementer spawns a **genuinely independent** reviewer (verified: separate context, not self-review) via Codex's own sub-agent tool — `multi_agent_v1.spawn_agent(agent_type="reviewer", fork_context=false)` then `wait_agent`. `fork_context=false` is what makes it independent: the reviewer starts from its prompt only, not the implementer's working context.

Two guardrails are mandatory in the brief, or the loop runs away — an adversarial reviewer keeps finding deeper edge cases forever (observed: 3 straight NO-GOs on a trivial `slugify`):
- **Bound the loop**: at most ~2 review rounds; fix only P1 (real defects), record P2/P3 without fixing.
- **Abstract the report**: detailed findings, per-round review logs, command output, and reasoning go to a worker-unique evidence artifact such as `<worker-name>-evidence.md`; the report body stays concise and decision-oriented. Use a dashboard when it helps, but do not make the shape more important than the signal.
- **Keep sign-off evidence on the surface**: the report body must include `VERIFICATION` lines with `PASS` / `FAIL` / `NOT RUN` plus one short evidence note for each spec check or verification scenario. This summary is dispatcher sign-off evidence, not technical log spill.
- **Avoid cwd artifact collisions**: the worker-isolated `~/.meight/repos/.../workers/<name>/result.md` is the final message record, not a separate hidden detail channel. If a worker leaves non-code artifact documents in the task cwd — reports, analyses, evidence, handoffs, or similar files — never use fixed generic names like `result.md`. Parallel workers in the same cwd can overwrite each other and pollute the repo. Require worker-unique names such as `<worker-name>-evidence.md` or `<worker-name>-<short-topic>.md`, with the worker name as the prefix for every cwd artifact document. Code edits still go directly in their normal source paths; this naming rule is only for extra artifact documents in cwd.

Brief block to paste:

```
## Review & report protocol (required)
1. When implementation is done, spawn an independent reviewer via
   multi_agent_v1.spawn_agent(agent_type="reviewer", fork_context=false) + wait_agent.
   Adversarial review. At most 2 rounds.
2. Fix only P1 (real defects). Record P2/P3 — do not fix.
3. Put all detailed findings / per-round review logs / command output / technical reasoning in
   a worker-unique evidence artifact: <worker-name>-evidence.md. Make it self-contained for
   a follow-up worker with handoff, file/line evidence, verification commands, and open decisions.
   Never put technical logs in the report body; only the concise VERIFICATION summary belongs there.
   Do not use fixed generic cwd artifact names like result.md.
4. Report to 루 in whatever concise shape fits the task, but include these signals:
   - result: GO / NO-GO, or the plain-language equivalent
   - verification: PASS / FAIL / NOT RUN for the checks that matter, with one short evidence note
   - P1 blockers fixed or still open
   - decisions 루 must make: scope, UX, user-visible behavior, priority, risk appetite, irreversible action, or acceptance conflict; write "none" if none
   - files changed and commit/push status when relevant
   - where the detailed evidence artifact is
```

When to use which: **self-reviewing worker** = bounded implementation where Codex should own technical execution and keep 루 out of technical detail. **Separate review worker / cross-model A/B** (above) = high-stakes or architecture work where 루 should intentionally read the findings and weigh them.

## Writing briefs (template in README.md)

Goal / Scope / **Existing patterns (REQUIRED — without pointers Codex misdiagnoses existing patterns as defects)** / Constraints (domain rules only) / Verification / Report.

## Codex worker capabilities — reach past text-only coding

Codex workers aren't text-only coding agents. Tools vary by the worker's environment, auth, and sandbox, so **ask for the modality explicitly in the brief and require evidence** that it was used. Beyond core code work (implementation, risk/defect review, root-cause debugging, terminal/filesystem), these are the high-leverage modalities — reach for them *by name*, they're where Codex outruns a text-only agent:

- **Browser use**: open and click through localhost web apps — exercise real flows, verify responsive layouts, smoke-test features, capture screenshots. The actual app in a browser, not just unit tests.
- **Computer use**: operate desktop apps or OS UI when the task needs real application interaction rather than repository inspection.
- **Vision / screenshots**: inspect images and screenshots — catch layout overlap, text clipping, broken rendering, asset mismatches, visual regressions against mocks / Figma / production.
- **Asset & document work**: generate or edit images (mocks, sprites, UI or asset visuals); inspect / create / render PDFs, docs, CSV/XLSX.
- **Research**: current docs, APIs, release notes, pricing, policies — time-sensitive facts when browsing is available.
- **Connector-backed**: GitHub, Google Drive, Figma, Canva, Hugging Face, Sentry, and similar when the session has enabled them.

Combine evidence types before claiming UI / E2E / integration behavior is correct, and name the evidence you expect back: screenshot path, browser URL, visual-comparison notes, terminal/test output, source link, changed-asset path. Especially reach for a worker on: UI QA after frontend changes; localhost flows that need real clicking; fresh-context review after Claude implements (edge cases, concurrency, money-path, auth, data migration, external APIs); current-docs verification when an API/SDK/pricing/public fact may have changed; and cross-checking Claude's own visual / layout / product assumptions with an independent run.

## State / caveats

- Worker artifacts: `<daemon-home>/repos/<repo-key>/workers/<name>/{brief.md,status.json,events.log,result.md}`
- Low-level commands: daemon / start / wait / result / list / shutdown [--force] / launchd
- Lifecycle: foreground `MEIGHT_IDLE_TIMEOUT_SEC` default is 1800s, but `daemon --idle-timeout-sec 0` disables it. Managed `dispatch`/LaunchAgent starts pass idle disable through both env and daemon args; LaunchAgent jobs also infer managed mode from `XPC_SERVICE_NAME=com.keepitmello.meight` if an older loaded job lacks the env. Trust `meight ping`/startup log for the running value, not just the plist file. `MEIGHT_WORKER_GC_TTL_SEC` (default 3600s) removes terminal workers from daemon memory while keeping disk artifacts; after that, same-thread follow is expired
- High-stakes or irreversible work: never accept a worker's "done" on its word — require runtime evidence plus your own sign-off, always
- **Restart the daemon after editing meight.py** (a live daemon keeps running old code)
- Beta SDK (`openai-codex==0.1.0b3`, pinned): re-run the SPEC.md verification suite when upgrading
- Source & docs (README / SPEC / ARCHITECTURE): github.com/keepitmello/claude-codex-meight
