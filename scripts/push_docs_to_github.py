#!/usr/bin/env python3
"""Push README.md, docs/QUICKSTART.md, MCP_README.md to GitHub via MCP Manager."""
import json
import sys
from pathlib import Path

try:
    from urllib.request import Request, urlopen
    from urllib.error import HTTPError, URLError
except ImportError:
    Request, urlopen, HTTPError, URLError = None, None, None, None

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DOCS = ["README.md", "docs/QUICKSTART.md", "MCP_README.md"]


def rpc_call(url: str, method: str, params: dict) -> dict:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    req = Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=30) as resp:
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


def main():
    url = "http://localhost:8000"
    owner = "kwalus"
    repo = "Canopy"
    message = "docs: update README, QUICKSTART, MCP_README (TTL, agent-instructions, security)"

    for rel_path in DOCS:
        path = PROJECT_ROOT / rel_path
        if not path.is_file():
            print(f"Skip (not found): {rel_path}", file=sys.stderr)
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        path_str = rel_path.replace("\\", "/")

        print(f"Get SHA: {path_str}", file=sys.stderr)
        out = tool_call(url, "github", "get_file_sha", {"owner": owner, "repo": repo, "path": path_str})
        sha = None
        if out.get("success") and out.get("result"):
            ref = out["result"]
            sha = ref.get("sha") if isinstance(ref, dict) else None
        if not sha and out.get("error"):
            print(f"  get_file_sha: {out.get('error')} (will create new)", file=sys.stderr)

        args = {"owner": owner, "repo": repo, "path": path_str, "content": content, "message": message}
        if sha:
            args["sha"] = sha
        print(f"Push: {path_str}", file=sys.stderr)
        out = tool_call(url, "github", "create_or_update_file", args)
        if not out.get("success"):
            print(f"  FAILED: {out.get('error', out)}", file=sys.stderr)
            return 1
        print(f"  OK", file=sys.stderr)
    print("Done.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
