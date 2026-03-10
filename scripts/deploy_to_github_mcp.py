#!/usr/bin/env python3
"""
Deploy Canopy to a private GitHub repo via MCP Manager (JSON-RPC 2.0).

Prerequisites:
  - MCP Manager running (e.g. http://localhost:8000)
  - GitHub authenticated in MCP Manager (valid token)

Usage:
  python scripts/deploy_to_github_mcp.py [--owner YOUR_GITHUB_USER] [--create-repo]
  python scripts/deploy_to_github_mcp.py --dry-run   # list files only

If --owner is omitted, the script calls get_user to obtain it.
"""

import argparse
import json
import sys
from pathlib import Path

try:
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError
except ImportError:
    Request, urlopen, HTTPError, URLError = None, None, None, None

# Project root (parent of scripts/)
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Files/dirs to exclude (relative to PROJECT_ROOT)
EXCLUDE = {
    ".git",
    "venv",
    "data",
    "logs",
    ".env",
    "cursor-mcp-config.json",
    "__pycache__",
    ".DS_Store",
    "*.pyc",
    "*.log",
}


# Files that MUST NEVER be pushed (local/agent/IDE). Same as push_one_file_mcp._NEVER_PUSH.
_NEVER_PUSH_PATTERNS = (
    "AGENT_NOTE_",
    "AGENT_REPLY_",
    "API_KEY_SETUP.md",
    ".cursorrules",
    "GITHUB_PUSH_GUIDE_FOR_WINDOWS_AGENT.md",
)


def should_include(path: Path) -> bool:
    """Only include files needed to run the project. Exclude all runtime data, DBs, secrets, agent notes."""
    rel = path.relative_to(PROJECT_ROOT)
    parts = rel.parts
    name = path.name

    # Local/agent/IDE — MUST NEVER push
    if name == ".cursorrules":
        return False
    if ".cursor" in parts:
        return False
    if name.startswith("AGENT_NOTE_") or name.startswith("AGENT_REPLY_"):
        return False
    if name in ("API_KEY_SETUP.md", "GITHUB_PUSH_GUIDE_FOR_WINDOWS_AGENT.md"):
        return False

    # Runtime, secrets, config
    if name == ".DS_Store" or path.suffix in (".pyc", ".log"):
        return False
    if path.suffix in (".db", ".db-journal") or name.endswith(".db-journal"):
        return False
    if "cursor-mcp-config.json" in parts or name == "cursor-mcp-config.json":
        return False
    if name == ".env" or name.endswith(".log"):
        return False
    if "secret_key" in name or "peer_identity" in name:
        return False
    for excl in (".git", "venv", "data", "logs", "__pycache__", "provisional", "patents"):
        if excl in parts:
            return False
    return True


def collect_files() -> list[Path]:
    out = []
    for f in PROJECT_ROOT.rglob("*"):
        if f.is_file() and should_include(f):
            out.append(f)
    # Workspace rule: .cursorrules must stay local — never push IDE config
    out = [p for p in out if ".cursorrules" not in p.parts and p.name != ".cursorrules"]
    return sorted(out, key=lambda p: str(p))


def rpc_call(url: str, method: str, params: dict) -> dict:
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params,
    }
    req = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    return body


def tool_call(url: str, server: str, tool: str, arguments: dict) -> dict:
    res = rpc_call(
        url,
        "tools/call",
        {
            "name": "call_tool",
            "arguments": {
                "server": server,
                "tool": tool,
                "arguments": arguments,
            },
        },
    )
    text = (res.get("result") or {}).get("content") or []
    if not text or not isinstance(text[0].get("text"), str):
        return {"success": False, "error": "No result content"}
    return json.loads(text[0]["text"])


def main():
    parser = argparse.ArgumentParser(
        description="Deploy Canopy to GitHub via MCP Manager. "
        "PREFER push_one_file_mcp.py for incremental updates (changed files only)."
    )
    parser.add_argument("--mcp-url", default="http://localhost:8000", help="MCP Manager URL")
    parser.add_argument("--owner", help="GitHub owner (username). If omitted, fetched via get_user.")
    parser.add_argument("--repo", default="Canopy", help="Repository name")
    parser.add_argument("--create-repo", action="store_true", help="Create the repo if it does not exist")
    parser.add_argument("--dry-run", action="store_true", help="Only list files that would be uploaded")
    args = parser.parse_args()

    files = collect_files()
    rel_paths = [str(f.relative_to(PROJECT_ROOT)) for f in files]
    if not args.dry_run:
        print(
            "WARNING: This pushes ALL files. For incremental updates, use push_one_file_mcp.py instead.\n",
            file=sys.stderr,
        )
    if args.dry_run:
        for p in rel_paths:
            print(p)
        print(f"\nTotal: {len(rel_paths)} files", file=sys.stderr)
        return 0

    url = args.mcp_url.rstrip("/")
    owner = args.owner
    if not owner:
        print("Getting GitHub user...", file=sys.stderr)
        out = tool_call(url, "github", "get_user", {})
        if not out.get("success") or not out.get("result"):
            err = out.get("error") or out.get("result", {})
            if isinstance(err, dict) and "error" in err:
                err = err["error"]
            print(f"get_user failed: {err}", file=sys.stderr)
            return 1
        user = out.get("result", {}).get("user") or out.get("result", {})
        owner = user.get("login") or out.get("login")
        if not owner:
            err = out.get("error") or (out.get("result") or {}).get("error") or "Unknown"
            print(f"get_user failed: {err}", file=sys.stderr)
            print("If GitHub is authenticated elsewhere, run with: --owner YOUR_GITHUB_USERNAME", file=sys.stderr)
            return 1
        print(f"Using owner: {owner}", file=sys.stderr)
    repo = args.repo

    if args.create_repo:
        print("Creating repo...", file=sys.stderr)
        out = tool_call(
            url,
            "github",
            "create_repo",
            {
                "name": repo,
                "description": "Local-first mesh communication tool. Privacy-first messaging, P2P, API keys, MCP.",
                "private": True,
                "auto_init": False,
            },
        )
        if not out.get("success"):
            print(f"create_repo failed: {out.get('error', out)}", file=sys.stderr)
            return 1
        print("Repo created.", file=sys.stderr)

    for i, path in enumerate(files):
        rel = path.relative_to(PROJECT_ROOT)
        path_str = str(rel).replace("\\", "/")
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except Exception as e:
            print(f"Skip {path_str}: {e}", file=sys.stderr)
            continue
        msg = f"Add {path_str}" if i < 1 else f"Add {path_str}"
        print(f"[{i+1}/{len(files)}] {path_str}", file=sys.stderr)
        out = tool_call(
            url,
            "github",
            "create_or_update_file",
            {
                "owner": owner,
                "repo": repo,
                "path": path_str,
                "content": content,
                "message": msg,
            },
        )
        if not out.get("success"):
            print(f"  FAILED: {out.get('error', out)}", file=sys.stderr)

    print("Done.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
