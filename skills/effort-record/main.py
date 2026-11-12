"""effort-record: turn session usage into ledger events, per role, and close a ticket's effort.

Subcommands (all print one JSON object on stdout):

  estimate  --ticket EDS-n --est-pct N [--sprint S]
            Records the ticket's estimate (the expected share of the weekly limit).
  record    --ticket EDS-n --transcript [AGENT=]FILE [--transcript ...] [--sprint S]
            Reads the role segments (role-assume's segments.jsonl) and the session
            transcripts, and appends one `effort` event per closed segment and model
            plus one `unassigned` event per model for usage in the ticket's period
            that no segment claims. Tokens become percent of the weekly limit with
            the newest calibration for the model. Already-recorded events are skipped.
  close     --ticket EDS-n [--sprint S]
            Sums the ticket's effort per role, computes delta and ratio against the
            estimate, appends a `close` event and prints the [EFFORT] comment and the
            value for Jira's "Actual usage (%)".
  report    [--ticket EDS-n]
            Per ticket and role percent, the unassigned figure and the overall total.

The ledger is read and written only through the ledger-append skill. Delta, ratio
and totals are always computed here, never typed.
"""

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import logging

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_BACKEND = os.getenv("LOG_BACKEND", "flat-file")


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "level": record.levelname,
            "skill": "effort-record",
            "message": record.getMessage(),
            "timestamp": self.formatTime(record)
        })


if LOG_BACKEND != "cloudwatch":
    os.makedirs("logs", exist_ok=True)
handler = logging.StreamHandler() if LOG_BACKEND == "cloudwatch" else logging.FileHandler("logs/effort-record.log")
handler.setFormatter(JsonFormatter())

logger = logging.getLogger("effort-record")
logger.setLevel(LOG_LEVEL)
if not logger.handlers:
    logger.addHandler(handler)


UNASSIGNED = "unassigned"
SEGMENTS_FILE = "segments.jsonl"
STATE_DIR_ENV = "EDS_ROLE_STATE_DIR"
LEDGER_APPEND_ENV = "EDS_LEDGER_APPEND"
EXIT_ERROR = 2
USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)
KIND_BY_ROLE = {"reviewer": "review", "lead": "coordination"}


class EffortError(Exception):
    """A refusal the caller must see; printed as JSON and exits 2."""


# ---------- time and numbers ----------

def parse_ts(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise EffortError(f"timestamp '{value}' is not ISO 8601.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def stable_id(*parts):
    return hashlib.sha1("|".join(str(p) for p in parts).encode("utf-8")).hexdigest()


def num(value):
    """Trim a percent for the [EFFORT] comment: 3.3, 3, 0.05 (at most 2 decimals)."""
    text = f"{round(float(value), 2):.2f}".rstrip("0").rstrip(".")
    return "0" if text in ("", "-0") else text


# ---------- talking to ledger-append ----------

def find_ledger_append():
    here = Path(__file__).resolve().parent
    candidates = [os.environ.get(LEDGER_APPEND_ENV), here.parent / "ledger-append" / "main.py"]
    for cand in candidates:
        if cand and Path(cand).is_file():
            return Path(cand)
    raise EffortError("ledger-append not found. Set EDS_LEDGER_APPEND to its main.py, or install the "
                      "ledger-append skill next to this one. Without it nothing is read or written.")


def call_ledger(args, *argv):
    cmd = [sys.executable, str(find_ledger_append()), argv[0]]
    if getattr(args, "ledger_dir", None):
        cmd += ["--ledger-dir", args.ledger_dir]
    cmd += list(argv[1:])
    proc = subprocess.run(cmd, capture_output=True, text=True)
    try:
        out = json.loads(proc.stdout)
    except json.JSONDecodeError:
        raise EffortError(f"ledger-append returned no JSON: {proc.stderr.strip() or proc.stdout.strip()}")
    if proc.returncode != 0:
        raise EffortError(f"ledger-append refused: {out.get('error', out)}")
    return out


def ledger_read(args, **filters):
    argv = ["read"]
    for key, value in filters.items():
        if value:
            argv += [f"--{key}", value]
    return call_ledger(args, *argv)["events"]


def ledger_append(args, event):
    return call_ledger(args, "append", "--event", json.dumps(event))


# ---------- segments (the contract role-assume documents) ----------

def segments_path(explicit):
    if explicit:
        return Path(explicit)
    base = Path(os.environ.get(STATE_DIR_ENV) or Path.home() / ".eds" / "role-segments")
    return base / SEGMENTS_FILE


def read_segments(path):
    path = Path(path)
    if not path.is_file():
        raise EffortError(f"No segment file at {path}. Without role segments every message is unassigned; "
                          "pass --segments or set EDS_ROLE_STATE_DIR.")
    segments = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        ev = json.loads(line)
        if ev.get("event") == "segment_open":
            segments[ev["segment_id"]] = {
                "segment_id": ev["segment_id"], "role": ev["role"], "agent": ev["agent"],
                "session": ev.get("session", ""), "ticket": ev.get("ticket", ""),
                "ts_open": ev["ts"], "ts_close": None}
        elif ev.get("event") == "segment_close" and ev["segment_id"] in segments:
            segments[ev["segment_id"]]["ts_close"] = ev["ts"]
    return list(segments.values())


# ---------- transcripts ----------

def split_transcript_arg(value):
    """`AGENT=FILE` limits the file to that agent's segments; a bare FILE matches any agent's."""
    head, sep, tail = value.partition("=")
    if sep and head and "/" not in head and "\\" not in head and ":" not in head:
        return head, tail
    return None, value


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


def load_messages(transcript_args):
    """[(when, model, tokens, agent_or_None)], each API message once (deduped by message.id)."""
    messages, seen = [], set()
    for value in transcript_args:
        agent, path = split_transcript_arg(value)
        if not Path(path).is_file():
            raise EffortError(f"Transcript not found: {path}")
        for when, mid, model, tokens in iter_usage(path):
            if mid:
                if mid in seen:
                    continue
                seen.add(mid)
            messages.append((when, model, tokens, agent))
    return messages


def owner(segments, when, agent):
    """The segment whose half-open span [open, close) holds `when`, or None."""
    for seg in segments:
        if agent and seg["agent"] != agent:
            continue
        start = parse_ts(seg["ts_open"])
        end = parse_ts(seg["ts_close"]) if seg["ts_close"] else None
        if start <= when and (end is None or when < end):
            return seg
    return None


# ---------- calibration ----------

def newest(events):
    return max(events, key=lambda e: str(e.get("ts", ""))) if events else None


def factor_for(calibrations, model):
    """(tokens per 1% of the weekly limit, factor_id, note) for `model`, or None when uncalibrated.

    The newest `weekly` line wins; otherwise the newest `five_hour` line combined with the newest
    `ratio` line (weekly = five-hour tokens-per-1% / weekly_per_five_hour). The model on a line is
    matched as a prefix, longest first."""
    def best(basis):
        pool = [c for c in calibrations if c.get("basis") == basis and c.get("model")
                and model.startswith(c["model"])]
        if not pool:
            return None
        longest = max(len(c["model"]) for c in pool)
        return newest([c for c in pool if len(c["model"]) == longest])

    weekly = best("weekly")
    if weekly:
        return float(weekly["tokens_per_pct"]), weekly["event_id"], ""
    five = best("five_hour")
    ratio = newest([c for c in calibrations if c.get("basis") == "ratio"])
    if five and ratio:
        return (float(five["tokens_per_pct"]) / float(ratio["weekly_per_five_hour"]), five["event_id"],
                f"weekly factor from five-hour line via ratio {ratio['event_id']}")
    return None


# ---------- commands ----------

def cmd_estimate(args):
    event = {"event": "estimate", "ticket": args.ticket, "est_pct": float(args.est_pct)}
    if args.sprint:
        event["sprint"] = args.sprint
    event["event_id"] = stable_id("estimate", args.ticket, args.est_pct)
    return ledger_append(args, event)


def cmd_record(args):
    segments = read_segments(segments_path(args.segments))
    mine = [s for s in segments if s["ticket"] == args.ticket]
    if not mine:
        raise EffortError(f"No role segment is tagged with {args.ticket}. Nothing to record: effort without a "
                          "segment is unassigned, and a ticket's period comes from its segments.")
    flags = []
    open_ones = [s for s in mine if not s["ts_close"]]
    for s in open_ones:
        flags.append(f"Segment {s['segment_id']} ({s['role']}) is still open: not recorded. "
                     "Release the role (role-release), then record again.")
    closed = [s for s in mine if s["ts_close"]]
    messages = load_messages(args.transcript)
    calibrations = ledger_read(args, event="calibration")
    existing = {e["event_id"]: e for e in ledger_read(args, ticket=args.ticket, event="effort")}

    per_segment = {}      # (segment_id, model) -> tokens
    unassigned = {}       # model -> tokens, inside the ticket's period, claimed by no segment
    period_start = min(parse_ts(s["ts_open"]) for s in mine)
    period_end = None if open_ones else max(parse_ts(s["ts_close"]) for s in closed)
    claimed_elsewhere = 0
    for when, model, tokens, agent in messages:
        seg = owner(segments, when, agent)
        if seg is not None:
            if seg["ticket"] == args.ticket and seg["ts_close"]:
                key = (seg["segment_id"], model)
                per_segment[key] = per_segment.get(key, 0) + tokens
            elif seg["ticket"] != args.ticket:
                claimed_elsewhere += 1
            continue
        if period_end is not None and period_start <= when <= period_end:
            unassigned[model] = unassigned.get(model, 0) + tokens
    if period_end is None and not closed:
        flags.append("No closed segment: the unassigned figure for the period cannot be fixed yet.")
    elif period_end is None:
        flags.append("The ticket still has an open segment: its unassigned figure is not recorded yet.")

    planned = []
    by_id = {s["segment_id"]: s for s in closed}
    for (segment_id, model), tokens in sorted(per_segment.items()):
        seg = by_id[segment_id]
        planned.append({
            "event": "effort", "event_id": stable_id("effort", segment_id, model), "ts": seg["ts_close"],
            "ticket": args.ticket, "role": seg["role"], "agent": seg["agent"], "model": model,
            "kind": args.kind or KIND_BY_ROLE.get(seg["role"], "work"), "tokens": tokens,
            "segment_id": segment_id, "window_start": seg["ts_open"], "window_end": seg["ts_close"]})
    if period_end is not None:
        for model, tokens in sorted(unassigned.items()):
            planned.append({
                "event": "effort", "event_id": stable_id("effort", UNASSIGNED, args.ticket,
                                                         fmt_ts(period_start), fmt_ts(period_end), model),
                "ts": fmt_ts(period_end), "ticket": args.ticket, "role": UNASSIGNED, "model": model,
                "kind": "work", "tokens": tokens,
                "window_start": fmt_ts(period_start), "window_end": fmt_ts(period_end),
                "note": "usage in the ticket's period that no role segment claims"})

    uncalibrated, recorded, skipped = set(), [], []
    for event in planned:
        if args.sprint:
            event["sprint"] = args.sprint
        factor = factor_for(calibrations, event["model"])
        if factor:
            per_pct, factor_id, note = factor
            event["usage_pct"] = round(event["tokens"] / per_pct, 4)
            event["factor_id"] = factor_id
            if note:
                event["note"] = (event.get("note", "") + "; " if event.get("note") else "") + note
        else:
            uncalibrated.add(event["model"])
            event["note"] = (event.get("note", "") + "; " if event.get("note") else "") + \
                "uncalibrated: no tokens-per-1% factor for this model, so no usage_pct"
        prior = existing.get(event["event_id"])
        if prior is not None:
            if prior.get("tokens") != event["tokens"]:
                flags.append(f"Event {event['event_id']} ({event['role']}, {event['model']}) was recorded with "
                             f"{prior.get('tokens')} tokens but the transcripts now give {event['tokens']}: not "
                             "rewritten. Correct it with a new event that refers to it in `note`.")
            skipped.append(event["event_id"])
            continue
        if not args.dry_run:
            ledger_append(args, event)
        recorded.append(event)
    if uncalibrated:
        flags.append("No calibration for: " + ", ".join(sorted(uncalibrated))
                     + ". Their tokens are recorded without usage_pct and are not in any percent total.")
    if claimed_elsewhere:
        flags.append(f"{claimed_elsewhere} message(s) belong to segments of other tickets and were left out.")
    logger.info("record ticket=%s recorded=%d skipped=%d dry_run=%s", args.ticket, len(recorded), len(skipped), args.dry_run)

    by_role = {}
    for ev in recorded:
        by_role[ev["role"]] = round(by_role.get(ev["role"], 0) + ev.get("usage_pct", 0), 4)
    return {"ticket": args.ticket, "dry_run": bool(args.dry_run), "recorded": len(recorded),
            "already_recorded": len(skipped), "by_role_pct_new": by_role, "events": recorded, "flags": flags}


def summarize(events, ticket):
    """Per-role percent, unassigned percent and uncalibrated tokens for one ticket, from effort events."""
    by_role, unassigned, uncalibrated = {}, 0.0, 0
    for ev in events:
        if ev.get("event") != "effort" or ev.get("ticket") != ticket:
            continue
        if "usage_pct" not in ev:
            uncalibrated += int(ev.get("tokens", 0))
            continue
        if ev["role"] == UNASSIGNED:
            unassigned += ev["usage_pct"]
        else:
            by_role[ev["role"]] = by_role.get(ev["role"], 0.0) + ev["usage_pct"]
    return ({r: round(v, 4) for r, v in by_role.items()}, round(unassigned, 4), uncalibrated)


def effort_comment(by_role, unassigned, total, est, uncalibrated):
    parts = [f"{role} {num(pct)}" for role, pct in sorted(by_role.items(), key=lambda kv: (-kv[1], kv[0]))]
    if unassigned:
        parts.append(f"unassigned {num(unassigned)}")
    tail = f"total {num(total)}" + (f" vs est {num(est)}" if est is not None else " (no estimate)")
    parts.append(tail)
    text = "[EFFORT] " + " | ".join(parts)
    if uncalibrated:
        text += f" | +{uncalibrated} tokens uncalibrated"
    return text


def cmd_close(args):
    events = ledger_read(args, ticket=args.ticket)
    by_role, unassigned, uncalibrated = summarize(events, args.ticket)
    if not by_role and not unassigned and not uncalibrated:
        raise EffortError(f"No effort events for {args.ticket} in the ledger. Run `record` first; "
                          "a close with no usage would record a zero that is not measured.")
    total = round(sum(by_role.values()), 4)
    estimates = [e for e in events if e.get("event") == "estimate"]
    latest = newest(estimates)
    est = float(latest["est_pct"]) if latest else None
    event = {"event": "close", "ticket": args.ticket, "actual_pct": total, "by_role": by_role,
             "unassigned_pct": unassigned}
    if args.sprint:
        event["sprint"] = args.sprint
    if est is not None:
        event["est_pct"] = est
        event["delta_pct"] = round(total - est, 4)
        if est > 0:
            event["ratio"] = round(total / est, 4)
    event["event_id"] = stable_id("close", args.ticket, json.dumps(by_role, sort_keys=True), unassigned, est)
    result = ledger_append(args, event)
    flags = []
    if est is None:
        flags.append("No estimate recorded for this ticket (run `estimate`): delta and ratio are omitted.")
    if uncalibrated:
        flags.append(f"{uncalibrated} tokens have no calibration factor and are not in the total.")
    return {
        "ticket": args.ticket, "by_role_pct": by_role, "unassigned_pct": unassigned, "total_pct": total,
        "estimate_pct": est, "delta_pct": event.get("delta_pct"), "ratio": event.get("ratio"),
        "comment": effort_comment(by_role, unassigned, total, est, uncalibrated),
        "jira_actual_usage": round(total, 2),
        "jira_note": "Post `comment` on the ticket and on the epic. Set Actual usage (%) to jira_actual_usage "
                     "from the trial onward; while the system is being set up it stays empty (EDS-72 D5, D12).",
        "close_event_written": result["appended"], "flags": flags,
    }


def cmd_report(args):
    events = ledger_read(args)
    tickets = sorted({e["ticket"] for e in events if e.get("event") == "effort" and e.get("ticket")})
    if args.ticket:
        tickets = [t for t in tickets if t == args.ticket]
    rows, total_roles, total_unassigned, total_uncal = [], {}, 0.0, 0
    for ticket in tickets:
        by_role, unassigned, uncal = summarize(events, ticket)
        rows.append({"ticket": ticket, "by_role_pct": by_role, "unassigned_pct": unassigned,
                     "total_pct": round(sum(by_role.values()), 4), "uncalibrated_tokens": uncal})
        for role, pct in by_role.items():
            total_roles[role] = total_roles.get(role, 0.0) + pct
        total_unassigned += unassigned
        total_uncal += uncal
    return {
        "tickets": rows,
        "overall": {"by_role_pct": {r: round(v, 4) for r, v in sorted(total_roles.items())},
                    "unassigned_pct": round(total_unassigned, 4),
                    "roles_total_pct": round(sum(total_roles.values()), 4),
                    "grand_total_pct": round(sum(total_roles.values()) + total_unassigned, 4),
                    "uncalibrated_tokens": total_uncal},
    }


# ---------- entry point ----------

def build_parser():
    parser = argparse.ArgumentParser(description="Record per-role plan usage in the ledger and close a ticket's effort.")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p):
        p.add_argument("--ledger-dir", help="The eds-data ledger directory (default: ledger-append finds it).")
        p.add_argument("--sprint", default="")

    p = sub.add_parser("estimate")
    common(p)
    p.add_argument("--ticket", required=True)
    p.add_argument("--est-pct", required=True, type=float)
    p = sub.add_parser("record")
    common(p)
    p.add_argument("--ticket", required=True)
    p.add_argument("--transcript", action="append", required=True, help="[AGENT=]FILE, repeatable.")
    p.add_argument("--segments", help="role-assume's segments.jsonl (default: its state directory).")
    p.add_argument("--kind", choices=("work", "coordination", "review", "rework"),
                   help="Override the kind derived from the role.")
    p.add_argument("--dry-run", action="store_true", help="Compute and print; append nothing.")
    p = sub.add_parser("close")
    common(p)
    p.add_argument("--ticket", required=True)
    p = sub.add_parser("report")
    common(p)
    p.add_argument("--ticket")
    return parser


COMMANDS = {"estimate": cmd_estimate, "record": cmd_record, "close": cmd_close, "report": cmd_report}


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        result = COMMANDS[args.command](args)
    except EffortError as exc:
        logger.error("refused: %s", exc)
        print(json.dumps({"error": str(exc)}, indent=2))
        return EXIT_ERROR
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
