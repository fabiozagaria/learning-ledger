#!/usr/bin/env python3
"""learning-ledger: an honest, local evidence log for learning.

Stdlib only. All output is JSON on stdout. Errors are JSON on stderr, exit 2.

The point of this script is that the maturity rules live in code, not in a
prompt: a model cannot talk its way into marking a topic "autonomous" when the
evidence does not support it.

Files (in the ledger directory):
  topics.json     current state of every topic
  sessions.jsonl  append-only history, one JSON object per line
  config.json     settings (rest days)
"""
import argparse
import json
import os
import re
import sys
import tempfile
from datetime import date, datetime, timedelta

WEEKDAYS = ["mon", "tue", "wed", "thu", "fri", "sat", "sun"]
LEVELS = ["not_assessed", "fragile", "with_support", "autonomous", "consolidated"]
LEVEL_RANK = {name: i for i, name in enumerate(LEVELS)}
CLAIMABLE = LEVELS[1:]
SUPPORT = ["none", "guiding_questions", "hints", "minimal_example",
           "partial_solution", "full_solution"]
EVIDENCE = ["observed_answers", "observed_exercise", "reviewed_code", "self_assessed"]
SESSION_TYPES = ["review", "new_topic", "exercise", "debugging", "design",
                 "code_review", "verification"]

MIN_DEFERRED_GAP = 2        # working days since the previous attempt
CONSOLIDATION_TARGET = 2    # distinct unaided deferred scenarios
LEVEL_DEFAULT_DAYS = {"not_assessed": 1, "fragile": 1, "with_support": 3,
                      "autonomous": 7, "consolidated": 14}
LEVEL_MAX_DAYS = {"not_assessed": 1, "fragile": 3, "with_support": 5}
DEFAULT_REST_DAYS = ["sat", "sun"]

ID_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


class LedgerError(Exception):
    pass


# ---------------------------------------------------------------- dates

def parse_date(value, what="date"):
    if not isinstance(value, str) or not DATE_RE.match(value):
        raise LedgerError(f"{what} must be YYYY-MM-DD, got {value!r}")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise LedgerError(f"{what} is not a real date: {value!r}")


def rest_set(rest_days):
    return {WEEKDAYS.index(d) for d in rest_days}


def add_working_days(start, n, rest_days):
    """Date reached after n working days, counting from the day after start."""
    if n < 1:
        raise LedgerError("interval must be at least 1 working day")
    rest = rest_set(rest_days)
    d = start
    left = n
    while left > 0:
        d += timedelta(days=1)
        if d.weekday() not in rest:
            left -= 1
    return d


def working_days_between(a, b, rest_days):
    """Working days in (a, b]. 0 if b <= a."""
    rest = rest_set(rest_days)
    count = 0
    d = a
    while d < b:
        d += timedelta(days=1)
        if d.weekday() not in rest:
            count += 1
    return count


def weekday_name(d):
    return WEEKDAYS[d.weekday()]


def days_from_score(score_30):
    pct = score_30 / 30 * 100
    if pct < 50:
        return 1
    if pct < 60:
        return 2
    if pct < 70:
        return 3
    if pct < 85:
        return 7
    if pct < 95:
        return 14
    return 30


# ---------------------------------------------------------------- storage

class Store:
    def __init__(self, directory):
        self.dir = directory
        self.topics_path = os.path.join(directory, "topics.json")
        self.sessions_path = os.path.join(directory, "sessions.jsonl")
        self.config_path = os.path.join(directory, "config.json")

    def require(self):
        if not os.path.isfile(self.topics_path):
            raise LedgerError(
                f"ledger not initialized in {self.dir!r}; run the init command first")

    def load_topics(self):
        self.require()
        with open(self.topics_path, encoding="utf-8") as f:
            return json.load(f)["topics"]

    def load_config(self):
        if not os.path.isfile(self.config_path):
            return {"rest_days": list(DEFAULT_REST_DAYS)}
        with open(self.config_path, encoding="utf-8") as f:
            return json.load(f)

    def save_topics(self, topics):
        atomic_write(self.topics_path, json.dumps({"topics": topics}, indent=2,
                                                  ensure_ascii=False) + "\n")

    def append_session(self, entry):
        with open(self.sessions_path, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def load_sessions(self):
        if not os.path.isfile(self.sessions_path):
            return []
        out = []
        with open(self.sessions_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    out.append(json.loads(line))
        return out


def atomic_write(path, text):
    d = os.path.dirname(os.path.abspath(path))
    fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def new_topic(name, area):
    return {"name": name, "area": area, "level": "not_assessed",
            "last_attempt": None, "next_review": None, "interval_weekdays": None,
            "gaps": [], "scenarios_seen": [], "deferred_scenarios": [],
            "attempts": 0}


def parse_rest_days(value):
    days = [d.strip().lower() for d in value.split(",") if d.strip()]
    for d in days:
        if d not in WEEKDAYS:
            raise LedgerError(f"unknown weekday {d!r}; use {', '.join(WEEKDAYS)}")
    if len(set(days)) >= 7:
        raise LedgerError("rest days cannot cover the whole week")
    return sorted(set(days), key=WEEKDAYS.index)


# ---------------------------------------------------------------- record

def _check_enum(payload, key, allowed, required=True):
    value = payload.get(key)
    if value is None:
        if required:
            raise LedgerError(f"missing required field {key!r}")
        return None
    if value not in allowed:
        raise LedgerError(f"{key} must be one of {allowed}, got {value!r}")
    return value


def _check_str_list(payload, key):
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, list) or not all(isinstance(x, str) for x in value):
        raise LedgerError(f"{key} must be a list of strings")
    return value


def validate_payload(payload, today):
    if not isinstance(payload, dict):
        raise LedgerError("record payload must be a JSON object")
    p = {}
    p["date"] = parse_date(payload.get("date", today.isoformat()), "date")
    if p["date"] > today:
        raise LedgerError(f"session date {p['date']} is in the future (today is {today})")
    p["type"] = _check_enum(payload, "type", SESSION_TYPES)
    p["support"] = _check_enum(payload, "support", SUPPORT)
    p["evidence"] = _check_enum(payload, "evidence", EVIDENCE)

    score = payload.get("score_30")
    if score is not None:
        if isinstance(score, bool) or not isinstance(score, (int, float)) \
                or not 0 <= score <= 30:
            raise LedgerError("score_30 must be a number between 0 and 30")
    p["score_30"] = score

    dur = payload.get("duration_min")
    if dur is not None and (isinstance(dur, bool) or not isinstance(dur, int) or dur < 1):
        raise LedgerError("duration_min must be a positive integer")
    p["duration_min"] = dur

    override = payload.get("interval_weekdays")
    if override is not None and (isinstance(override, bool)
                                 or not isinstance(override, int)
                                 or not 1 <= override <= 90):
        raise LedgerError("interval_weekdays must be an integer between 1 and 90")
    p["interval_weekdays"] = override

    for key in ("summary", "next_action"):
        v = payload.get(key)
        if v is not None and not isinstance(v, str):
            raise LedgerError(f"{key} must be a string")
        p[key] = v
    for key in ("autonomous_work", "supported_work", "key_errors"):
        p[key] = _check_str_list(payload, key)

    topics = payload.get("topics")
    if not isinstance(topics, list) or not topics:
        raise LedgerError("topics must be a non-empty list")
    seen = set()
    p["topics"] = []
    for t in topics:
        if not isinstance(t, dict):
            raise LedgerError("each topic entry must be an object")
        tid = t.get("id")
        if not isinstance(tid, str) or not tid:
            raise LedgerError("each topic entry needs an 'id'")
        if tid in seen:
            raise LedgerError(f"duplicate topic id in one session: {tid!r}")
        seen.add(tid)
        outcome = _check_enum(t, "outcome", CLAIMABLE)
        scenario = t.get("scenario")
        if scenario is not None and not isinstance(scenario, str):
            raise LedgerError("scenario must be a string")
        gaps = _check_str_list(t, "gaps")
        p["topics"].append({"id": tid, "outcome": outcome,
                            "scenario": scenario, "gaps": gaps})
    return p


def _snapshot(t):
    return {"level": t["level"], "last_attempt": t["last_attempt"],
            "next_review": t["next_review"],
            "interval_weekdays": t["interval_weekdays"],
            "gaps": list(t["gaps"]), "attempts": t["attempts"]}


def apply_topic(topic, entry, p, rest_days):
    """Return (new_topic, report) without touching the input."""
    t = json.loads(json.dumps(topic))
    before = _snapshot(t)
    reasons = []
    claimed = entry["outcome"]
    on = p["date"]
    observed = p["evidence"] != "self_assessed"

    if t["last_attempt"] is not None:
        last = parse_date(t["last_attempt"], "stored last_attempt")
        if on < last:
            raise LedgerError(
                f"topic {entry['id']!r}: session date {on} is before its last attempt {last}")
        gap = working_days_between(last, on, rest_days)
    else:
        gap = None

    scenario = (entry["scenario"] or "").strip().lower() or None
    level = claimed

    if not observed:
        prev = t["level"]
        level = claimed if LEVEL_RANK[claimed] <= LEVEL_RANK[prev] else prev
        if level != claimed:
            reasons.append(
                f"self-assessed evidence cannot raise the level; kept {prev} "
                f"(claimed {claimed})")
        else:
            reasons.append("self-assessed: level not raised, review in 1 working day")
    else:
        if LEVEL_RANK[level] >= LEVEL_RANK["autonomous"] and p["support"] != "none":
            level = "with_support"
            reasons.append(
                f"support was {p['support']}; autonomous/consolidated need support none, "
                f"capped to with_support (claimed {claimed})")

        unaided = p["support"] == "none" and LEVEL_RANK[level] >= LEVEL_RANK["autonomous"]
        counts = (unaided and gap is not None and gap >= MIN_DEFERRED_GAP
                  and scenario is not None and scenario not in t["scenarios_seen"])
        if counts:
            t["deferred_scenarios"].append(scenario)
            reasons.append(
                f"counted as deferred unaided scenario ({gap} working days since last attempt)")
        elif unaided and scenario is not None and scenario in t["scenarios_seen"]:
            reasons.append("scenario already seen on this topic; does not count as new")
        elif unaided and gap is not None and gap < MIN_DEFERRED_GAP:
            reasons.append(
                f"only {gap} working day(s) since last attempt "
                f"(need {MIN_DEFERRED_GAP}); not counted as deferred")
        elif unaided and gap is not None and scenario is None:
            reasons.append("no scenario given; not counted as deferred")

        if scenario is not None and scenario not in t["scenarios_seen"]:
            t["scenarios_seen"].append(scenario)

        if LEVEL_RANK[level] < LEVEL_RANK["autonomous"] and t["deferred_scenarios"]:
            t["deferred_scenarios"] = []
            reasons.append("result below autonomous: consolidation progress reset")

        if level == "consolidated" and len(t["deferred_scenarios"]) < CONSOLIDATION_TARGET:
            level = "autonomous"
            reasons.append(
                f"consolidated needs {CONSOLIDATION_TARGET} distinct unaided deferred "
                f"scenarios, have {len(t['deferred_scenarios'])}; capped to autonomous")

    capped = level != claimed

    # interval
    if p["interval_weekdays"] is not None:
        days = p["interval_weekdays"]
        source = "override"
    elif not observed:
        days, source = 1, "self-assessed"
    elif p["score_30"] is not None:
        days, source = days_from_score(p["score_30"]), "score"
    else:
        days, source = LEVEL_DEFAULT_DAYS[level], "level default"
    cap = LEVEL_MAX_DAYS.get(level)
    if cap is not None and days > cap:
        reasons.append(f"interval {days} reduced to {cap} for level {level}")
        days = cap

    t["level"] = level
    t["last_attempt"] = on.isoformat()
    t["interval_weekdays"] = days
    nxt = add_working_days(on, days, rest_days)
    t["next_review"] = nxt.isoformat()
    t["attempts"] += 1
    if entry["gaps"] is not None:
        t["gaps"] = entry["gaps"]

    progress = f"{len(t['deferred_scenarios'])}/{CONSOLIDATION_TARGET}"
    report = {"id": entry["id"], "claimed": claimed, "capped": capped,
              "interval_source": source, "reasons": reasons,
              "consolidation_progress": progress,
              "before": before, "after": _snapshot(t),
              "next_review_weekday": weekday_name(nxt)}
    return t, report


def apply_record(topics, payload, today, rest_days):
    """Pure function: returns (new_topics, session_entry, reports)."""
    p = validate_payload(payload, today)
    for entry in p["topics"]:
        if entry["id"] not in topics:
            raise LedgerError(f"unknown topic id {entry['id']!r}; add it first")
    new_topics = dict(topics)
    reports = []
    for entry in p["topics"]:
        nt, rep = apply_topic(topics[entry["id"]], entry, p, rest_days)
        new_topics[entry["id"]] = nt
        reports.append(rep)
    session = {"date": p["date"].isoformat(), "type": p["type"],
               "support": p["support"], "evidence": p["evidence"],
               "score_30": p["score_30"], "duration_min": p["duration_min"],
               "summary": p["summary"], "autonomous_work": p["autonomous_work"],
               "supported_work": p["supported_work"], "key_errors": p["key_errors"],
               "next_action": p["next_action"],
               "topics": [{"id": r["id"], "claimed": r["claimed"],
                           "from": r["before"]["level"],
                           "level": r["after"]["level"], "capped": r["capped"]}
                          for r in reports]}
    return new_topics, session, reports


# ---------------------------------------------------------------- views

def build_due(topics, today, rest_days):
    rest = rest_set(rest_days)
    due, upcoming, unassessed = [], [], []
    horizon = today + timedelta(days=7)
    for tid, t in topics.items():
        if t["next_review"] is None:
            unassessed.append({"id": tid, "name": t["name"], "area": t["area"]})
            continue
        nr = parse_date(t["next_review"], "stored next_review")
        row = {"id": tid, "name": t["name"], "area": t["area"], "level": t["level"],
               "next_review": t["next_review"], "gaps": t["gaps"]}
        if nr <= today:
            row["overdue_working_days"] = working_days_between(nr, today, rest_days)
            due.append(row)
        elif nr <= horizon:
            upcoming.append(row)
    due.sort(key=lambda r: (LEVEL_RANK[r["level"]], r["next_review"], r["id"]))
    upcoming.sort(key=lambda r: (r["next_review"], r["id"]))
    unassessed.sort(key=lambda r: r["id"])
    return {"today": today.isoformat(), "weekday": weekday_name(today),
            "rest_day": today.weekday() in rest, "due": due,
            "upcoming": upcoming, "unassessed": unassessed}


def build_status(topics, today, rest_days):
    by_level = {lvl: 0 for lvl in LEVELS}
    by_area = {}
    for t in topics.values():
        by_level[t["level"]] += 1
        a = by_area.setdefault(t["area"], {lvl: 0 for lvl in LEVELS})
        a[t["level"]] += 1
    dv = build_due(topics, today, rest_days)
    return {"today": dv["today"], "weekday": dv["weekday"], "rest_day": dv["rest_day"],
            "total_topics": len(topics), "by_level": by_level, "by_area": by_area,
            "due_count": len(dv["due"]), "unassessed_count": len(dv["unassessed"])}


def build_report(topics, sessions, today, days, rest_days):
    """Summary of sessions in the window (today - days, today]."""
    start = today - timedelta(days=days)
    window = [s for s in sessions
              if start < parse_date(s["date"], "stored session date") <= today]
    by_type, by_support, touched = {}, {}, {}
    minutes = 0
    for s in window:
        by_type[s["type"]] = by_type.get(s["type"], 0) + 1
        by_support[s["support"]] = by_support.get(s["support"], 0) + 1
        minutes += s.get("duration_min") or 0
        for t in s["topics"]:
            row = touched.setdefault(t["id"], {
                "id": t["id"], "sessions": 0, "capped": 0,
                "from": t.get("from", "unknown"), "to": t["level"]})
            row["sessions"] += 1
            row["capped"] += 1 if t["capped"] else 0
            row["to"] = t["level"]
    dv = build_due(topics, today, rest_days)
    return {"from": (start + timedelta(days=1)).isoformat(), "to": today.isoformat(),
            "sessions": len(window), "minutes_logged": minutes,
            "by_type": by_type, "by_support": by_support,
            "unaided_sessions": by_support.get("none", 0),
            "topics_touched": sorted(touched.values(), key=lambda r: r["id"]),
            "capped_topic_results": sum(r["capped"] for r in touched.values()),
            "due_now": [r["id"] for r in dv["due"]],
            "unassessed_count": len(dv["unassessed"])}


# ---------------------------------------------------------------- CLI

def emit(obj):
    print(json.dumps(obj, indent=2, ensure_ascii=False))


def read_json_arg(path):
    try:
        if path:
            with open(path, encoding="utf-8") as f:
                return json.load(f)
        return json.load(sys.stdin)
    except json.JSONDecodeError as e:
        raise LedgerError(f"invalid JSON input: {e}")
    except OSError as e:
        raise LedgerError(f"cannot read input: {e}")


def check_topic_id(tid):
    if not isinstance(tid, str) or not ID_RE.match(tid):
        raise LedgerError(
            f"invalid topic id {tid!r}: use lowercase letters, digits and single hyphens")


def run(args):
    today = parse_date(args.today, "--today") if args.today else date.today()
    store = Store(args.dir)
    cmd = args.command

    if cmd == "init":
        os.makedirs(store.dir, exist_ok=True)
        created = []
        if not os.path.isfile(store.topics_path):
            store.save_topics({})
            created.append("topics.json")
        if not os.path.isfile(store.config_path):
            rest = parse_rest_days(args.rest_days) if args.rest_days else DEFAULT_REST_DAYS
            atomic_write(store.config_path,
                         json.dumps({"rest_days": rest}, indent=2) + "\n")
            created.append("config.json")
        if not os.path.isfile(store.sessions_path):
            open(store.sessions_path, "a", encoding="utf-8").close()
            created.append("sessions.jsonl")
        emit({"dir": store.dir, "created": created,
              "rest_days": store.load_config()["rest_days"]})
        return

    topics = store.load_topics()
    rest_days = store.load_config()["rest_days"]

    if cmd == "topic":
        if args.topic_cmd == "add":
            check_topic_id(args.id)
            if args.id in topics:
                raise LedgerError(f"topic {args.id!r} already exists")
            topics[args.id] = new_topic(args.name, args.area)
            store.save_topics(topics)
            emit({"added": args.id})
        else:
            data = read_json_arg(args.file)
            items = data.get("topics") if isinstance(data, dict) else data
            if not isinstance(items, list):
                raise LedgerError("import file must be a list or {\"topics\": [...]}")
            added, skipped = [], []
            for it in items:
                if not isinstance(it, dict) or "name" not in it:
                    raise LedgerError("each imported topic needs 'id' and 'name'")
                check_topic_id(it.get("id"))
                if it["id"] in topics:
                    skipped.append(it["id"])
                    continue
                topics[it["id"]] = new_topic(it["name"], it.get("area", "general"))
                added.append(it["id"])
            store.save_topics(topics)
            emit({"added": added, "skipped": skipped})
    elif cmd == "due":
        emit(build_due(topics, today, rest_days))
    elif cmd == "status":
        emit(build_status(topics, today, rest_days))
    elif cmd == "report":
        if args.days < 1:
            raise LedgerError("--days must be at least 1")
        emit(build_report(topics, store.load_sessions(), today, args.days, rest_days))
    elif cmd == "show":
        if args.id not in topics:
            raise LedgerError(f"unknown topic id {args.id!r}")
        recent = [s for s in store.load_sessions()
                  if any(x["id"] == args.id for x in s["topics"])][-5:]
        emit({"id": args.id, "topic": topics[args.id], "recent_sessions": recent})
    elif cmd == "record":
        payload = read_json_arg(args.file)
        new_topics, session, reports = apply_record(topics, payload, today, rest_days)
        if args.dry_run:
            emit({"dry_run": True, "date": session["date"],
                  "weekday": weekday_name(parse_date(session["date"])),
                  "reports": reports})
            return
        store.append_session(session)
        store.save_topics(new_topics)
        emit({"dry_run": False, "date": session["date"], "reports": reports})


def build_parser():
    ap = argparse.ArgumentParser(prog="ledger.py", description=__doc__.split("\n")[0])
    ap.add_argument("--dir", default=os.environ.get("LEARNING_LEDGER_DIR",
                                                    "./.learning-ledger"))
    ap.add_argument("--today", help="override today's date (YYYY-MM-DD), for tests")
    sub = ap.add_subparsers(dest="command", required=True)

    p = sub.add_parser("init")
    p.add_argument("--rest-days", help="comma list, default sat,sun; e.g. 'sun' or 'fri,sat'")

    t = sub.add_parser("topic")
    ts = t.add_subparsers(dest="topic_cmd", required=True)
    a = ts.add_parser("add")
    a.add_argument("--id", required=True)
    a.add_argument("--name", required=True)
    a.add_argument("--area", default="general")
    i = ts.add_parser("import")
    i.add_argument("file", nargs="?")

    sub.add_parser("due")
    sub.add_parser("status")
    rp = sub.add_parser("report")
    rp.add_argument("--days", type=int, default=7)
    s = sub.add_parser("show")
    s.add_argument("id")
    r = sub.add_parser("record")
    r.add_argument("--dry-run", action="store_true")
    r.add_argument("--file")
    return ap


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        run(args)
    except LedgerError as e:
        print(json.dumps({"error": str(e)}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
