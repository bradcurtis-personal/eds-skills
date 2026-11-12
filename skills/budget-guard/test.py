"""
Acceptance test for the budget-guard skill.

Behavior tests run main.main() against a disposable ledger directory and state
directory, calling the real sibling ledger-append skill through its command line.
They never touch the real eds-data clone or the real readings cache.
"""

import contextlib
import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
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
NOW = "2026-11-12T12:00:00Z"
RESETS = "2026-11-12T14:00:00Z"      # the window runs 09:00Z to 14:00Z


def test_skill_json_valid_and_complete():
    data = json.loads((SKILL_DIR / "skill.json").read_text(encoding="utf-8"))
    for field in REQUIRED_METADATA_FIELDS:
        assert field in data, f"skill.json missing required field: {field}"
    assert data["name"] == "budget-guard"
    assert data["category"] == "system"


def test_skill_md_has_valid_frontmatter():
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    assert match, "SKILL.md must start with YAML frontmatter"
    if yaml is not None:
        frontmatter = yaml.safe_load(match.group(1))
        assert frontmatter["name"] == "budget-guard"
        assert isinstance(frontmatter["description"], str) and frontmatter["description"].strip()
    else:
        assert re.search(r"^name: budget-guard$", match.group(1), re.M)
        assert re.search(r'^description: ".+"$', match.group(1), re.M)


def test_logic_file_exists():
    assert (SKILL_DIR / "main.py").exists(), "expected logic file main.py is missing"


# ---------- behavior ----------

def _load_module(workdir):
    previous = os.getcwd()
    os.chdir(workdir)  # the logging bootstrap creates logs/ in the working directory
    try:
        spec = importlib.util.spec_from_file_location("budget_guard_main", SKILL_DIR / "main.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        os.chdir(previous)


class _Env:
    def __init__(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.ledger = self.root / "ledger"
        self.ledger.mkdir()
        self.state = self.root / "state"
        self.module = _load_module(self.root)
        self.n = 0

    def run(self, *argv):
        previous = os.getcwd()
        os.chdir(self.root)  # log files go here, not into the checkout
        buffer = io.StringIO()
        try:
            with contextlib.redirect_stdout(buffer):
                extra = []
                if argv[0] in ("check", "sprint"):
                    extra += ["--ledger-dir", str(self.ledger)]
                if argv[0] in ("check", "reading"):
                    extra += ["--state-dir", str(self.state)]
                code = self.module.main([argv[0], *extra, *argv[1:]])
        finally:
            os.chdir(previous)
        return code, json.loads(buffer.getvalue())

    def ledger_append(self, event):
        proc = subprocess.run([sys.executable, str(self.module.find_ledger_append()), "append",
                               "--ledger-dir", str(self.ledger), "--event", json.dumps(event)],
                              capture_output=True, text=True, cwd=self.root)
        assert proc.returncode == 0, proc.stdout + proc.stderr

    def calibrate(self):
        for model, per in (("claude-sonnet", 1400000), ("claude-haiku", 5700000)):
            self.ledger_append({"event": "calibration", "basis": "five_hour", "model": model,
                                "tokens_per_pct": per, "status": "provisional", "source": "EDS-108",
                                "ts": "2026-11-09T00:00:00Z"})

    def effort(self, sprint, role, pct=None, tokens=1000, model="claude-sonnet-5-5"):
        self.n += 1
        event = {"event": "effort", "event_id": f"e{self.n}", "ts": "2026-11-12T10:00:00.000Z",
                 "ticket": "EDS-96", "role": role, "model": model, "kind": "work", "tokens": tokens,
                 "sprint": sprint}
        if role != "unassigned":
            event["agent"] = "a1"
        if pct is not None:
            event["usage_pct"] = pct
        self.ledger_append(event)

    def reading(self, percent, at="2026-11-12T11:30:00Z", resets=RESETS):
        code, out = self.run("reading", "--percent", str(percent), "--at", at, "--resets-at", resets)
        assert code == 0, out
        return out

    def transcript(self, name, messages):
        path = self.root / name
        lines = [json.dumps({"timestamp": when, "message": {"id": mid, "model": model,
                                                            "usage": {"input_tokens": tokens}}})
                 for when, mid, model, tokens in messages]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return str(path)

    def status_file(self, used, resets):
        path = self.root / "status.json"
        path.write_text(json.dumps({"rate_limits": {"five_hour": {"used_percentage": used, "resets_at": resets}}}),
                        encoding="utf-8")
        return str(path)

    def close(self):
        self._tmp.cleanup()


def test_a_manual_reading_at_75_percent_stops_the_run():
    """Acceptance criterion 4: the stop at 75%."""
    env = _Env()
    try:
        env.reading(75)
        code, out = env.run("check", "--now", NOW)
        assert code == 3 and out["verdict"] == "stop", out
        assert out["five_hour_pct"] == 75.0 and out["source"] == "manual"
        assert out["message"].startswith("STOP:") and RESETS in out["message"]
        env.reading(80, at="2026-11-12T11:40:00Z")
        assert env.run("check", "--now", NOW)[0] == 3
    finally:
        env.close()


def test_below_the_threshold_is_ok_with_its_source_named():
    env = _Env()
    try:
        env.reading(74)
        code, out = env.run("check", "--now", NOW)
        assert code == 0 and out["verdict"] == "ok", out
        assert out["source"] == "manual" and out["confidence"] == "medium" and out["lower_bound"] is False
        assert out["message"].startswith("OK:")
        assert env.run("check", "--now", NOW, "--threshold", "50")[0] == 3   # the threshold is a parameter
    finally:
        env.close()


def test_with_no_source_the_answer_is_unavailable_and_lists_why():
    env = _Env()
    try:
        code, out = env.run("check", "--now", NOW)
        assert code == 4 and out["verdict"] == "unavailable" and out["five_hour_pct"] is None
        assert out["message"].startswith("UNAVAILABLE:") and "nothing is guessed" in out["message"]
        assert [t["source"] for t in out["tried"]] == ["status-line", "manual", "transcript"]
        assert all(t["used"] is False and t["reason"] for t in out["tried"])
        assert "decision 30(j)" in out["tried"][0]["reason"]
    finally:
        env.close()


def test_a_stale_or_reset_reading_is_not_used():
    env = _Env()
    try:
        env.reading(80, at="2026-11-12T09:30:00Z")                         # 2.5 hours old
        code, out = env.run("check", "--now", NOW)
        assert code == 4 and "older than 60 minutes" in out["tried"][1]["reason"], out
        assert env.run("check", "--now", NOW, "--max-age-min", "180")[0] == 3   # fresh enough on request
        code, out = env.run("check", "--now", "2026-11-12T14:30:00Z", "--max-age-min", "999")
        assert code == 4 and "reset" in out["tried"][1]["reason"], out
    finally:
        env.close()


def test_a_reading_must_carry_a_window_that_resets_within_five_hours():
    env = _Env()
    try:
        code, out = env.run("reading", "--percent", "40", "--at", NOW, "--resets-at", "2026-11-12T18:00:00Z")
        assert code == 2 and "five hours" in out["error"]
        code, out = env.run("reading", "--percent", "140", "--at", NOW, "--resets-at", RESETS)
        assert code == 2 and "between 0 and 100" in out["error"]
        assert not (env.state / "readings.jsonl").exists()
    finally:
        env.close()


def test_transcript_tokens_since_the_reading_are_added_and_duplicates_counted_once():
    env = _Env()
    try:
        env.calibrate()
        env.reading(70, at="2026-11-12T11:00:00Z")
        transcript = env.transcript("t.jsonl", [
            ("2026-11-12T10:00:00Z", "old", "claude-sonnet-5-5", 99000000),    # before the reading: not added
            ("2026-11-12T11:10:00Z", "m1", "claude-sonnet-5-5", 4200000),      # 3.0 points
            ("2026-11-12T11:10:00Z", "m1", "claude-sonnet-5-5", 4200000),      # the same API message again
            ("2026-11-12T11:20:00Z", "m2", "claude-haiku-5-5", 5700000),       # 1.0 point
        ])
        code, out = env.run("check", "--now", NOW, "--transcript", transcript)
        assert out["source"] == "manual+transcript" and out["five_hour_pct"] == 74.0, out
        assert code == 0 and out["verdict"] == "ok" and out["lower_bound"] is False
        more = env.transcript("u.jsonl", [("2026-11-12T11:30:00Z", "m3", "claude-sonnet-5-5", 1400000)])
        code, out = env.run("check", "--now", NOW, "--transcript", transcript, "--transcript", more)
        assert code == 3 and out["five_hour_pct"] == 75.0, out
    finally:
        env.close()


def test_an_uncalibrated_model_makes_a_lower_bound_that_cannot_show_ok():
    env = _Env()
    try:
        env.calibrate()
        env.reading(40, at="2026-11-12T11:00:00Z")
        transcript = env.transcript("t.jsonl", [("2026-11-12T11:30:00Z", "m1", "claude-opus-5-5", 5000000)])
        code, out = env.run("check", "--now", NOW, "--transcript", transcript)
        assert code == 4 and out["verdict"] == "unverified" and out["lower_bound"] is True, out
        assert any("no five-hour factor" in f for f in out["flags"])
        assert out["message"].startswith("UNVERIFIED:")
        # but a lower bound at or above the threshold is still a certain stop
        env.reading(76, at="2026-11-12T11:20:00Z")
        code, out = env.run("check", "--now", NOW, "--transcript", transcript)
        assert code == 3 and "or more" in out["message"], out
    finally:
        env.close()


def test_a_transcript_alone_gives_a_lower_bound_inside_the_window():
    env = _Env()
    try:
        env.calibrate()
        transcript = env.transcript("t.jsonl", [
            ("2026-11-12T08:00:00Z", "before", "claude-sonnet-5-5", 999000000),   # before the window: not counted
            ("2026-11-12T10:00:00Z", "m1", "claude-sonnet-5-5", 70000000),       # 50 points
        ])
        code, out = env.run("check", "--now", NOW, "--transcript", transcript, "--window-resets", RESETS)
        assert code == 4 and out["verdict"] == "unverified" and out["source"] == "transcript", out
        assert out["five_hour_pct"] == 50.0 and out["confidence"] == "low" and out["lower_bound"] is True
        bigger = env.transcript("b.jsonl", [("2026-11-12T10:00:00Z", "m2", "claude-sonnet-5-5", 105000000)])
        code, out = env.run("check", "--now", NOW, "--transcript", bigger, "--window-resets", RESETS)
        assert code == 3 and out["verdict"] == "stop" and out["five_hour_pct"] == 75.0, out
        code, out = env.run("check", "--now", NOW, "--transcript", transcript)
        assert code == 4 and "reset time is not known" in out["tried"][2]["reason"], out
    finally:
        env.close()


def test_a_transcript_without_calibration_lines_is_unavailable_not_zero():
    env = _Env()                                   # no calibration lines in the ledger
    try:
        transcript = env.transcript("t.jsonl", [("2026-11-12T10:00:00Z", "m1", "claude-sonnet-5-5", 70000000)])
        code, out = env.run("check", "--now", NOW, "--transcript", transcript, "--window-resets", RESETS)
        assert code == 4 and out["verdict"] == "unavailable", out
    finally:
        env.close()


def test_the_status_line_file_is_preferred_and_checked_for_age_and_reset():
    env = _Env()
    try:
        env.reading(10)
        path = env.status_file(80, RESETS)
        mtime = datetime(2026, 11, 12, 11, 20, tzinfo=timezone.utc).timestamp()
        os.utime(path, (mtime, mtime))
        code, out = env.run("check", "--now", NOW, "--status-file", path)
        assert code == 3 and out["source"] == "status-line" and out["confidence"] == "high", out
        code, out = env.run("check", "--now", "2026-11-12T13:00:00Z", "--status-file", path)   # file is 100 minutes old
        assert out["source"] != "status-line" and "older than 60 minutes" in out["tried"][0]["reason"], out
        code, out = env.run("check", "--now", "2026-11-12T14:05:00Z", "--status-file", path)
        assert "already reset" in out["tried"][0]["reason"], out
        bad = env.root / "bad.json"
        bad.write_text("{}", encoding="utf-8")
        assert "no rate_limits" in env.run("check", "--now", NOW, "--status-file", str(bad))[1]["tried"][0]["reason"]
    finally:
        env.close()


def test_sprint_total_is_reported_against_the_cap():
    env = _Env()
    try:
        env.effort("S1", "developer", 12.0)
        env.effort("S1", "developer", 3.5)
        env.effort("S1", "reviewer", 4.0)
        env.effort("S1", "unassigned", 1.5)
        env.effort("S2", "developer", 29.0)                      # another sprint: left out
        code, out = env.run("sprint", "--sprint", "S1")
        assert code == 0 and out["verdict"] == "ok", out
        assert out["by_role_pct"] == {"developer": 15.5, "reviewer": 4.0} and out["unassigned_pct"] == 1.5
        assert out["total_pct"] == 21.0 and out["share_of_cap_pct"] == 70.0 and out["remaining_pct"] == 9.0
        assert out["message"].startswith("OK:") and out["cap_pct"] == 30.0
        code, out = env.run("sprint", "--sprint", "S1", "--cap", "21")
        assert code == 3 and out["verdict"] == "over_cap" and out["message"].startswith("OVER CAP:")
        code, out = env.run("sprint", "--sprint", "S2")
        assert code == 0 and out["total_pct"] == 29.0, out
    finally:
        env.close()


def test_sprint_at_the_cap_stops_and_uncalibrated_tokens_make_the_total_a_lower_bound():
    env = _Env()
    try:
        env.effort("S3", "developer", 30.0)
        env.effort("S3", "reviewer", None, tokens=5000, model="claude-opus-5-5")
        code, out = env.run("sprint", "--sprint", "S3")
        assert code == 3 and out["verdict"] == "over_cap" and out["total_pct"] == 30.0, out
        assert any("5000 tokens have no calibration factor" in f for f in out["flags"])
    finally:
        env.close()


def test_a_sprint_with_no_recorded_effort_is_unavailable_not_zero():
    env = _Env()
    try:
        code, out = env.run("sprint", "--sprint", "NOPE")
        assert code == 4 and out["verdict"] == "unavailable" and out["total_pct"] is None
        assert "Zero is not reported" in out["message"]
    finally:
        env.close()


def test_a_missing_transcript_is_refused():
    env = _Env()
    try:
        code, out = env.run("check", "--now", NOW, "--transcript", str(env.root / "nope.jsonl"))
        assert code == 2 and "Transcript not found" in out["error"]
    finally:
        env.close()


if __name__ == "__main__":
    tests = [fn for name, fn in sorted(globals().items()) if name.startswith("test_") and callable(fn)]
    for fn in tests:
        fn()
    print(f"All {len(tests)} budget-guard tests passed.")
