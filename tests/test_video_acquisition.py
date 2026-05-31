from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from src import run_pipeline


class VideoAcquisitionResolutionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.root = Path(self.temp_dir.name)
        self.previous_cwd = Path.cwd()
        os.chdir(self.root)
        self.run_dir = self.root / "outputs" / "synthetic_run"
        self.audit_dir = self.run_dir / "audit"
        self.audit_dir.mkdir(parents=True)
        (self.audit_dir / "run_metadata.json").write_text(
            json.dumps({"run_id": "synthetic_run", "status": "initialized"}),
            encoding="utf-8",
        )
        self.video_path = self.root / "source.mp4"
        self.video_path.write_bytes(b"synthetic video placeholder")
        self.config = {
            "video_url": "https://example.com/public-lecture-video",
            "run_id": "synthetic_run",
            "output_dir": str(self.root / "outputs"),
        }

    def tearDown(self) -> None:
        os.chdir(self.previous_cwd)
        self.temp_dir.cleanup()

    def _info(self, width: int, height: int) -> dict:
        return {
            "id": "synthetic-video",
            "title": "Synthetic lecture",
            "duration": 120,
            "ext": "mp4",
            "extractor": "synthetic",
            "extractor_key": "Synthetic",
            "webpage_url": self.config["video_url"],
            "requested_downloads": [{"filepath": str(self.video_path)}],
            "requested_formats": [
                {
                    "format_id": f"video-{height}",
                    "format_note": f"{height}p",
                    "width": width,
                    "height": height,
                    "ext": "mp4",
                    "vcodec": "h264",
                },
                {
                    "format_id": "audio",
                    "ext": "m4a",
                    "vcodec": "none",
                    "acodec": "aac",
                },
            ],
            "acodec": "aac",
        }

    def _fake_youtube_dl(
        self,
        *,
        info: dict | None = None,
        error: Exception | None = None,
        warnings: list[str] | None = None,
    ) -> type:
        class FakeYoutubeDL:
            last_options: dict | None = None

            def __init__(self, options: dict) -> None:
                type(self).last_options = options
                self.options = options

            def __enter__(self) -> "FakeYoutubeDL":
                return self

            def __exit__(self, *args: object) -> None:
                return None

            def extract_info(self, url: str, download: bool) -> dict:
                for warning in warnings or []:
                    self.options["logger"].warning(warning)
                if error is not None:
                    raise error
                assert info is not None
                return info

        return FakeYoutubeDL

    def _download(
        self,
        *,
        width: int = 1920,
        height: int = 1080,
        config: dict | None = None,
        error: Exception | None = None,
        warnings: list[str] | None = None,
    ) -> tuple[dict, dict | None, type]:
        info = None if error is not None else self._info(width, height)
        fake_youtube_dl = self._fake_youtube_dl(
            info=info,
            error=error,
            warnings=warnings,
        )
        probe = {
            "available": True,
            "width": width,
            "height": height,
            "vcodec": "h264",
            "acodec": "aac",
            "warning": None,
        }
        with (
            mock.patch("src.run_pipeline.import_yt_dlp", return_value=fake_youtube_dl),
            mock.patch("src.run_pipeline.probe_video_metadata", return_value=probe),
        ):
            report, video_info = run_pipeline.download_video(
                config or self.config,
                self.run_dir,
            )
        return report, video_info, fake_youtube_dl

    def test_default_selector_prefers_1080p_or_higher_then_best_available(self) -> None:
        options = run_pipeline.resolve_download_options(self.config)

        self.assertEqual(options["preferred_video_height"], 1080)
        self.assertTrue(options["allow_video_resolution_fallback"])
        self.assertEqual(options["resolution_fallback_strategy"], "best_available")
        self.assertTrue(
            options["effective_format_selector"].startswith(
                "bestvideo[height>=1080]+bestaudio/"
            )
        )
        self.assertIn("bestvideo[height>=1080]", options["effective_format_selector"])
        self.assertTrue(
            options["effective_format_selector"].endswith("/bestvideo+bestaudio/best")
        )

    def test_1080p_available_is_success_without_quality_warning(self) -> None:
        report, video_info, _ = self._download(width=1920, height=1080)

        self.assertIsNotNone(video_info)
        self.assertEqual(report["status"], "success")
        self.assertEqual(report["acquisition_status"], "success")
        self.assertFalse(report["resolution_fallback_used"])
        self.assertIsNone(report["resolution_warning"])
        self.assertEqual(report["actual_video_height"], 1080)
        self.assertEqual(report["downloaded_height"], 1080)
        self.assertEqual(report["selected_format_id"], "video-1080+audio")
        self.assertEqual(report["downloaded_format_id"], "video-1080+audio")

    def test_720p_uses_best_available_fallback_and_updates_metadata(self) -> None:
        report, video_info, _ = self._download(width=1280, height=720)

        self.assertIsNotNone(video_info)
        self.assertEqual(report["status"], "success")
        self.assertEqual(report["acquisition_status"], "degraded")
        self.assertTrue(report["resolution_fallback_used"])
        self.assertIn("best-available fallback", report["resolution_warning"])
        metadata = json.loads(
            (self.audit_dir / "run_metadata.json").read_text(encoding="utf-8")
        )
        self.assertEqual(metadata["acquisition"]["actual_video_height"], 720)
        self.assertTrue(metadata["acquisition"]["resolution_fallback_used"])

    def test_480p_continues_with_explicit_low_resolution_warning(self) -> None:
        report, video_info, _ = self._download(width=854, height=480)

        self.assertIsNotNone(video_info)
        self.assertEqual(report["status"], "success")
        self.assertEqual(report["acquisition_status"], "degraded")
        self.assertTrue(report["resolution_fallback_used"])
        self.assertIn("below preferred_video_height", report["resolution_warning"])
        self.assertEqual(report["actual_video_width"], 854)
        self.assertEqual(report["actual_video_height"], 480)

    def test_no_downloadable_format_is_distinct_failure(self) -> None:
        report, video_info, _ = self._download(
            error=RuntimeError("Requested format is not available"),
        )

        self.assertIsNone(video_info)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["acquisition_status"], "failed")
        self.assertEqual(report["error"]["type"], "NoDownloadableVideoFormat")
        self.assertNotEqual(report["error"]["type"], "TargetResolutionUnavailable")

    def test_explicit_strict_mode_preserves_target_resolution_failure(self) -> None:
        strict_config = {
            **self.config,
            "min_video_height": 1080,
            "allow_video_resolution_fallback": False,
        }
        report, video_info, _ = self._download(
            config=strict_config,
            error=RuntimeError("Requested format is not available"),
        )

        self.assertIsNone(video_info)
        self.assertEqual(report["status"], "failed")
        self.assertEqual(report["error"]["type"], "TargetResolutionUnavailable")
        self.assertIn("fallback is disabled", report["error"]["message"])

    def test_javascript_runtime_warning_is_recorded_without_blocking_download(self) -> None:
        warning = (
            "No supported JavaScript runtime could be found. "
            "Format extraction may be incomplete."
        )
        report, video_info, _ = self._download(
            width=1280,
            height=720,
            warnings=[warning],
        )

        self.assertIsNotNone(video_info)
        self.assertEqual(report["status"], "success")
        self.assertEqual(report["environment_warnings"], [warning])
        self.assertIn(warning, report["warnings"])

    def test_no_format_report_keeps_javascript_environment_uncertainty(self) -> None:
        warning = "No supported JavaScript runtime could be found."
        report, video_info, _ = self._download(
            error=RuntimeError("Requested format is not available"),
            warnings=[warning],
        )

        self.assertIsNone(video_info)
        self.assertEqual(report["error"]["type"], "NoDownloadableVideoFormat")
        self.assertEqual(report["environment_warnings"], [warning])
        self.assertIn("environment warnings", report["error"]["message"])

    def test_legacy_target_video_height_remains_supported(self) -> None:
        options = run_pipeline.resolve_download_options(
            {
                **self.config,
                "target_video_height": 720,
            }
        )

        self.assertEqual(options["preferred_video_height"], 720)
        self.assertEqual(options["target_video_height"], 720)


if __name__ == "__main__":
    unittest.main()
