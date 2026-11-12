"""ledger-append: the one reader/writer module for the eds-data ledger.

Subcommands (all print one JSON object on stdout):

  append  --event JSON | --event-file FILE [--ledger-dir DIR]
          Validates one event against the record schema, fills event_id and
          schema_version when absent, and appends it to the right file
          (ledger/YYYY-MM.jsonl, or ledger/calibration.jsonl). An event_id
          already in the file is a no-op, so importing twice changes nothing.
  read    [--ledger-dir DIR] [--ticket EDS-n] [--event TYPE]
          Prints the events, oldest first, each with its `event` type set.
  commit  [--repo DIR] [--message TEXT] [--push]
          Commits what append wrote straight to `main`, but only when the diff
          contains nothing except ledger/ and reports/ files (the eds-data
          data-only rule). Anything else is refused.

The record format lives in eds-data docs/RECORD_SCHEMA.md; FIELDS below mirrors
it and the test fails if they drift apart. No other code opens ledger files.
"""

import argparse
import json
import os
import re
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import logging

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_BACKEND = os.getenv("LOG_BACKEND", "flat-file")


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "level": record.levelname,
            "skill": "ledger-append",
            "message": record.getMessage(),
            "timestamp": self.formatTime(record)
        })


if LOG_BACKEND != "cloudwatch":
    os.makedirs("logs", exist_ok=True)
handler = logging.StreamHandler() if LOG_BACKEND == "cloudwatch" else logging.FileHandler("logs/ledger-append.log")
handler.setFormatter(JsonFormatter())

logger = logging.getLogger("ledger-append")
logger.setLevel(LOG_LEVEL)
if not logger.handlers:
    logger.addHandler(handler)


SCHEMA_VERSION = 2
EXIT_ERROR = 2
LEDGER_DIR_ENV = "EDS_LEDGER_DIR"
CALIBRATION_FILE = "calibration.jsonl"
DATA_ONLY_DIRS = ("ledger/", "reports/")

KINDS = ("work", "coordination", "review", "rework")
BASES = ("five_hour", "weekly", "ratio")
STATUSES = ("provisional", "measured")
EVENTS = ("effort", "estimate", "close", "calibration")

# type: s string, i integer, n number (not bool), o object of str -> number
COMMON = {"event_id": "s", "schema_version": "i", "ts": "s", "event": "s"}
FIELDS = {
    "effort": {
        "required": {"ticket": "s", "role": "s", "model": "s", "tokens": "i", "kind": "s"},
        "optional": {"sprint": "s", "agent": "s", "skill": "s", "usage_pct": "n", "note": "s",
                     "segment_id": "s", "window_start": "s", "window_end": "s", "factor_id": "s"},
    },
    "estimate": {
        "required": {"ticket": "s", "est_pct": "n"},
        "optional": {"sprint": "s", "role": "s", "agent": "s", "note": "s"},
    },
    "close": {
        "required": {"ticket": "s", "actual_pct": "n"},
        "optional": {"sprint": "s", "agent": "s", "note": "s", "est_pct": "n", "delta_pct": "n",
                     "ratio": "n", "unassigned_pct": "n", "by_role": "o"},
    },
    "calibration": {
        "required": {"basis": "s"},
        "optional": {"model": "s", "tokens_per_pct": "n", "low": "n", "high": "n",
                     "weekly_per_five_hour": "n", "factor_version": "s", "status": "s",
                     "source": "s", "note": "s"},
    },
}


class LedgerError(Exception):
    """A refusal the caller must see; printed as JSON and exits 2."""


# ---------- time ----------

def parse_ts(value):
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        raise LedgerError(f"ts '{value}' is not ISO 8601.")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now_ts():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------- locating the ledger ----------

def find_ledger_dir(explicit=None):
    candidates = [explicit, os.environ.get(LEDGER_DIR_ENV)]
    cwd = Path.cwd()
    candidates += [cwd / "ledger", cwd.parent / "eds-data" / "ledger", "/mnt/c/repos/eds-data/ledger"]
    for cand in candidates:
        if cand and Path(cand).is_dir():
            return Path(cand)
    raise LedgerError("ledger directory not found. Pass --ledger-dir, set EDS_LEDGER_DIR, or run from the "
                      "eds-data clone. Nothing is written without it.")


# ---------- validation ----------

def infer_event(rec):
    """The event type of a version 1 line, which has no `event` field."""
    if rec.get("event"):
        return rec["event"]
    if "tokens" in rec:
        return "effort"
    if "est_pct" in rec:
        return "estimate"
    if "actual_pct" in rec:
        return "close"
    return None


def _type_ok(kind, value):
    if kind == "s":
        return isinstance(value, str)
    if kind == "i":
        return isinstance(value, int) and not isinstance(value, bool)
    if kind == "n":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if kind == "o":
        return isinstance(value, dict) and all(isinstance(k, str) and _type_ok("n", v) for k, v in value.items())
    return False


def validate(event):
    """Raise LedgerError unless `event` fits the schema exactly."""
    kind = event.get("event")
    if kind not in EVENTS:
        raise LedgerError(f"event must be one of {', '.join(EVENTS)}; got {kind!r}.")
    spec = FIELDS[kind]
    allowed = {**COMMON, **spec["required"], **spec["optional"]}
    unknown = sorted(set(event) - set(allowed))
    if unknown:
        raise LedgerError(
            f"{kind} event has fields the schema does not define: {', '.join(unknown)}. "
            "Adding a field is a schema change: a PR to eds-data, not a direct write.")
    for name in ("event_id", "schema_version", "ts", "event", *spec["required"]):
        if name not in event:
            raise LedgerError(f"{kind} event is missing required field '{name}'.")
    for name, value in event.items():
        if not _type_ok(allowed[name], value):
            raise LedgerError(f"field '{name}' has the wrong type ({type(value).__name__}).")
    parse_ts(event["ts"])
    for name in ("window_start", "window_end"):
        if name in event:
            parse_ts(event[name])
    if kind == "effort":
        if event["kind"] not in KINDS:
            raise LedgerError(f"kind must be one of {', '.join(KINDS)}.")
        if event["tokens"] < 0:
            raise LedgerError("tokens cannot be negative.")
        if not event["role"]:
            raise LedgerError("role cannot be empty: use 'unassigned' for usage no role can claim.")
        if "usage_pct" in event and event["usage_pct"] < 0:
            raise LedgerError("usage_pct cannot be negative.")
    if kind == "calibration":
        if event["basis"] not in BASES:
            raise LedgerError(f"basis must be one of {', '.join(BASES)}.")
        if event["basis"] == "ratio":
            if "weekly_per_five_hour" not in event or event["weekly_per_five_hour"] <= 0:
                raise LedgerError("a ratio calibration needs weekly_per_five_hour greater than 0.")
            if "model" in event or "tokens_per_pct" in event:
                raise LedgerError("a ratio calibration carries only weekly_per_five_hour, not model or tokens_per_pct.")
        else:
            if "model" not in event or "tokens_per_pct" not in event or event["tokens_per_pct"] <= 0:
                raise LedgerError("a five_hour or weekly calibration needs model and tokens_per_pct greater than 0.")
            if "weekly_per_five_hour" in event:
                raise LedgerError("weekly_per_five_hour belongs on a ratio calibration only.")
        if "status" in event and event["status"] not in STATUSES:
            raise LedgerError(f"status must be one of {', '.join(STATUSES)}.")


# ---------- the store ----------

def path_for(ledger_dir, event):
    if event["event"] == "calibration":
        return Path(ledger_dir) / CALIBRATION_FILE
    return Path(ledger_dir) / (parse_ts(event["ts"]).strftime("%Y-%m") + ".jsonl")


def read_file(path):
    path = Path(path)
    if not path.is_file():
        return []
    out = []
    for n, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            raise LedgerError(f"{path.name} line {n} is not valid JSON; ledger files are never edited by hand.")
        out.append(rec)
    return out


def read_all(ledger_dir):
    events = []
    for path in sorted(Path(ledger_dir).glob("*.jsonl")):
        for rec in read_file(path):
            rec = {**rec}
            rec["event"] = infer_event(rec) or "unknown"
            events.append(rec)
    events.sort(key=lambda r: str(r.get("ts", "")))
    return events


def append_event(ledger_dir, event):
    """Validate and append one event. Returns (path, written). One whole line in one write."""
    event = dict(event)
    event.setdefault("event_id", uuid.uuid4().hex)
    event.setdefault("schema_version", SCHEMA_VERSION)
    event.setdefault("ts", now_ts())
    validate(event)
    path = path_for(ledger_dir, event)
    if any(rec.get("event_id") == event["event_id"] for rec in read_file(path)):
        logger.info("duplicate event_id %s ignored", event["event_id"])
        return path, False
    line = (json.dumps(event, separators=(",", ":"), sort_keys=False) + "\n").encode("utf-8")
    fd = os.open(path, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)
    logger.info("appended %s event %s to %s", event["event"], event["event_id"], path.name)
    return path, True


# ---------- commands ----------

def cmd_append(args):
    if bool(args.event) == bool(args.event_file):
        raise LedgerError("Pass exactly one of --event JSON or --event-file FILE.")
    raw = args.event if args.event else Path(args.event_file).read_text(encoding="utf-8")
    try:
        event = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise LedgerError(f"event is not valid JSON: {exc}")
    if not isinstance(event, dict):
        raise LedgerError("event must be a JSON object.")
    path, written = append_event(find_ledger_dir(args.ledger_dir), event)
    return {"appended": written, "file": path.name, "path": str(path),
            "note": None if written else "event_id already present; nothing written."}


def cmd_read(args):
    events = read_all(find_ledger_dir(args.ledger_dir))
    if args.ticket:
        events = [e for e in events if e.get("ticket") == args.ticket]
    if args.event:
        events = [e for e in events if e.get("event") == args.event]
    return {"count": len(events), "events": events}


def _git(repo, *argv):
    proc = subprocess.run(["git", "-C", str(repo), *argv], capture_output=True, text=True)
    # rstrip only: the first column of `git status --porcelain` can be a leading space
    return proc.returncode, proc.stdout.rstrip(), proc.stderr.strip()


def changed_paths(repo):
    """Every path git sees as changed or untracked, as repo-relative forward-slash strings."""
    code, out, err = _git(repo, "status", "--porcelain", "--untracked-files=all")
    if code != 0:
        raise LedgerError(f"git status failed: {err}")
    paths = []
    for line in out.splitlines():
        entry = line[3:]
        if " -> " in entry:  # a rename touches two paths
            paths.extend(p.strip('"') for p in entry.split(" -> "))
        else:
            paths.append(entry.strip('"'))
    return paths


def cmd_commit(args):
    ledger_dir = find_ledger_dir(args.repo + "/ledger" if args.repo else None)
    repo = Path(args.repo) if args.repo else ledger_dir.parent
    if not (repo / "docs" / "RECORD_SCHEMA.md").is_file():
        raise LedgerError(f"{repo} is not the eds-data repo (no docs/RECORD_SCHEMA.md). Nothing committed.")
    code, branch, err = _git(repo, "rev-parse", "--abbrev-ref", "HEAD")
    if code != 0 or branch != "main":
        raise LedgerError(f"On branch '{branch}', not main. Data-only commits go straight to main only; "
                          "any other change is a branch, a PR and Brad's merge.")
    paths = changed_paths(repo)
    if not paths:
        return {"committed": False, "note": "Nothing to commit."}
    foreign = [p for p in paths if not p.startswith(DATA_ONLY_DIRS)]
    if foreign:
        raise LedgerError("The diff contains more than ledger data: " + ", ".join(foreign)
                          + ". Nothing committed: a mixed change is structural (branch, PR, Brad's merge).")
    for rel in paths:  # only new lines: a ledger file is never rewritten, so no deletions or edits to old lines
        code, out, _ = _git(repo, "diff", "--numstat", "HEAD", "--", rel)
        if code == 0 and out:
            added, removed = out.split("\t")[:2]
            if removed not in ("0", "-"):
                raise LedgerError(f"{rel} has removed or changed lines; ledger files are append-only. Nothing committed.")
    code, out, err = _git(repo, "add", "--", *paths)
    if code != 0:
        raise LedgerError(f"git add failed: {err}")
    message = args.message or "data: append ledger events"
    code, out, err = _git(repo, "commit", "-m", message)
    if code != 0:
        raise LedgerError(f"git commit failed: {err or out}")
    result = {"committed": True, "paths": paths, "pushed": False}
    if args.push:
        code, out, err = _git(repo, "push", "origin", "main")
        if code != 0:
            raise LedgerError(f"Committed locally but git push failed: {err}. Run it in WSL, and pull first if main moved.")
        result["pushed"] = True
    logger.info("data-only commit %s pushed=%s", ",".join(paths), result["pushed"])
    return result


# ---------- entry point ----------

def build_parser():
    parser = argparse.ArgumentParser(description="Append to and read the eds-data ledger.")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("append")
    p.add_argument("--event")
    p.add_argument("--event-file")
    p.add_argument("--ledger-dir")
    p = sub.add_parser("read")
    p.add_argument("--ledger-dir")
    p.add_argument("--ticket")
    p.add_argument("--event", choices=EVENTS)
    p = sub.add_parser("commit")
    p.add_argument("--repo", help="The eds-data clone (default: the parent of the ledger directory).")
    p.add_argument("--message")
    p.add_argument("--push", action="store_true")
    return parser


COMMANDS = {"append": cmd_append, "read": cmd_read, "commit": cmd_commit}


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        result = COMMANDS[args.command](args)
    except LedgerError as exc:
        logger.error("refused: %s", exc)
        print(json.dumps({"error": str(exc)}, indent=2))
        return EXIT_ERROR
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
