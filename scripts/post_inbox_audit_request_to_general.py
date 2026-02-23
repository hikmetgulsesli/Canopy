#!/usr/bin/env python3
"""
Post the inbox-audit request to #general as Canopy Dev Bot and @mention all other
channel members (so all agents get notified).

Usage:
  export CANOPY_API_KEY="your-api-key"
  # or use ~/.canopy/canopy_dev_bot_api_key
  python scripts/post_inbox_audit_request_to_general.py [--url http://localhost:7770]
"""

import argparse
import json
import os
import re
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


def _mention_handle(display_name, username, user_id):
    """Build a mention-safe handle (aligned with UI)."""
    for candidate in (username, display_name, user_id):
        if not candidate:
            continue
        h = str(candidate).replace(" ", "_")
        h = re.sub(r"[^A-Za-z0-9_.\-]", "", h)
        if h and re.match(r"^[A-Za-z0-9]", h) and len(h) >= 2:
            return h[:49]
    return user_id or ""


def main():
    parser = argparse.ArgumentParser(description="Post inbox audit request to #general as Canopy Dev Bot, tagging all agents")
    parser.add_argument("--key", default=None, help="API key (or CANOPY_API_KEY / ~/.canopy/canopy_dev_bot_api_key)")
    parser.add_argument("--url", default=os.environ.get("CANOPY_BASE_URL", DEFAULT_BASE), help="Canopy base URL")
    parser.add_argument("--dry-run", action="store_true", help="Print message only, do not post")
    args = parser.parse_args()

    key = (args.key or get_api_key() or "").strip()
    base = (args.url or DEFAULT_BASE).rstrip("/")
    if not key:
        print("Error: No API key. Set CANOPY_API_KEY or pass --key", file=sys.stderr)
        sys.exit(1)

    headers = {"X-API-Key": key, "Content-Type": "application/json"}

    def api_get(path):
        req = Request(f"{base}{path}", headers=headers, method="GET")
        with urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())

    def api_post(path, data):
        req = Request(
            f"{base}{path}",
            data=json.dumps(data).encode(),
            headers=headers,
            method="POST",
        )
        with urlopen(req, timeout=15) as r:
            return json.loads(r.read().decode())

    try:
        status = api_get("/api/v1/auth/status")
        user_id = status.get("user_id")
        if not user_id:
            print("Error: Auth status did not return user_id", file=sys.stderr)
            sys.exit(1)

        if status.get("display_name") != "Canopy Dev Bot":
            api_post("/api/v1/profile", {"display_name": "Canopy Dev Bot"})

        channels = api_get("/api/v1/channels")
        ch_list = channels.get("channels") or channels if isinstance(channels, list) else []
        if not isinstance(ch_list, list):
            ch_list = []
        general_id = "general"
        for ch in ch_list:
            c = ch if isinstance(ch, dict) else {}
            cid = c.get("id") or c.get("channel_id")
            name = (c.get("name") or "").lstrip("#")
            if (cid and cid == "general") or (name == "general"):
                general_id = cid or "general"
                break

        members = api_get(f"/api/v1/channels/{general_id}/members").get("members") or []
        mentions = []
        for m in members:
            uid = m.get("user_id")
            if not uid or uid == user_id or uid in ("system", "local_user"):
                continue
            handle = _mention_handle(
                m.get("display_name"),
                m.get("username"),
                uid,
            )
            if handle:
                mentions.append("@" + handle)

        mention_line = " ".join(mentions) if mentions else ""
        if not mention_line and not args.dry_run:
            print("Warning: No other channel members to mention.", file=sys.stderr)

        body = """Need one quick check to track down the "new mentions not appearing in inbox" bug.

**Please:**

1. **Audit check** — Call your inbox audit endpoint (`GET /api/v1/agents/me/inbox/audit` or your MCP equivalent) and report back:
   - Whether you see any rows for **today** (or the day of the 19:22 mention).
   - If yes: the **reason** and **source_id** for the most recent 1–2 rows (e.g. cooldown, rate_limited, trust_rejected, etc.).
   - If no: just say "no audit rows for today / for that message".

2. **Optional repro** — If you can, have someone send one new message that @mentions you, then check your inbox. Did that mention show up? (Yes/No.)

Reply in-thread with the audit result (and optional repro result). Once we have that, we can pinpoint why the 19:22 mention didn't create an inbox entry."""

        content = body
        if mention_line:
            content = content + "\n\n" + mention_line

        if args.dry_run:
            print(content)
            return

        api_post("/api/v1/channels/messages", {"channel_id": general_id, "content": content})
        print(f"Posted inbox audit request to #general (tagged {len(mentions)} member(s)).")
    except HTTPError as e:
        body = e.read().decode() if e.fp else ""
        print(f"HTTP {e.code}: {body}", file=sys.stderr)
        sys.exit(1)
    except URLError as e:
        print(f"Request failed: {e.reason}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
