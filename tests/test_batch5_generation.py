from __future__ import annotations

import json
import os
import socket
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image, ImageDraw

from src.batch5_generation import (
    Batch5AInputError,
    MissingApiKeyEnvironmentVariable,
    UnsafePromptPackPath,
    UnsupportedContentGenerationBackend,
    batch5_output_paths,
    resolve_prompt_pack_path,
    resolve_batch5_options,
    run_batch_5a,
)


class Batch5AGenerationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.run_dir = self.root / "outputs" / "synthetic_run"
        self.audit_dir = self.run_dir / "audit"
        self.keyframe_dir = self.run_dir / "assets" / "keyframes"
        self.audit_dir.mkdir(parents=True)
        self.keyframe_dir.mkdir(parents=True)
        self.config = {
            "video_url": "https://example.com/public-lecture-video",
            "run_id": "synthetic_run",
            "output_dir": str(self.root / "outputs"),
            "content_generation_backend": "none",
            "content_generation_backend_mode": "skeleton",
            "generate_llm_prompt_pack": True,
            "llm_prompt_pack_path": "audit/handout_prompt_pack.jsonl",
            "content_unit_max_gap_seconds": 45,
            "content_unit_max_duration_seconds": 240,
            "content_unit_min_transcript_chars": 80,
            "handout_max_images_per_unit": 1,
            "handout_min_image_spacing_seconds": 0,
            "llm_allow_network_calls": False,
        }
        self._write_formal_inputs()

    def tearDown(self) -> None:
        self.temp_dir.cleanup()

    def _write_json(self, path: Path, payload: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def _make_keyframe(self, index: int) -> Path:
        path = self.keyframe_dir / f"keyframe_{index:04d}.jpg"
        image = Image.new("RGB", (640, 360), "white")
        draw = ImageDraw.Draw(image)
        draw.rectangle((60, 80, 560, 300), fill=(25 + (index * 8), 25, 25))
        draw.text((90, 100 + index), f"Example {index}", fill="white")
        image.save(path)
        return path

    def _write_formal_inputs(self) -> None:
        transcripts = []
        visuals = []
        alignments = []
        for index in range(1, 5):
            keyframe = self._make_keyframe(index)
            start = float((index - 1) * 10)
            end = float(index * 10)
            visuals.append(
                {
                    "id": index,
                    "start": start,
                    "end": end,
                    "source_frame_time": start,
                    "keyframe_path": str(keyframe),
                }
            )
            for offset in range(2):
                transcript_id = ((index - 1) * 2) + offset + 1
                transcript_start = start + (offset * 5)
                transcript_end = transcript_start + 4
                text = f"Grounded transcript excerpt {transcript_id} for visual segment {index}."
                transcripts.append(
                    {
                        "id": transcript_id,
                        "start": transcript_start,
                        "end": transcript_end,
                        "text": text,
                    }
                )
                alignments.append(
                    {
                        "transcript_segment_id": transcript_id,
                        "transcript_index": transcript_id - 1,
                        "transcript_start": transcript_start,
                        "transcript_end": transcript_end,
                        "transcript_text": text,
                        "matched_visual_segment_id": index,
                        "visual_start": start,
                        "visual_end": end,
                        "keyframe_path": str(keyframe),
                        "source_frame_time": start,
                        "match_reason": "time_overlap",
                        "overlap_seconds": 4,
                        "distance_seconds": 0,
                        "confidence": "high",
                        "quality_flags": [],
                    }
                )
        self._write_json(
            self.audit_dir / "raw_transcript.json",
            {
                "run_id": "synthetic_run",
                "source": {"type": "platform_subtitle", "language": "en"},
                "segments": transcripts,
                "segment_count": len(transcripts),
            },
        )
        self._write_json(
            self.audit_dir / "visual_segments.json",
            {
                "run_id": "synthetic_run",
                "status": "success",
                "segments": visuals,
                "segment_count": len(visuals),
            },
        )
        self._write_json(
            self.audit_dir / "frame_report.json",
            {
                "run_id": "synthetic_run",
                "status": "success",
                "smoke_test": False,
                "keyframe_count": len(visuals),
            },
        )
        self._write_json(
            self.audit_dir / "alignment.json",
            {
                "run_id": "synthetic_run",
                "status": "success",
                "method": "transcript_visual_time_alignment_v1",
                "inputs": {
                    "raw_transcript_path": str(self.audit_dir / "raw_transcript.json"),
                    "visual_segments_path": str(self.audit_dir / "visual_segments.json"),
                    "frame_report_path": str(self.audit_dir / "frame_report.json"),
                    "keyframe_dir": str(self.keyframe_dir),
                },
                "aligned_segment_count": len(alignments),
                "unaligned_segment_count": 0,
                "low_confidence_segment_count": 0,
                "alignments": alignments,
            },
        )

    def _read_prompt_pack(self) -> list[dict]:
        path = self.audit_dir / "handout_prompt_pack.jsonl"
        return [
            json.loads(line)
            for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]

    def test_valid_formal_inputs_generate_scaffold_and_prompt_pack(self) -> None:
        content_map = run_batch_5a(self.config, self.run_dir)
        self.assertEqual(content_map["status"], "success")
        self.assertGreater(len(content_map["content_units"]), 0)
        self.assertTrue((self.audit_dir / "content_map.json").exists())
        self.assertTrue((self.audit_dir / "review_report.md").exists())
        self.assertTrue((self.run_dir / "lecture_handout.md").exists())
        self.assertTrue((self.audit_dir / "handout_prompt_pack.jsonl").exists())
        starts = [unit["start_time"] for unit in content_map["content_units"]]
        self.assertEqual(starts, sorted(starts))

    def test_default_prompt_pack_path_is_allowed(self) -> None:
        self.config.pop("llm_prompt_pack_path")
        run_batch_5a(self.config, self.run_dir)
        self.assertTrue((self.audit_dir / "handout_prompt_pack.jsonl").exists())

    def test_custom_prompt_pack_path_inside_audit_is_allowed(self) -> None:
        self.config["llm_prompt_pack_path"] = "audit/custom_prompt_pack.jsonl"
        run_batch_5a(self.config, self.run_dir)
        self.assertTrue((self.audit_dir / "custom_prompt_pack.jsonl").exists())

    def test_dot_audit_prompt_pack_path_is_allowed(self) -> None:
        self.config["llm_prompt_pack_path"] = "./audit/custom_prompt_pack.jsonl"
        run_batch_5a(self.config, self.run_dir)
        self.assertTrue((self.audit_dir / "custom_prompt_pack.jsonl").exists())

    def test_normalized_prompt_pack_path_inside_audit_is_allowed(self) -> None:
        self.config["llm_prompt_pack_path"] = "audit/sub/../custom_prompt_pack.jsonl"
        run_batch_5a(self.config, self.run_dir)
        self.assertTrue((self.audit_dir / "custom_prompt_pack.jsonl").exists())

    def assert_unsafe_prompt_pack_path(self, configured_path: str) -> None:
        self.config["llm_prompt_pack_path"] = configured_path
        with self.assertRaisesRegex(UnsafePromptPackPath, "llm_prompt_pack_path"):
            run_batch_5a(self.config, self.run_dir)

    def test_parent_traversal_prompt_pack_path_is_rejected_before_clear(self) -> None:
        sentinel = self.run_dir.parent / "escaped_prompt_pack.jsonl"
        sentinel.write_text("keep sentinel", encoding="utf-8")
        stale_handout = self.run_dir / "lecture_handout.md"
        stale_handout.write_text("keep stale handout", encoding="utf-8")
        self.assert_unsafe_prompt_pack_path("../escaped_prompt_pack.jsonl")
        self.assertEqual(sentinel.read_text(encoding="utf-8"), "keep sentinel")
        self.assertEqual(stale_handout.read_text(encoding="utf-8"), "keep stale handout")

    def test_nested_parent_traversal_prompt_pack_path_is_rejected(self) -> None:
        self.assert_unsafe_prompt_pack_path("audit/../../escaped_prompt_pack.jsonl")

    def test_audit_parent_traversal_prompt_pack_path_is_rejected(self) -> None:
        self.assert_unsafe_prompt_pack_path("audit/../escaped_prompt_pack.jsonl")

    def test_absolute_prompt_pack_path_is_rejected(self) -> None:
        self.assert_unsafe_prompt_pack_path(str(self.root / "escaped_prompt_pack.jsonl"))

    def test_windows_drive_prompt_pack_path_is_rejected(self) -> None:
        self.assert_unsafe_prompt_pack_path(r"C:\escaped_prompt_pack.jsonl")

    def test_backslash_parent_traversal_prompt_pack_path_is_rejected(self) -> None:
        self.assert_unsafe_prompt_pack_path(r"..\escaped_prompt_pack.jsonl")

    def test_mixed_separator_traversal_prompt_pack_path_is_rejected(self) -> None:
        self.assert_unsafe_prompt_pack_path(r"audit\..\../escaped_prompt_pack.jsonl")

    def test_directory_prompt_pack_path_is_rejected(self) -> None:
        directory = self.audit_dir / "custom_prompt_pack.jsonl"
        directory.mkdir()
        self.assert_unsafe_prompt_pack_path("audit/custom_prompt_pack.jsonl")

    def test_prompt_pack_path_requires_jsonl_suffix(self) -> None:
        self.assert_unsafe_prompt_pack_path("audit/custom_prompt_pack.json")

    def test_symlink_escape_prompt_pack_path_is_rejected(self) -> None:
        outside_dir = self.root / "outside"
        outside_dir.mkdir()
        link = self.audit_dir / "linked"
        try:
            link.symlink_to(outside_dir, target_is_directory=True)
        except (OSError, NotImplementedError) as error:
            self.skipTest(f"Directory symlink unavailable: {error}")
        self.assert_unsafe_prompt_pack_path("audit/linked/escaped_prompt_pack.jsonl")

    def test_direct_prompt_pack_resolver_returns_resolved_audit_path(self) -> None:
        resolved = resolve_prompt_pack_path(
            self.run_dir,
            "audit/sub/../custom_prompt_pack.jsonl",
        )
        self.assertEqual(resolved, (self.audit_dir / "custom_prompt_pack.jsonl").resolve())

    def test_smoke_or_failed_alignment_fails_closed(self) -> None:
        alignment_path = self.audit_dir / "alignment.json"
        payload = json.loads(alignment_path.read_text(encoding="utf-8"))
        payload["status"] = "failed"
        self._write_json(alignment_path, payload)
        with self.assertRaises(Batch5AInputError):
            run_batch_5a(self.config, self.run_dir)
        self.assertFalse((self.run_dir / "lecture_handout.md").exists())

    def test_missing_alignment_fails_closed(self) -> None:
        (self.audit_dir / "alignment.json").unlink()
        with self.assertRaises(Batch5AInputError):
            run_batch_5a(self.config, self.run_dir)

    def test_smoke_frame_report_fails_closed(self) -> None:
        frame_path = self.audit_dir / "frame_report.json"
        payload = json.loads(frame_path.read_text(encoding="utf-8"))
        payload["smoke_test"] = True
        self._write_json(frame_path, payload)
        with self.assertRaises(Batch5AInputError):
            run_batch_5a(self.config, self.run_dir)

    def test_references_and_selected_keyframes_are_valid(self) -> None:
        content_map = run_batch_5a(self.config, self.run_dir)
        transcript_ids = set(range(1, 9))
        visual_ids = set(range(1, 5))
        for unit in content_map["content_units"]:
            self.assertTrue(set(unit["transcript_item_ids"]).issubset(transcript_ids))
            self.assertTrue(set(unit["visual_segment_ids"]).issubset(visual_ids))
            for selected in unit["selected_keyframes"]:
                self.assertTrue(Path(selected["keyframe_path"]).exists())

    def test_rapid_near_duplicate_group_keeps_one_representative(self) -> None:
        content_map = run_batch_5a(self.config, self.run_dir)
        groups = content_map["near_duplicate_image_groups"]
        self.assertTrue(any(group["group_type"] == "rapid_visual_burst" for group in groups))
        selected_count = sum(
            len(unit["selected_keyframes"]) for unit in content_map["content_units"]
        )
        self.assertEqual(selected_count, 1)
        dropped = [
            item
            for unit in content_map["content_units"]
            for item in unit["dropped_near_duplicate_keyframes"]
        ]
        self.assertGreaterEqual(len(dropped), 3)
        self.assertTrue(all(item["reason"] for item in dropped))

    def test_none_backend_generates_skeleton_without_api_key(self) -> None:
        content_map = run_batch_5a(self.config, self.run_dir)
        backend = content_map["content_generation_backend"]
        self.assertEqual(backend["name"], "none")
        self.assertFalse(backend["api_key_read"])
        self.assertTrue(
            all(item["status"] == "skipped" for item in backend["generation_results"])
        )
        handout = (self.run_dir / "lecture_handout.md").read_text(encoding="utf-8")
        self.assertIn("讲义骨架草稿", handout)
        self.assertIn("尚未经过人工审核", handout)

    def test_unsupported_backend_fails_closed(self) -> None:
        self.config["content_generation_backend"] = "openai_compatible"
        self.config["llm_api_key_env"] = "EXAMPLE_API_KEY_ENV"
        with self.assertRaises(UnsupportedContentGenerationBackend):
            run_batch_5a(self.config, self.run_dir)
        self.assertFalse((self.run_dir / "lecture_handout.md").exists())

    def test_future_backend_without_api_key_env_fails_closed(self) -> None:
        self.config["content_generation_backend"] = "local"
        with self.assertRaises(MissingApiKeyEnvironmentVariable):
            run_batch_5a(self.config, self.run_dir)

    def test_batch5a_does_not_make_network_calls(self) -> None:
        with mock.patch.object(
            socket,
            "create_connection",
            side_effect=AssertionError("Network call attempted."),
        ):
            run_batch_5a(self.config, self.run_dir)

    def test_prompt_pack_is_bounded_and_references_existing_evidence(self) -> None:
        content_map = run_batch_5a(self.config, self.run_dir)
        prompt_items = self._read_prompt_pack()
        self.assertEqual(len(prompt_items), len(content_map["content_units"]))
        raw_payload = json.loads(
            (self.audit_dir / "raw_transcript.json").read_text(encoding="utf-8")
        )
        raw_transcript = json.dumps(raw_payload)
        prompt_pack_text = (self.audit_dir / "handout_prompt_pack.jsonl").read_text(
            encoding="utf-8"
        )
        self.assertNotEqual(prompt_pack_text, raw_transcript)
        full_transcript_text = " ".join(item["text"] for item in raw_payload["segments"])
        self.assertNotIn(full_transcript_text, prompt_pack_text)
        transcript_ids = {item["id"] for item in raw_payload["segments"]}
        visual_payload = json.loads(
            (self.audit_dir / "visual_segments.json").read_text(encoding="utf-8")
        )
        visual_ids = {item["id"] for item in visual_payload["segments"]}
        for item in prompt_items:
            self.assertEqual(item["schema_version"], "handout_prompt_pack_v1")
            self.assertTrue(set(item["transcript_item_ids"]).issubset(transcript_ids))
            self.assertTrue(set(item["visual_segment_ids"]).issubset(visual_ids))
            for selected in item["selected_keyframe_metadata"]:
                self.assertTrue(Path(selected["keyframe_path"]).exists())
            self.assertIn("desired_output_schema", item)
            self.assertIn("grounding_rules", item)

    def test_generated_artifacts_do_not_include_environment_secret(self) -> None:
        marker = "DO_NOT_LEAK_THIS_VALUE"
        os.environ["EXAMPLE_SECRET_ENV"] = marker
        try:
            run_batch_5a(self.config, self.run_dir)
            options = resolve_batch5_options(self.config)
            paths = batch5_output_paths(self.run_dir, options)
            generated = "\n".join(
                path.read_text(encoding="utf-8")
                for path in paths.values()
                if path.exists()
            )
            self.assertNotIn(marker, generated)
        finally:
            os.environ.pop("EXAMPLE_SECRET_ENV", None)

    def test_production_selection_logic_has_no_case_specific_hardcodes(self) -> None:
        production_text = (
            Path("src/batch5_generation.py").read_text(encoding="utf-8")
            + Path("src/run_pipeline.py").read_text(encoding="utf-8")
        )
        forbidden = (
            "1640",
            "1650",
            "1660",
            "1680",
            "1990",
            "batch2_test",
            "r1qZpYAmqmg",
            "Pretraining Data",
        )
        for item in forbidden:
            self.assertNotIn(item, production_text)


if __name__ == "__main__":
    unittest.main()
