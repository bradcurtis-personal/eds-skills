"""role-assume: declare the role an agent assumes and attribute its effort to it.

Subcommands (all print one JSON object on stdout):

  assume    --role ID --agent NAME [--ticket EDS-n] [--session ID]
            Declares the role, closes any segment this agent holds (a switch),
            opens an effort segment, and prints the stamp, trailer, identities,
            tiers and the rules read from ROLE_REGISTRY.md.
  release   --agent NAME [--session ID]
            Closes the segment this agent holds. Flags it when none is open.
  status    --agent NAME [--session ID]
            Shows the open segment, or flags that effort is unassigned.
  check     --agent NAME [--session ID] --system S [--tier T] [--identity I]
            Is the role allowed this tier / identity? A refusal prints a
            request addressed to the lead and exits 3.
  attribute --transcript FILE [--transcript FILE ...] [--agent NAME]
            Splits the token usage in session transcripts by segment. Usage
            outside every segment is recorded as `unassigned` and flagged.

The role records and the rules live in engineering-design-system
(role-registry.yaml, ROLE_REGISTRY.md); this skill reads them and copies
neither. Segment events are appended to segments.jsonl in the state directory
(default ~/.eds/role-segments, override with EDS_ROLE_STATE_DIR): a local
cache outside every repo. Writing the ledger is EDS-77's job.
"""

import argparse
import re
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import yaml

import logging
import json
import os

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
LOG_BACKEND = os.getenv("LOG_BACKEND", "flat-file")


class JsonFormatter(logging.Formatter):
    def format(self, record):
        return json.dumps({
            "level": record.levelname,
            "skill": "role-assume",
            "message": record.getMessage(),
            "timestamp": self.formatTime(record)
        })


if LOG_BACKEND != "cloudwatch":
    os.makedirs("logs", exist_ok=True)
handler = logging.StreamHandler() if LOG_BACKEND == "cloudwatch" else logging.FileHandler("logs/role-assume.log")
handler.setFormatter(JsonFormatter())

logger = logging.getLogger("role-assume")
logger.setLevel(LOG_LEVEL)
if not logger.handlers:
    logger.addHandler(handler)


SCHEMA_VERSION = 1
UNASSIGNED = "unassigned"
SEGMENTS_FILE = "segments.jsonl"
EXIT_ERROR = 2
EXIT_DENIED = 3

REGISTRY_ENV = "EDS_REGISTRY"
STATE_DIR_ENV = "EDS_ROLE_STATE_DIR"
USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "cache_creation_input_tokens",
    "cache_read_input_tokens",
)


class RoleError(Exception):
    """A refusal the agent must see; printed as JSON and exits 2."""


# ---------- time ----------

def parse_ts(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def fmt_ts(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def now_ts(args):
    if getattr(args, "now", None):
        return fmt_ts(parse_ts(args.now))
    return fmt_ts(datetime.now(timezone.utc))


# ---------- registry ----------

def find_registry(explicit=None):
    candidates = []
    if explicit:
        candidates.append(Path(explicit))
    if os.environ.get(REGISTRY_ENV):
        candidates.append(Path(os.environ[REGISTRY_ENV]))
    cwd = Path.cwd()
    candidates += [
        cwd / "role-registry.yaml",
        cwd.parent / "engineering-design-system" / "role-registry.yaml",
        Path("/mnt/c/repos/engineering-design-system/role-registry.yaml"),
    ]
    for path in candidates:
        if path.is_file():
            return path
    raise RoleError(
        "role-registry.yaml not found. Pass --registry, set EDS_REGISTRY, or run from the "
        "engineering-design-system clone. Without the registry no role can be assumed."
    )


def load_registry(explicit=None):
    path = find_registry(explicit)
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not isinstance(data.get("roles"), list):
        raise RoleError(f"{path} is not a role registry (no 'roles' list).")
    roles = {r["id"]: r for r in data["roles"]}
    return path, roles


def read_section(doc_text, heading):
    """The body of the `## <heading>...` section of ROLE_REGISTRY.md, up to the next rule."""
    match = re.search(r"^## " + re.escape(heading) + r".*?\n(.*?)(?=^---\s*$|\Z)", doc_text, re.S | re.M)
    return match.group(1).strip() if match else ""


def load_doc(registry_path):
    doc = registry_path.parent / "ROLE_REGISTRY.md"
    if not doc.is_file():
        raise RoleError(f"{doc} not found; the rules and tier vocabulary live there.")
    return doc, doc.read_text(encoding="utf-8")


def tier_vocabulary(doc_text):
    """{system: [tiers lowest to highest]} read from the tier table in ROLE_REGISTRY.md."""
    vocab = {}
    for line in read_section(doc_text, "Permission tiers").splitlines():
        row = re.match(r"^\|\s*`(\w+)`\s*\|(.*)\|\s*$", line)
        if row:
            # drop the parenthesised descriptions, which can mention other backticked words
            tiers = re.findall(r"`([a-z-]+)`", re.sub(r"\([^)]*\)", "", row.group(2)))
            if tiers and tiers[0] == "none":
                vocab[row.group(1)] = tiers
    return vocab


# ---------- segment store (append-only, local cache) ----------

def state_dir(args):
    path = Path(getattr(args, "state_dir", None) or os.environ.get(STATE_DIR_ENV)
                or Path.home() / ".eds" / "role-segments")
    path.mkdir(parents=True, exist_ok=True)
    return path


def append_event(args, event):
    """One whole line in one write on an O_APPEND handle, so a reader never sees half a line."""
    event = {"event_id": uuid.uuid4().hex, "schema_version": SCHEMA_VERSION, **event}
    line = (json.dumps(event, separators=(",", ":")) + "\n").encode("utf-8")
    fd = os.open(state_dir(args) / SEGMENTS_FILE, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)
    try:
        os.write(fd, line)
        os.fsync(fd)
    finally:
        os.close(fd)
    return event


def read_events(path):
    path = Path(path)
    if not path.is_file():
        return []
    events = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            events.append(json.loads(line))
    return events


def segments_from(events):
    """Replay events into segments: {segment_id: {...open fields, ts_close, close_reason}}."""
    segments = {}
    for ev in events:
        kind = ev.get("event")
        if kind == "segment_open":
            segments[ev["segment_id"]] = {
                "segment_id": ev["segment_id"], "role": ev["role"], "agent": ev["agent"],
                "session": ev.get("session", ""), "ticket": ev.get("ticket", ""),
                "ts_open": ev["ts"], "ts_close": None, "close_reason": None,
            }
        elif kind == "segment_close" and ev["segment_id"] in segments:
            segments[ev["segment_id"]]["ts_close"] = ev["ts"]
            segments[ev["segment_id"]]["close_reason"] = ev.get("reason", "release")
    return list(segments.values())


def open_segment(args, agent, session):
    events = read_events(state_dir(args) / SEGMENTS_FILE)
    for seg in segments_from(events):
        if seg["ts_close"] is None and seg["agent"] == agent and seg["session"] == (session or ""):
            return seg
    return None


def close_segment(args, seg, reason):
    stamp = now_ts(args)
    append_event(args, {"event": "segment_close", "ts": stamp,
                        "segment_id": seg["segment_id"], "reason": reason})
    return {**seg, "ts_close": stamp, "close_reason": reason}


# ---------- commands ----------

def cmd_assume(args):
    registry_path, roles = load_registry(args.registry)
    role = roles.get(args.role)
    if role is None:
        raise RoleError(f"Unknown role '{args.role}'. Known roles: {', '.join(sorted(roles))}.")
    if role.get("status") != "active":
        raise RoleError(f"Role '{args.role}' is {role.get('status')}: a dormant role is not assumed until Brad sets it active.")
    if role.get("type") == "human":
        raise RoleError(f"Role '{args.role}' is a human role; an agent does not assume it. Ask the lead or Brad.")
    doc_path, doc_text = load_doc(registry_path)

    previous = open_segment(args, args.agent, args.session)
    closed = close_segment(args, previous, "switch") if previous else None

    segment = {
        "event": "segment_open", "ts": now_ts(args), "segment_id": uuid.uuid4().hex,
        "role": role["ledger_key"], "agent": args.agent,
        "session": args.session or "", "ticket": args.ticket or "",
    }
    append_event(args, segment)
    logger.info("assume role=%s agent=%s ticket=%s", role["id"], args.agent, args.ticket or "")

    display = role["display_name"]
    return {
        "assumed": role["id"],
        "segment": {k: segment[k] for k in ("segment_id", "role", "agent", "session", "ticket", "ts")},
        "closed_previous": closed,
        "stamp": f"[{display}]",
        "commit_trailer": f"Role: {display}",
        "identities": role["identities"],
        "tiers": role["tiers"],
        "default_model": role["default_model"],
        "plugin": role["plugin"],
        "plugin_note": f"Invoke the '{role['plugin']}' plugin skill for the role's own expectations, if it is installed. "
                       "Role plugins are built later; until one exists the registry rules below are the role's rules.",
        "registry": str(registry_path),
        "rules_source": str(doc_path),
        "role_assumption_rules": read_section(doc_text, "Role-assumption rules"),
        "do_not_list": read_section(doc_text, "DO-NOT list"),
        "capability_requests": "A needed capability this role lacks is a request to the lead: run `check` and send the request it prints. Do not obtain it another way.",
    }


def cmd_release(args):
    seg = open_segment(args, args.agent, args.session)
    if seg is None:
        logger.warning("release with no open segment agent=%s", args.agent)
        return {"released": None,
                "flag": "No open segment for this agent: effort since the last release is recorded as unassigned."}
    closed = close_segment(args, seg, "release")
    logger.info("release role=%s agent=%s", seg["role"], args.agent)
    return {"released": closed,
            "note": "Effort from now on is unassigned until a role is assumed again."}


def cmd_status(args):
    seg = open_segment(args, args.agent, args.session)
    if seg is None:
        return {"open": None, "flag": "No role assumed: effort is recorded as unassigned."}
    return {"open": seg}


def cmd_check(args):
    registry_path, roles = load_registry(args.registry)
    seg = open_segment(args, args.agent, args.session)
    if seg is None:
        return {"allowed": False,
                "reason": "No role assumed; assume one before acting. Effort now is unassigned."}, EXIT_DENIED
    role = roles[seg["role"]]
    _, doc_text = load_doc(registry_path)
    vocab = tier_vocabulary(doc_text)
    system = args.system
    if system not in vocab:
        raise RoleError(f"Unknown system '{system}'. Known systems: {', '.join(sorted(vocab))}.")

    problems = []
    have = role["tiers"].get(system, "none")
    if args.tier:
        if args.tier not in vocab[system]:
            raise RoleError(f"Unknown tier '{args.tier}' for {system}. Tiers: {', '.join(vocab[system])}.")
        if vocab[system].index(have) < vocab[system].index(args.tier):
            problems.append(f"needs {system} tier '{args.tier}'; role '{role['id']}' holds '{have}'")
    if args.identity:
        own = role["identities"].get(system)
        if args.identity != own:
            problems.append(
                f"identity '{args.identity}' on {system} is not this role's; role '{role['id']}' acts as '{own}'. "
                "Never use another role's credentials")
    if not problems:
        return {"allowed": True, "role": role["id"], "system": system, "tier": have}, 0

    recipient = "product-owner" if role["id"] == "lead" else "lead"
    text = (f"[{role['display_name']}] Request to {roles[recipient]['display_name']}: "
            f"{'; '.join(problems)}. Not proceeding until granted.")
    request = {"to": recipient, "from": role["id"], "system": system, "tier": args.tier,
               "identity": args.identity, "text": text}
    append_event(args, {"event": "capability_request", "ts": now_ts(args),
                        "segment_id": seg["segment_id"], "role": seg["role"], "to": recipient,
                        "system": system, "tier": args.tier or "", "text": text})
    logger.warning("denied role=%s system=%s tier=%s identity=%s", role["id"], system, args.tier, args.identity)
    return {"allowed": False, "role": role["id"], "reason": problems, "request": request}, EXIT_DENIED


def iter_usage(transcript):
    """Yield (datetime, message_id, model, usage dict) for each assistant message in a transcript JSONL."""
    for line in Path(transcript).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        rec = json.loads(line)
        msg = rec.get("message")
        stamp = rec.get("timestamp") or rec.get("ts")
        if not isinstance(msg, dict) or not isinstance(msg.get("usage"), dict) or not stamp:
            continue
        yield parse_ts(stamp), msg.get("id"), msg.get("model", ""), msg["usage"]


def cmd_attribute(args):
    segments = segments_from(read_events(args.segments or state_dir(args) / SEGMENTS_FILE))
    if args.agent:
        segments = [s for s in segments if s["agent"] == args.agent]
    spans = [(parse_ts(s["ts_open"]), parse_ts(s["ts_close"]) if s["ts_close"] else None, s) for s in segments]

    totals = {s["segment_id"]: {**s, "messages": 0, "tokens": 0, "by_model": {}} for s in segments}
    unassigned = {"messages": 0, "tokens": 0, "by_model": {}}
    seen = set()
    for transcript in args.transcript:
        for when, mid, model, usage in iter_usage(transcript):
            if mid:  # each API message is written twice to the jsonl: dedupe by message.id
                if mid in seen:
                    continue
                seen.add(mid)
            tokens = sum(int(usage.get(f) or 0) for f in USAGE_FIELDS)
            bucket = unassigned
            for start, end, seg in spans:
                if start <= when and (end is None or when < end):
                    bucket = totals[seg["segment_id"]]
                    break
            bucket["messages"] += 1
            bucket["tokens"] += tokens
            bucket["by_model"][model] = bucket["by_model"].get(model, 0) + tokens

    by_role = {}
    for seg in totals.values():
        by_role[seg["role"]] = by_role.get(seg["role"], 0) + seg["tokens"]
    if unassigned["tokens"]:
        by_role[UNASSIGNED] = unassigned["tokens"]
    flags = []
    if unassigned["messages"]:
        flags.append(f"{unassigned['messages']} message(s), {unassigned['tokens']} tokens fell outside every segment "
                     f"and are recorded as '{UNASSIGNED}'.")
    flags += [f"Segment {s['segment_id']} ({s['role']}) is still open: counted to now." for s in segments if not s["ts_close"]]
    return {
        "usage_fields_summed": list(USAGE_FIELDS),
        "segments": list(totals.values()),
        UNASSIGNED: unassigned,
        "by_role": by_role,
        "total_tokens": sum(by_role.values()),
        "flags": flags,
    }


# ---------- entry point ----------

def build_parser():
    parser = argparse.ArgumentParser(description="Declare a role, open and close effort segments, attribute usage.")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p, agent_required=True):
        p.add_argument("--agent", required=agent_required, help="Name of the agent doing the work.")
        p.add_argument("--session", default="", help="Session id, when the agent has one.")
        p.add_argument("--registry", help="Path to role-registry.yaml (default: found from the environment).")
        p.add_argument("--state-dir", help=f"Segment state directory (default ${STATE_DIR_ENV} or ~/.eds/role-segments).")
        p.add_argument("--now", help="ISO 8601 UTC time to stamp events with, for tests and replay.")

    p = sub.add_parser("assume")
    common(p)
    p.add_argument("--role", required=True)
    p.add_argument("--ticket", default="")
    p = sub.add_parser("release")
    common(p)
    p = sub.add_parser("status")
    common(p)
    p = sub.add_parser("check")
    common(p)
    p.add_argument("--system", required=True)
    p.add_argument("--tier")
    p.add_argument("--identity")
    p = sub.add_parser("attribute")
    common(p, agent_required=False)
    p.add_argument("--transcript", action="append", required=True)
    p.add_argument("--segments", help="Segment file (default: the state directory's).")
    return parser


COMMANDS = {"assume": cmd_assume, "release": cmd_release, "status": cmd_status,
            "check": cmd_check, "attribute": cmd_attribute}


def main(argv=None):
    args = build_parser().parse_args(argv)
    try:
        result = COMMANDS[args.command](args)
    except RoleError as exc:
        logger.error("refused: %s", exc)
        print(json.dumps({"error": str(exc)}, indent=2))
        return EXIT_ERROR
    code = 0
    if isinstance(result, tuple):
        result, code = result
    print(json.dumps(result, indent=2))
    return code


if __name__ == "__main__":
    sys.exit(main())
