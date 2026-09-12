#!/usr/bin/env python3
"""
tooling/package_skill.py

Shared engine for the eds-skills packaging + release pipeline.

Modes:
  check    - CI PR gate. For every skill whose files changed vs the base
             branch, require skill.json's version to have increased, and
             run that skill's test.py.
  release  - CI post-merge step (idempotent). For every skill in the repo,
             if no GitHub Release exists yet for its current skill.json
             version, package it as a standalone plugin, create the
             Release (tag <skill>/v<version>) with the .plugin zip
             attached, then open (and merge) a PR that regenerates
             marketplace.json / plugins/ so the org's GitHub-synced
             plugin marketplace picks up the new version.

Usage:
  python3 tooling/package_skill.py check --base <branch>
  python3 tooling/package_skill.py release
"""
import argparse
import json
import os
import subprocess
import sys
import urllib.request
import urllib.error
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
SKILLS_DIR = REPO_ROOT / "skills"
PLUGINS_DIR = REPO_ROOT / "plugins"
MARKETPLACE_FILE = REPO_ROOT / ".claude-plugin" / "marketplace.json"
MARKETPLACE_NAME = "eds-skills"
MARKETPLACE_OWNER = {"name": "Engineering Design System"}


def run(cmd, **kwargs):
    return subprocess.run(
        cmd, cwd=REPO_ROOT, check=True, text=True, capture_output=True, **kwargs
    )


def parse_version(v):
    try:
        return tuple(int(p) for p in v.split("."))
    except ValueError:
        sys.exit(f"Invalid version '{v}': expected MAJOR.MINOR.PATCH")


def list_skills():
    if not SKILLS_DIR.exists():
        return []
    return sorted(p.name for p in SKILLS_DIR.iterdir() if p.is_dir())


def skill_version(skill_name, ref=None):
    path_in_repo = f"skills/{skill_name}/skill.json"
    if ref is None:
        data = json.loads((SKILLS_DIR / skill_name / "skill.json").read_text())
    else:
        result = run(["git", "show", f"{ref}:{path_in_repo}"])
        data = json.loads(result.stdout)
    return data["version"]


# ---------- check mode ----------

def changed_skills(base_ref):
    run(["git", "fetch", "origin", base_ref, "--depth=50"])
    result = run(
        ["git", "diff", "--name-only", f"origin/{base_ref}...HEAD", "--", "skills/"]
    )
    names = set()
    for line in result.stdout.splitlines():
        parts = line.split("/")
        if len(parts) >= 2 and parts[0] == "skills":
            names.add(parts[1])
    return sorted(names)


def cmd_check(base_ref):
    skills = changed_skills(base_ref)
    if not skills:
        print("No skill files changed. Nothing to check.")
        return

    failures = []
    for name in skills:
        print(f"--- Checking {name} ---")
        try:
            base_version = skill_version(name, ref=f"origin/{base_ref}")
        except subprocess.CalledProcessError:
            base_version = None  # new skill, nothing to compare against
        head_version = skill_version(name)

        if base_version is not None:
            if parse_version(head_version) <= parse_version(base_version):
                failures.append(
                    f"{name}: version not bumped (base={base_version}, "
                    f"head={head_version}). Bump skills/{name}/skill.json's "
                    f"version field."
                )
                continue

        test_path = SKILLS_DIR / name / "test.py"
        if test_path.exists():
            result = subprocess.run([sys.executable, str(test_path)], cwd=REPO_ROOT)
            if result.returncode != 0:
                failures.append(f"{name}: test.py failed")
        else:
            print(f"  (no test.py for {name}, skipping contract test)")

    if failures:
        print("\nFAILED:")
        for f in failures:
            print(f"  - {f}")
        sys.exit(1)
    print("\nAll changed skills passed.")


# ---------- release mode ----------

def github_api(method, path, token, data=None):
    url = f"https://api.github.com{path}"
    body = json.dumps(data).encode() if data is not None else None
    req = urllib.request.Request(
        url,
        data=body,
        method=method,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )
    try:
        with urllib.request.urlopen(req) as resp:
            return resp.status, json.loads(resp.read().decode() or "{}")
    except urllib.error.HTTPError as e:
        body_text = e.read().decode()
        return e.code, (json.loads(body_text) if body_text else {})


def release_exists(repo, tag, token):
    status, _ = github_api("GET", f"/repos/{repo}/releases/tags/{tag}", token)
    return status == 200


def build_plugin_zip(name, version, out_dir):
    skill_json = json.loads((SKILLS_DIR / name / "skill.json").read_text())
    plugin_manifest = {
        "name": name,
        "version": version,
        "description": skill_json.get("description", ""),
    }
    out_dir.mkdir(parents=True, exist_ok=True)
    zip_path = out_dir / f"{name}-v{version}.plugin"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(".claude-plugin/plugin.json", json.dumps(plugin_manifest, indent=2))
        zf.write(SKILLS_DIR / name / "SKILL.md", f"skills/{name}/SKILL.md")
    return zip_path


def create_release(repo, tag, name, version, zip_path, token, commit_sha):
    status, release = github_api(
        "POST",
        f"/repos/{repo}/releases",
        token,
        {
            "tag_name": tag,
            "target_commitish": commit_sha,
            "name": f"{name} v{version}",
            "body": f"Automated release of the `{name}` skill, version {version}.",
        },
    )
    if status not in (200, 201):
        sys.exit(f"Failed to create release for {tag}: {release}")

    upload_url = release["upload_url"].split("{")[0]
    with open(zip_path, "rb") as f:
        req = urllib.request.Request(
            f"{upload_url}?name={zip_path.name}",
            data=f.read(),
            method="POST",
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/zip",
            },
        )
        urllib.request.urlopen(req)
    print(f"Released {tag} -> {release['html_url']}")


def regenerate_marketplace():
    plugins_entries = []
    for name in list_skills():
        skill_json = json.loads((SKILLS_DIR / name / "skill.json").read_text())
        version = skill_json["version"]
        plugin_dir = PLUGINS_DIR / name
        (plugin_dir / ".claude-plugin").mkdir(parents=True, exist_ok=True)
        (plugin_dir / "skills" / name).mkdir(parents=True, exist_ok=True)

        plugin_manifest = {
            "name": name,
            "version": version,
            "description": skill_json.get("description", ""),
        }
        (plugin_dir / ".claude-plugin" / "plugin.json").write_text(
            json.dumps(plugin_manifest, indent=2) + "\n"
        )
        skill_md_src = SKILLS_DIR / name / "SKILL.md"
        (plugin_dir / "skills" / name / "SKILL.md").write_text(skill_md_src.read_text())

        plugins_entries.append(
            {
                "name": name,
                "source": f"./plugins/{name}",
                "description": skill_json.get("description", ""),
                "version": version,
            }
        )

    MARKETPLACE_FILE.parent.mkdir(parents=True, exist_ok=True)
    MARKETPLACE_FILE.write_text(
        json.dumps(
            {
                "name": MARKETPLACE_NAME,
                "owner": MARKETPLACE_OWNER,
                "plugins": plugins_entries,
            },
            indent=2,
        )
        + "\n"
    )


def open_and_merge_marketplace_pr(repo, token, base_branch="main"):
    result = run(["git", "status", "--porcelain", "plugins/", ".claude-plugin/"])
    if not result.stdout.strip():
        print("Marketplace files already up to date; no PR needed.")
        return

    sha_suffix = os.environ.get("GITHUB_SHA", "local")[:7]
    branch = f"bot/sync-marketplace-{sha_suffix}"

    run(["git", "config", "user.name", "eds-skills-bot"])
    run(["git", "config", "user.email", "actions@users.noreply.github.com"])
    run(["git", "checkout", "-b", branch])
    run(["git", "add", "plugins/", ".claude-plugin/"])
    run(["git", "commit", "-m", "chore: sync plugin marketplace"])

    remote = f"https://x-access-token:{token}@github.com/{repo}.git"
    run(["git", "push", remote, f"HEAD:{branch}"])

    status, pr = github_api(
        "POST",
        f"/repos/{repo}/pulls",
        token,
        {
            "title": "chore: sync plugin marketplace",
            "head": branch,
            "base": base_branch,
            "body": (
                "Auto-generated: syncs marketplace.json and plugins/ with the "
                "latest released skill versions. No human review needed -- "
                "these files are fully derived from skills/*/skill.json and "
                "skills/*/SKILL.md."
            ),
        },
    )
    if status not in (200, 201):
        sys.exit(f"Failed to open marketplace sync PR: {pr}")
    number = pr["number"]
    print(f"Opened PR #{number}: {pr['html_url']}")

    status, merge_result = github_api(
        "PUT",
        f"/repos/{repo}/pulls/{number}/merge",
        token,
        {"merge_method": "squash"},
    )
    if status == 200:
        print(f"Auto-merged PR #{number}.")
    else:
        print(
            f"WARNING: could not auto-merge PR #{number} ({merge_result}). "
            f"It likely needs a manual merge, or branch protection needs an "
            f"exception for eds-skills-bot / GitHub Actions."
        )


def cmd_release():
    token = os.environ.get("GITHUB_TOKEN")
    repo = os.environ.get("GITHUB_REPOSITORY")
    commit_sha = (
        os.environ.get("GITHUB_SHA") or run(["git", "rev-parse", "HEAD"]).stdout.strip()
    )
    if not token or not repo:
        sys.exit("GITHUB_TOKEN and GITHUB_REPOSITORY must be set for release mode.")

    for name in list_skills():
        version = skill_version(name)
        tag = f"{name}/v{version}"
        if release_exists(repo, tag, token):
            print(f"{tag} already released, skipping.")
            continue
        print(f"Releasing {tag}...")
        zip_path = build_plugin_zip(name, version, REPO_ROOT / "dist")
        create_release(repo, tag, name, version, zip_path, token, commit_sha)

    regenerate_marketplace()
    open_and_merge_marketplace_pr(repo, token)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="mode", required=True)
    check_p = sub.add_parser("check")
    check_p.add_argument("--base", required=True)
    sub.add_parser("release")
    args = parser.parse_args()

    if args.mode == "check":
        cmd_check(args.base)
    elif args.mode == "release":
        cmd_release()


if __name__ == "__main__":
    main()
