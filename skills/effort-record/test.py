"""
Acceptance test for the effort-record skill.

Behavior tests run main.main() against a disposable ledger directory and
role-segment file, calling the real sibling ledger-append skill through its
command line. They never touch the real eds-data clone or the real segment cache.
"""

import contextlib
import importlib.util
import io
import json
import os
import re
import tempfile
from pathlib import Path

try:
    import yaml
except ImportError:
    yaml = None

SKILL_DIR = Path(__file__).parent
REQUIRED_METADATA_FIELDS = [
    "name", "version", "category", "layer", "rank", "description", "inputs",
    "outputs", "dependencies", "stack", "runtime-independent", "logging",
]


def test_skill_json_valid_and_complete():
    data = json.loads((SKILL_DIR / "skill.json").read_text(encoding="utf-8"))
    for field in REQUIRED_METADATA_FIELDS:
        assert field in data, f"skill.json missing required field: {field}"
    assert data["name"] == "effort-record"
    assert data["category"] == "system"


def test_skill_md_has_valid_frontmatter():
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    assert match, "SKILL.md must start with YAML frontmatter"
    if yaml is not None:
        frontmatter = yaml.safe_load(match.group(1))
        assert frontmatter["name"] == "effort-record"
        assert isinstance(frontmatter["description"], str) and frontmatter["description"].strip()
    else:
        assert re.search(r"^name: effort-record$", match.group(1), re.M)
        assert re.search(r'^description: ".+"$', match.group(1), re.M)


def test_logic_file_exists():
    assert (SKILL_DIR / "main.py").exists(), "expected logic file main.py is missing"


# ---------- behavior ----------

def _load_module(workdir):
    previous = os.getcwd()
    os.chdir(workdir)  # the logging bootstrap creates logs/ in the working directory
    try:
        spec = importlib.util.spec_from_file_location("effort_record_main", SKILL_DIR / "main.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        os.chdir(previous)


def _ts(minute, hour=10):
    return f"2026-11-12T{hour:02d}:{minute:02d}:00.000Z"


class _Env:
    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ledger = self.root / "ledger"
        self.ledger.mkdir()
        self.segments = self.root / "segments.jsonl"
        self.module = _load_module(self.root)
        self._events = []

    def run(self, *argv):
        previous = os.getcwd()
        os.chdir(self.root)  # ledger-append's log file goes here, not into the checkout
        buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(buffer):
                extra = ["--segments", str(self.segments)] if argv[0] == "record" else []
                code = self.module.main([argv[0], "--ledger-dir", str(self.ledger), *extra, *argv[1:]])
        finally:
            os.chdir(previous)
        return code, json.loads(buffer.getvalue())

    def ledger_append(self, event):
        from_main = self.module.find_ledger_append()
        import subprocess, sys
        proc = subprocess.run([sys.executable, str(from_main), "append", "--ledger-dir", str(self.ledger),
                               "--event", json.dumps(event)], capture_output=True, text=True, cwd=self.root)
        assert proc.returncode == 0, proc.stdout + proc.stderr

    def calibrate(self):
        self.ledger_append({"event": "calibration", "basis": "five_hour", "model": "claude-sonnet",
                            "tokens_per_pct": 1400000, "status": "provisional", "source": "EDS-108",
                            "ts": "2026-11-09T00:00:00Z"})
        self.ledger_append({"event": "calibration", "basis": "five_hour", "model": "claude-haiku",
                            "tokens_per_pct": 5700000, "status": "provisional", "source": "EDS-108",
                            "ts": "2026-11-09T00:00:00Z"})
        self.ledger_append({"event": "calibration", "basis": "ratio", "weekly_per_five_hour": 0.25,
                            "status": "provisional", "source": "EDS-108", "ts": "2026-11-09T00:00:00Z"})

    def segment(self, seg_id, role, agent, ticket, open_at, close_at=None):
        self._events.append({"event": "segment_open", "ts": open_at, "segment_id": seg_id, "role": role,
                             "agent": agent, "session": "", "ticket": ticket})
        if close_at:
            self._events.append({"event": "segment_close", "ts": close_at, "segment_id": seg_id, "reason": "release"})
        self.segments.write_text("".join(json.dumps(e) + "\n" for e in self._events), encoding="utf-8")

    def transcript(self, name, messages):
        path = self.root / name
        lines = []
        for when, mid, model, usage in messages:
            lines.append(json.dumps({"timestamp": when, "message": {"id": mid, "model": model, "usage": usage}}))
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(path)

    def close(self):
        self._tmp.cleanup()


def _usage(total):
    """Split a total over all four usage fields so the sum is what counts."""
    quarter = total // 4
    return {"input_tokens": quarter, "output_tokens": quarter,
            "cache_creation_input_tokens": quarter, "cache_read_input_tokens": total - 3 * quarter}


def _scenario(env):
    """One ticket, three roles' worth of usage, one gap, one duplicate, one foreign segment."""
    env.calibrate()
    env.segment("s-dev", "developer", "a1", "EDS-77", _ts(0), _ts(10))
    env.segment("s-rev", "reviewer", "a1", "EDS-77", _ts(15), _ts(20))
    env.segment("s-other", "developer", "a1", "EDS-78", _ts(20), _ts(30))
    return env.transcript("session.jsonl", [
        (_ts(2), "m1", "claude-sonnet-5-5", _usage(2800000)),      # developer: 2.8M / 5.6M = 0.5
        (_ts(2), "m1", "claude-sonnet-5-5", _usage(2800000)),      # the same API message again: counted once
        (_ts(12), "m2", "claude-haiku-5-5", _usage(5700000)),      # in the gap, no segment: unassigned 0.25
        (_ts(16), "m3", "claude-sonnet-5-5", _usage(1400000)),     # reviewer: 0.25
        (_ts(17), "m4", "claude-opus-5-5", _usage(1000)),          # reviewer, but no factor for Opus
        (_ts(25), "m5", "claude-sonnet-5-5", _usage(9999999)),     # inside another ticket's segment
        (_ts(0, hour=11), "m6", "claude-sonnet-5-5", _usage(9999999)),  # after the ticket's period
    ])


def test_record_splits_usage_by_role_and_keeps_an_unassigned_figure():
    env = _Env()
    try:
        transcript = _scenario(env)
        code, out = env.run("record", "--ticket", "EDS-77", "--transcript", transcript)
        assert code == 0, out
        assert out["by_role_pct_new"] == {"developer": 0.5, "unassigned": 0.25, "reviewer": 0.25}, out["by_role_pct_new"]
        flags = " ".join(out["flags"])
        assert "claude-opus-5-5" in flags and "1 message(s) belong to segments of other tickets" in flags
        kinds = {(e["role"], e["model"]): e["kind"] for e in out["events"]}
        assert kinds[("developer", "claude-sonnet-5-5")] == "work"
        assert kinds[("reviewer", "claude-sonnet-5-5")] == "review"
        opus = next(e for e in out["events"] if e["model"] == "claude-opus-5-5")
        assert "usage_pct" not in opus and opus["tokens"] == 1000 and "uncalibrated" in opus["note"]
        dev = next(e for e in out["events"] if e["role"] == "developer")
        assert dev["tokens"] == 2800000, "the duplicate line must not double-count"
        assert dev["segment_id"] == "s-dev" and dev["factor_id"] and "ratio" in dev["note"]
        # the ledger holds the same lines
        code, ledger = env.run("report")
        assert ledger["tickets"][0]["by_role_pct"] == {"developer": 0.5, "reviewer": 0.25}
        assert ledger["tickets"][0]["unassigned_pct"] == 0.25
    finally:
        env.close()


def test_record_twice_changes_nothing_and_flags_a_changed_transcript():
    env = _Env()
    try:
        transcript = _scenario(env)
        first = env.run("record", "--ticket", "EDS-77", "--transcript", transcript)[1]
        again = env.run("record", "--ticket", "EDS-77", "--transcript", transcript)[1]
        assert again["recorded"] == 0 and again["already_recorded"] == first["recorded"]
        assert not any("was recorded with" in f for f in again["flags"])
        # a bigger transcript for the same segment is flagged, never rewritten
        bigger = env.transcript("bigger.jsonl", [(_ts(2), "x1", "claude-sonnet-5-5", _usage(3000000))])
        out = env.run("record", "--ticket", "EDS-77", "--transcript", bigger)[1]
        assert any("was recorded with 2800000 tokens" in f for f in out["flags"]), out["flags"]
        code, ledger = env.run("report")
        assert ledger["tickets"][0]["by_role_pct"]["developer"] == 0.5
    finally:
        env.close()


def test_dry_run_appends_nothing():
    env = _Env()
    try:
        transcript = _scenario(env)
        out = env.run("record", "--ticket", "EDS-77", "--transcript", transcript, "--dry-run")[1]
        assert out["dry_run"] and out["recorded"] == 4
        assert env.run("report")[1]["tickets"] == []
    finally:
        env.close()


def test_close_computes_delta_ratio_and_the_effort_comment():
    env = _Env()
    try:
        transcript = _scenario(env)
        env.run("estimate", "--ticket", "EDS-77", "--est-pct", "1")
        env.run("record", "--ticket", "EDS-77", "--transcript", transcript)
        code, out = env.run("close", "--ticket", "EDS-77")
        assert code == 0, out
        assert out["total_pct"] == 0.75 and out["delta_pct"] == -0.25 and out["ratio"] == 0.75
        assert out["comment"] == ("[EFFORT] developer 0.5 | reviewer 0.25 | unassigned 0.25 | "
                                  "total 0.75 vs est 1 | +1000 tokens uncalibrated"), out["comment"]
        assert out["jira_actual_usage"] == 0.75 and "EDS-72 D5" in out["jira_note"]
        closes = json.loads(subprocess_read(env, "close"))
        assert len(closes) == 1 and closes[0]["actual_pct"] == 0.75 and closes[0]["delta_pct"] == -0.25
        assert closes[0]["by_role"] == {"developer": 0.5, "reviewer": 0.25} and closes[0]["unassigned_pct"] == 0.25
        # closing again with the same ledger changes nothing
        again = env.run("close", "--ticket", "EDS-77")[1]
        assert again["close_event_written"] is False
    finally:
        env.close()


def subprocess_read(env, event):
    import subprocess, sys
    proc = subprocess.run([sys.executable, str(env.module.find_ledger_append()), "read", "--ledger-dir",
                           str(env.ledger), "--event", event], capture_output=True, text=True, cwd=env.root)
    return json.dumps(json.loads(proc.stdout)["events"])


def test_close_without_an_estimate_omits_delta_and_ratio_and_says_so():
    env = _Env()
    try:
        transcript = _scenario(env)
        env.run("record", "--ticket", "EDS-77", "--transcript", transcript)
        out = env.run("close", "--ticket", "EDS-77")[1]
        assert out["delta_pct"] is None and out["ratio"] is None
        assert "(no estimate)" in out["comment"] and any("No estimate" in f for f in out["flags"])
    finally:
        env.close()


def test_close_with_no_recorded_effort_is_refused():
    env = _Env()
    try:
        code, out = env.run("close", "--ticket", "EDS-77")
        assert code == 2 and "Run `record` first" in out["error"]
    finally:
        env.close()


def test_an_open_segment_is_not_recorded_and_blocks_the_unassigned_figure():
    env = _Env()
    try:
        env.calibrate()
        env.segment("s-dev", "developer", "a1", "EDS-77", _ts(0))
        transcript = env.transcript("t.jsonl", [(_ts(2), "m1", "claude-sonnet-5-5", _usage(2800000)),
                                                (_ts(40), "m2", "claude-sonnet-5-5", _usage(2800000))])
        out = env.run("record", "--ticket", "EDS-77", "--transcript", transcript)[1]
        assert out["recorded"] == 0
        assert any("still open" in f for f in out["flags"])
    finally:
        env.close()


def test_a_ticket_with_no_segment_is_refused():
    env = _Env()
    try:
        env.calibrate()
        env.segment("s-x", "developer", "a1", "EDS-78", _ts(0), _ts(10))
        transcript = env.transcript("t.jsonl", [(_ts(2), "m1", "claude-sonnet-5-5", _usage(100))])
        code, out = env.run("record", "--ticket", "EDS-77", "--transcript", transcript)
        assert code == 2 and "No role segment is tagged with EDS-77" in out["error"]
    finally:
        env.close()


def test_a_transcript_tagged_with_another_agent_does_not_match_this_agents_segment():
    env = _Env()
    try:
        env.calibrate()
        env.segment("s-dev", "developer", "a1", "EDS-77", _ts(0), _ts(10))
        env.segment("s-rev", "reviewer", "a2", "EDS-77", _ts(0), _ts(10))
        path = env.transcript("t.jsonl", [(_ts(2), "m1", "claude-sonnet-5-5", _usage(2800000))])
        out = env.run("record", "--ticket", "EDS-77", "--transcript", f"a2={path}")[1]
        assert [e["role"] for e in out["events"]] == ["reviewer"], out["events"]
    finally:
        env.close()


def test_the_factor_prefers_weekly_then_five_hour_with_ratio_and_longest_model_prefix():
    env = _Env()
    try:
        f = env.module.factor_for
        cals = [
            {"event_id": "a", "ts": "1", "basis": "five_hour", "model": "claude-sonnet", "tokens_per_pct": 1000.0},
            {"event_id": "r", "ts": "1", "basis": "ratio", "weekly_per_five_hour": 0.5},
            {"event_id": "b", "ts": "2", "basis": "five_hour", "model": "claude-sonnet-5", "tokens_per_pct": 3000.0},
        ]
        assert f(cals, "claude-sonnet-5-5")[:2] == (6000.0, "b")       # longest prefix, then / ratio
        assert f(cals, "claude-sonnet-4")[:2] == (2000.0, "a")
        assert f(cals, "claude-opus-5-5") is None                      # no line for the model
        assert f([c for c in cals if c["basis"] != "ratio"], "claude-sonnet-5-5") is None  # no ratio yet
        cals.append({"event_id": "w", "ts": "3", "basis": "weekly", "model": "claude-sonnet", "tokens_per_pct": 7000.0})
        assert f(cals, "claude-sonnet-5-5")[:2] == (7000.0, "w")       # a weekly line wins
    finally:
        env.close()


def test_report_gives_per_ticket_and_overall_totals_with_unassigned_apart():
    env = _Env()
    try:
        transcript = _scenario(env)
        env.run("record", "--ticket", "EDS-77", "--transcript", transcript)
        report = env.run("report")[1]["overall"]
        assert report["by_role_pct"] == {"developer": 0.5, "reviewer": 0.25}
        assert report["unassigned_pct"] == 0.25 and report["roles_total_pct"] == 0.75
        assert report["grand_total_pct"] == 1.0 and report["uncalibrated_tokens"] == 1000
    finally:
        env.close()


def test_split_transcript_arg_leaves_paths_alone():
    env = _Env()
    try:
        s = env.module.split_transcript_arg
        assert s("a1=/tmp/x.jsonl") == ("a1", "/tmp/x.jsonl")
        assert s("/tmp/a=b.jsonl") == (None, "/tmp/a=b.jsonl")
        assert s("C:\\x\\y=z.jsonl") == (None, "C:\\x\\y=z.jsonl")
        assert s("plain.jsonl") == (None, "plain.jsonl")
    finally:
        env.close()


if __name__ == "__main__":
    tests = [fn for name, fn in sorted(globals().items()) if name.startswith("test_") and callable(fn)]
    for fn in tests:
        fn()
    print(f"All {len(tests)} effort-record tests passed.")
