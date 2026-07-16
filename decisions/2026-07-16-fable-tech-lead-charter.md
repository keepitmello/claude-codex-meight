# What should the Fable dispatcher's system prompt be, now that steering doctrine exists?

DATE: 2026-07-16 · FORK: doctrine application (same-day continuation of the sol steering rewrite)

CONTEXT: `~/.claude/orchestrator.md` (injected via the `cs` alias) predated
Fable 5 and the steering doctrine. Known defects: subagent-definition
frontmatter naming nonexistent tools and a "MUST BE USED" subagent framing, a
dead skill reference (`Skill(spec-first)` — the real name is `Skill(spec)`), a
stale Skill Router table competing with harness-injected skill listings, and
prescriptive density the official Fable 5 prompting guide warns about
("skills developed for prior models are often too prescriptive for Claude
Fable 5 and can degrade output quality").

DECISION: Replaced by `~/.claude/tech-lead.md`; `cs`/`cs-codex` aliases
repointed (backup `~/.zshrc.bak-20260716`; rollback is a one-line alias
revert — `orchestrator.md` itself is untouched). Design principles:

- Layer split per the prompting-principles doctrine: persona and mass live in
  the output style and memory; this file is the role charter. Disposition is
  written as identity ("your seat is outside the frame"), guardrails stay
  imperative — positive framing for dispositions, negatives reserved for
  invariants.
- Steering section, generative before defensive: lead beyond the request
  ("the request is an entry point, not a boundary"; "saying is always in
  scope, doing waits for agreement"), the three-purchases value function
  (progress / open decision / record-strengthening), plan-as-hypothesis
  ("no longer worth doing" is a completion state), reframe-before-force
  ("your best moves are often reframings, not efforts"), and phase-bounded
  dispatch ("you are the fresh context that arrives on schedule").
- No mechanical safety nets, unlike sol's AGENTS.md: the dispatcher seat
  receives reassessment triggers structurally (every dispatch return is a
  physical event), so identity-level steering suffices where sol needed
  countable backstops.
- Kept verbatim as control points, not model hedges: Hard Gates (money-path,
  two-reads, blocked→consult, spec-first, pause criteria), Model Policy
  (downsize=Opus, negative-result rule), the verification chain, the meight
  pointer (now "two rails, one protocol": Agent tool + meight share brief /
  stop-rule / compressed-report discipline).
- Removed: harness-duplicated instructions, the Skill Router table, the
  frontmatter.

RATIONALE FOR "MORE DISPOSITION, FEWER RULES": explicit user feedback — wants
stronger metacognition, big-picture and creative leading ("point out what I
didn't see and steer the project there"), not more constraints. Regression
risk assessed as low: the outside-the-box quality users already observed never
came from orchestrator.md (it has no such language) — it comes from the model,
the persona layer, and the harness, all untouched. The rewrite removes
suppressors and lowers the threshold for beyond-request observations rather
than adding a capability.

VERIFY IN USE (N=1 observation; no proof is possible for disposition text):
frequency of unprompted beyond-request observations; reframe-before-force
behavior under blockage; absence of overreach (leading without agreement).
One real deletion to watch: the pre-emptive "hard implementation → consult"
gate was absorbed into blocked/two-reads routing — watch whether proactive
consult use drops. Rollback if these regress.

STATUS: adopted · further trimming expected (the user intends to keep carving
the Fable prompt)

Related: `decisions/2026-07-16-dual-dispatcher.md` (dispatcher seat decision,
same day), `~/.codex/guides/case-studies/2026-07-16-agents-steering-persona-rewrite.md`
(sol-side AGENTS.md rewrite plus the six-run blind A/B evidence that grounds
both documents).
