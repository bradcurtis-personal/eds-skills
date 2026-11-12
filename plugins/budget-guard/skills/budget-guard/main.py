"""budget-guard: stop an agent run at 75% of the five-hour window and report sprint usage against its cap.

Subcommands (all print one JSON object on stdout):

  reading  --percent N --resets-at TS [--at TS]
           Stores a manual reading (Settings > Usage, whole percent, "Current session") with its
           time and the time the window resets. A local cache outside every repo.
  check    [--threshold 75] [--max-age-min 60] [--status-file F] [--transcript FILE ...]
           Resolves the five-hour percentage from the best source available, names the source and
           how far to trust it, and answers ok, stop (exit 3) or unavailable (exit 4).
  sprint   --sprint S [--cap 30]
           Sums the sprint's recorded effort (percent of the weekly limit) from the ledger,
           through ledger-append, and compares it with the cap.

Sources for `check`, best first (EDS-72 decision 30(j): no automatic live source is confirmed):
  1. status-line  a JSON file with rate_limits.five_hour (only if a status line ever writes one)
  2. manual       the newest reading, if fresh and its window has not reset;
                  plus transcript tokens since the reading when transcripts are given
  3. transcript   tokens inside the window / the five-hour factor, a lower bound only

It never guesses: a reading it cannot take is reported as unavailable, with the reason.
"""

import argparse
import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import logging

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_BACKEND = os.getenv("LOG_BACKEND", "flat-file")


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "level": record.levelname,
            "skill": "budget-guard",
            "message": record.getMessage(),
            "timestamp": self.formatTime(record)
        })


if LOG_BACKEND != "cloudwatch":
    os.makedirs("logs", exist_ok=True)
handler = logging.StreamHandler() if LOG_BACKEND == "cloudwatch" else logging.FileHandler("logs/budget-guard.log")
handler.setFormatter(JsonFormatter())

logger = logging.getLogger("budget-guard")
logger.setLevel(LOG_LEVEL)
if not logger.handlers:
    logger.addHandler(handler)


THRESHOLD_PCT = 75.0          # D6: stop at 75% of the five-hour window
SPRINT_CAP_PCT = 30.0         # D6: sprint cap, percent of the weekly limit
WINDOW = timedelta(hours=5)
READINGS_FILE = "readings.jsonl"
STATE_DIR_ENV = "EDS_BUDGET_STATE_DIR"
STATUS_FILE_ENV = "EDS_STATUS_FILE"
LEDGER_APPEND_ENV = "EDS_LEDGER_APPEND"
USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)
EXIT_ERROR = 2
EXIT_STOP = 3
EXIT_UNAVAILABLE = 4


class GuardError(Exception):
    """A refusal the caller must see; printed as JSON and exits 2."""


# ---------- time ----------

def parse_ts(value):
    try:
        if isinstance(value, (int, float)):
            return datetime.fromtimestamp(float(value), tz=timezone.utc)
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, OverflowError, OSError):
        raise GuardError(f"timestamp '{value}' is not ISO 8601.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def now_from(args):
    return parse_ts(args.now) if args.now else datetime.now(timezone.utc)


def pct(value):
    return round(float(value), 2)


# ---------- talking to ledger-append ----------

def find_ledger_append():
    here = Path(__file__).resolve().parent
    for cand in (os.environ.get(LEDGER_APPEND_ENV), here.parent / "ledger-append" / "main.py"):
        if cand and Path(cand).is_file():
            return Path(cand)
    raise GuardError("ledger-append not found. Set EDS_LEDGER_APPEND to its main.py, or install the "
                     "ledger-append skill next to this one.")


def ledger_read(args, **filters):
    cmd = [sys.executable, str(find_ledger_append()), "read"]
    if getattr(args, "ledger_dir", None):
        cmd += ["--ledger-dir", args.ledger_dir]
    for key, value in filters.items():
        if value:
            cmd += [f"--{key}", value]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise GuardError(f"ledger-append returned no JSON: {proc.stderr.strip() or proc.stdout.strip()}")
    if proc.returncode != 0:
        raise GuardError(f"ledger-append refused: {out.get('error', out)}")
    return out["events"]


def five_hour_factor(calibrations, model):
    """(tokens per 1% of the five-hour window, factor_id) for `model`, or None. The newest line whose
    model is the longest prefix of `model` wins."""
    pool = [c for c in calibrations if c.get("basis") == "five_hour" and c.get("model")
            and model.startswith(c["model"])]
    if not pool:
        return None
    longest = max(len(c["model"]) for c in pool)
    best = max((c for c in pool if len(c["model"]) == longest), key=lambda c: str(c.get("ts", "")))
    return float(best["tokens_per_pct"]), best["event_id"]


# ---------- manual readings (local cache) ----------

def readings_path(args):
    base = Path(getattr(args, "state_dir", None) or os.environ.get(STATE_DIR_ENV)
                or Path.home() / ".eds" / "budget-guard")
    return base / READINGS_FILE


def read_readings(path):
    if not path.is_file():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            out.append(json.loads(line))
    return out


def cmd_reading(args):
    at = parse_ts(args.at) if args.at else datetime.now(timezone.utc)
    resets = parse_ts(args.resets_at)
    if not 0 <= args.percent <= 100:
        raise GuardError("--percent must be between 0 and 100.")
    if not at < resets <= at + WINDOW:
        raise GuardError("--resets-at must be after the reading and at most five hours from it: the "
                         "five-hour window resets within five hours of any reading.")
    record = {"ts": fmt_ts(at), "percent": pct(args.percent), "resets_at": fmt_ts(resets),
              "basis": "five_hour", "source": "manual"}
    path = readings_path(args)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record) + "\n")
    logger.info("reading stored percent=%s at=%s", record["percent"], record["ts"])
    return {"stored": record, "file": str(path)}


# ---------- transcripts ----------

def iter_usage(transcript):
    for line in Path(transcript).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        msg = rec.get("message")
        stamp = rec.get("timestamp") or rec.get("ts")
        if not isinstance(msg, dict) or not isinstance(msg.get("usage"), dict) or not stamp:
            continue
        tokens = sum(int(msg["usage"].get(f) or 0) for f in USAGE_FIELDS)
        yield parse_ts(stamp), msg.get("id"), msg.get("model", "") or "unknown", tokens


def load_messages(transcripts):
    """[(when, model, tokens)], each API message once (deduped by message.id: each is written twice)."""
    messages, seen = [], set()
    for path in transcripts:
        if not Path(path).is_file():
            raise GuardError(f"Transcript not found: {path}")
        for when, mid, model, tokens in iter_usage(path):
            if mid:
                if mid in seen:
                    continue
                seen.add(mid)
            messages.append((when, model, tokens))
    return messages


def tokens_to_pct(args, messages, start, end, include_start):
    """(percent added, uncalibrated tokens, factor ids) for messages in the span. Models with no
    five-hour factor are counted as uncalibrated tokens, never converted by a guess."""
    per_model = {}
    for when, model, tokens in messages:
        inside = (start <= when if include_start else start < when) and when <= end
        if inside:
            per_model[model] = per_model.get(model, 0) + tokens
    if not per_model:
        return 0.0, 0, []
    calibrations = ledger_read(args, event="calibration")
    total, uncalibrated, ids = 0.0, 0, []
    for model, tokens in sorted(per_model.items()):
        factor = five_hour_factor(calibrations, model)
        if factor is None:
            uncalibrated += tokens
        else:
            total += tokens / factor[0]
            ids.append(factor[1])
    return total, uncalibrated, sorted(set(ids))


# ---------- the five-hour check ----------

def try_status_file(args, now):
    path = args.status_file or os.environ.get(STATUS_FILE_ENV)
    if not path:
        return None, "no status-line file configured (a status line did not run in the Desktop Code tab, decision 30(j))"
    path = Path(path)
    if not path.is_file():
        return None, f"status-line file {path} does not exist"
    try:
        five = json.loads(path.read_text(encoding="utf-8"))["rate_limits"]["five_hour"]
        used, resets = float(five["used_percentage"]), parse_ts(five["resets_at"])
    except (ValueError, KeyError, TypeError, json.JSONDecodeError, GuardError):
        return None, "status-line file has no rate_limits.five_hour.used_percentage and resets_at"
    written = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
    if resets <= now:
        return None, f"status-line window already reset at {fmt_ts(resets)}"
    if now - written > timedelta(minutes=args.max_age_min):
        return None, f"status-line file is older than {args.max_age_min} minutes"
    return {"source": "status-line", "percent": used, "confidence": "high", "lower_bound": False,
            "reading_at": fmt_ts(written), "window_resets_at": fmt_ts(resets), "flags": []}, "used"


def try_manual(args, now, messages):
    readings = sorted(read_readings(readings_path(args)), key=lambda r: r["ts"])
    if not readings:
        return None, "no manual reading stored (run `reading` after looking at Settings > Usage)", None
    last = readings[-1]
    at, resets = parse_ts(last["ts"]), parse_ts(last["resets_at"])
    if resets <= now:
        return None, f"the newest manual reading's window reset at {fmt_ts(resets)}: take a new reading", last
    if at > now:
        return None, "the newest manual reading is dated after now", last
    if now - at > timedelta(minutes=args.max_age_min):
        return None, f"the newest manual reading ({last['ts']}) is older than {args.max_age_min} minutes", last
    percent, flags, lower, source, confidence = float(last["percent"]), [], False, "manual", "medium"
    flags.append("Settings > Usage shows whole percents: the reading is accurate to about one point.")
    if messages:
        try:
            added, uncal, ids = tokens_to_pct(args, messages, at, now, include_start=False)
        except GuardError as exc:
            return None, f"transcripts given but their usage cannot be converted: {exc}", last
        percent += added
        source = "manual+transcript"
        if added:
            flags.append(f"Added {pct(added)} points from transcript tokens since the reading "
                         f"(factors {', '.join(ids)}; rough, EDS-72 Open Decision 10).")
        if uncal:
            lower = True
            flags.append(f"{uncal} tokens since the reading have no five-hour factor (for example Opus): "
                         "the percentage is a lower bound.")
    return {"source": source, "percent": percent, "confidence": confidence, "lower_bound": lower,
            "reading_at": last["ts"], "window_resets_at": last["resets_at"], "flags": flags}, "used", last


def try_transcript(args, now, messages, last_reading):
    if not messages:
        return None, "no transcripts given"
    resets = parse_ts(args.window_resets) if args.window_resets else None
    if resets is None and last_reading and parse_ts(last_reading["resets_at"]) > now:
        resets = parse_ts(last_reading["resets_at"])
    if resets is None or resets <= now:
        return None, "the window's reset time is not known (pass --window-resets, or store a reading that carries it)"
    start = resets - WINDOW
    try:
        percent, uncal, ids = tokens_to_pct(args, messages, start, now, include_start=True)
    except GuardError as exc:
        return None, f"transcript usage cannot be converted: {exc}"
    if not ids:
        return None, ("no transcript tokens inside the window have a five-hour factor"
                      if uncal else "no transcript tokens fall inside the window")
    flags = [f"Estimated from transcript tokens inside the window {fmt_ts(start)} to {fmt_ts(resets)} "
             f"(factors {', '.join(ids) or 'none'}; rough). Usage outside these transcripts, claude.ai chat "
             "included, is not counted, so this is a lower bound."]
    if uncal:
        flags.append(f"{uncal} tokens have no five-hour factor and are not counted.")
    return {"source": "transcript", "percent": percent, "confidence": "low", "lower_bound": True,
            "reading_at": fmt_ts(now), "window_resets_at": fmt_ts(resets), "flags": flags}, "used"


def cmd_check(args):
    now = now_from(args)
    messages = load_messages(args.transcript or [])
    tried, chosen = [], None

    result, why = try_status_file(args, now)
    tried.append({"source": "status-line", "used": result is not None, "reason": why})
    chosen = result

    last = None
    if chosen is None:
        result, why, last = try_manual(args, now, messages)
        tried.append({"source": "manual", "used": result is not None, "reason": why})
        chosen = result

    if chosen is None:
        result, why = try_transcript(args, now, messages, last)
        tried.append({"source": "transcript", "used": result is not None, "reason": why})
        chosen = result

    out = {"threshold_pct": args.threshold, "checked_at": fmt_ts(now), "tried": tried}
    if chosen is None:
        out.update({"verdict": "unavailable", "five_hour_pct": None, "source": None,
                    "message": "UNAVAILABLE: no usable five-hour reading, so nothing is reported and nothing is "
                               "guessed. Read Settings > Usage and run `reading`, then check again.",
                    "flags": []})
        logger.warning("check unavailable")
        return EXIT_UNAVAILABLE, out
    percent = chosen["percent"]
    out.update({k: chosen[k] for k in ("source", "confidence", "lower_bound", "reading_at",
                                       "window_resets_at", "flags")})
    out["five_hour_pct"] = pct(percent)
    if percent >= args.threshold:
        out["verdict"] = "stop"
        out["message"] = (f"STOP: the five-hour window is at {pct(percent)}%"
                          f"{' or more' if chosen['lower_bound'] else ''} (threshold {pct(args.threshold)}%, "
                          f"source {chosen['source']}). Finish no new work: report to the lead (to Brad if you "
                          f"are the lead) with the state of the ticket. The window resets at "
                          f"{chosen['window_resets_at']}.")
        logger.warning("check stop pct=%s source=%s", out["five_hour_pct"], chosen["source"])
        return EXIT_STOP, out
    if chosen["lower_bound"]:
        out["verdict"] = "unverified"
        out["message"] = (f"UNVERIFIED: at least {pct(percent)}% (source {chosen['source']}), a lower bound only, "
                          "so it cannot show the run is below the threshold. Store a fresh manual reading with "
                          "`reading`, then check again.")
        return EXIT_UNAVAILABLE, out
    out["verdict"] = "ok"
    out["message"] = (f"OK: the five-hour window is at {pct(percent)}% (threshold {pct(args.threshold)}%, "
                      f"source {chosen['source']}, confidence {chosen['confidence']}).")
    logger.info("check ok pct=%s source=%s", out["five_hour_pct"], chosen["source"])
    return 0, out


# ---------- sprint usage ----------

def cmd_sprint(args):
    events = [e for e in ledger_read(args, event="effort") if e.get("sprint") == args.sprint]
    if not events:
        out = {"sprint": args.sprint, "cap_pct": args.cap, "verdict": "unavailable", "total_pct": None,
               "message": f"UNAVAILABLE: no effort events carry sprint '{args.sprint}'. Zero is not reported "
                          "because nothing was measured: run effort-record `record --sprint` first.",
               "flags": []}
        return EXIT_UNAVAILABLE, out
    by_role, unassigned, uncal = {}, 0.0, 0
    for ev in events:
        if "usage_pct" not in ev:
            uncal += int(ev.get("tokens", 0))
        elif ev.get("role") == "unassigned":
            unassigned += ev["usage_pct"]
        else:
            by_role[ev["role"]] = by_role.get(ev["role"], 0.0) + ev["usage_pct"]
    roles_total = sum(by_role.values())
    total = roles_total + unassigned
    flags = ["Percentages use rough calibration factors (EDS-72 Open Decision 10)."]
    if uncal:
        flags.append(f"{uncal} tokens have no calibration factor and are not in the total: it is a lower bound.")
    out = {"sprint": args.sprint, "cap_pct": args.cap, "by_role_pct": {r: pct(v) for r, v in sorted(by_role.items())},
           "unassigned_pct": pct(unassigned), "roles_total_pct": pct(roles_total), "total_pct": pct(total),
           "share_of_cap_pct": pct(total / args.cap * 100), "remaining_pct": pct(args.cap - total),
           "events": len(events), "flags": flags}
    if total >= args.cap:
        out["verdict"] = "over_cap"
        out["message"] = (f"OVER CAP: sprint {args.sprint} has used {pct(total)}% of the weekly limit "
                          f"against a cap of {pct(args.cap)}%. Stop pulling work in and report to the lead.")
        return EXIT_STOP, out
    out["verdict"] = "ok"
    out["message"] = (f"OK: sprint {args.sprint} has used {pct(total)}% of the weekly limit, "
                      f"{pct(total / args.cap * 100)}% of its {pct(args.cap)}% cap.")
    return 0, out


# ---------- entry point ----------

def build_parser():
    parser = argparse.ArgumentParser(description="Stop at 75% of the five-hour window; report sprint usage against its cap.")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("reading")
    p.add_argument("--percent", required=True, type=float, help="The 'Current session' percent from Settings > Usage.")
    p.add_argument("--resets-at", required=True, help="When that window resets (ISO 8601).")
    p.add_argument("--at", help="When the reading was taken (default: now).")
    p.add_argument("--state-dir")
    p = sub.add_parser("check")
    p.add_argument("--threshold", type=float, default=THRESHOLD_PCT)
    p.add_argument("--max-age-min", type=float, default=60)
    p.add_argument("--status-file")
    p.add_argument("--transcript", action="append", help="A session or subagent transcript JSONL, repeatable.")
    p.add_argument("--window-resets", help="When the current window resets, if no reading carries it.")
    p.add_argument("--now", help="Treat this time as now (ISO 8601), for tests and replays.")
    p.add_argument("--ledger-dir")
    p.add_argument("--state-dir")
    p = sub.add_parser("sprint")
    p.add_argument("--sprint", required=True)
    p.add_argument("--cap", type=float, default=SPRINT_CAP_PCT)
    p.add_argument("--ledger-dir")
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        if args.command == "reading":
            code, result = 0, cmd_reading(args)
        elif args.command == "check":
            code, result = cmd_check(args)
        else:
            code, result = cmd_sprint(args)
    except GuardError as exc:
        logger.error("refused: %s", exc)
        print(json.dumps({"error": str(exc)}, indent=2))
        return EXIT_ERROR
    print(json.dumps(result, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
