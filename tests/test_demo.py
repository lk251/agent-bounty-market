from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from agent_bounty.demo import demo_rehearse, run_demo_local, run_demo_replay


class DemoCommandTests(unittest.TestCase):
    def test_demo_local_captures_replayable_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_demo_local(state_dir=Path(tmp) / "state")
            self.assertTrue(result["ok"], result)
            self.assertEqual(result["label"], "Local simulation")

            replay = run_demo_replay(bundle_dir=Path(result["bundle_dir"]))
            self.assertTrue(replay["ok"], replay)
            self.assertEqual(replay["label"], "Local simulation replay")
            self.assertEqual(replay["timeline"]["bounty_state"], "paid")

    def test_demo_replay_rejects_tampered_bundle(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_demo_local(state_dir=Path(tmp) / "state")
            bundle_path = Path(result["bundle_dir"]) / "bundle.json"
            bundle = json.loads(bundle_path.read_text(encoding="utf-8"))
            bundle["label"] = "Live"
            bundle_path.write_text(json.dumps(bundle, sort_keys=True), encoding="utf-8")

            replay = run_demo_replay(bundle_dir=Path(result["bundle_dir"]))
            self.assertFalse(replay["ok"], replay)
            self.assertIn("bundle.json digest mismatch", replay["validation"]["mismatches"])

    def test_demo_rehearse_local_runs_local_and_replay_stages(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = demo_rehearse(mode="local", state_dir=Path(tmp) / "rehearsal")
            self.assertTrue(result["ok"], result)
            self.assertEqual([stage["name"] for stage in result["stages"]], ["preflight", "local-run", "replay-validation"])
            self.assertGreaterEqual(result["total_duration_ms"], 0)


if __name__ == "__main__":
    unittest.main()
