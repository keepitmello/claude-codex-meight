# Should the dispatcher seat open to Codex (sol) sessions, and with what default?

DATE: 2026-07-16 · FORK: two-design (dispatcher analysis + blind sol research/design sessions)

ANALYSIS A (dispatcher, Claude): The dispatcher's job splits into enforcement
(brief contracts, verification gates — literal-reader strengths) and
recognition (noticing a dead plan, portfolio steering — frame-outside
strengths). Protocol absorbs most quality variance; the residual risk is
Type-B failure (continuing a dead direction past a phase boundary), where a
fresh-context, cross-model dispatcher is strongest.

DESIGN B (mate, blind): Codex app officially supports parent–child subagent
orchestration (`spawn_agent`/`send_input`/`wait_agent`/`close_agent`,
`features.multi_agent` stable, `max_depth` 1, `max_threads` 6). App sessions
have local shell access, so the existing `meight` CLI works unchanged from a
Codex main session — no second harness needed.

DISAGREEMENT: none — both converged on "one protocol, second runtime".

RESOLUTION: evidence — the 2026-07-16 six-run blind handover experiment showed
fresh-context sol steers correctly under either prompt (3/3 on both arms,
including the closed-decision dilemma). The dispatcher seat is structurally
fresh (compressed reports only), so sol qualifies for it. Cross-model
blind-spot decorrelation and long-project reassessment decay still favor
Claude for direction-sensitive work; user ergonomics also favor Claude as the
main seat.

DECISION: Default dispatcher stays a Claude Code (fable) session. A Codex
app/CLI (sol) session may dispatch through `~/.codex/skills/meight` — a thin
binding that points at this repo's `skills/meight/SKILL.md` — with a routing
line added to `~/.codex/AGENTS.md` Workflow routing. `max_depth` stays 1:
today's bottleneck is delegation quality, not delegation depth, and depth-2
workers would run outside dispatcher visibility.

Predictions to verify in production (not yet evidence): sol-dispatched runs
are equivalent on bounded work; watch for Type-B events and late-project
reassessment decay in long sol-dispatched projects. Enforcement-heavy
verification gates may be a sol-dispatcher strength.

STATUS: adopted

Related: `~/.codex/guides/case-studies/2026-07-16-agents-steering-persona-rewrite.md`
(same-day `~/.codex/AGENTS.md` steering rewrite plus the six-run A/B evidence).
