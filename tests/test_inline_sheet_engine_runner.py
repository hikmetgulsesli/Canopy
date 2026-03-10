"""Regression wrapper for the standalone inline spreadsheet engine."""

import shutil
import subprocess
import sys
import unittest
from pathlib import Path


class TestInlineSheetEngineRunner(unittest.TestCase):
    def test_node_engine_regressions(self):
        node = shutil.which("node")
        if not node:
            self.skipTest("node is not installed")

        repo_root = Path(__file__).resolve().parent.parent
        script_path = repo_root / "tests" / "test_inline_sheet_engine.js"
        result = subprocess.run(
            [node, str(script_path)],
            cwd=str(repo_root),
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            self.fail(
                "inline sheet engine regression script failed\n"
                f"stdout:\n{result.stdout}\n"
                f"stderr:\n{result.stderr}"
            )
        self.assertIn("inline sheet engine ok", result.stdout)


if __name__ == "__main__":
    unittest.main()
