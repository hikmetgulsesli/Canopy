#!/usr/bin/env python3
"""
Validate that tracked Canopy files on disk match the latest on GitHub (main).

Uses the same MCP at localhost:8000 as push_one_file_mcp.py. Requires:
- MCP Manager running (e.g. on port 8000) with a GitHub tool that can return file content.
- If the MCP only has get_file_sha / create_or_update_file, we only check that each file
  exists on GitHub (SHA fetched); full content comparison requires a get_file_contents-style tool.

Usage:
  python scripts/validate_github_sync.py
  python scripts/validate_github_sync.py --list   # only list files we would check
"""

import json
import sys
from pathlib import Path

try:
    from urllib.request import Request, urlopen
except ImportError:
    Request, urlopen = None, None

PROJECT_ROOT = Path(__file__).resolve().parent.parent
URL = "http://localhost:8000"
OWNER = "kwalus"
REPO = "Canopy"
REF = "main"

# Key files we care about (canopy source + UI templates we've been updating)
FILES_TO_CHECK = [
    "canopy/__init__.py",
    "canopy/api/routes.py",
    "canopy/core/app.py",
    "canopy/core/channels.py",
    "canopy/core/config.py",
    "canopy/core/database.py",
    "canopy/core/feed.py",
    "canopy/core/files.py",
    "canopy/core/messaging.py",
    "canopy/core/profile.py",
    "canopy/mcp/server.py",
    "canopy/network/manager.py",
    "canopy/network/routing.py",
    "canopy/ui/routes.py",
    "canopy/ui/templates/channels.html",
    "canopy/ui/templates/feed.html",
    "canopy/ui/templates/messages.html",
    "canopy/main.py",
]


def rpc_call(method: str, params: dict) -> dict:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    req = Request(
        URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=25) as resp:
        return json.loads(resp.read().decode())


def tool_call(server: str, tool: str, arguments: dict) -> dict:
    res = rpc_call(
        "tools/call",
        {"name": "call_tool", "arguments": {"server": server, "tool": tool, "arguments": arguments}},
    )
    text = (res.get("result") or {}).get("content") or []
    if not text or not isinstance(text[0].get("text"), str):
        return {"success": False, "error": res.get("error") or "No result content"}
    try:
        return json.loads(text[0]["text"])
    except json.JSONDecodeError:
        return {"success": True, "text": text[0]["text"]}


def get_file_sha(path: str) -> dict:
    return tool_call("github", "get_file_sha", {"owner": OWNER, "repo": REPO, "path": path})


def get_file_content(path: str) -> dict:
    # Try common tool names that return file content from GitHub
    for tool in ("get_file_contents", "get_file_content", "get_repository_file", "read_file"):
        out = tool_call("github", tool, {"owner": OWNER, "repo": REPO, "path": path, "ref": REF})
        if out.get("success") and (out.get("content") or out.get("result") or out.get("text")):
            return out
        # Some APIs use different param name
        out = tool_call("github", tool, {"owner": OWNER, "repo": REPO, "path": path})
        if out.get("success") and (out.get("content") or out.get("result") or out.get("text")):
            return out
    return {"success": False, "error": "No get-content tool found (tried get_file_contents, get_file_content, get_repository_file, read_file)"}


def main():
    if "--list" in sys.argv:
        for f in FILES_TO_CHECK:
            p = PROJECT_ROOT / f
            print(f"{f}  (exists={p.is_file()})")
        return 0

    print("Validating local files against GitHub main...")
    print(f"MCP URL: {URL}  repo: {OWNER}/{REPO}")
    print()

    missing_local = []
    sha_ok = []
    sha_fail = []
    content_ok = []
    content_diff = []
    content_unknown = []

    for rel_path in FILES_TO_CHECK:
        local_path = PROJECT_ROOT / rel_path
        if not local_path.is_file():
            missing_local.append(rel_path)
            continue

        local_content = local_path.read_text(encoding="utf-8", errors="replace")

        # 1) Check file exists on GitHub (get SHA)
        out = get_file_sha(rel_path)
        if not out.get("success"):
            sha_fail.append((rel_path, out.get("error", "unknown")))
            continue
        sha_ok.append(rel_path)

        # 2) Try to get remote content and compare
        out = get_file_content(rel_path)
        if not out.get("success"):
            content_unknown.append((rel_path, out.get("error", "could not fetch content")))
            continue

        remote = None
        result = out.get("result")
        if isinstance(result, dict):
            # MCP Manager style: result.file.content (decoded string)
            f = result.get("file")
            if isinstance(f, dict) and "content" in f and isinstance(f["content"], str):
                remote = f["content"]
            # GitHub API style: result.content as base64
            elif "content" in result and result.get("encoding") == "base64":
                import base64
                remote = base64.b64decode(result["content"]).decode("utf-8", errors="replace")
            elif "content" in result and isinstance(result["content"], str):
                remote = result["content"]
        if isinstance(out.get("content"), str):
            remote = out["content"]
        if isinstance(out.get("text"), str):
            remote = out["text"]
        if remote is None:
            content_unknown.append((rel_path, "content not in expected shape"))
            continue

        if local_content.strip() == remote.strip():
            content_ok.append(rel_path)
        else:
            content_diff.append(rel_path)

    # Report
    if missing_local:
        print("Missing locally (skipped):")
        for f in missing_local:
            print(f"  - {f}")
        print()

    if sha_fail:
        print("Not on GitHub or error fetching SHA:")
        for f, err in sha_fail:
            print(f"  - {f}: {err}")
        print()

    if content_unknown:
        print("On GitHub but could not compare content (MCP may not expose get_file_contents):")
        for f, err in content_unknown:
            print(f"  - {f}: {err}")
        print("  → Run with git: git fetch origin && git diff origin/main --stat")
        print()

    if content_diff:
        print("DIFF (local differs from GitHub):")
        for f in content_diff:
            print(f"  - {f}")
        print()

    if content_ok:
        print("In sync (local matches GitHub):")
        for f in content_ok:
            print(f"  - {f}")
        print()

    print(f"Summary: {len(sha_ok)} files on GitHub, {len(content_ok)} content-matched, {len(content_diff)} diff, {len(content_unknown)} unknown (no get-content tool)")
    if content_diff or sha_fail:
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
