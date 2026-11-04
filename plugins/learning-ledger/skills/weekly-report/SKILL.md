---
name: weekly-report
description: Summarizes the last week (or N days) of the learning ledger: sessions, time, how much was done without help, where levels were capped, and what is due. Read-only. Use when the user asks for a weekly summary, progress report, or "how did I do this week".
---

# weekly-report

Read-only. Never writes to the ledger.

```
PY=$(for c in python3 python py; do "$c" -c "import sys; sys.exit(sys.version_info[0] != 3)" 2>/dev/null && { echo "$c"; break; }; done)
LEDGER="$PY ${CLAUDE_PLUGIN_ROOT}/scripts/ledger.py"
```

If `$PY` is empty, no working Python 3 was found (on Windows `python3` is often a Microsoft Store stub that does not run). Tell the user to install Python 3 and stop; do not work around it.

## Steps

1. Run `$LEDGER report` (default 7 days; use `--days N` if the user asked for another window). If it errors with "not initialized", say there is nothing to report yet and point to `/learning-ledger:study-today`.
2. If `sessions` is 0, say so in one line and mention what is `due_now`. Stop.
3. Otherwise report, in short prose with at most one small table for topics:
   - sessions and minutes logged; how many sessions were fully unaided (`unaided_sessions`) versus supported (`by_support`)
   - topics touched with level movement (`from` → `to`) and how often a result was capped (`capped_topic_results`)
   - what is due now and how many topics are still unassessed
4. Add **one** observation the data actually supports (for example "3 of 4 sessions needed hints on transactions"). Do not invent trends from one week of data and do not praise or scold.
5. Suggest one next step: usually `/learning-ledger:quiz` on the weakest due topic.

## Rules

- Report only what the ledger says. If `from` is `unknown`, the session predates level tracking; say so instead of guessing.
- No motivational filler.
