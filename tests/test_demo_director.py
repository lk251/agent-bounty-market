from __future__ import annotations

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from agent_bounty.demo_presentation import build_director_data, prepare_demo_director_report


REPO_ROOT = Path(__file__).resolve().parents[1]
WINNING_BUNDLE = REPO_ROOT / "demo" / "bundles" / "winning-run"


class DemoDirectorTests(unittest.TestCase):
    def test_director_generates_all_scene_assets_from_valid_bundle(self):
        with copied_bundle() as bundle_dir:
            report = prepare_demo_director_report(bundle_dir=bundle_dir, host="127.0.0.1", port=8788, duration=120)

            self.assertTrue(report["ok"], report["mismatches"])
            self.assertEqual(report["scene_count"], 7)
            self.assertEqual(report["url"], "http://127.0.0.1:8788/director.html?duration=120")
            self.assertEqual(report["record_url"], "http://127.0.0.1:8788/director-record.html?duration=120&autoplay=1")
            self.assertEqual(
                sorted(report["asset_paths"]),
                ["director-cues.json", "director-notes.html", "director-record.html", "director.html"],
            )
            for relative in report["asset_paths"]:
                self.assertTrue((bundle_dir / relative).exists(), relative)

    def test_director_cues_have_required_scenes_and_exact_duration(self):
        with copied_bundle() as bundle_dir:
            prepare_demo_director_report(bundle_dir=bundle_dir, duration=120)
            cues = json.loads((bundle_dir / "director-cues.json").read_text(encoding="utf-8"))

            self.assertEqual(cues["schema"], "agent-bounty-demo-director-cues-v1")
            self.assertEqual(sum(scene["duration_seconds"] for scene in cues["scenes"]), 120)
            self.assertEqual(
                [scene["title"] for scene in cues["scenes"]],
                [
                    "Problem",
                    "Project buys work",
                    "Agents choose",
                    "Trust boundary",
                    "Settlement",
                    "Compounding",
                    "Close",
                ],
            )

    def test_director_facts_match_bundle_summary(self):
        bundle = json.loads((WINNING_BUNDLE / "bundle.json").read_text(encoding="utf-8"))
        data = build_director_data(bundle, duration=120)
        summary = bundle["summary"]
        scenes = {scene["id"]: scene for scene in data["scenes"]}

        problem_stats = stat_map(scenes["problem"])
        settlement_stats = stat_map(scenes["settlement"])
        compounding_stats = stat_map(scenes["compounding"])

        self.assertEqual(problem_stats["Reward"], f"{summary['reward']} {summary['currency']}")
        self.assertEqual(settlement_stats["External"], f"{summary['external_transfer']} {summary['currency']}")
        self.assertEqual(compounding_stats["Retained credit"], f"{summary['retained_operating_credit']} {summary['currency']}")
        self.assertEqual(data["bundle_digest"], bundle["bundle_content_digest"])

    def test_truth_badge_and_blockers_are_visible_without_private_data(self):
        with copied_bundle() as bundle_dir:
            prepare_demo_director_report(bundle_dir=bundle_dir, duration=120)
            data = json.loads((bundle_dir / "director-cues.json").read_text(encoding="utf-8"))
            html_text = (bundle_dir / "director.html").read_text(encoding="utf-8")
            notes_text = (bundle_dir / "director-notes.html").read_text(encoding="utf-8")
            serialized = "\n".join(path.read_text(encoding="utf-8") for path in bundle_dir.glob("director*"))

            self.assertEqual(data["truth_badge"], "Mixed real/fallback")
            self.assertGreaterEqual(html_text.count("Mixed real/fallback"), 7)
            self.assertIn("fallback", html_text.lower())
            self.assertIn("blocked", html_text.lower())
            self.assertIn("Presenter Notes", html_text)
            self.assertIn("Presenter Notes", notes_text)
            for forbidden in ("sk_test_", "whsec_", "ghp_", "/home/", "/Users/"):
                self.assertNotIn(forbidden, serialized)

    def test_record_route_excludes_presenter_notes_and_keeps_controls(self):
        with copied_bundle() as bundle_dir:
            prepare_demo_director_report(bundle_dir=bundle_dir, duration=120)
            director_html = (bundle_dir / "director.html").read_text(encoding="utf-8")
            record_html = (bundle_dir / "director-record.html").read_text(encoding="utf-8")

            self.assertIn("Presenter Notes", director_html)
            self.assertNotIn("Presenter Notes", record_html)
            for marker in ("ArrowRight", "ArrowLeft", "Escape", "autoplay", "prefers-reduced-motion"):
                self.assertIn(marker, record_html)
            script_payload = record_html.split('<script type="application/json" id="director-data">', 1)[1].split("</script>", 1)[0]
            self.assertIn('{"bundle_digest"', script_payload)
            self.assertNotIn("&quot;", script_payload)

    def test_tampered_bundle_refuses_director_generation(self):
        with copied_bundle() as bundle_dir:
            dashboard = bundle_dir / "dashboard.html"
            dashboard.write_text(dashboard.read_text(encoding="utf-8") + "\n<!-- tamper -->\n", encoding="utf-8")

            report = prepare_demo_director_report(bundle_dir=bundle_dir, duration=120)

            self.assertFalse(report["ok"])
            self.assertEqual(report["scene_count"], 0)
            self.assertIn("digest mismatch for dashboard.html", report["mismatches"])
            self.assertFalse((bundle_dir / "director.html").exists())


def copied_bundle():
    temp = tempfile.TemporaryDirectory()
    root = Path(temp.name)
    bundle_dir = root / "winning-run"
    shutil.copytree(WINNING_BUNDLE, bundle_dir)
    for path in bundle_dir.glob("director*"):
        if path.is_file():
            path.unlink()

    class _Context:
        def __enter__(self) -> Path:
            return bundle_dir

        def __exit__(self, exc_type, exc, tb) -> None:
            temp.cleanup()

    return _Context()


def stat_map(scene: dict) -> dict[str, str]:
    return {item["label"]: item["value"] for item in scene["stats"]}
