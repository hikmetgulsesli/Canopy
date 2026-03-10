#!/usr/bin/env python3
"""Push a single file to GitHub via MCP Manager. Usage: python push_one_file_mcp.py <path> [commit_msg]"""
import json
import sys
from pathlib import Path

try:
    from urllib.request import Request, urlopen
except ImportError:
    Request, urlopen = None, None

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def rpc_call(url: str, method: str, params: dict) -> dict:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    req = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode("utf-8"))


def tool_call(url: str, server: str, tool: str, arguments: dict) -> dict:
    res = rpc_call(
        url,
        "tools/call",
        {"name": "call_tool", "arguments": {"server": server, "tool": tool, "arguments": arguments}},
    )
    text = (res.get("result") or {}).get("content") or []
    if not text or not isinstance(text[0].get("text"), str):
        return {"success": False, "error": res.get("error") or "No result content"}
    return json.loads(text[0]["text"])


# Files that must never be pushed (local/agent/IDE — workspace rule: stay local)
_NEVER_PUSH = (
    "AGENT_NOTE_",
    "AGENT_REPLY_",
    "API_KEY_SETUP.md",
    "GITHUB_PUSH_GUIDE_FOR_WINDOWS_AGENT.md",
    ".cursorrules",
)

# Directories that must NEVER be pushed (confidential/legal)
_NEVER_PUSH_DIRS = ("provisional", "patents")


def main():
    if len(sys.argv) < 2:
        print("Usage: python push_one_file_mcp.py <rel_path> [commit_msg]", file=sys.stderr)
        return 1
    rel_path = sys.argv[1].replace("\\", "/")
    basename = Path(rel_path).name
    # Workspace rule: .cursorrules and other local-only files must never be pushed
    if ".cursorrules" in rel_path or any(basename.startswith(p.rstrip("*")) or basename == p for p in _NEVER_PUSH):
        print(f"Refusing to push {rel_path} (agent notes and local files stay local)", file=sys.stderr)
        return 1
    # Block any file inside confidential directories
    rel_parts = Path(rel_path).parts
    if any(d in rel_parts for d in _NEVER_PUSH_DIRS):
        print(f"Refusing to push {rel_path} (confidential directory)", file=sys.stderr)
        return 1
    message = sys.argv[2] if len(sys.argv) > 2 else f"Update {rel_path}"
    path = PROJECT_ROOT / rel_path
    if not path.is_file():
        print(f"Not a file: {path}", file=sys.stderr)
        return 1
    content = path.read_text(encoding="utf-8", errors="replace")
    url = "http://localhost:8000"
    owner = "kwalus"
    repo = "Canopy"

    print(f"Get SHA: {rel_path}", file=sys.stderr)
    out = tool_call(url, "github", "get_file_sha", {"owner": owner, "repo": repo, "path": rel_path})
    sha = None
    if out.get("success") and out.get("result"):
        ref = out["result"]
        sha = ref.get("sha") if isinstance(ref, dict) else None
    if not sha and out.get("error"):
        print(f"  get_file_sha: {out.get('error')} (will create new)", file=sys.stderr)

    args = {"owner": owner, "repo": repo, "path": rel_path, "content": content, "message": message}
    if sha:
        args["sha"] = sha
    print(f"Push: {rel_path}", file=sys.stderr)
    out = tool_call(url, "github", "create_or_update_file", args)
    if not out.get("success"):
        print(f"FAILED: {out.get('error', out)}", file=sys.stderr)
        return 1
    print("OK", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
