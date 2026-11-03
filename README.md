# learning-ledger

An honest evidence log for learning, as a [Claude Code](https://claude.com/claude-code) plugin.

Most AI tutors grade you, then decide how well you know the topic, and the same model is both judge and bookkeeper. Over time the record drifts upward: a topic you solved once with hints becomes "mastered".

`learning-ledger` splits the job. Claude runs the quizzes and exercises. A small, tested script keeps the record and **enforces the rules in code**, so the level cannot be inflated by wording:

- Solved with any help (hints, a minimal example, part of the solution)? The topic cannot be `autonomous`.
- Only your own opinion of how it went (`self_assessed`)? The level cannot go up.
- `consolidated` needs two distinct, unaided scenarios on separate working days. Repeating the same exercise does not count.
- A miss resets the consolidation progress.
- Reviews are scheduled in **working days** and skip your rest days (default: Saturday and Sunday).

Everything is stored locally in plain files. No account, no network, no dependencies beyond Python 3.

## Install

```bash
claude plugin marketplace add fabiozagaria/learning-ledger
claude plugin install learning-ledger@learning-ledger
```

For local development: `claude --plugin-dir ./plugins/learning-ledger`.

## Skills

| Skill | What it does |
|---|---|
| `/learning-ledger:study-today` | Reads the ledger and recommends one thing to study today. Read-only. |
| `/learning-ledger:quiz` | One question at a time, free recall, graded out of 30 before any explanation. Modes: quick quiz, interrogation, interview simulation, error review. |
| `/learning-ledger:practice` | Gives a brief (goal, constraints, success criteria) with no solution, then reviews your code and classifies findings as bug, risk, optional improvement or style. |
| `/learning-ledger:log-session` | Records the session. Shows a dry run (`before → after`, why a level was capped, next review weekday) and writes only after you confirm. |

## Quick start

1. Ask Claude: "what should I study today?" (`study-today`). On first use it offers to create the ledger and import a starter topic list (`examples/java-spring-topics.json`, about 23 Java/Spring topics) or you add your own.
2. Run `/learning-ledger:quiz` on a topic.
3. Run `/learning-ledger:log-session`. Review the dry run, confirm.

The ledger lives in `.learning-ledger/` in the directory where you run Claude (or set `LEARNING_LEDGER_DIR`). It is git-ignored by this repo's `.gitignore`; decide yourself whether to commit yours.

## The ledger script

`plugins/learning-ledger/scripts/ledger.py` is a standalone CLI (stdlib only). Output is JSON; errors are JSON on stderr with exit code 2.

```bash
python3 scripts/ledger.py init [--rest-days sat,sun]
python3 scripts/ledger.py topic add --id jpa-n-plus-one --name "N+1 queries" --area persistence
python3 scripts/ledger.py topic import examples/java-spring-topics.json
python3 scripts/ledger.py due
python3 scripts/ledger.py status
python3 scripts/ledger.py show jpa-n-plus-one
echo '{...}' | python3 scripts/ledger.py record --dry-run
```

Files: `topics.json` (current state), `sessions.jsonl` (append-only history), `config.json` (rest days).

### Levels

`not_assessed` < `fragile` < `with_support` < `autonomous` < `consolidated`

### Review intervals (working days)

Based on the `score_30` of the session when given, then capped by level: under 50% → 1, 50–59% → 2, 60–69% → 3, 70–84% → 7, 85–94% → 14, 95%+ → 30. `fragile` is capped at 3 and `with_support` at 5. Self-assessed sessions always review in 1. You can override with `interval_weekdays`.

## Tests

```bash
python3 -m unittest discover -s tests
```

## Limits

- Claude still does the grading of your answers; the script cannot verify that. It limits what a grade can *do* to the record, it does not make the grade objective.
- Evidence types and support levels are reported by the model from the conversation. Treat the ledger as an honest log, not an exam certificate.
- Single user, local files, no sync.

## License

MIT
