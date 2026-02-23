#!/usr/bin/env python3
"""Fetch recent #general messages (e.g. to read audit responses)."""
import json
import os
import sys
from pathlib import Path
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

DEFAULT_BASE = "http://localhost:7770"

def get_api_key():
    key = os.environ.get("CANOPY_API_KEY")
    if key:
        return key.strip()
    p = Path.home() / ".canopy" / "canopy_dev_bot_api_key"
    if p.exists():
        return p.read_text().strip()
    return None

def main():
    key = (get_api_key() or "").strip()
    base = (os.environ.get("CANOPY_BASE_URL") or DEFAULT_BASE).rstrip("/")
    if not key:
        print("Error: No API key.", file=sys.stderr)
        sys.exit(1)
    limit = int(os.environ.get("LIMIT", "60"))
    req = Request(
        f"{base}/api/v1/channels/general/messages?limit={limit}",
        headers={"X-API-Key": key},
        method="GET",
    )
    with urlopen(req, timeout=15) as r:
        data = json.loads(r.read().decode())
    messages = data.get("messages") or []
    for m in reversed(messages):
        author = m.get("display_name") or m.get("username") or m.get("user_id") or "?"
        content = (m.get("content") or "").strip()
        created = m.get("created_at", "")[:19] if m.get("created_at") else ""
        print(f"[{created}] {author}:")
        print(content)
        print("-" * 60)

if __name__ == "__main__":
    main()
