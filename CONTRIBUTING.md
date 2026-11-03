# Contributing

Small project, simple rules.

- **Topic packs** are the easiest contribution: add `plugins/learning-ledger/examples/<name>-topics.json` with ids matching `^[a-z0-9]+(-[a-z0-9]+)*$` and short English names. Keep packs to 10-25 topics that can be tested by a question or an exercise.
- **Ledger rules** live in `plugins/learning-ledger/scripts/ledger.py` and must have a test. A change must never let a level end up higher than the evidence supports.
- **Skills** are plain markdown in `plugins/learning-ledger/skills/`. Skills report evidence; they must not try to decide levels.
- Standard library only. No dependencies.

Run the tests before opening a PR:

```bash
python3 -m unittest discover -s tests
claude plugin validate .
```
