---
name: study-today
description: Reads the learning ledger and recommends what to study today: one concrete priority, based on what is due and overdue. Use when the user asks what to study, review or practice today, or at the start of a study session.
---

# study-today

Read-only. This skill never writes to the ledger.

```
LEDGER="python3 ${CLAUDE_PLUGIN_ROOT}/scripts/ledger.py"
```

## Steps

1. Run `$LEDGER status` and `$LEDGER due`.
   - Error "not initialized": offer `$LEDGER init`, then import a starter pack from `"${CLAUDE_PLUGIN_ROOT}/examples/"` with `$LEDGER topic import <file>` (`java-spring`, `python-core`, `sql-databases`, `system-design`, `devops-basics`; ask which fits), or adding their own topics with `topic add`. Stop there.
2. **If `rest_day` is true,** say it is a rest day, mention what is due next, and let the user decide. Do not push.
3. Otherwise recommend **one** priority:
   - the first item in `due` (already sorted: weakest level first, then oldest), or
   - if nothing is due, the most useful `unassessed` topic, or an item in `upcoming`.
   Say why in one or two sentences (level, how overdue, known `gaps`).
4. Offer the right next step: `/learning-ledger:quiz` for a due review, `/learning-ledger:practice` for a topic that needs applied work.
5. Add at most one line of context: how many topics are due, and how many are unassessed.

## Rules

- One priority, not a plan. Do not list everything that is due unless asked.
- Do not invent progress; only report what the ledger says.
- No guilt about overdue items. Overdue is a fact, not a verdict.
