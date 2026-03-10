#!/usr/bin/env python3
"""
Copy only the files that should be pushed to GitHub into a target folder.
Use the same rules as list_pushable_files.py. Does not touch .git in the destination.
Run from repo root. Usage: python scripts/sync_to_github_folder.py [destination_dir]
"""
import fnmatch
import shutil
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_DEST = Path("/Users/konradw/Dropbox/Canopy")

EXCLUDE_DIRS = {
    ".git", "__pycache__",
    ".venv", "venv", "env", "ENV", "env.bak", "venv.bak",
    ".vscode", ".idea", ".cursor",
    "data", "logs", "agent_note", "agents", "research and references",
    "flask_session", "peers", "network_state", "backup", "backups",
    "htmlcov", ".tox", ".pytest_cache", "site", ".ipynb_checkpoints", ".mypy_cache",
    "develop-eggs", "dist", "downloads", "eggs", "lib", "parts", "sdist", "var", "wheels", "build",
    "provisional", "provisional_next", "patents", "node_modules", "tmp", "temp",
}

EXCLUDE_GLOBS = [
    "*.pyc", "*.pyo", "*$py.class", "*.so", "*.egg", "*.egg-info", ".DS_Store",
    ".env", ".env.*", "*.db", "*.db-journal", "cursor-mcp-config.json", "tray_state.json",
    ".cursorrules", "*.swp", "*.swo", "*~", "*.tmp", "*.temp", "*.backup",
    "*.key", "*.pem", "*.cert", ".coverage", ".python-version",
    "P2P_MILESTONE.md", "API_KEY_SETUP.md", "GITHUB_PUSH_RULES.md", "CURSOR_MCP_SETUP.md",
    "START_CANOPY_MCP.md", "QUICK_START.txt", "AGENT_NOTE_*.md", "AGENT_REPLY_*.md",
    "GITHUB_PUSH_GUIDE_FOR_WINDOWS_AGENT.md", "docs/DEPLOY_GITHUB.md", "docs/COPILOT_*.md", "docs/TRACE_*.md",
    "scripts/announce_*.txt", "docs/P2P_ARCHITECTURE.md", "docs/P2P_IMPLEMENTATION.md",
    "build_handover_zip.py", "PATENT_*.md", "PROVISIONAL_*", "*.textClipping",
    "filing_checklist.md", "prior_art_*.md", "identifier_dedup_addendum.md",
    "CANOPY_PROVISIONAL_PATENT.*", ".dmypy.json", "dmypy.json",
]

EXCLUDE_PREFIXES = ("config/production.ini", "config/secrets.env", ".env.local", ".env.production")


def should_exclude(rel_path: str) -> bool:
    for part in Path(rel_path).parts:
        if part in EXCLUDE_DIRS:
            return True
    for prefix in EXCLUDE_PREFIXES:
        if rel_path == prefix or rel_path.startswith(prefix + "/"):
            return True
    for pattern in EXCLUDE_GLOBS:
        if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(Path(rel_path).name, pattern):
            return True
    return False


def main():
    dest = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_DEST
    dest = dest.resolve()
    if dest == REPO:
        print("Destination cannot be the repo root. Exiting.")
        sys.exit(1)
    if not REPO.is_dir():
        print("Repo root not found. Exiting.")
        sys.exit(1)

    files = []
    for path in REPO.rglob("*"):
        if not path.is_file():
            continue
        try:
            rel = path.relative_to(REPO).as_posix()
        except ValueError:
            continue
        if should_exclude(rel):
            continue
        files.append(rel)

    files.sort()
    dest.mkdir(parents=True, exist_ok=True)

    for rel in files:
        src = REPO / rel
        dst = dest / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)

    print(f"Copied {len(files)} files to {dest}")
    print("Do not copy or overwrite .git in the destination — use your own init/push from there.")


if __name__ == "__main__":
    main()
