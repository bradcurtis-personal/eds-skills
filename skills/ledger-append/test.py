"""
Acceptance test for the ledger-append skill.

Behavior tests run main.main() against a disposable ledger directory and, for
`commit`, a throwaway git repo with a bare remote. They never touch the real
eds-data clone.
"""

import contextlib
import importlib.util
import io
import json
import os
import re
import subprocess
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
    assert data["name"] == "ledger-append"
    assert data["category"] == "system"


def test_skill_md_has_valid_frontmatter():
    text = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")
    match = re.match(r"^---\s*\n(.*?)\n---\s*\n", text, re.DOTALL)
    assert match, "SKILL.md must start with YAML frontmatter"
    if yaml is not None:
        frontmatter = yaml.safe_load(match.group(1))
        assert frontmatter["name"] == "ledger-append"
        assert isinstance(frontmatter["description"], str) and frontmatter["description"].strip()
    else:
        assert re.search(r"^name: ledger-append$", match.group(1), re.M)
        assert re.search(r'^description: ".+"$', match.group(1), re.M)


def test_logic_file_exists():
    assert (SKILL_DIR / "main.py").exists(), "expected logic file main.py is missing"


# ---------- behavior ----------

def _load_module(workdir):
    previous = os.getcwd()
    os.chdir(workdir)  # the logging bootstrap creates logs/ in the working directory
    try:
        spec = importlib.util.spec_from_file_location("ledger_append_main", SKILL_DIR / "main.py")
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
        self.module = _load_module(self.root)

    def run(self, *argv):
        buffer = io.StringIO()
        with contextlib.redirect_stdout(buffer):
            code = self.module.main(list(argv))
        return code, json.loads(buffer.getvalue())

    def append(self, event):
        return self.run("append", "--ledger-dir", str(self.ledger), "--event", json.dumps(event))

    def lines(self, name):
        path = self.ledger / name
        return [json.loads(x) for x in path.read_text(encoding="utf-8").splitlines()] if path.exists() else []

    def close(self):
        self._tmp.cleanup()


EFFORT = {"event": "effort", "ticket": "EDS-77", "role": "developer", "model": "claude-sonnet-5-5",
          "tokens": 1200, "kind": "work", "ts": "2026-11-12T10:00:00Z"}


def test_append_fills_ids_and_partitions_by_month():
    env = _Env()
    try:
        code, out = env.append(EFFORT)
        assert code == 0 and out["appended"] is True and out["file"] == "2026-11.jsonl"
        code, out = env.append({**EFFORT, "ts": "2026-12-01T00:00:01Z"})
        assert out["file"] == "2026-12.jsonl"
        (line,) = env.lines("2026-11.jsonl")
        assert line["schema_version"] == 2 and len(line["event_id"]) >= 16
        assert line["tokens"] == 1200 and line["role"] == "developer"
    finally:
        env.close()


def test_the_same_event_id_twice_changes_nothing():
    env = _Env()
    try:
        event = {**EFFORT, "event_id": "fixed-1"}
        assert env.append(event)[1]["appended"] is True
        code, out = env.append(event)
        assert code == 0 and out["appended"] is False
        assert len(env.lines("2026-11.jsonl")) == 1
    finally:
        env.close()


def test_calibration_events_go_to_their_own_file():
    env = _Env()
    try:
        code, out = env.append({"event": "calibration", "basis": "five_hour", "model": "claude-sonnet",
                                "tokens_per_pct": 1400000, "low": 1100000, "high": 1900000,
                                "status": "provisional", "source": "EDS-108 test 4"})
        assert code == 0 and out["file"] == "calibration.jsonl"
        code, out = env.append({"event": "calibration", "basis": "ratio", "weekly_per_five_hour": 0.25})
        assert code == 0
        assert len(env.lines("calibration.jsonl")) == 2
    finally:
        env.close()


def test_refuses_what_the_schema_does_not_allow():
    env = _Env()
    try:
        bad = [
            {**EFFORT, "colour": "red"},                         # undefined field
            {k: v for k, v in EFFORT.items() if k != "tokens"},  # missing required field
            {**EFFORT, "tokens": "many"},                        # wrong type
            {**EFFORT, "tokens": True},                          # bool is not an integer
            {**EFFORT, "kind": "play"},                          # not an allowed kind
            {**EFFORT, "role": ""},                              # empty role
            {**EFFORT, "ts": "yesterday"},                       # not ISO 8601
            {**EFFORT, "event": "weather"},                      # unknown event type
            {"event": "calibration", "basis": "weekly", "model": "claude-sonnet"},  # no factor
            {"event": "calibration", "basis": "ratio", "weekly_per_five_hour": 0.25, "model": "x"},
            {"event": "close", "ticket": "EDS-77", "actual_pct": 1, "by_role": {"lead": "a lot"}},
        ]
        for event in bad:
            code, out = env.append(event)
            assert code == 2 and "error" in out, event
        assert not list(env.ledger.glob("*.jsonl")), "a refused event must write nothing"
    finally:
        env.close()


def test_read_returns_oldest_first_with_filters_and_infers_version_1_types():
    env = _Env()
    try:
        env.append({**EFFORT, "ts": "2026-11-12T12:00:00Z", "event_id": "b"})
        env.append({"event": "estimate", "ticket": "EDS-77", "est_pct": 3, "ts": "2026-11-12T09:00:00Z"})
        env.append({**EFFORT, "ticket": "EDS-78", "ts": "2026-11-12T11:00:00Z"})
        # a version 1 line has no `event` field: written directly, as the old format allowed
        (env.ledger / "2026-11.jsonl").write_text(
            (env.ledger / "2026-11.jsonl").read_text(encoding="utf-8")
            + json.dumps({"event_id": "v1", "schema_version": 1, "ts": "2026-11-12T08:00:00Z",
                          "ticket": "EDS-77", "role": "lead", "model": "m", "kind": "work", "tokens": 5}) + "\n",
            encoding="utf-8")
        code, out = env.run("read", "--ledger-dir", str(env.ledger))
        assert [e["ts"] for e in out["events"]] == sorted(e["ts"] for e in out["events"])
        assert out["count"] == 4
        code, out = env.run("read", "--ledger-dir", str(env.ledger), "--ticket", "EDS-77", "--event", "effort")
        assert out["count"] == 2 and {e["event_id"] for e in out["events"]} >= {"b", "v1"}
        assert all(e["event"] == "effort" for e in out["events"])
    finally:
        env.close()


def test_a_ledger_line_that_is_not_json_is_reported_not_skipped():
    env = _Env()
    try:
        env.append(EFFORT)
        with open(env.ledger / "2026-11.jsonl", "a", encoding="utf-8") as fh:
            fh.write("not json\n")
        code, out = env.run("read", "--ledger-dir", str(env.ledger))
        assert code == 2 and "line 2" in out["error"]
    finally:
        env.close()


def test_the_field_lists_match_the_record_schema_when_it_is_reachable():
    env = _Env()
    try:
        candidates = [os.environ.get("EDS_DATA_REPO"), SKILL_DIR.parents[2] / "eds-data", "/mnt/c/repos/eds-data"]
        doc = next((Path(c) / "docs" / "RECORD_SCHEMA.md" for c in candidates
                    if c and (Path(c) / "docs" / "RECORD_SCHEMA.md").is_file()), None)
        if doc is None:
            print("  (record schema not reachable, skipping the drift check)")
            return
        text = doc.read_text(encoding="utf-8")
        if f"`schema_version` {env.module.SCHEMA_VERSION}" not in text:
            print("  (reachable record schema is another version, skipping the drift check)")
            return
        names = set(env.module.COMMON)
        for spec in env.module.FIELDS.values():
            names |= set(spec["required"]) | set(spec["optional"])
        missing = sorted(n for n in names if f"`{n}`" not in text)
        assert not missing, f"RECORD_SCHEMA.md does not define: {missing}"
    finally:
        env.close()


# ---------- commit ----------

def _git(cwd, *argv):
    env = {**os.environ, "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"}
    proc = subprocess.run(["git", "-C", str(cwd), *argv], capture_output=True, text=True, env=env)
    assert proc.returncode == 0, (argv, proc.stderr)
    return proc.stdout.strip()


class _Repo(_Env):
    """A throwaway eds-data clone with a bare remote."""

    def __init__(self):
        super().__init__()
        self.remote = self.root / "remote.git"
        subprocess.run(["git", "init", "--bare", "-b", "main", str(self.remote)], check=True, capture_output=True)
        self.repo = self.root / "eds-data"
        self.repo.mkdir()
        _git(self.repo, "init", "-b", "main")
        (self.repo / "docs").mkdir()
        (self.repo / "docs" / "RECORD_SCHEMA.md").write_text("# schema\n", encoding="utf-8")
        (self.repo / "ledger").mkdir()
        (self.repo / "ledger" / ".gitkeep").write_text("", encoding="utf-8")
        (self.repo / "CLAUDE.md").write_text("rules\n", encoding="utf-8")
        _git(self.repo, "add", ".")
        _git(self.repo, "commit", "-m", "init")
        _git(self.repo, "remote", "add", "origin", str(self.remote))
        _git(self.repo, "push", "-u", "origin", "main")
        self.ledger = self.repo / "ledger"
        os.environ.update({"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.com",
                           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.com"})

    def commit(self, *extra):
        return self.run("commit", "--repo", str(self.repo), *extra)


def test_commit_takes_a_data_only_change_to_main_and_pushes_it():
    env = _Repo()
    try:
        env.append(EFFORT)
        code, out = env.commit("--message", "data: test", "--push")
        assert code == 0 and out["committed"] and out["pushed"], out
        assert out["paths"] == ["ledger/2026-11.jsonl"]
        assert _git(env.repo, "status", "--porcelain") == ""
        assert _git(env.repo, "rev-parse", "HEAD") == _git(env.remote, "rev-parse", "main")
        code, out = env.commit()
        assert code == 0 and out["committed"] is False
    finally:
        env.close()


def test_commit_refuses_a_mixed_change_and_commits_nothing():
    env = _Repo()
    try:
        env.append(EFFORT)
        (env.repo / "CLAUDE.md").write_text("changed rules\n", encoding="utf-8")
        before = _git(env.repo, "rev-parse", "HEAD")
        code, out = env.commit()
        assert code == 2 and "CLAUDE.md" in out["error"]
        assert _git(env.repo, "rev-parse", "HEAD") == before
    finally:
        env.close()


def test_commit_refuses_off_main_and_a_rewritten_ledger_line():
    env = _Repo()
    try:
        env.append(EFFORT)
        _git(env.repo, "add", "-A")
        _git(env.repo, "commit", "-m", "first line")
        path = env.ledger / "2026-11.jsonl"
        path.write_text(path.read_text(encoding="utf-8").replace('"tokens":1200', '"tokens":9999'), encoding="utf-8")
        code, out = env.commit()
        assert code == 2 and "append-only" in out["error"], out
        _git(env.repo, "checkout", "--", ".")
        _git(env.repo, "checkout", "-b", "feature/x")
        env.append({**EFFORT, "tokens": 5})
        code, out = env.commit()
        assert code == 2 and "not main" in out["error"]
    finally:
        env.close()


def test_commit_refuses_a_directory_that_is_not_eds_data():
    env = _Env()
    try:
        code, out = env.run("commit", "--repo", str(env.root))
        assert code == 2 and "not the eds-data repo" in out["error"]
    finally:
        env.close()


if __name__ == "__main__":
    tests = [fn for name, fn in sorted(globals().items()) if name.startswith("test_") and callable(fn)]
    for fn in tests:
        fn()
    print(f"All {len(tests)} ledger-append tests passed.")
