from __future__ import annotations

import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

from agent_bounty.execution import LocalIsolatedProcessBackend, openshell_status


class ExecutionBackendTests(unittest.TestCase):
    def test_backend_scrubs_parent_secret_environment(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            script = tmp_path / "probe.py"
            script.write_text(
                "import os\n"
                "print(os.environ.get('AGENT_BOUNTY_SENTINEL', 'missing'))\n"
                "print(os.environ.get('GITHUB_TOKEN', 'missing'))\n",
                encoding="utf-8",
            )
            old = os.environ.get("AGENT_BOUNTY_SENTINEL")
            old_github = os.environ.get("GITHUB_TOKEN")
            os.environ["AGENT_BOUNTY_SENTINEL"] = "trusted-parent-secret"
            os.environ["GITHUB_TOKEN"] = "trusted-github-token"
            try:
                result = LocalIsolatedProcessBackend().run(
                    [sys.executable, str(script)],
                    cwd=tmp_path,
                    env={},
                    timeout_seconds=3.0,
                    max_output_bytes=10_000,
                )
            finally:
                if old is None:
                    os.environ.pop("AGENT_BOUNTY_SENTINEL", None)
                else:
                    os.environ["AGENT_BOUNTY_SENTINEL"] = old
                if old_github is None:
                    os.environ.pop("GITHUB_TOKEN", None)
                else:
                    os.environ["GITHUB_TOKEN"] = old_github
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.decode().splitlines(), ["missing", "missing"])

    def test_timeout_kills_process_group(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            pid_file = tmp_path / "child.pid"
            script = tmp_path / "hang.py"
            script.write_text(
                "import pathlib, subprocess, sys, time\n"
                "child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'])\n"
                f"pathlib.Path({str(pid_file)!r}).write_text(str(child.pid))\n"
                "time.sleep(30)\n",
                encoding="utf-8",
            )
            result = LocalIsolatedProcessBackend().run(
                [sys.executable, str(script)],
                cwd=tmp_path,
                env={},
                timeout_seconds=0.5,
                max_output_bytes=10_000,
            )
            self.assertTrue(result.timed_out)
            if pid_file.exists():
                pid = int(pid_file.read_text())
                deadline = time.monotonic() + 3.0
                alive = True
                while time.monotonic() < deadline:
                    try:
                        os.kill(pid, 0)
                    except ProcessLookupError:
                        alive = False
                        break
                    status_path = Path(f"/proc/{pid}/status")
                    if status_path.exists() and "\nState:\tZ" in status_path.read_text(errors="ignore"):
                        alive = False
                        break
                    time.sleep(0.05)
                self.assertFalse(alive, f"child process {pid} survived timeout")

    def test_output_capture_is_bounded(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            script = tmp_path / "flood.py"
            script.write_text("import sys\nsys.stdout.write('x' * 200000)\n", encoding="utf-8")
            result = LocalIsolatedProcessBackend().run(
                [sys.executable, str(script)],
                cwd=tmp_path,
                env={},
                timeout_seconds=3.0,
                max_output_bytes=1024,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertLessEqual(len(result.stdout), 1024)
            self.assertIn(b"truncated", result.stdout)

    def test_openshell_status_reports_digest_or_blocker(self):
        status = openshell_status()
        self.assertEqual(status["schema"], "openshell-backend-status-v1")
        self.assertTrue(str(status["policy_digest"]).startswith("sha256:"))
        self.assertTrue(status["available"] or status["blocker"])


if __name__ == "__main__":
    unittest.main()
