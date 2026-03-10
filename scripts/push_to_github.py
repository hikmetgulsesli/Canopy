#!/usr/bin/env python3
"""
Push local files to GitHub via the MCP Manager's push_files_to_repo tool.

Uses the Git Data API under the hood (one atomic commit, no SHA pre-fetching).

Usage:
    # Direct push to main (trivial changes only):
    python scripts/push_to_github.py \
        --files canopy/__init__.py canopy/core/app.py \
        --message "chore: version bump"

    # PR-based workflow (recommended for Python/config changes):
    python scripts/push_to_github.py \
        --files canopy/core/app.py pyproject.toml \
        --message "feat: my change" \
        --pr --branch-name feat/my-change --pr-title "feat: my change" \
        --pr-body "Description of changes"

Or import and call push_files() / push_as_pr() directly.

PR workflow:
  push_as_pr() creates a feature branch, pushes files, opens a PR, polls
  GitHub Actions CI until it passes, then merges and deletes the branch.
  Use this for any .py or config file changes so mypy catches issues first.

Direct push:
  push_files() pushes straight to main. Use only for trivial non-code changes
  (docs, single-line version bumps, etc.).
"""
import argparse
import base64
import json
import time
import urllib.request
from pathlib import Path

MANAGER = "http://localhost:8000"
REPO_DIR = Path(__file__).resolve().parent.parent
OWNER = "kwalus"
REPO = "Canopy"
BRANCH = "main"


def mgr_call(tool, args, timeout=120):
    payload = {"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": tool, "arguments": args}}
    req = urllib.request.Request(
        MANAGER,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def get_inner(r):
    text = r.get("result", {}).get("content", [{}])[0].get("text", "{}")
    data = json.loads(text) if text.startswith("{") else {}
    return data.get("result", data)


def _build_file_entries(file_paths):
    """Read local files and return the payload list for push_files_to_repo."""
    files = []
    for fpath in file_paths:
        full = REPO_DIR / fpath
        if not full.exists():
            print(f"  SKIP (not found): {fpath}")
            continue
        try:
            content = full.read_text(encoding="utf-8")
            entry = {"path": str(fpath), "content": content}
        except UnicodeDecodeError:
            content = base64.b64encode(full.read_bytes()).decode()
            entry = {"path": str(fpath), "content": content, "content_is_base64": True}
        files.append(entry)
    return files


def push_files(file_paths, message, owner=OWNER, repo=REPO, branch=BRANCH):
    """
    Push a list of local file paths to GitHub in one atomic commit.

    Pushes directly to `branch` (default: main). Use only for trivial
    non-Python changes. For .py or config files prefer push_as_pr().

    file_paths: list of paths relative to repo root (strings or Path objects).
    Returns True on success.
    """
    files = _build_file_entries(file_paths)
    if not files:
        print("Nothing to push.")
        return False

    print(f"Pushing {len(files)} files in one commit: \"{message}\"")
    result = mgr_call("call_tool", {
        "server": "github",
        "tool": "push_files_to_repo",
        "arguments": {"owner": owner, "repo": repo, "branch": branch,
                      "message": message, "files": files},
    })
    inner = get_inner(result)
    if inner.get("success"):
        sha = inner.get("commit", {}).get("sha", "") if isinstance(inner.get("commit"), dict) else str(inner.get("commit", ""))
        print(f"  Done. Commit: {sha[:12] if sha else 'n/a'}")
        return True
    else:
        print(f"  FAILED: {str(inner)[:400]}")
        return False


def push_as_pr(
    file_paths,
    branch_name,
    commit_message,
    pr_title,
    pr_body="",
    base_branch=BRANCH,
    owner=OWNER,
    repo=REPO,
    wait_for_ci=True,
    ci_timeout_seconds=300,
    auto_merge=True,
):
    """
    Push files via a PR so GitHub Actions CI (mypy, etc.) runs before merge.

    Workflow:
      1. Create feature branch from base_branch.
      2. Push all files to that branch in one atomic commit.
      3. Open a pull request.
      4. If wait_for_ci=True, poll CI status until pass/fail or timeout.
      5. If auto_merge=True and CI passed, merge the PR and delete the branch.

    Returns a dict with keys: pr_number, pr_url, ci_status, merged.
    Raises RuntimeError if CI fails or a critical step errors.
    """
    files = _build_file_entries(file_paths)
    if not files:
        raise ValueError("No files found to push.")

    # 1. Create feature branch
    print(f"Creating branch '{branch_name}' from '{base_branch}'...")
    r = mgr_call("call_tool", {
        "server": "github", "tool": "create_branch",
        "arguments": {"owner": owner, "repo": repo,
                      "branch_name": branch_name, "from_ref": base_branch},
    })
    inner = get_inner(r)
    if not inner.get("success", True) and "already exists" not in str(inner).lower():
        raise RuntimeError(f"create_branch failed: {inner}")
    print(f"  Branch ready.")

    # 2. Push files to the feature branch
    print(f"Pushing {len(files)} files to '{branch_name}'...")
    r = mgr_call("call_tool", {
        "server": "github", "tool": "push_files_to_repo",
        "arguments": {"owner": owner, "repo": repo, "branch": branch_name,
                      "message": commit_message, "files": files},
    })
    inner = get_inner(r)
    if not inner.get("success"):
        raise RuntimeError(f"push_files_to_repo failed: {str(inner)[:400]}")
    sha = inner.get("commit", {}).get("sha", "") if isinstance(inner.get("commit"), dict) else ""
    print(f"  Pushed. Commit: {sha[:12] if sha else 'n/a'}")

    # 3. Open pull request
    print("Opening pull request...")
    r = mgr_call("call_tool", {
        "server": "github", "tool": "create_pull_request",
        "arguments": {"owner": owner, "repo": repo, "title": pr_title,
                      "body": pr_body, "head": branch_name, "base": base_branch},
    })
    inner = get_inner(r)
    pr = inner.get("pull_request", inner)
    pr_number = pr.get("number") or pr.get("pr_number")
    pr_url = pr.get("html_url", f"https://github.com/{owner}/{repo}/pull/{pr_number}")
    if not pr_number:
        raise RuntimeError(f"create_pull_request failed: {str(inner)[:400]}")
    print(f"  PR #{pr_number}: {pr_url}")

    if not wait_for_ci:
        return {"pr_number": pr_number, "pr_url": pr_url, "ci_status": "skipped", "merged": False}

    # 4. Poll CI status
    print(f"Waiting for CI (timeout {ci_timeout_seconds}s)...", flush=True)
    deadline = time.time() + ci_timeout_seconds
    ci_status = "pending"
    poll_interval = 15
    while time.time() < deadline:
        time.sleep(poll_interval)
        r = mgr_call("call_tool", {
            "server": "github", "tool": "get_copilot_pr_status",
            "arguments": {"owner": owner, "repo": repo, "issue_number": pr_number},
        })
        inner = get_inner(r)
        checks = inner.get("checks", inner.get("status", {}))
        # Normalise — different MCP versions return different shapes
        if isinstance(checks, dict):
            overall = checks.get("overall", checks.get("conclusion", checks.get("state", "pending")))
        else:
            overall = str(checks)
        overall = overall.lower() if overall else "pending"
        print(f"  CI: {overall}")
        if overall in ("success", "passed", "completed"):
            ci_status = "success"
            break
        elif overall in ("failure", "failed", "error", "cancelled"):
            ci_status = "failure"
            break
        poll_interval = min(poll_interval * 1.5, 60)  # back off up to 60s
    else:
        ci_status = "timeout"

    print(f"CI result: {ci_status}")

    if ci_status != "success":
        print(f"  CI did not pass ({ci_status}). PR left open for review: {pr_url}")
        return {"pr_number": pr_number, "pr_url": pr_url, "ci_status": ci_status, "merged": False}

    if not auto_merge:
        return {"pr_number": pr_number, "pr_url": pr_url, "ci_status": ci_status, "merged": False}

    # 5. Merge and clean up
    print("Merging PR...")
    r = mgr_call("call_tool", {
        "server": "github", "tool": "merge_pull_request",
        "arguments": {"owner": owner, "repo": repo, "pr_number": pr_number,
                      "merge_method": "squash"},
    })
    inner = get_inner(r)
    merged = inner.get("merged", inner.get("success", False))
    if merged:
        print("  Merged.")
        mgr_call("call_tool", {
            "server": "github", "tool": "delete_branch",
            "arguments": {"owner": owner, "repo": repo, "branch": branch_name},
        })
        print(f"  Branch '{branch_name}' deleted.")
    else:
        print(f"  Merge failed: {str(inner)[:200]}")

    return {"pr_number": pr_number, "pr_url": pr_url, "ci_status": ci_status, "merged": bool(merged)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Push files to GitHub via MCP Manager")
    parser.add_argument("--files", nargs="+", required=True, help="File paths relative to repo root")
    parser.add_argument("--message", "-m", required=True, help="Commit message")
    parser.add_argument("--owner", default=OWNER)
    parser.add_argument("--repo", default=REPO)
    parser.add_argument("--branch", default=BRANCH)
    # PR mode
    parser.add_argument("--pr", action="store_true", help="Use PR workflow instead of direct push")
    parser.add_argument("--branch-name", help="Feature branch name (required with --pr)")
    parser.add_argument("--pr-title", help="PR title (defaults to commit message)")
    parser.add_argument("--pr-body", default="", help="PR description body")
    parser.add_argument("--no-auto-merge", action="store_true", help="Open PR but don't auto-merge")
    parser.add_argument("--ci-timeout", type=int, default=300, help="CI wait timeout in seconds")
    args = parser.parse_args()

    if args.pr:
        if not args.branch_name:
            parser.error("--branch-name is required when using --pr")
        result = push_as_pr(
            file_paths=args.files,
            branch_name=args.branch_name,
            commit_message=args.message,
            pr_title=args.pr_title or args.message,
            pr_body=args.pr_body,
            base_branch=args.branch,
            owner=args.owner,
            repo=args.repo,
            auto_merge=not args.no_auto_merge,
            ci_timeout_seconds=args.ci_timeout,
        )
        print(f"\nResult: {result}")
    else:
        push_files(args.files, args.message, args.owner, args.repo, args.branch)
