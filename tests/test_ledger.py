import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPT = os.path.join(ROOT, "plugins", "learning-ledger", "scripts", "ledger.py")
sys.path.insert(0, os.path.dirname(SCRIPT))
import ledger as L  # noqa: E402

REST = ["sat", "sun"]


def topic(**kw):
    t = L.new_topic("T", "a")
    t.update(kw)
    return t


def payload(outcome="autonomous", support="none", evidence="observed_exercise",
            on="2026-11-02", scenario="A", tid="t", **kw):
    p = {"date": on, "type": "exercise", "support": support, "evidence": evidence,
         "topics": [{"id": tid, "outcome": outcome, "scenario": scenario}]}
    p.update(kw)
    return p


def rec(topics, p, today="2026-12-31", rest=REST):
    nt, session, reports = L.apply_record(topics, p, date.fromisoformat(today), rest)
    return nt, reports[0]


class DateMath(unittest.TestCase):
    def test_working_days_skip_weekend(self):
        d = date(2026, 11, 6)  # Friday
        self.assertEqual(L.add_working_days(d, 1, REST), date(2026, 11, 9))
        self.assertEqual(L.add_working_days(date(2026, 11, 4), 2, REST), date(2026, 11, 6))
        self.assertEqual(L.add_working_days(date(2026, 11, 5), 3, REST), date(2026, 11, 10))
        self.assertEqual(L.add_working_days(date(2026, 11, 7), 1, REST), date(2026, 11, 9))

    def test_without_rest_days(self):
        self.assertEqual(L.add_working_days(date(2026, 11, 6), 1, []), date(2026, 11, 7))

    def test_custom_rest_days(self):
        self.assertEqual(L.add_working_days(date(2026, 11, 5), 1, ["fri"]), date(2026, 11, 7))

    def test_between(self):
        self.assertEqual(L.working_days_between(date(2026, 11, 2), date(2026, 11, 5), REST), 3)
        self.assertEqual(L.working_days_between(date(2026, 11, 6), date(2026, 11, 9), REST), 1)
        self.assertEqual(L.working_days_between(date(2026, 11, 9), date(2026, 11, 2), REST), 0)

    def test_score_thresholds(self):
        cases = {0: 1, 14: 1, 15: 2, 17: 2, 18: 3, 20: 3, 21: 7, 25: 7, 26: 14,
                 28: 14, 29: 30, 30: 30}
        for score, days in cases.items():
            self.assertEqual(L.days_from_score(score), days, score)

    def test_rest_days_validation(self):
        with self.assertRaises(L.LedgerError):
            L.parse_rest_days("mon,tue,wed,thu,fri,sat,sun")
        with self.assertRaises(L.LedgerError):
            L.parse_rest_days("funday")
        self.assertEqual(L.parse_rest_days("sun, sat"), ["sat", "sun"])


class Levels(unittest.TestCase):
    def test_aided_cannot_be_autonomous(self):
        for s in ("hints", "guiding_questions", "full_solution"):
            _, r = rec({"t": topic()}, payload(support=s))
            self.assertEqual(r["after"]["level"], "with_support", s)
            self.assertTrue(r["capped"])

    def test_unaided_first_attempt_autonomous(self):
        _, r = rec({"t": topic()}, payload())
        self.assertEqual(r["after"]["level"], "autonomous")
        self.assertFalse(r["capped"])

    def test_self_assessed_never_raises(self):
        nt, r = rec({"t": topic()}, payload(evidence="self_assessed"))
        self.assertEqual(r["after"]["level"], "not_assessed")
        self.assertEqual(r["after"]["interval_weekdays"], 1)
        t = topic(level="fragile", last_attempt="2026-11-02", attempts=1)
        _, r = rec({"t": t}, payload(evidence="self_assessed", on="2026-11-03"))
        self.assertEqual(r["after"]["level"], "fragile")

    def test_self_assessed_can_lower(self):
        t = topic(level="autonomous", last_attempt="2026-11-02", attempts=1)
        _, r = rec({"t": t}, payload(outcome="fragile", evidence="self_assessed",
                                     on="2026-11-03"))
        self.assertEqual(r["after"]["level"], "fragile")

    def test_consolidation_sequence(self):
        topics = {"t": topic()}
        topics, r = rec(topics, payload(on="2026-11-02", scenario="A"))  # Mon
        self.assertEqual(r["after"]["level"], "autonomous")
        self.assertEqual(r["consolidation_progress"], "0/2")
        topics, r = rec(topics, payload(outcome="consolidated", on="2026-11-05",
                                        scenario="B"))  # Thu
        self.assertEqual(r["after"]["level"], "autonomous")
        self.assertTrue(r["capped"])
        self.assertEqual(r["consolidation_progress"], "1/2")
        topics, r = rec(topics, payload(outcome="consolidated", on="2026-11-10",
                                        scenario="C"))  # Tue
        self.assertEqual(r["after"]["level"], "consolidated")
        self.assertEqual(r["consolidation_progress"], "2/2")
        self.assertEqual(r["after"]["interval_weekdays"], 14)

    def test_repeated_scenario_does_not_count(self):
        topics = {"t": topic()}
        topics, _ = rec(topics, payload(on="2026-11-02", scenario="A"))
        topics, r = rec(topics, payload(on="2026-11-05", scenario="a"))
        self.assertEqual(r["consolidation_progress"], "0/2")

    def test_too_soon_does_not_count(self):
        topics = {"t": topic()}
        topics, _ = rec(topics, payload(on="2026-11-02", scenario="A"))
        topics, r = rec(topics, payload(on="2026-11-03", scenario="B"))
        self.assertEqual(r["consolidation_progress"], "0/2")

    def test_missing_scenario_does_not_count(self):
        topics = {"t": topic()}
        topics, _ = rec(topics, payload(on="2026-11-02", scenario="A"))
        topics, r = rec(topics, payload(on="2026-11-05", scenario=None))
        self.assertEqual(r["consolidation_progress"], "0/2")

    def test_aided_attempt_does_not_count(self):
        topics = {"t": topic()}
        topics, _ = rec(topics, payload(on="2026-11-02", scenario="A"))
        topics, r = rec(topics, payload(on="2026-11-05", scenario="B", support="hints"))
        self.assertEqual(r["consolidation_progress"], "0/2")

    def test_reset_on_miss(self):
        topics = {"t": topic()}
        topics, _ = rec(topics, payload(on="2026-11-02", scenario="A"))
        topics, r = rec(topics, payload(on="2026-11-05", scenario="B"))
        self.assertEqual(r["consolidation_progress"], "1/2")
        topics, r = rec(topics, payload(outcome="with_support", on="2026-11-10",
                                        support="hints", scenario="C"))
        self.assertEqual(r["consolidation_progress"], "0/2")
        self.assertEqual(r["after"]["level"], "with_support")

    def test_self_assessed_does_not_reset_or_count(self):
        topics = {"t": topic()}
        topics, _ = rec(topics, payload(on="2026-11-02", scenario="A"))
        topics, _ = rec(topics, payload(on="2026-11-05", scenario="B"))
        topics, r = rec(topics, payload(outcome="consolidated", on="2026-11-10",
                                        evidence="self_assessed", scenario="C"))
        self.assertEqual(r["consolidation_progress"], "1/2")
        self.assertEqual(r["after"]["level"], "autonomous")


class Intervals(unittest.TestCase):
    def test_score_drives_interval(self):
        _, r = rec({"t": topic()}, payload(score_30=27))
        self.assertEqual(r["after"]["interval_weekdays"], 14)
        self.assertEqual(r["after"]["next_review"], "2026-11-20")  # Mon + 14 wd

    def test_level_caps_interval(self):
        _, r = rec({"t": topic()}, payload(outcome="fragile", support="hints",
                                           score_30=29))
        self.assertEqual(r["after"]["interval_weekdays"], 3)
        _, r = rec({"t": topic()}, payload(outcome="with_support", support="hints",
                                           score_30=29))
        self.assertEqual(r["after"]["interval_weekdays"], 5)

    def test_level_default_without_score(self):
        _, r = rec({"t": topic()}, payload())
        self.assertEqual(r["after"]["interval_weekdays"], 7)

    def test_override_and_validation(self):
        _, r = rec({"t": topic()}, payload(interval_weekdays=2))
        self.assertEqual(r["after"]["interval_weekdays"], 2)
        for bad in (0, 91, 1.5, True):
            with self.assertRaises(L.LedgerError):
                rec({"t": topic()}, payload(interval_weekdays=bad))

    def test_weekend_session_lands_on_working_day(self):
        _, r = rec({"t": topic()}, payload(on="2026-11-07", outcome="fragile",
                                           support="hints"))
        self.assertEqual(r["after"]["next_review"], "2026-11-09")
        self.assertEqual(r["next_review_weekday"], "mon")


class Validation(unittest.TestCase):
    def bad(self, p, topics=None):
        with self.assertRaises(L.LedgerError):
            rec(topics or {"t": topic()}, p, today="2026-11-03")

    def test_errors(self):
        self.bad(payload(tid="nope"))
        self.bad(payload(on="2026-11-04"))           # future
        self.bad(payload(on="2026-13-01"))
        self.bad(payload(on="3/11/2026"))
        self.bad(payload(support="lots"))
        self.bad(payload(evidence="vibes"))
        self.bad(payload(outcome="genius"))
        self.bad(payload(outcome="not_assessed"))
        self.bad(payload(score_30=31))
        self.bad(payload(score_30=-1))
        self.bad(payload(duration_min=0))
        self.bad({"type": "review", "support": "none", "evidence": "observed_answers",
                  "topics": []})
        p = payload()
        p["topics"].append(dict(p["topics"][0]))
        self.bad(p)
        self.bad([])

    def test_chronology(self):
        t = topic(level="autonomous", last_attempt="2026-11-03", attempts=1)
        self.bad(payload(on="2026-11-02"), {"t": t})

    def test_input_not_mutated(self):
        topics = {"t": topic()}
        snapshot = json.dumps(topics, sort_keys=True)
        rec(topics, payload())
        self.assertEqual(json.dumps(topics, sort_keys=True), snapshot)

    def test_gaps_replace_only_when_given(self):
        topics = {"t": topic(gaps=["old"])}
        p = payload()
        topics2, _ = rec(topics, p)
        self.assertEqual(topics2["t"]["gaps"], ["old"])
        p["topics"][0]["gaps"] = ["new"]
        topics3, _ = rec(topics, p)
        self.assertEqual(topics3["t"]["gaps"], ["new"])


class Views(unittest.TestCase):
    def test_due_order_and_flags(self):
        topics = {
            "b": topic(level="autonomous", next_review="2026-11-02", attempts=1),
            "a": topic(level="fragile", next_review="2026-11-03", attempts=1),
            "c": topic(level="fragile", next_review="2026-11-02", attempts=1),
            "d": topic(),
            "e": topic(level="autonomous", next_review="2026-11-06", attempts=1),
            "f": topic(level="autonomous", next_review="2026-12-30", attempts=1),
        }
        v = L.build_due(topics, date(2026, 11, 3), REST)
        self.assertEqual([r["id"] for r in v["due"]], ["c", "a", "b"])
        self.assertEqual(v["due"][0]["overdue_working_days"], 1)
        self.assertEqual(v["due"][1]["overdue_working_days"], 0)
        self.assertEqual([r["id"] for r in v["unassessed"]], ["d"])
        self.assertEqual([r["id"] for r in v["upcoming"]], ["e"])
        self.assertFalse(v["rest_day"])
        self.assertTrue(L.build_due(topics, date(2026, 11, 7), REST)["rest_day"])

    def test_status(self):
        topics = {"a": topic(level="fragile", next_review="2026-11-02", attempts=1),
                  "b": topic()}
        s = L.build_status(topics, date(2026, 11, 3), REST)
        self.assertEqual(s["total_topics"], 2)
        self.assertEqual(s["by_level"]["fragile"], 1)
        self.assertEqual(s["due_count"], 1)
        self.assertEqual(s["unassessed_count"], 1)


class Cli(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.dir = os.path.join(self.tmp.name, "ledger")

    def tearDown(self):
        self.tmp.cleanup()

    def run_cli(self, *args, stdin=None, today="2026-11-03"):
        return subprocess.run(
            [sys.executable, "-I", SCRIPT, "--dir", self.dir, "--today", today,
             *args], input=stdin, capture_output=True, text=True)

    def read(self, name):
        with open(os.path.join(self.dir, name), encoding="utf-8") as f:
            return f.read()

    def test_flow(self):
        r = self.run_cli("init")
        self.assertEqual(r.returncode, 0, r.stderr)
        r = self.run_cli("init")  # idempotent
        self.assertEqual(json.loads(r.stdout)["created"], [])
        ex = os.path.join(ROOT, "plugins", "learning-ledger", "examples",
                          "java-spring-topics.json")
        r = self.run_cli("topic", "import", ex)
        self.assertEqual(r.returncode, 0, r.stderr)
        added = json.loads(r.stdout)["added"]
        self.assertGreaterEqual(len(added), 15)
        r = self.run_cli("topic", "import", ex)
        out = json.loads(r.stdout)
        self.assertEqual(out["added"], [])
        self.assertEqual(len(out["skipped"]), len(added))

        tid = added[0]
        p = json.dumps(payload(tid=tid, on="2026-11-02", support="hints",
                               outcome="autonomous"))
        before = self.read("topics.json")
        r = self.run_cli("record", "--dry-run", stdin=p)
        self.assertEqual(r.returncode, 0, r.stderr)
        rep = json.loads(r.stdout)
        self.assertTrue(rep["dry_run"])
        self.assertEqual(rep["reports"][0]["after"]["level"], "with_support")
        self.assertEqual(self.read("topics.json"), before)
        self.assertEqual(self.read("sessions.jsonl"), "")

        r = self.run_cli("record", stdin=p)
        self.assertEqual(r.returncode, 0, r.stderr)
        lines = self.read("sessions.jsonl").splitlines()
        self.assertEqual(len(lines), 1)
        r = self.run_cli("show", tid)
        self.assertEqual(len(json.loads(r.stdout)["recent_sessions"]), 1)
        r = self.run_cli("due")  # next review is Thu 2026-11-05
        self.assertEqual(json.loads(r.stdout)["due"], [])
        r = self.run_cli("due", today="2026-11-06")
        self.assertEqual(json.loads(r.stdout)["due"][0]["id"], tid)
        r = self.run_cli("status")
        self.assertEqual(json.loads(r.stdout)["by_level"]["with_support"], 1)

    def test_errors_exit_2_json(self):
        r = self.run_cli("due")
        self.assertEqual(r.returncode, 2)
        self.assertIn("error", json.loads(r.stderr))
        self.run_cli("init")
        r = self.run_cli("topic", "add", "--id", "Bad Id", "--name", "x")
        self.assertEqual(r.returncode, 2)
        r = self.run_cli("record", stdin="not json")
        self.assertEqual(r.returncode, 2)
        r = self.run_cli("show", "missing")
        self.assertEqual(r.returncode, 2)
        r = self.run_cli("--today", "nope", "due")
        self.assertNotEqual(r.returncode, 0)

    def test_topic_add_and_rest_days(self):
        self.run_cli("init", "--rest-days", "sun")
        cfg = json.loads(self.read("config.json"))
        self.assertEqual(cfg["rest_days"], ["sun"])
        r = self.run_cli("topic", "add", "--id", "jpa-basics", "--name", "JPA basics")
        self.assertEqual(r.returncode, 0)
        r = self.run_cli("topic", "add", "--id", "jpa-basics", "--name", "dup")
        self.assertEqual(r.returncode, 2)


if __name__ == "__main__":
    unittest.main()
