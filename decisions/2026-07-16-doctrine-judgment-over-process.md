# Dispatcher doctrine will prefer judgment over process prescriptions

DATE: 2026-07-16 · FORK: operator-decided after model-capability re-evaluation

BACKGROUND: Anthropic's Fable 5 guidance warns that skills written for earlier
models can become too prescriptive and should be reviewed and reduced when the
new model performs better without those instructions. The operator applied that
guidance to meight's dispatcher-facing doctrine. The existing docs had grown a
specific development pipeline around the interface: fixed plan-review and code-
review cycles, mandatory disclosure when scaling gates down, and dispatcher
complete-diff reading as a final gate. Those choices were one operator's
workflow, not required meight semantics.

DECISION:

1. Dispatcher doctrine states principles and exposes tools rather than
   prescribing a default chain. Avoiding overengineering is the top priority.
   The dispatcher selects gates per task by failure cost and records the choice
   in one line.
2. Plan review and adversarial review remain available patterns. Their thread
   mechanics and `APPROVE`/`REVISE` decision-report encoding remain interface
   knowledge, but fixed round counts and mandatory pipeline placement do not.
3. Complete-diff reading is abolished as a sign-off requirement in every mode.
   For reviewed work, sign-off is the review verdict plus verification evidence.
   Worker-mode review is a separate dispatcher-spawned `--mode review` session
   when the dispatcher judges it warranted; delegate-mode review remains the
   contract's internal fresh-context reviewer.
4. `skills/meight/SKILL.md` is the only dispatcher-facing source for commands,
   exact `QUESTION` syntax, report schemas, and decision-mode encoding.
   `CLAUDE.md` and `AGENTS.md` point to it instead of duplicating the interface.
5. The drop-in dispatcher templates retain clearly marked, adjustable operator
   policy slots: model routing, failure-cost hard gates, money-path sign-off,
   and mode semantics. They do not present one operator's preferred workflow as
   a universal requirement.
6. Evidence-based completion, `NO-GO` blocker semantics, question ownership,
   decision/preference/lesson records, and daemon migration/runtime guidance
   remain intact.

RELATIONSHIP TO PRIOR DECISIONS: This decision keeps the four-mode axis and
worker/delegate ownership split adopted in
`2026-07-16-worker-delegate-split.md`. It supersedes that record only where it
assigned a dispatcher complete-diff read or fixed review-cycle behavior to
worker-mode sign-off. Session-side mate, worker, delegate, and common contracts
are intentionally unchanged.

STATUS: adopted
