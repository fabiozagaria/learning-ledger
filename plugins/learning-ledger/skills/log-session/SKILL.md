---
name: log-session
description: Records a finished study or practice session in the local learning ledger, with honest support and evidence levels. Shows a dry-run (before → after, cap reasons, next review weekday) and writes only after the user confirms. Use after a quiz, exercise, debugging or review session, or when the user says "log this session".
---

# log-session

The ledger is a local file store (`.learning-ledger/`). A script enforces the maturity rules, so your job is to report the **evidence accurately**. You cannot raise a level by wording things generously, and you must not try.

```
PY=$(for c in python3 python py; do "$c" -c "import sys; sys.exit(sys.version_info[0] != 3)" 2>/dev/null && { echo "$c"; break; }; done)
LEDGER="$PY ${CLAUDE_PLUGIN_ROOT}/scripts/ledger.py"
```

If `$PY` is empty, no working Python 3 was found (on Windows `python3` is often a Microsoft Store stub that does not run). Tell the user to install Python 3 and stop; do not work around it.

## Steps

1. **Check the ledger exists:** `$LEDGER status`. If it errors with "not initialized", ask whether to run `$LEDGER init` (optionally `--rest-days sun`; the default rest days are Saturday and Sunday).
2. **Collect from the conversation**, asking only for what is missing:
   - `type`: review, new_topic, exercise, debugging, design, code_review, verification
   - `evidence`: `observed_answers` (you saw the learner answer), `observed_exercise` (you saw them do the work), `reviewed_code` (you reviewed code they wrote), `self_assessed` (they only say how it went)
   - `support`: the **strongest** help actually given in the session — `none`, `guiding_questions`, `hints`, `minimal_example`, `partial_solution`, `full_solution`. Questions and snippets used only to *verify* understanding are not support.
   - per topic: `id`, `outcome` (`fragile`, `with_support`, `autonomous`, `consolidated`) as your honest assessment, a short `scenario` (what concrete situation was used; reusing the same scenario does not count as new evidence), and `gaps` if they changed
   - optional: `score_30`, `duration_min`, `summary`, `autonomous_work`, `supported_work`, `key_errors`, `next_action`, `interval_weekdays` (override), `date` (defaults to today, never in the future)
   If a topic id does not exist yet, add it: `$LEDGER topic add --id <kebab-case> --name "<name>" --area <area>`.
3. **Build the JSON** and run a dry-run (never skip it):
   `echo '<json>' | $LEDGER record --dry-run`
4. **Show the result** per topic as `before → after`: level, next review (with weekday), any `reasons` (caps, resets, "not counted as deferred"), and consolidation progress like `1/2`. If a level was capped, say why in one sentence; do not argue with the script.
5. **Write only after the user says OK:** same command without `--dry-run`. If they want changes, rebuild the JSON and dry-run again.
6. Finish in two lines: what was recorded and what is next (the earliest next review).

## Rules

- Never claim a level above the evidence. If unsure between two levels, choose the lower one.
- `autonomous` and `consolidated` require `support: none`. `consolidated` additionally needs two distinct unaided scenarios on separate days; the script counts this, you do not.
- Do not record anything the user asked you not to record.
- Never put passwords, tokens or secrets in summaries.
- Do not edit `topics.json` or `sessions.jsonl` by hand.
- If the script returns an error, show the message and fix the input; do not work around it.
