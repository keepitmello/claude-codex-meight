# Decision Records

Durable output of consensus-mode direction decisions (see the Learning Loop
section of `skills/meight/SKILL.md`). One file per direction-setting fork,
named `YYYY-MM-DD-<slug>.md`:

```md
# <the question>
DATE: <date> · MODE: consensus|delegation
READ A (dispatcher): <one-paragraph position>
READ B (worker, blind|anchored): <one-paragraph position>
DISAGREEMENT: <where they split, or "none">
RESOLUTION: evidence|value-judgment — <what settled it>
DECISION: <what was chosen>
STATUS: adopted
```

Never delete a record; mark it `STATUS: superseded by <file>` instead.
