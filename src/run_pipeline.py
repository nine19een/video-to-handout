from __future__ import annotations

import argparse
import ast
import html
import json
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUIRED_CONFIG_FIELDS = ("video_url", "run_id", "output_dir")
DEFAULT_SUBTITLE_LANGUAGES = ("en", "zh-Hans", "zh", "zh-CN")
DEFAULT_OUTPUT_LANGUAGE = "zh-CN"
DEFAULT_PREFERRED_VIDEO_HEIGHT = 1080
DEFAULT_TARGET_VIDEO_HEIGHT = DEFAULT_PREFERRED_VIDEO_HEIGHT
DEFAULT_MIN_VIDEO_HEIGHT = 1080
DEFAULT_ALLOW_VIDEO_RESOLUTION_FALLBACK = True
DEFAULT_RESOLUTION_FALLBACK_STRATEGY = "best_available"
DEFAULT_MIN_KEYFRAME_HEIGHT = 1080
DEFAULT_TRANSCRIPTION_BACKEND = "faster-whisper"
DEFAULT_TRANSCRIPTION_MODEL = "base"
DEFAULT_TRANSCRIPTION_DEVICE = "cpu"
DEFAULT_TRANSCRIPTION_COMPUTE_TYPE = "int8"
DEFAULT_FRAME_INTERVAL_SECONDS = 10.0
DEFAULT_MAX_KEYFRAMES = 30
DEFAULT_MIN_VISUAL_DIFFERENCE_SCORE = 0.12
DEFAULT_MIN_STABLE_DURATION_SECONDS = 20.0
DEFAULT_MIN_FRAME_VARIANCE = 2.0
DEFAULT_MIN_SHARPNESS_SCORE = 1.5
DEFAULT_DARK_FRAME_MEAN_THRESHOLD = 5.0
DEFAULT_BRIGHT_FRAME_MEAN_THRESHOLD = 250.0
DEFAULT_SOLID_FRAME_VARIANCE_THRESHOLD = 2.0
DEFAULT_DUPLICATE_SIMILARITY_THRESHOLD = 0.92
DEFAULT_DUPLICATE_HASH_DISTANCE_THRESHOLD = 0.08
DEFAULT_COMPARISON_REGION_MODE = "full_frame"
DEFAULT_COMPARISON_CENTER_CROP_PERCENT = 1.0
DEFAULT_OCR_BACKEND = "none"
DEFAULT_OCR_MAX_CHARS = 500
DEFAULT_OCR_MIN_TEXT_LENGTH = 4
DEFAULT_ANIMATION_COLLAPSE_ENABLED = True
DEFAULT_COLLAPSE_WINDOW_SECONDS = 90.0
DEFAULT_BUILD_GROUP_MAX_GAP_SECONDS = 40.0
DEFAULT_MAX_INTERMEDIATE_KEYFRAMES_PER_GROUP = 1
DEFAULT_BUILD_GROUP_SIMILARITY_THRESHOLD = 0.45
DEFAULT_BUILD_GROUP_HASH_DISTANCE_THRESHOLD = 0.35
DEFAULT_MIN_SCENE_CHANGE_SCORE = 0.55
DEFAULT_FINAL_STATE_PREFERENCE = "fuller_final_state"
DEFAULT_COLLAPSE_REPORT_ENABLED = True
DEFAULT_FULLER_STATE_SCORING_ENABLED = True
DEFAULT_FULLER_STATE_WEIGHT = 1.0
DEFAULT_TIME_PREFERENCE_WEIGHT = 0.08
DEFAULT_CONTENT_AREA_WEIGHT = 0.45
DEFAULT_DETAIL_DENSITY_WEIGHT = 0.25
DEFAULT_LAYOUT_RICHNESS_WEIGHT = 0.30
DEFAULT_CONSERVATIVE_GROUP_MERGE_ENABLED = True
DEFAULT_GROUP_MERGE_MAX_GAP_SECONDS = 150.0
DEFAULT_GROUP_MERGE_MIN_CONTINUITY_SCORE = 0.72
DEFAULT_TITLE_REGION_MAX_DIFFERENCE = 0.14
DEFAULT_FULLER_REPLACEMENT_MIN_DELTA = 0.01
DEFAULT_REPORT_GROUP_DECISIONS_LIMIT = 200
DEFAULT_FINAL_STATE_TRACE_ENABLED = True
DEFAULT_FINAL_STATE_TRACE_REPORT_LIMIT = 50
DEFAULT_LOW_CONTENT_LOOKAHEAD_ENABLED = True
DEFAULT_LOW_CONTENT_LOOKAHEAD_SECONDS = 180.0
DEFAULT_LOW_CONTENT_CONTENT_AREA_THRESHOLD = 0.12
DEFAULT_LOW_CONTENT_DETAIL_DENSITY_THRESHOLD = 0.10
DEFAULT_LOW_CONTENT_LAYOUT_RICHNESS_THRESHOLD = 0.30
DEFAULT_LOW_CONTENT_TITLE_REGION_MAX_DIFFERENCE = 0.22
DEFAULT_LOW_CONTENT_SLIDE_REGION_MAX_DIFFERENCE = 0.70
DEFAULT_TITLE_ONLY_PENALTY_ENABLED = True
DEFAULT_TITLE_SLIDE_KEEP_POLICY = "keep_if_no_fuller_same_context"
DEFAULT_GROUP_FULLNESS_RESET_MIN_DELTA = 0.18
DEFAULT_STRONG_TITLE_REGION_MAX_DIFFERENCE = 0.08
DEFAULT_STRONG_TITLE_GROUP_MERGE_MAX_GAP_SECONDS = 300.0
DEFAULT_STRONG_TITLE_BUILD_GROUP_HASH_DISTANCE_THRESHOLD = 0.45
DEFAULT_ADAPTIVE_RESCAN_ENABLED = False
DEFAULT_ADAPTIVE_RESCAN_INTERVAL_SECONDS = 2.0
DEFAULT_ADAPTIVE_RESCAN_WINDOW_SECONDS = 90.0
MAX_COLLAPSE_GROUP_SUMMARIES = 25
SUBTITLE_SUFFIXES = {".vtt", ".srt"}
VISUAL_EXTRACTION_METHOD = "ffmpeg_interval_plus_pillow_difference_v1"
ALIGNMENT_METHOD = "transcript_visual_time_alignment_v1"
MIN_VISUAL_TRANSCRIPT_COVERAGE_RATIO = 0.8
NEAREST_VISUAL_MATCH_MAX_DISTANCE_SECONDS = 30.0


class FFmpegNotFound(RuntimeError):
    pass


class FFmpegPreflightFailed(RuntimeError):
    pass


class FrameExtractionFailed(RuntimeError):
    pass


class NoCandidateFrames(RuntimeError):
    pass


class PillowFrameReadFailed(RuntimeError):
    pass


class NoAcceptableKeyframes(RuntimeError):
    def __init__(
        self,
        message: str,
        quality_summary: dict[str, Any] | None = None,
        keyframe_selection: dict[str, Any] | None = None,
        comparison_region: dict[str, Any] | None = None,
        warnings: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.quality_summary = quality_summary
        self.keyframe_selection = keyframe_selection
        self.comparison_region = comparison_region
        self.warnings = warnings or []


class MissingRawTranscript(RuntimeError):
    pass


class MissingVisualSegments(RuntimeError):
    pass


class MissingFrameReport(RuntimeError):
    pass


class VisualEvidenceIsSmoke(RuntimeError):
    pass


class VisualCoverageTooShort(RuntimeError):
    pass


class InvalidTranscriptSegment(RuntimeError):
    pass


class InvalidVisualSegment(RuntimeError):
    pass


class MissingKeyframeFile(RuntimeError):
    pass


class InvalidTimeline(RuntimeError):
    pass


class DownloadedVideoResolutionUnknown(RuntimeError):
    pass


class TargetResolutionUnavailable(RuntimeError):
    pass


class NoDownloadableVideoFormat(RuntimeError):
    pass


class DownloadedVideoBelowMinimumResolution(RuntimeError):
    pass


class KeyframeResolutionBelowMinimum(RuntimeError):
    pass


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_scalar(value: str) -> Any:
    stripped = value.strip()
    if not stripped:
        return ""
    if stripped.lower() in {"null", "none", "~"}:
        return None
    if stripped.lower() in {"true", "false"}:
        return stripped.lower() == "true"
    if stripped[0] in {"'", '"', "["}:
        try:
            parsed = ast.literal_eval(stripped)
        except (SyntaxError, ValueError):
            return stripped.strip("'\"")
        return parsed
    return stripped


def load_config(config_path: Path) -> dict[str, Any]:
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    config = {}
    with config_path.open("r", encoding="utf-8") as file:
        for line_number, line in enumerate(file, start=1):
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            if ":" not in stripped:
                raise ValueError(f"Invalid config line {line_number}: {line.rstrip()}")
            key, value = stripped.split(":", 1)
            key = key.strip().lstrip("\ufeff")
            if not key:
                raise ValueError(f"Invalid empty config key on line {line_number}.")
            config[key] = parse_scalar(value)

    missing_fields = [
        field
        for field in REQUIRED_CONFIG_FIELDS
        if config.get(field) is None or not str(config.get(field, "")).strip()
    ]
    if missing_fields:
        joined = ", ".join(missing_fields)
        raise ValueError(f"Missing required config field(s): {joined}")

    return config


def normalize_string_list(value: Any, default: tuple[str, ...]) -> list[str]:
    if value is None or value == "":
        return list(default)
    if isinstance(value, list):
        items = value
    else:
        items = str(value).split(",")
    normalized = [str(item).strip() for item in items if str(item).strip()]
    return normalized or list(default)


def validate_run_id(run_id: str) -> str:
    normalized = run_id.strip()
    if normalized in {"", ".", ".."}:
        raise ValueError("run_id must be a non-empty directory name.")
    if any(separator in normalized for separator in ("/", "\\")):
        raise ValueError("run_id must not contain path separators.")
    return normalized


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)
        file.write("\n")


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise ValueError(f"Expected JSON object in {path}.")
    return payload


def initialize_run(config_path: Path) -> tuple[dict[str, Any], Path]:
    resolved_config_path = config_path.resolve()
    config = load_config(resolved_config_path)

    run_id = validate_run_id(str(config["run_id"]))
    video_url = str(config["video_url"]).strip()
    output_dir = Path(str(config["output_dir"]).strip())
    output_language = str(config.get("output_language", DEFAULT_OUTPUT_LANGUAGE)).strip()
    if not output_language:
        output_language = DEFAULT_OUTPUT_LANGUAGE

    run_dir = output_dir / run_id
    keyframes_dir = run_dir / "assets" / "keyframes"
    audit_dir = run_dir / "audit"

    keyframes_dir.mkdir(parents=True, exist_ok=True)
    audit_dir.mkdir(parents=True, exist_ok=True)

    metadata = {
        "run_id": run_id,
        "video_url": video_url,
        "output_dir": str(output_dir),
        "output_language": output_language,
        "config_path": str(resolved_config_path),
        "created_at": utc_now(),
        "status": "initialized",
    }

    write_json(audit_dir / "run_metadata.json", metadata)

    return config, run_dir


def error_payload(error: BaseException) -> dict[str, str]:
    return {
        "type": error.__class__.__name__,
        "message": str(error),
    }


def import_yt_dlp() -> Any:
    try:
        from yt_dlp import YoutubeDL
    except ImportError as error:
        raise RuntimeError(
            "yt-dlp is not installed. Install dependencies with: pip install -r requirements.txt"
        ) from error
    return YoutubeDL


def find_executable(name: str) -> str | None:
    found = shutil.which(name) or shutil.which(f"{name}.exe")
    if found is not None:
        return found
    where_path = shutil.which("where.exe")
    if where_path is None:
        return None
    try:
        result = subprocess.run(
            [where_path, name],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except Exception:
        return None
    if result.returncode != 0:
        return None
    for line in result.stdout.splitlines():
        candidate = line.strip()
        if candidate:
            return candidate
    return None


def bool_or_default(value: Any, default: bool) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    normalized = str(value).strip().lower()
    if normalized in {"true", "1", "yes", "y", "on"}:
        return True
    if normalized in {"false", "0", "no", "n", "off"}:
        return False
    raise ValueError(f"Expected boolean value, got: {value!r}")


def configured_preferred_video_height(config: dict[str, Any]) -> int:
    preferred = config.get("preferred_video_height")
    if preferred is not None and preferred != "":
        return positive_int_or_default(
            preferred,
            DEFAULT_PREFERRED_VIDEO_HEIGHT,
            "preferred_video_height",
        )
    return positive_int_or_default(
        config.get("target_video_height"),
        DEFAULT_PREFERRED_VIDEO_HEIGHT,
        "target_video_height",
    )


def resolve_download_options(config: dict[str, Any]) -> dict[str, Any]:
    preferred_height = configured_preferred_video_height(config)
    min_height = positive_int_or_default(
        config.get("min_video_height"),
        DEFAULT_MIN_VIDEO_HEIGHT,
        "min_video_height",
    )
    override = optional_string(config.get("yt_dlp_format"))
    allow_fallback = bool_or_default(
        config.get("allow_video_resolution_fallback"),
        DEFAULT_ALLOW_VIDEO_RESOLUTION_FALLBACK,
    )
    fallback_strategy = string_or_default(
        config.get("resolution_fallback_strategy"),
        DEFAULT_RESOLUTION_FALLBACK_STRATEGY,
    ).lower()
    if fallback_strategy != DEFAULT_RESOLUTION_FALLBACK_STRATEGY:
        raise ValueError(
            "resolution_fallback_strategy must be best_available."
        )
    if override is not None:
        selector = override
    else:
        selector = (
            f"bestvideo[height>={preferred_height}]+bestaudio/"
            f"bestvideo[height>={preferred_height}][ext=mp4]+"
            "bestaudio[ext=m4a]/"
            f"best[height>={preferred_height}]"
        )
        if allow_fallback:
            selector = f"{selector}/bestvideo+bestaudio/best"
        else:
            selector = (
                f"{selector}/"
                f"bestvideo[height>={min_height}]+bestaudio/"
                f"bestvideo[height>={min_height}][ext=mp4]+bestaudio[ext=m4a]/"
                f"best[height>={min_height}]"
            )
    return {
        "preferred_video_height": preferred_height,
        "target_video_height": preferred_height,
        "min_video_height": min_height,
        "allow_video_resolution_fallback": allow_fallback,
        "resolution_fallback_strategy": fallback_strategy,
        "yt_dlp_format": override,
        "effective_format_selector": selector,
    }


class YtDlpWarningCollector:
    def __init__(self) -> None:
        self.warnings: list[str] = []

    def debug(self, message: str) -> None:
        pass

    def info(self, message: str) -> None:
        pass

    def warning(self, message: str) -> None:
        self.warnings.append(str(message).strip())

    def error(self, message: str) -> None:
        pass


def environment_warnings_from(messages: list[str]) -> list[str]:
    environment_markers = (
        "javascript runtime",
        "js runtime",
    )
    return sorted(
        {
            message
            for message in messages
            if any(marker in message.lower() for marker in environment_markers)
        }
    )


def update_run_metadata_acquisition(run_dir: Path, report: dict[str, Any]) -> None:
    metadata_path = run_dir / "audit" / "run_metadata.json"
    metadata = read_json(metadata_path) if metadata_path.exists() else {}
    metadata["acquisition"] = {
        "status": report.get("acquisition_status"),
        "requested_preferred_height": report.get("requested_preferred_height"),
        "actual_video_width": report.get("actual_video_width"),
        "actual_video_height": report.get("actual_video_height"),
        "actual_video_resolution": report.get("downloaded_resolution"),
        "resolution_fallback_used": report.get("resolution_fallback_used"),
        "resolution_warning": report.get("resolution_warning"),
        "environment_warnings": report.get("environment_warnings") or [],
    }
    write_json(metadata_path, metadata)


def write_download_report(
    report_path: Path,
    run_dir: Path,
    report: dict[str, Any],
) -> None:
    write_json(report_path, report)
    update_run_metadata_acquisition(run_dir, report)


def first_requested_video_format(info: dict[str, Any]) -> dict[str, Any]:
    requested_formats = info.get("requested_formats")
    if isinstance(requested_formats, list):
        for item in requested_formats:
            if isinstance(item, dict) and item.get("vcodec") not in {None, "none"}:
                return item
    return info


def requested_format_id(info: dict[str, Any]) -> str | None:
    requested_formats = info.get("requested_formats")
    if isinstance(requested_formats, list) and requested_formats:
        ids = [
            str(item.get("format_id"))
            for item in requested_formats
            if isinstance(item, dict) and item.get("format_id") is not None
        ]
        return "+".join(ids) if ids else None
    value = info.get("format_id")
    return str(value) if value is not None else None


def probe_video_metadata(video_path: Path) -> dict[str, Any]:
    ffprobe_path = find_executable("ffprobe")
    if ffprobe_path is None:
        return probe_video_metadata_with_ffmpeg(video_path)

    command = [
        ffprobe_path,
        "-v",
        "error",
        "-show_entries",
        "stream=codec_type,codec_name,width,height",
        "-of",
        "json",
        str(video_path),
    ]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as error:
        return {
            "available": True,
            "width": None,
            "height": None,
            "vcodec": None,
            "acodec": None,
            "warning": f"ffprobe failed: {error}",
        }
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "ffprobe failed.").strip()
        return {
            "available": True,
            "width": None,
            "height": None,
            "vcodec": None,
            "acodec": None,
            "warning": message,
        }
    try:
        payload = json.loads(result.stdout or "{}")
    except json.JSONDecodeError as error:
        return {
            "available": True,
            "width": None,
            "height": None,
            "vcodec": None,
            "acodec": None,
            "warning": f"ffprobe returned invalid JSON: {error}",
        }

    video_stream = None
    audio_stream = None
    for stream in payload.get("streams") or []:
        if not isinstance(stream, dict):
            continue
        if stream.get("codec_type") == "video" and video_stream is None:
            video_stream = stream
        if stream.get("codec_type") == "audio" and audio_stream is None:
            audio_stream = stream

    return {
        "available": True,
        "width": video_stream.get("width") if video_stream else None,
        "height": video_stream.get("height") if video_stream else None,
        "vcodec": video_stream.get("codec_name") if video_stream else None,
        "acodec": audio_stream.get("codec_name") if audio_stream else None,
        "warning": None if video_stream else "ffprobe found no video stream.",
    }


def probe_video_metadata_with_ffmpeg(video_path: Path) -> dict[str, Any]:
    ffmpeg_path = find_executable("ffmpeg")
    if ffmpeg_path is None:
        return {
            "available": False,
            "width": None,
            "height": None,
            "vcodec": None,
            "acodec": None,
            "warning": "Neither ffprobe nor ffmpeg was found on PATH.",
        }
    try:
        result = subprocess.run(
            [ffmpeg_path, "-hide_banner", "-i", str(video_path)],
            capture_output=True,
            text=True,
            timeout=30,
        )
    except Exception as error:
        return {
            "available": True,
            "width": None,
            "height": None,
            "vcodec": None,
            "acodec": None,
            "warning": f"ffmpeg metadata probe failed: {error}",
        }

    text = "\n".join(part for part in (result.stderr, result.stdout) if part)
    video_line = next(
        (line.strip() for line in text.splitlines() if " Video: " in line),
        "",
    )
    audio_line = next(
        (line.strip() for line in text.splitlines() if " Audio: " in line),
        "",
    )
    resolution_match = re.search(r"(?<![A-Za-z0-9])(\d{2,5})x(\d{2,5})(?![A-Za-z0-9])", video_line)
    codec_match = re.search(r"Video:\s*([^,\s]+)", video_line)
    audio_match = re.search(r"Audio:\s*([^,\s]+)", audio_line)
    if resolution_match is None:
        return {
            "available": True,
            "width": None,
            "height": None,
            "vcodec": codec_match.group(1) if codec_match else None,
            "acodec": audio_match.group(1) if audio_match else None,
            "warning": "ffmpeg fallback found no video resolution.",
        }
    return {
        "available": True,
        "width": int(resolution_match.group(1)),
        "height": int(resolution_match.group(2)),
        "vcodec": codec_match.group(1) if codec_match else None,
        "acodec": audio_match.group(1) if audio_match else None,
        "warning": "ffprobe was not found; used ffmpeg metadata fallback.",
    }


def resolution_text(width: Any, height: Any) -> str | None:
    if width is None or height is None:
        return None
    return f"{width}x{height}"


def resolution_check(
    actual_height: int | None,
    preferred_height: int,
    min_height: int,
    allow_fallback: bool,
) -> dict[str, Any]:
    if actual_height is None:
        return {
            "status": "unknown",
            "message": "Downloaded video height could not be determined.",
            "target_height": preferred_height,
            "preferred_height": preferred_height,
            "min_height": min_height,
            "actual_height": None,
        }
    if actual_height >= preferred_height:
        return {
            "status": "success",
            "message": "Downloaded video height meets the preferred quality target.",
            "target_height": preferred_height,
            "preferred_height": preferred_height,
            "min_height": min_height,
            "actual_height": actual_height,
        }
    if actual_height >= min_height:
        return {
            "status": "degraded",
            "message": (
                "Downloaded video is below preferred_video_height but meets "
                "min_video_height. Visual evidence quality requires human review."
            ),
            "target_height": preferred_height,
            "preferred_height": preferred_height,
            "min_height": min_height,
            "actual_height": actual_height,
        }
    return {
        "status": "degraded" if allow_fallback else "failed",
        "message": (
            "Downloaded video is below preferred_video_height and min_video_height; "
            "best-available fallback was accepted. Low-resolution visual evidence "
            "quality requires human review."
            if allow_fallback
            else "Downloaded video is below min_video_height and fallback is disabled."
        ),
        "target_height": preferred_height,
        "preferred_height": preferred_height,
        "min_height": min_height,
        "actual_height": actual_height,
    }


def find_downloaded_video(info: dict[str, Any], video_dir: Path) -> Path | None:
    for item in info.get("requested_downloads") or []:
        raw_path = item.get("filepath") or item.get("_filename")
        if raw_path:
            path = Path(raw_path)
            if path.exists():
                return path

    filename = info.get("_filename")
    if filename:
        path = Path(filename)
        if path.exists():
            return path

    candidates = [
        path
        for path in video_dir.iterdir()
        if path.is_file()
        and path.suffix.lower() not in SUBTITLE_SUFFIXES
        and not path.name.endswith((".part", ".ytdl"))
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def download_video(config: dict[str, Any], run_dir: Path) -> tuple[dict[str, Any], dict[str, Any] | None]:
    run_id = validate_run_id(str(config["run_id"]))
    video_url = str(config["video_url"]).strip()
    audit_dir = run_dir / "audit"
    video_dir = Path("data") / "raw" / "videos" / run_id
    video_dir.mkdir(parents=True, exist_ok=True)
    report_path = audit_dir / "download_report.json"
    download_options = resolve_download_options(config)
    ytdlp_logger = YtDlpWarningCollector()

    base_report: dict[str, Any] = {
        "run_id": run_id,
        "video_url": video_url,
        "status": "failed",
        "video_path": None,
        "video_id": None,
        "title": None,
        "duration_seconds": None,
        "ext": None,
        "extractor": None,
        "extractor_key": None,
        "webpage_url": None,
        "requested_format": download_options["yt_dlp_format"],
        "effective_format_selector": download_options["effective_format_selector"],
        "requested_preferred_height": download_options["preferred_video_height"],
        "target_video_height": download_options["target_video_height"],
        "min_video_height": download_options["min_video_height"],
        "allow_video_resolution_fallback": download_options[
            "allow_video_resolution_fallback"
        ],
        "resolution_fallback_strategy": download_options[
            "resolution_fallback_strategy"
        ],
        "acquisition_status": "failed",
        "resolution_fallback_used": False,
        "resolution_warning": None,
        "environment_warnings": [],
        "selected_format_id": None,
        "selected_format_note": None,
        "selected_ext": None,
        "selected_vcodec": None,
        "selected_acodec": None,
        "actual_video_width": None,
        "actual_video_height": None,
        "downloaded_format_id": None,
        "downloaded_ext": None,
        "downloaded_width": None,
        "downloaded_height": None,
        "downloaded_resolution": None,
        "downloaded_vcodec": None,
        "downloaded_acodec": None,
        "downloaded_filesize": None,
        "downloaded_filesize_approx": None,
        "resolution_check": {
            "status": "unknown",
            "message": "Download has not completed.",
            "target_height": download_options["target_video_height"],
            "preferred_height": download_options["preferred_video_height"],
            "min_height": download_options["min_video_height"],
            "actual_height": None,
        },
        "warnings": [],
        "error": None,
        "created_at": utc_now(),
    }

    try:
        YoutubeDL = import_yt_dlp()
        ydl_opts = {
            "format": download_options["effective_format_selector"],
            "outtmpl": str(video_dir / "%(id)s.%(ext)s"),
            "noplaylist": True,
            "quiet": False,
            "no_warnings": False,
            "logger": ytdlp_logger,
            "hls_prefer_native": True,
            "nopart": False,
            "merge_output_format": "mp4",
        }
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
    except Exception as error:
        message = str(error)
        warnings = sorted(set([*ytdlp_logger.warnings, message]))
        environment_warnings = environment_warnings_from(warnings)
        base_report["warnings"] = warnings
        base_report["environment_warnings"] = environment_warnings
        if "format" in message.lower() and "available" in message.lower():
            if download_options["allow_video_resolution_fallback"]:
                acquisition_error: RuntimeError = NoDownloadableVideoFormat(
                    "yt-dlp could not find any downloadable video format. "
                    "Format extraction may be incomplete when environment warnings are present."
                )
            else:
                acquisition_error = TargetResolutionUnavailable(
                    "No downloadable format met min_video_height while resolution "
                    "fallback is disabled."
                )
            base_report["error"] = error_payload(acquisition_error)
            base_report["resolution_check"] = {
                "status": "failed",
                "message": str(acquisition_error),
                "target_height": download_options["target_video_height"],
                "preferred_height": download_options["preferred_video_height"],
                "min_height": download_options["min_video_height"],
                "actual_height": None,
            }
        else:
            base_report["error"] = error_payload(error)
        write_download_report(report_path, run_dir, base_report)
        return base_report, None

    video_path = find_downloaded_video(info, video_dir)
    if video_path is None:
        base_report["error"] = {
            "type": "MissingDownloadedFile",
            "message": "yt-dlp completed but no downloaded video file was found.",
        }
        write_download_report(report_path, run_dir, base_report)
        return base_report, info

    video_format = first_requested_video_format(info)
    probe = probe_video_metadata(video_path)
    warnings = list(ytdlp_logger.warnings)
    if probe.get("warning"):
        warnings.append(str(probe["warning"]))
    probed_width = probe.get("width")
    probed_height = probe.get("height")
    info_width = video_format.get("width") or info.get("width")
    info_height = video_format.get("height") or info.get("height")
    downloaded_width = probed_width if probed_width is not None else info_width
    downloaded_height = probed_height if probed_height is not None else info_height
    try:
        actual_height = int(downloaded_height) if downloaded_height is not None else None
    except (TypeError, ValueError):
        actual_height = None
        warnings.append(f"Downloaded height was not numeric: {downloaded_height!r}")
    check = resolution_check(
        actual_height=actual_height,
        preferred_height=int(download_options["preferred_video_height"]),
        min_height=int(download_options["min_video_height"]),
        allow_fallback=bool(download_options["allow_video_resolution_fallback"]),
    )
    filesize = video_path.stat().st_size if video_path.exists() else None
    approx_filesize = (
        video_format.get("filesize_approx")
        or video_format.get("filesize")
        or info.get("filesize_approx")
        or info.get("filesize")
    )
    report = {
        **base_report,
        "status": "success",
        "acquisition_status": "degraded" if check["status"] == "degraded" else "success",
        "video_path": str(video_path),
        "video_id": info.get("id"),
        "title": info.get("title"),
        "duration_seconds": info.get("duration"),
        "ext": video_path.suffix.lstrip(".") or info.get("ext"),
        "extractor": info.get("extractor"),
        "extractor_key": info.get("extractor_key"),
        "webpage_url": info.get("webpage_url") or video_url,
        "resolution_fallback_used": (
            check["status"] == "degraded"
            and bool(download_options["allow_video_resolution_fallback"])
        ),
        "resolution_warning": check["message"] if check["status"] != "success" else None,
        "environment_warnings": environment_warnings_from(warnings),
        "selected_format_id": requested_format_id(info),
        "selected_format_note": video_format.get("format_note") or info.get("format_note"),
        "selected_ext": video_path.suffix.lstrip(".") or info.get("ext"),
        "selected_vcodec": probe.get("vcodec") or video_format.get("vcodec"),
        "selected_acodec": probe.get("acodec") or info.get("acodec"),
        "actual_video_width": downloaded_width,
        "actual_video_height": downloaded_height,
        "downloaded_format_id": requested_format_id(info),
        "downloaded_ext": video_path.suffix.lstrip(".") or info.get("ext"),
        "downloaded_width": downloaded_width,
        "downloaded_height": downloaded_height,
        "downloaded_resolution": resolution_text(downloaded_width, downloaded_height),
        "downloaded_vcodec": probe.get("vcodec") or video_format.get("vcodec"),
        "downloaded_acodec": probe.get("acodec") or info.get("acodec"),
        "downloaded_filesize": filesize,
        "downloaded_filesize_approx": approx_filesize,
        "resolution_check": check,
        "warnings": sorted(set(warnings)),
        "error": None,
        "created_at": utc_now(),
    }
    if check["status"] == "unknown":
        error = DownloadedVideoResolutionUnknown(check["message"])
        report["status"] = "failed"
        report["acquisition_status"] = "failed"
        report["resolution_warning"] = check["message"]
        report["error"] = error_payload(error)
    elif check["status"] == "failed":
        error = DownloadedVideoBelowMinimumResolution(check["message"])
        report["status"] = "failed"
        report["acquisition_status"] = "failed"
        report["resolution_warning"] = check["message"]
        report["error"] = error_payload(error)
    write_download_report(report_path, run_dir, report)
    return report, info


def available_languages(info: dict[str, Any], key: str) -> list[str]:
    value = info.get(key)
    if not isinstance(value, dict):
        return []
    return sorted(str(language) for language in value.keys())


def choose_subtitle(
    info: dict[str, Any], preferred_languages: list[str]
) -> tuple[str | None, str | None]:
    platform_languages = available_languages(info, "subtitles")
    automatic_languages = available_languages(info, "automatic_captions")

    for language in preferred_languages:
        if language in platform_languages:
            return language, "platform"
    for language in preferred_languages:
        match = find_prefix_compatible_language(language, platform_languages)
        if match is not None:
            return match, "platform"
    for language in preferred_languages:
        if language in automatic_languages:
            return language, "automatic"
    for language in preferred_languages:
        match = find_prefix_compatible_language(language, automatic_languages)
        if match is not None:
            return match, "automatic"
    return None, None


def find_prefix_compatible_language(
    preferred_language: str, available: list[str]
) -> str | None:
    prefix = f"{preferred_language}-"
    for language in available:
        if language.startswith(prefix):
            return language
    return None


def find_subtitle_file(subtitle_dir: Path, video_id: str, language: str) -> Path | None:
    candidates = [
        path
        for path in subtitle_dir.glob(f"{video_id}.{language}.*")
        if path.suffix.lower() in SUBTITLE_SUFFIXES
    ]
    if not candidates:
        candidates = [
            path
            for path in subtitle_dir.iterdir()
            if path.is_file()
            and path.suffix.lower() in SUBTITLE_SUFFIXES
            and f".{language}." in path.name
        ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def parse_timestamp(value: str) -> float:
    normalized = value.strip().replace(",", ".")
    parts = normalized.split(":")
    if len(parts) == 2:
        hours = 0
        minutes, seconds = parts
    elif len(parts) == 3:
        hours, minutes, seconds = parts
    else:
        raise ValueError(f"Invalid timestamp: {value}")
    return int(hours) * 3600 + int(minutes) * 60 + float(seconds)


def clean_subtitle_text(lines: list[str]) -> str:
    text = " ".join(line.strip() for line in lines if line.strip())
    text = re.sub(r"<\d{2}:\d{2}:\d{2}\.\d{3}>", "", text)
    text = re.sub(r"<\d{2}:\d{2}\.\d{3}>", "", text)
    text = re.sub(r"<[^>]+>", "", text)
    text = re.sub(r"\s+", " ", text)
    return html.unescape(text).strip()


def is_text_contained(inner: str, outer: str) -> bool:
    normalized_inner = re.sub(r"\s+", " ", inner).strip().lower()
    normalized_outer = re.sub(r"\s+", " ", outer).strip().lower()
    return bool(normalized_inner) and normalized_inner in normalized_outer


def clean_rolling_caption_lines(lines: list[str], previous_text: str) -> str:
    cleaned_lines = []
    for line in lines:
        cleaned = clean_subtitle_text([line])
        if not cleaned:
            continue
        if previous_text and is_text_contained(cleaned, previous_text):
            continue
        cleaned_lines.append(cleaned)
    return clean_subtitle_text(cleaned_lines)


def remove_redundant_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []

    for index, segment in enumerate(segments):
        text = str(segment["text"])
        duration = float(segment["end"]) - float(segment["start"])
        previous_text = str(segments[index - 1]["text"]) if index > 0 else ""
        next_text = str(segments[index + 1]["text"]) if index + 1 < len(segments) else ""

        if duration <= 0.05 and (
            is_text_contained(text, previous_text) or is_text_contained(text, next_text)
        ):
            continue
        if is_text_contained(text, previous_text) or is_text_contained(text, next_text):
            continue

        if filtered and (
            is_text_contained(text, str(filtered[-1]["text"]))
            or is_text_contained(str(filtered[-1]["text"]), text)
        ):
            if len(text) > len(str(filtered[-1]["text"])):
                filtered[-1] = segment
            continue

        filtered.append(segment)

    return [
        {
            "id": index,
            "start": segment["start"],
            "end": segment["end"],
            "text": segment["text"],
        }
        for index, segment in enumerate(filtered, start=1)
    ]


def parse_subtitle_file(path: Path) -> list[dict[str, Any]]:
    content = path.read_text(encoding="utf-8-sig", errors="replace")
    lines = content.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    segments: list[dict[str, Any]] = []
    index = 0

    while index < len(lines):
        line = lines[index].strip()
        if "-->" not in line:
            index += 1
            continue

        timing = line
        start_raw, end_raw = [part.strip() for part in timing.split("-->", 1)]
        end_raw = end_raw.split()[0]

        text_lines = []
        index += 1
        while index < len(lines) and "-->" not in lines[index]:
            stripped = lines[index].strip()
            if stripped and not stripped.upper().startswith(("WEBVTT", "NOTE", "STYLE", "REGION")):
                text_lines.append(stripped)
            index += 1

        previous_text = str(segments[-1]["text"]) if segments else ""
        text = clean_rolling_caption_lines(text_lines, previous_text)
        if not text:
            continue

        segments.append(
            {
                "id": len(segments) + 1,
                "start": parse_timestamp(start_raw),
                "end": parse_timestamp(end_raw),
                "text": text,
            }
        )

    return remove_redundant_segments(segments)


def write_raw_transcript(
    run_dir: Path,
    run_id: str,
    selected_source: str,
    selected_language: str,
    subtitle_path: Path,
    segments: list[dict[str, Any]],
) -> None:
    source_type = (
        "automatic_subtitle" if selected_source == "automatic" else "platform_subtitle"
    )
    payload = {
        "run_id": run_id,
        "source": {
            "type": source_type,
            "language": selected_language,
            "subtitle_path": str(subtitle_path),
            "is_auto_generated": selected_source == "automatic",
        },
        "fallback_required": False,
        "fallback_reason": None,
        "segments": segments,
        "segment_count": len(segments),
        "created_at": utc_now(),
    }
    write_json(run_dir / "audit" / "raw_transcript.json", payload)


def remove_stale_raw_transcript(run_dir: Path) -> None:
    transcript_path = run_dir / "audit" / "raw_transcript.json"
    if transcript_path.exists():
        transcript_path.unlink()


def download_and_parse_subtitles(
    config: dict[str, Any],
    run_dir: Path,
    video_info: dict[str, Any],
) -> dict[str, Any]:
    run_id = validate_run_id(str(config["run_id"]))
    video_url = str(config["video_url"]).strip()
    preferred_languages = normalize_string_list(
        config.get("preferred_subtitle_languages"), DEFAULT_SUBTITLE_LANGUAGES
    )
    subtitle_dir = Path("data") / "raw" / "subtitles" / run_id
    subtitle_dir.mkdir(parents=True, exist_ok=True)
    report_path = run_dir / "audit" / "subtitle_report.json"

    base_report: dict[str, Any] = {
        "run_id": run_id,
        "status": "no_subtitle_available",
        "preferred_languages": preferred_languages,
        "selected_language": None,
        "selected_source": None,
        "subtitle_path": None,
        "available_platform_subtitles": available_languages(video_info, "subtitles"),
        "available_auto_subtitles": available_languages(video_info, "automatic_captions"),
        "segment_count": 0,
        "fallback_required": True,
        "fallback_reason": None,
        "error": None,
        "created_at": utc_now(),
    }

    selected_language, selected_source = choose_subtitle(video_info, preferred_languages)
    if selected_language is None or selected_source is None:
        base_report["fallback_reason"] = (
            "No platform or automatic subtitles matched preferred_subtitle_languages."
        )
        remove_stale_raw_transcript(run_dir)
        write_json(report_path, base_report)
        return base_report

    try:
        YoutubeDL = import_yt_dlp()
        ydl_opts = {
            "skip_download": True,
            "writesubtitles": selected_source == "platform",
            "writeautomaticsub": selected_source == "automatic",
            "subtitleslangs": [selected_language],
            "subtitlesformat": "vtt/srt",
            "outtmpl": str(subtitle_dir / "%(id)s.%(ext)s"),
            "noplaylist": True,
            "quiet": False,
            "no_warnings": False,
        }
        with YoutubeDL(ydl_opts) as ydl:
            subtitle_info = ydl.extract_info(video_url, download=True)
    except Exception as error:
        report = {
            **base_report,
            "status": "failed",
            "selected_language": selected_language,
            "selected_source": selected_source,
            "fallback_reason": "Subtitle download failed.",
            "error": error_payload(error),
            "created_at": utc_now(),
        }
        remove_stale_raw_transcript(run_dir)
        write_json(report_path, report)
        return report

    video_id = str(subtitle_info.get("id") or video_info.get("id") or "")
    subtitle_path = find_subtitle_file(subtitle_dir, video_id, selected_language)
    if subtitle_path is None:
        report = {
            **base_report,
            "status": "no_subtitle_downloaded",
            "selected_language": selected_language,
            "selected_source": selected_source,
            "fallback_reason": "yt-dlp reported subtitles but no subtitle file was downloaded.",
            "created_at": utc_now(),
        }
        remove_stale_raw_transcript(run_dir)
        write_json(report_path, report)
        return report

    try:
        segments = parse_subtitle_file(subtitle_path)
    except Exception as error:
        report = {
            **base_report,
            "status": "failed",
            "selected_language": selected_language,
            "selected_source": selected_source,
            "subtitle_path": str(subtitle_path),
            "fallback_reason": "Subtitle file could not be parsed.",
            "error": error_payload(error),
            "created_at": utc_now(),
        }
        remove_stale_raw_transcript(run_dir)
        write_json(report_path, report)
        return report

    if not segments:
        report = {
            **base_report,
            "status": "no_usable_subtitle_segments",
            "selected_language": selected_language,
            "selected_source": selected_source,
            "subtitle_path": str(subtitle_path),
            "fallback_reason": "Subtitle file contained no parseable timed text segments.",
            "created_at": utc_now(),
        }
        remove_stale_raw_transcript(run_dir)
        write_json(report_path, report)
        return report

    write_raw_transcript(
        run_dir,
        run_id,
        selected_source,
        selected_language,
        subtitle_path,
        segments,
    )
    report = {
        **base_report,
        "status": "success",
        "selected_language": selected_language,
        "selected_source": selected_source,
        "subtitle_path": str(subtitle_path),
        "segment_count": len(segments),
        "fallback_required": False,
        "fallback_reason": None,
        "error": None,
        "created_at": utc_now(),
    }
    write_json(report_path, report)
    return report


def optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def optional_positive_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    number = float(value)
    if number <= 0:
        raise ValueError("transcription_smoke_seconds must be greater than 0.")
    return number


def positive_float_or_default(value: Any, default: float, field_name: str) -> float:
    if value is None or value == "":
        return default
    number = float(value)
    if number <= 0:
        raise ValueError(f"{field_name} must be greater than 0.")
    return number


def optional_positive_float_for_field(value: Any, field_name: str) -> float | None:
    if value is None or value == "":
        return None
    number = float(value)
    if number <= 0:
        raise ValueError(f"{field_name} must be greater than 0.")
    return number


def nonnegative_float_or_default(value: Any, default: float, field_name: str) -> float:
    if value is None or value == "":
        return default
    number = float(value)
    if number < 0:
        raise ValueError(f"{field_name} must be greater than or equal to 0.")
    return number


def positive_int_or_default(value: Any, default: int, field_name: str) -> int:
    if value is None or value == "":
        return default
    number = int(value)
    if number <= 0:
        raise ValueError(f"{field_name} must be greater than 0.")
    return number


def optional_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    return float(value)


def string_or_default(value: Any, default: str) -> str:
    normalized = optional_string(value)
    return normalized if normalized is not None else default


def configured_run_dir(config: dict[str, Any]) -> Path:
    run_id = validate_run_id(str(config["run_id"]))
    output_dir = Path(str(config["output_dir"]).strip())
    return output_dir / run_id


def report_path_for_transcription(run_dir: Path, smoke_test: bool) -> Path:
    filename = "transcription_report.smoke.json" if smoke_test else "transcription_report.json"
    return run_dir / "audit" / filename


def transcript_path_for_transcription(run_dir: Path, smoke_test: bool) -> Path:
    filename = "raw_transcript.smoke.json" if smoke_test else "raw_transcript.json"
    return run_dir / "audit" / filename


def base_transcription_report(
    run_id: str,
    config: dict[str, Any],
    video_path: str | None,
    smoke_test: bool,
    smoke_seconds: float | None,
) -> dict[str, Any]:
    return {
        "run_id": run_id,
        "status": "failed",
        "video_path": video_path,
        "backend": str(
            config.get("transcription_backend") or DEFAULT_TRANSCRIPTION_BACKEND
        ).strip(),
        "model": str(
            config.get("transcription_model") or DEFAULT_TRANSCRIPTION_MODEL
        ).strip(),
        "device": str(
            config.get("transcription_device") or DEFAULT_TRANSCRIPTION_DEVICE
        ).strip(),
        "compute_type": str(
            config.get("transcription_compute_type")
            or DEFAULT_TRANSCRIPTION_COMPUTE_TYPE
        ).strip(),
        "configured_language": optional_string(config.get("transcription_language")),
        "detected_language": None,
        "segment_count": 0,
        "smoke_test": smoke_test,
        "smoke_seconds": smoke_seconds,
        "error": None,
        "created_at": utc_now(),
    }


def write_transcription_report(
    run_dir: Path,
    report: dict[str, Any],
    smoke_test: bool,
) -> dict[str, Any]:
    write_json(report_path_for_transcription(run_dir, smoke_test), report)
    return report


def failure_transcription_report(
    run_dir: Path,
    run_id: str,
    config: dict[str, Any],
    video_path: str | None,
    smoke_test: bool,
    smoke_seconds: float | None,
    error: BaseException,
) -> dict[str, Any]:
    report = base_transcription_report(
        run_id, config, video_path, smoke_test, smoke_seconds
    )
    report["error"] = error_payload(error)
    return write_transcription_report(run_dir, report, smoke_test)


def skipped_transcription_report(
    run_dir: Path,
    run_id: str,
    config: dict[str, Any],
    video_path: str | None,
    smoke_test: bool,
    smoke_seconds: float | None,
    skip_reason: str,
) -> dict[str, Any]:
    report = base_transcription_report(
        run_id, config, video_path, smoke_test, smoke_seconds
    )
    report["status"] = "skipped"
    report["skip_reason"] = skip_reason
    return write_transcription_report(run_dir, report, smoke_test)


def find_existing_video_for_run(run_id: str, download_report: dict[str, Any]) -> Path | None:
    raw_video_path = optional_string(download_report.get("video_path"))
    if raw_video_path:
        video_path = Path(raw_video_path)
        if video_path.exists():
            return video_path

    video_dir = Path("data") / "raw" / "videos" / run_id
    if not video_dir.exists():
        return None
    candidates = [
        path
        for path in video_dir.iterdir()
        if path.is_file()
        and path.suffix.lower() not in SUBTITLE_SUFFIXES
        and not path.name.endswith((".part", ".ytdl"))
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda path: path.stat().st_mtime)


def resolve_visual_options(
    config: dict[str, Any],
    frame_interval_override: float | None,
    frame_smoke_override: float | None,
    max_keyframes_override: int | None,
) -> dict[str, Any]:
    frame_interval_value = (
        frame_interval_override
        if frame_interval_override is not None
        else config.get("frame_interval_seconds")
    )
    smoke_value = (
        frame_smoke_override
        if frame_smoke_override is not None
        else config.get("frame_smoke_seconds")
    )
    max_keyframes_value = (
        max_keyframes_override
        if max_keyframes_override is not None
        else config.get("max_keyframes")
    )

    return {
        "frame_interval_seconds": positive_float_or_default(
            frame_interval_value,
            DEFAULT_FRAME_INTERVAL_SECONDS,
            "frame_interval_seconds",
        ),
        "smoke_seconds": optional_positive_float_for_field(
            smoke_value,
            "frame_smoke_seconds",
        ),
        "max_keyframes": positive_int_or_default(
            max_keyframes_value,
            DEFAULT_MAX_KEYFRAMES,
            "max_keyframes",
        ),
        "min_visual_difference_score": nonnegative_float_or_default(
            config.get("min_visual_difference_score"),
            DEFAULT_MIN_VISUAL_DIFFERENCE_SCORE,
            "min_visual_difference_score",
        ),
        "min_stable_duration_seconds": nonnegative_float_or_default(
            config.get("min_stable_duration_seconds"),
            DEFAULT_MIN_STABLE_DURATION_SECONDS,
            "min_stable_duration_seconds",
        ),
        "min_frame_variance": nonnegative_float_or_default(
            config.get("min_frame_variance"),
            DEFAULT_MIN_FRAME_VARIANCE,
            "min_frame_variance",
        ),
        "min_sharpness_score": nonnegative_float_or_default(
            config.get("min_sharpness_score"),
            DEFAULT_MIN_SHARPNESS_SCORE,
            "min_sharpness_score",
        ),
        "dark_frame_mean_threshold": nonnegative_float_or_default(
            config.get("dark_frame_mean_threshold"),
            DEFAULT_DARK_FRAME_MEAN_THRESHOLD,
            "dark_frame_mean_threshold",
        ),
        "bright_frame_mean_threshold": nonnegative_float_or_default(
            config.get("bright_frame_mean_threshold"),
            DEFAULT_BRIGHT_FRAME_MEAN_THRESHOLD,
            "bright_frame_mean_threshold",
        ),
        "solid_frame_variance_threshold": nonnegative_float_or_default(
            config.get("solid_frame_variance_threshold"),
            DEFAULT_SOLID_FRAME_VARIANCE_THRESHOLD,
            "solid_frame_variance_threshold",
        ),
        "duplicate_similarity_threshold": nonnegative_float_or_default(
            config.get("duplicate_similarity_threshold"),
            DEFAULT_DUPLICATE_SIMILARITY_THRESHOLD,
            "duplicate_similarity_threshold",
        ),
        "duplicate_hash_distance_threshold": nonnegative_float_or_default(
            config.get("duplicate_hash_distance_threshold"),
            DEFAULT_DUPLICATE_HASH_DISTANCE_THRESHOLD,
            "duplicate_hash_distance_threshold",
        ),
        "comparison_region_mode": string_or_default(
            config.get("comparison_region_mode"),
            DEFAULT_COMPARISON_REGION_MODE,
        ),
        "comparison_center_crop_percent": positive_float_or_default(
            config.get("comparison_center_crop_percent"),
            DEFAULT_COMPARISON_CENTER_CROP_PERCENT,
            "comparison_center_crop_percent",
        ),
        "comparison_crop_left": optional_float(config.get("comparison_crop_left")),
        "comparison_crop_top": optional_float(config.get("comparison_crop_top")),
        "comparison_crop_right": optional_float(config.get("comparison_crop_right")),
        "comparison_crop_bottom": optional_float(config.get("comparison_crop_bottom")),
        "ocr_backend": string_or_default(config.get("ocr_backend"), DEFAULT_OCR_BACKEND),
        "ocr_language": optional_string(config.get("ocr_language")),
        "ocr_max_chars": positive_int_or_default(
            config.get("ocr_max_chars"),
            DEFAULT_OCR_MAX_CHARS,
            "ocr_max_chars",
        ),
        "ocr_min_text_length": positive_int_or_default(
            config.get("ocr_min_text_length"),
            DEFAULT_OCR_MIN_TEXT_LENGTH,
            "ocr_min_text_length",
        ),
        "target_video_height": configured_preferred_video_height(config),
        "min_keyframe_height": positive_int_or_default(
            config.get("min_keyframe_height"),
            DEFAULT_MIN_KEYFRAME_HEIGHT,
            "min_keyframe_height",
        ),
        "animation_collapse_enabled": bool_or_default(
            config.get("animation_collapse_enabled"),
            DEFAULT_ANIMATION_COLLAPSE_ENABLED,
        ),
        "collapse_window_seconds": positive_float_or_default(
            config.get("collapse_window_seconds"),
            DEFAULT_COLLAPSE_WINDOW_SECONDS,
            "collapse_window_seconds",
        ),
        "build_group_max_gap_seconds": positive_float_or_default(
            config.get("build_group_max_gap_seconds"),
            DEFAULT_BUILD_GROUP_MAX_GAP_SECONDS,
            "build_group_max_gap_seconds",
        ),
        "max_intermediate_keyframes_per_group": positive_int_or_default(
            config.get("max_intermediate_keyframes_per_group"),
            DEFAULT_MAX_INTERMEDIATE_KEYFRAMES_PER_GROUP,
            "max_intermediate_keyframes_per_group",
        ),
        "build_group_similarity_threshold": nonnegative_float_or_default(
            config.get("build_group_similarity_threshold"),
            DEFAULT_BUILD_GROUP_SIMILARITY_THRESHOLD,
            "build_group_similarity_threshold",
        ),
        "build_group_hash_distance_threshold": nonnegative_float_or_default(
            config.get("build_group_hash_distance_threshold"),
            DEFAULT_BUILD_GROUP_HASH_DISTANCE_THRESHOLD,
            "build_group_hash_distance_threshold",
        ),
        "min_scene_change_score": nonnegative_float_or_default(
            config.get("min_scene_change_score"),
            DEFAULT_MIN_SCENE_CHANGE_SCORE,
            "min_scene_change_score",
        ),
        "final_state_preference": string_or_default(
            config.get("final_state_preference"),
            DEFAULT_FINAL_STATE_PREFERENCE,
        ),
        "collapse_report_enabled": bool_or_default(
            config.get("collapse_report_enabled"),
            DEFAULT_COLLAPSE_REPORT_ENABLED,
        ),
        "fuller_state_scoring_enabled": bool_or_default(
            config.get("fuller_state_scoring_enabled"),
            DEFAULT_FULLER_STATE_SCORING_ENABLED,
        ),
        "fuller_state_weight": nonnegative_float_or_default(
            config.get("fuller_state_weight"),
            DEFAULT_FULLER_STATE_WEIGHT,
            "fuller_state_weight",
        ),
        "time_preference_weight": nonnegative_float_or_default(
            config.get("time_preference_weight"),
            DEFAULT_TIME_PREFERENCE_WEIGHT,
            "time_preference_weight",
        ),
        "content_area_weight": nonnegative_float_or_default(
            config.get("content_area_weight"),
            DEFAULT_CONTENT_AREA_WEIGHT,
            "content_area_weight",
        ),
        "detail_density_weight": nonnegative_float_or_default(
            config.get("detail_density_weight"),
            DEFAULT_DETAIL_DENSITY_WEIGHT,
            "detail_density_weight",
        ),
        "layout_richness_weight": nonnegative_float_or_default(
            config.get("layout_richness_weight"),
            DEFAULT_LAYOUT_RICHNESS_WEIGHT,
            "layout_richness_weight",
        ),
        "conservative_group_merge_enabled": bool_or_default(
            config.get("conservative_group_merge_enabled"),
            DEFAULT_CONSERVATIVE_GROUP_MERGE_ENABLED,
        ),
        "group_merge_max_gap_seconds": positive_float_or_default(
            config.get("group_merge_max_gap_seconds"),
            DEFAULT_GROUP_MERGE_MAX_GAP_SECONDS,
            "group_merge_max_gap_seconds",
        ),
        "group_merge_min_continuity_score": nonnegative_float_or_default(
            config.get("group_merge_min_continuity_score"),
            DEFAULT_GROUP_MERGE_MIN_CONTINUITY_SCORE,
            "group_merge_min_continuity_score",
        ),
        "title_region_max_difference": nonnegative_float_or_default(
            config.get("title_region_max_difference"),
            DEFAULT_TITLE_REGION_MAX_DIFFERENCE,
            "title_region_max_difference",
        ),
        "fuller_replacement_min_delta": nonnegative_float_or_default(
            config.get("fuller_replacement_min_delta"),
            DEFAULT_FULLER_REPLACEMENT_MIN_DELTA,
            "fuller_replacement_min_delta",
        ),
        "report_group_decisions_limit": positive_int_or_default(
            config.get("report_group_decisions_limit"),
            DEFAULT_REPORT_GROUP_DECISIONS_LIMIT,
            "report_group_decisions_limit",
        ),
        "final_state_trace_enabled": bool_or_default(
            config.get("final_state_trace_enabled"),
            DEFAULT_FINAL_STATE_TRACE_ENABLED,
        ),
        "final_state_trace_report_limit": positive_int_or_default(
            config.get("final_state_trace_report_limit"),
            DEFAULT_FINAL_STATE_TRACE_REPORT_LIMIT,
            "final_state_trace_report_limit",
        ),
        "low_content_lookahead_enabled": bool_or_default(
            config.get("low_content_lookahead_enabled"),
            DEFAULT_LOW_CONTENT_LOOKAHEAD_ENABLED,
        ),
        "low_content_lookahead_seconds": positive_float_or_default(
            config.get("low_content_lookahead_seconds"),
            DEFAULT_LOW_CONTENT_LOOKAHEAD_SECONDS,
            "low_content_lookahead_seconds",
        ),
        "low_content_content_area_threshold": nonnegative_float_or_default(
            config.get("low_content_content_area_threshold"),
            DEFAULT_LOW_CONTENT_CONTENT_AREA_THRESHOLD,
            "low_content_content_area_threshold",
        ),
        "low_content_detail_density_threshold": nonnegative_float_or_default(
            config.get("low_content_detail_density_threshold"),
            DEFAULT_LOW_CONTENT_DETAIL_DENSITY_THRESHOLD,
            "low_content_detail_density_threshold",
        ),
        "low_content_layout_richness_threshold": nonnegative_float_or_default(
            config.get("low_content_layout_richness_threshold"),
            DEFAULT_LOW_CONTENT_LAYOUT_RICHNESS_THRESHOLD,
            "low_content_layout_richness_threshold",
        ),
        "low_content_title_region_max_difference": nonnegative_float_or_default(
            config.get("low_content_title_region_max_difference"),
            DEFAULT_LOW_CONTENT_TITLE_REGION_MAX_DIFFERENCE,
            "low_content_title_region_max_difference",
        ),
        "low_content_slide_region_max_difference": nonnegative_float_or_default(
            config.get("low_content_slide_region_max_difference"),
            DEFAULT_LOW_CONTENT_SLIDE_REGION_MAX_DIFFERENCE,
            "low_content_slide_region_max_difference",
        ),
        "title_only_penalty_enabled": bool_or_default(
            config.get("title_only_penalty_enabled"),
            DEFAULT_TITLE_ONLY_PENALTY_ENABLED,
        ),
        "title_slide_keep_policy": string_or_default(
            config.get("title_slide_keep_policy"),
            DEFAULT_TITLE_SLIDE_KEEP_POLICY,
        ),
        "group_fullness_reset_min_delta": nonnegative_float_or_default(
            config.get("group_fullness_reset_min_delta"),
            DEFAULT_GROUP_FULLNESS_RESET_MIN_DELTA,
            "group_fullness_reset_min_delta",
        ),
        "strong_title_region_max_difference": nonnegative_float_or_default(
            config.get("strong_title_region_max_difference"),
            DEFAULT_STRONG_TITLE_REGION_MAX_DIFFERENCE,
            "strong_title_region_max_difference",
        ),
        "strong_title_group_merge_max_gap_seconds": positive_float_or_default(
            config.get("strong_title_group_merge_max_gap_seconds"),
            DEFAULT_STRONG_TITLE_GROUP_MERGE_MAX_GAP_SECONDS,
            "strong_title_group_merge_max_gap_seconds",
        ),
        "strong_title_build_group_hash_distance_threshold": nonnegative_float_or_default(
            config.get("strong_title_build_group_hash_distance_threshold"),
            DEFAULT_STRONG_TITLE_BUILD_GROUP_HASH_DISTANCE_THRESHOLD,
            "strong_title_build_group_hash_distance_threshold",
        ),
        "adaptive_rescan_enabled": bool_or_default(
            config.get("adaptive_rescan_enabled"),
            DEFAULT_ADAPTIVE_RESCAN_ENABLED,
        ),
        "adaptive_rescan_interval_seconds": positive_float_or_default(
            config.get("adaptive_rescan_interval_seconds"),
            DEFAULT_ADAPTIVE_RESCAN_INTERVAL_SECONDS,
            "adaptive_rescan_interval_seconds",
        ),
        "adaptive_rescan_window_seconds": positive_float_or_default(
            config.get("adaptive_rescan_window_seconds"),
            DEFAULT_ADAPTIVE_RESCAN_WINDOW_SECONDS,
            "adaptive_rescan_window_seconds",
        ),
    }


def frame_time_token(seconds: float) -> str:
    return f"{seconds:010.3f}"


def optional_duration_seconds(value: Any) -> float | None:
    if value is None or value == "":
        return None
    number = float(value)
    if number < 0:
        return None
    return number


def comparison_region_requested(options: dict[str, Any]) -> dict[str, Any]:
    return {
        "mode": options.get("comparison_region_mode"),
        "center_crop_percent": options.get("comparison_center_crop_percent"),
        "crop_left": options.get("comparison_crop_left"),
        "crop_top": options.get("comparison_crop_top"),
        "crop_right": options.get("comparison_crop_right"),
        "crop_bottom": options.get("comparison_crop_bottom"),
    }


def full_frame_region(width: int, height: int, warning: str | None = None) -> dict[str, Any]:
    return {
        "mode": "full_frame",
        "requested": None,
        "effective": {
            "left": 0,
            "top": 0,
            "right": width,
            "bottom": height,
            "width": width,
            "height": height,
            "normalized": {
                "left": 0.0,
                "top": 0.0,
                "right": 1.0,
                "bottom": 1.0,
            },
        },
        "status": "full_frame" if warning is None else "fallback_full_frame",
        "warning": warning,
    }


def resolve_comparison_region(
    image_size: tuple[int, int],
    options: dict[str, Any],
) -> dict[str, Any]:
    width, height = image_size
    requested = comparison_region_requested(options)
    mode = str(options.get("comparison_region_mode") or DEFAULT_COMPARISON_REGION_MODE).strip()
    mode = mode.lower().replace("-", "_")

    if mode in {"", "full", "full_frame"}:
        region = full_frame_region(width, height)
        region["requested"] = requested
        return region

    if mode == "center_crop":
        percent = float(
            options.get("comparison_center_crop_percent")
            or DEFAULT_COMPARISON_CENTER_CROP_PERCENT
        )
        if percent <= 0 or percent > 1:
            region = full_frame_region(
                width,
                height,
                f"Invalid comparison_center_crop_percent: {percent}.",
            )
            region["requested"] = requested
            return region
        crop_width = max(1, int(round(width * percent)))
        crop_height = max(1, int(round(height * percent)))
        left = max(0, (width - crop_width) // 2)
        top = max(0, (height - crop_height) // 2)
        right = min(width, left + crop_width)
        bottom = min(height, top + crop_height)
        return {
            "mode": "center_crop",
            "requested": requested,
            "effective": {
                "left": left,
                "top": top,
                "right": right,
                "bottom": bottom,
                "width": right - left,
                "height": bottom - top,
                "normalized": {
                    "left": round(left / width, 6) if width else 0.0,
                    "top": round(top / height, 6) if height else 0.0,
                    "right": round(right / width, 6) if width else 1.0,
                    "bottom": round(bottom / height, 6) if height else 1.0,
                },
            },
            "status": "active",
            "warning": None,
        }

    if mode == "manual":
        values = [
            options.get("comparison_crop_left"),
            options.get("comparison_crop_top"),
            options.get("comparison_crop_right"),
            options.get("comparison_crop_bottom"),
        ]
        if any(value is None for value in values):
            region = full_frame_region(
                width,
                height,
                "Manual comparison crop requires left, top, right, and bottom.",
            )
            region["requested"] = requested
            return region
        left_n, top_n, right_n, bottom_n = [float(value) for value in values]
        if not (
            0 <= left_n < right_n <= 1
            and 0 <= top_n < bottom_n <= 1
        ):
            region = full_frame_region(
                width,
                height,
                "Manual comparison crop must use normalized bounds within 0..1.",
            )
            region["requested"] = requested
            return region
        left = int(round(width * left_n))
        top = int(round(height * top_n))
        right = int(round(width * right_n))
        bottom = int(round(height * bottom_n))
        if right <= left or bottom <= top:
            region = full_frame_region(
                width,
                height,
                "Manual comparison crop resolved to an empty region.",
            )
            region["requested"] = requested
            return region
        return {
            "mode": "manual",
            "requested": requested,
            "effective": {
                "left": left,
                "top": top,
                "right": right,
                "bottom": bottom,
                "width": right - left,
                "height": bottom - top,
                "normalized": {
                    "left": left_n,
                    "top": top_n,
                    "right": right_n,
                    "bottom": bottom_n,
                },
            },
            "status": "active",
            "warning": None,
        }

    region = full_frame_region(
        width,
        height,
        f"Unknown comparison_region_mode: {mode}.",
    )
    region["requested"] = requested
    return region


def crop_for_comparison(image: Any, region: dict[str, Any]) -> Any:
    effective = region["effective"]
    box = (
        int(effective["left"]),
        int(effective["top"]),
        int(effective["right"]),
        int(effective["bottom"]),
    )
    return image.crop(box)


def preflight_ffmpeg() -> dict[str, Any]:
    ffmpeg_path = find_executable("ffmpeg")
    if ffmpeg_path is None:
        raise FFmpegNotFound("ffmpeg was not found on PATH.")

    try:
        result = subprocess.run(
            [ffmpeg_path, "-version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
    except Exception as error:
        raise FFmpegPreflightFailed(f"ffmpeg -version failed: {error}") from error

    if result.returncode != 0:
        message = (result.stderr or result.stdout or "ffmpeg -version failed.").strip()
        raise FFmpegPreflightFailed(message)

    version_line = result.stdout.splitlines()[0] if result.stdout.splitlines() else ""
    return {
        "available": True,
        "path": ffmpeg_path,
        "version": version_line,
    }


def resolution_payload(width: Any, height: Any, warning: str | None = None) -> dict[str, Any]:
    return {
        "width": width,
        "height": height,
        "resolution": resolution_text(width, height),
        "warning": warning,
    }


def image_file_resolution(path: Path | None) -> dict[str, Any]:
    if path is None:
        return resolution_payload(None, None, "No image path was available.")
    try:
        Image, _ImageStat = import_pillow()
        with Image.open(path) as image:
            width, height = image.size
        return resolution_payload(width, height)
    except Exception as error:
        return resolution_payload(None, None, f"Could not read image resolution: {error}")


def video_resolution_payload(video_path: Path | None) -> dict[str, Any]:
    if video_path is None:
        return resolution_payload(None, None, "No video path was available.")
    metadata = probe_video_metadata(video_path)
    return resolution_payload(
        metadata.get("width"),
        metadata.get("height"),
        metadata.get("warning"),
    )


def keyframe_resolution_check(
    keyframe_resolution: dict[str, Any],
    options: dict[str, Any],
) -> dict[str, Any]:
    target_height = int(options.get("target_video_height") or DEFAULT_TARGET_VIDEO_HEIGHT)
    min_height = int(options.get("min_keyframe_height") or DEFAULT_MIN_KEYFRAME_HEIGHT)
    actual_height_raw = keyframe_resolution.get("height")
    try:
        actual_height = (
            int(actual_height_raw) if actual_height_raw is not None else None
        )
    except (TypeError, ValueError):
        actual_height = None
    if actual_height is None:
        return {
            "status": "unknown",
            "message": "Keyframe height could not be determined.",
            "target_height": target_height,
            "min_keyframe_height": min_height,
            "actual_keyframe_height": None,
            "warnings": [keyframe_resolution["warning"]]
            if keyframe_resolution.get("warning")
            else [],
            "errors": [],
        }
    if actual_height >= min_height:
        return {
            "status": "success",
            "message": "Keyframe height meets the configured minimum.",
            "target_height": target_height,
            "min_keyframe_height": min_height,
            "actual_keyframe_height": actual_height,
            "warnings": [],
            "errors": [],
        }
    return {
        "status": "failed",
        "message": "Keyframe height is below min_keyframe_height.",
        "target_height": target_height,
        "min_keyframe_height": min_height,
        "actual_keyframe_height": actual_height,
        "warnings": [],
        "errors": [
            f"keyframe height {actual_height} is below required minimum {min_height}"
        ],
    }


def frame_report_payload(
    run_id: str,
    video_path: str | None,
    status: str,
    options: dict[str, Any],
    frame_dir: Path,
    frame_count: int,
    keyframe_dir: Path,
    keyframe_count: int,
    duration_seconds: float | None,
    ffmpeg_info: dict[str, Any] | None,
    error: BaseException | None,
    selection_summary: dict[str, Any] | None = None,
    comparison_region: dict[str, Any] | None = None,
    ocr_report: dict[str, Any] | None = None,
    resolution_report: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    ffmpeg_info = ffmpeg_info or {}
    selection_summary = selection_summary or {}
    quality_checks = selection_summary.get("quality_checks") or {
        "enabled": True,
        "accepted_frame_count": 0,
        "rejected_frame_count": 0,
        "rejected_reasons": {},
        "quality_thresholds": {
            "min_frame_variance": options.get("min_frame_variance"),
            "min_sharpness_score": options.get("min_sharpness_score"),
            "dark_frame_mean_threshold": options.get("dark_frame_mean_threshold"),
            "bright_frame_mean_threshold": options.get("bright_frame_mean_threshold"),
            "solid_frame_variance_threshold": options.get("solid_frame_variance_threshold"),
        },
    }
    keyframe_selection = selection_summary.get("keyframe_selection") or {
        "first_valid_frame_count": 0,
        "difference_accepted_count": 0,
        "duplicate_rejected_count": 0,
        "duplicate_suppressed_count": 0,
        "quality_rejected_count": quality_checks.get("rejected_frame_count", 0),
        "stable_segment_count": keyframe_count,
    }
    animation_collapse = keyframe_selection.get("animation_collapse")
    if not isinstance(animation_collapse, dict):
        animation_collapse = (
            quality_checks.get("animation_collapse")
            if isinstance(quality_checks.get("animation_collapse"), dict)
            else empty_animation_collapse_summary(
                options,
                original_keyframe_count=keyframe_count,
                collapsed_keyframe_count=keyframe_count,
                enabled=bool(options.get("animation_collapse_enabled")),
            )
        )
    comparison_region = comparison_region or {
        "mode": options.get("comparison_region_mode"),
        "requested": comparison_region_requested(options),
        "effective": None,
        "status": "not_evaluated",
        "warning": None,
    }
    ocr_report = ocr_report or build_ocr_report(
        options,
        processed_keyframe_count=0,
        text_hint_count=0,
        warning=None,
    )
    warnings = warnings or []
    if comparison_region.get("warning"):
        warnings.append(str(comparison_region["warning"]))
    if ocr_report.get("warning"):
        warnings.append(str(ocr_report["warning"]))
    resolution_report = resolution_report or {
        "raw_video_resolution": resolution_payload(None, None, "not_evaluated"),
        "extracted_frame_resolution": resolution_payload(None, None, "not_evaluated"),
        "keyframe_resolution": resolution_payload(None, None, "not_evaluated"),
        "resolution_check": {
            "status": "unknown",
            "message": "Resolution was not evaluated.",
            "target_height": options.get("target_video_height"),
            "min_keyframe_height": options.get("min_keyframe_height"),
            "actual_keyframe_height": None,
            "warnings": [],
            "errors": [],
        },
    }
    for item in (
        resolution_report.get("raw_video_resolution"),
        resolution_report.get("extracted_frame_resolution"),
        resolution_report.get("keyframe_resolution"),
    ):
        if isinstance(item, dict) and item.get("warning"):
            warnings.append(str(item["warning"]))
    resolution_check_payload = resolution_report.get("resolution_check")
    if isinstance(resolution_check_payload, dict):
        for warning in resolution_check_payload.get("warnings") or []:
            warnings.append(str(warning))
    return {
        "run_id": run_id,
        "video_path": video_path,
        "status": status,
        "ffmpeg_available": ffmpeg_info.get("available"),
        "ffmpeg_path": ffmpeg_info.get("path"),
        "ffmpeg_version": ffmpeg_info.get("version"),
        "frame_interval_seconds": options.get("frame_interval_seconds"),
        "smoke_test": options.get("smoke_seconds") is not None,
        "smoke_seconds": options.get("smoke_seconds"),
        "frame_dir": str(frame_dir),
        "frame_count": frame_count,
        "keyframe_dir": str(keyframe_dir),
        "keyframe_count": keyframe_count,
        "max_keyframes": options.get("max_keyframes"),
        "duration_seconds": duration_seconds,
        "method": VISUAL_EXTRACTION_METHOD,
        "quality_checks": quality_checks,
        "accepted_frame_count": quality_checks.get("accepted_frame_count"),
        "rejected_frame_count": quality_checks.get("rejected_frame_count"),
        "rejected_reasons": quality_checks.get("rejected_reasons"),
        "quality_thresholds": quality_checks.get("quality_thresholds"),
        "frame_quality_checks": quality_checks,
        "keyframe_selection": keyframe_selection,
        "duplicate_suppressed_count": keyframe_selection.get("duplicate_suppressed_count"),
        "duplicate_rejected_count": keyframe_selection.get("duplicate_rejected_count"),
        "difference_accepted_count": keyframe_selection.get("difference_accepted_count"),
        "quality_rejected_count": keyframe_selection.get("quality_rejected_count"),
        "first_valid_frame_count": keyframe_selection.get("first_valid_frame_count"),
        "stable_segment_count": keyframe_selection.get("stable_segment_count"),
        "animation_collapse_enabled": animation_collapse.get("enabled"),
        "animation_collapse": animation_collapse,
        "collapsed_group_count": animation_collapse.get("collapsed_group_count"),
        "intermediate_suppressed_count": animation_collapse.get(
            "intermediate_suppressed_count"
        ),
        "replaced_intermediate_count": animation_collapse.get(
            "replaced_intermediate_count"
        ),
        "final_state_trace": animation_collapse.get("final_state_trace"),
        "comparison_region": comparison_region,
        "ocr": ocr_report,
        "raw_video_resolution": resolution_report.get("raw_video_resolution"),
        "extracted_frame_resolution": resolution_report.get(
            "extracted_frame_resolution"
        ),
        "keyframe_resolution": resolution_report.get("keyframe_resolution"),
        "resolution_check": resolution_report.get("resolution_check"),
        "warnings": sorted(set(warnings)),
        "error": error_payload(error) if error is not None else None,
        "created_at": utc_now(),
    }


def write_frame_report(run_dir: Path, report: dict[str, Any]) -> dict[str, Any]:
    write_json(run_dir / "audit" / "frame_report.json", report)
    return report


def write_failed_visual_segments(
    run_dir: Path,
    run_id: str,
    video_path: str | None,
    keyframe_dir: Path,
    error: BaseException,
    quality_summary: dict[str, Any] | None = None,
    keyframe_selection: dict[str, Any] | None = None,
    comparison_region: dict[str, Any] | None = None,
    ocr_report: dict[str, Any] | None = None,
) -> None:
    payload = {
        "run_id": run_id,
        "video_path": video_path,
        "method": VISUAL_EXTRACTION_METHOD,
        "status": "failed",
        "segments": [],
        "segment_count": 0,
        "keyframe_dir": str(keyframe_dir),
        "quality_summary": quality_summary or {},
        "keyframe_selection": keyframe_selection or {},
        "comparison_region": comparison_region,
        "ocr": ocr_report,
        "error": error_payload(error),
        "created_at": utc_now(),
    }
    write_json(run_dir / "audit" / "visual_segments.json", payload)


def write_visual_segments(
    run_dir: Path,
    run_id: str,
    video_path: Path,
    keyframe_dir: Path,
    segments: list[dict[str, Any]],
    smoke_test: bool,
    quality_summary: dict[str, Any] | None = None,
    comparison_region: dict[str, Any] | None = None,
    ocr_report: dict[str, Any] | None = None,
    animation_collapse: dict[str, Any] | None = None,
) -> dict[str, Any]:
    payload = {
        "run_id": run_id,
        "video_path": str(video_path),
        "method": VISUAL_EXTRACTION_METHOD,
        "status": "smoke_success" if smoke_test else "success",
        "segments": segments,
        "segment_count": len(segments),
        "keyframe_dir": str(keyframe_dir),
        "quality_summary": quality_summary or {},
        "comparison_region": comparison_region,
        "ocr": ocr_report,
        "animation_collapse": animation_collapse or {},
        "created_at": utc_now(),
    }
    write_json(run_dir / "audit" / "visual_segments.json", payload)
    return payload


def strict_video_path_from_download_report(download_report: dict[str, Any]) -> Path:
    raw_video_path = optional_string(download_report.get("video_path"))
    if raw_video_path is None:
        raise FileNotFoundError("download_report.json video_path is empty.")
    video_path = Path(raw_video_path)
    if not video_path.exists():
        raise FileNotFoundError(f"Downloaded video file not found: {video_path}")
    return video_path


def clear_generated_visual_files(directory: Path, patterns: tuple[str, ...]) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    for pattern in patterns:
        for path in directory.glob(pattern):
            if path.is_file():
                path.unlink()


def extract_candidate_frames(
    ffmpeg_path: str,
    video_path: Path,
    frame_dir: Path,
    frame_interval_seconds: float,
    smoke_seconds: float | None,
) -> list[dict[str, Any]]:
    clear_generated_visual_files(frame_dir, ("frame_*.jpg", "_raw_frame_*.jpg"))
    raw_pattern = frame_dir / "_raw_frame_%06d.jpg"
    command = [
        ffmpeg_path,
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
    ]
    if smoke_seconds is not None:
        command.extend(["-t", f"{smoke_seconds:g}"])
    command.extend(
        [
            "-i",
            str(video_path),
            "-vf",
            f"fps=1/{frame_interval_seconds:g}",
            "-q:v",
            "2",
            str(raw_pattern),
        ]
    )

    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        message = (result.stderr or result.stdout or "ffmpeg frame extraction failed.").strip()
        raise FrameExtractionFailed(message)

    raw_frames = sorted(frame_dir.glob("_raw_frame_*.jpg"))
    if not raw_frames:
        raise NoCandidateFrames("FFmpeg completed but generated no candidate frames.")

    candidates = []
    for index, raw_path in enumerate(raw_frames, start=1):
        frame_time = (index - 1) * frame_interval_seconds
        frame_path = frame_dir / f"frame_{index:06d}_t{frame_time_token(frame_time)}.jpg"
        raw_path.replace(frame_path)
        candidates.append(
            {
                "path": frame_path,
                "time": frame_time,
            }
        )
    return candidates


def import_pillow() -> tuple[Any, Any]:
    try:
        from PIL import Image, ImageStat
    except ImportError as error:
        raise RuntimeError(
            "Pillow is not installed. Install dependencies with: pip install -r requirements.txt"
        ) from error
    return Image, ImageStat


def pillow_resampling_filter(Image: Any) -> Any:
    if hasattr(Image, "Resampling"):
        return Image.Resampling.LANCZOS
    return Image.LANCZOS


def normalized_histogram(histogram: list[int]) -> list[float]:
    total = float(sum(histogram)) or 1.0
    return [value / total for value in histogram]


def average_hash_from_pixels(pixels: list[int]) -> tuple[int, ...]:
    average = sum(pixels) / len(pixels)
    return tuple(1 if pixel > average else 0 for pixel in pixels)


def estimate_content_area_ratio(pixels: list[int], threshold: int = 245) -> float:
    if not pixels:
        return 0.0
    return sum(1 for pixel in pixels if pixel < threshold) / len(pixels)


def estimate_detail_density(
    pixels: list[int],
    width: int,
    height: int,
    threshold: int = 12,
) -> float:
    if width < 2 or height < 2:
        return 0.0
    edge_count = 0
    comparison_count = 0
    for y in range(height):
        row_offset = y * width
        for x in range(width):
            current = pixels[row_offset + x]
            if x + 1 < width:
                edge_count += (
                    1 if abs(current - pixels[row_offset + x + 1]) > threshold else 0
                )
                comparison_count += 1
            if y + 1 < height:
                edge_count += (
                    1
                    if abs(current - pixels[row_offset + width + x]) > threshold
                    else 0
                )
                comparison_count += 1
    return edge_count / comparison_count if comparison_count else 0.0


def estimate_layout_richness(
    pixels: list[int],
    width: int,
    height: int,
    threshold: int = 245,
    grid_size: int = 8,
) -> float:
    if width < grid_size or height < grid_size:
        return 0.0
    occupied = 0
    total_cells = grid_size * grid_size
    cell_width = width // grid_size
    cell_height = height // grid_size
    for cell_y in range(grid_size):
        for cell_x in range(grid_size):
            values = []
            for y in range(cell_y * cell_height, (cell_y + 1) * cell_height):
                row_offset = y * width
                for x in range(cell_x * cell_width, (cell_x + 1) * cell_width):
                    values.append(pixels[row_offset + x])
            if estimate_content_area_ratio(values, threshold) > 0.08:
                occupied += 1
    return occupied / total_cells


def gray_signature(
    gray_image: Any,
    resample: Any,
    size: tuple[int, int] = (64, 64),
) -> dict[str, Any]:
    thumbnail = gray_image.resize(size, resample)
    pixels = list(thumbnail.getdata())
    small = thumbnail.resize((8, 8), resample)
    small_pixels = list(small.getdata())
    width, height = thumbnail.size
    return {
        "histogram": normalized_histogram(thumbnail.histogram()),
        "average_hash": average_hash_from_pixels(small_pixels),
        "content_area_ratio": estimate_content_area_ratio(pixels),
        "ink_density": estimate_content_area_ratio(pixels, threshold=220),
        "detail_density": estimate_detail_density(pixels, width, height),
        "layout_richness": estimate_layout_richness(pixels, width, height),
    }


def relative_crop(image: Any, box: tuple[float, float, float, float]) -> Any:
    width, height = image.size
    left, top, right, bottom = box
    return image.crop(
        (
            max(0, min(width, int(width * left))),
            max(0, min(height, int(height * top))),
            max(0, min(width, int(width * right))),
            max(0, min(height, int(height * bottom))),
        )
    )


def image_features(
    path: Path,
    Image: Any,
    ImageStat: Any,
    options: dict[str, Any],
) -> dict[str, Any]:
    try:
        with Image.open(path) as image:
            comparison_region = resolve_comparison_region(image.size, options)
            comparison_image = crop_for_comparison(image, comparison_region)
            gray = comparison_image.convert("L")
            resample = pillow_resampling_filter(Image)
            thumbnail = gray.resize((64, 64), resample)
            stat = ImageStat.Stat(thumbnail)
            histogram = thumbnail.histogram()
            small = thumbnail.resize((8, 8), resample)
            pixels = list(small.getdata())
            sharpness_score = estimate_sharpness_score(thumbnail)
            slide_region = relative_crop(image, (0.0, 0.08, 0.86, 1.0)).convert("L")
            title_region = relative_crop(image, (0.04, 0.06, 0.86, 0.28)).convert("L")
            slide_signature = gray_signature(slide_region, resample)
            title_signature = gray_signature(title_region, resample, size=(64, 32))
    except Exception as error:
        raise PillowFrameReadFailed(f"Pillow could not read frame {path}: {error}") from error

    return {
        "mean": float(stat.mean[0]),
        "variance": float(stat.var[0]),
        "sharpness_score": sharpness_score,
        "histogram": normalized_histogram(histogram),
        "average_hash": average_hash_from_pixels(pixels),
        "comparison_region": comparison_region,
        "slide_region": slide_signature,
        "title_region": title_signature,
    }


def estimate_sharpness_score(gray_thumbnail: Any) -> float:
    width, height = gray_thumbnail.size
    pixels = list(gray_thumbnail.getdata())
    if width < 2 or height < 2:
        return 0.0
    total = 0.0
    count = 0
    for y in range(height):
        row_offset = y * width
        for x in range(width):
            current = pixels[row_offset + x]
            if x + 1 < width:
                total += abs(current - pixels[row_offset + x + 1])
                count += 1
            if y + 1 < height:
                total += abs(current - pixels[row_offset + width + x])
                count += 1
    return total / count if count else 0.0


def frame_quality_thresholds(options: dict[str, Any]) -> dict[str, float | None]:
    return {
        "min_frame_variance": options.get("min_frame_variance"),
        "min_sharpness_score": options.get("min_sharpness_score"),
        "dark_frame_mean_threshold": options.get("dark_frame_mean_threshold"),
        "bright_frame_mean_threshold": options.get("bright_frame_mean_threshold"),
        "solid_frame_variance_threshold": options.get("solid_frame_variance_threshold"),
    }


def evaluate_frame_quality(
    features: dict[str, Any],
    options: dict[str, Any],
) -> dict[str, Any]:
    mean = float(features["mean"])
    variance = float(features["variance"])
    sharpness_score = float(features["sharpness_score"])
    reasons = []

    if (
        mean <= float(options["dark_frame_mean_threshold"])
        and variance <= max(100.0, float(options["min_frame_variance"]))
    ):
        reasons.append("dark_frame")
    if (
        mean >= float(options["bright_frame_mean_threshold"])
        and variance <= max(25.0, float(options["min_frame_variance"]))
    ):
        reasons.append("bright_frame")
    if variance <= float(options["solid_frame_variance_threshold"]):
        reasons.append("near_solid_frame")
    if variance < float(options["min_frame_variance"]):
        reasons.append("low_variance")
    if sharpness_score < float(options["min_sharpness_score"]):
        reasons.append("low_sharpness")

    return {
        "accepted": not reasons,
        "reasons": reasons,
        "metrics": {
            "brightness_mean": round(mean, 6),
            "brightness_variance": round(variance, 6),
            "sharpness_score": round(sharpness_score, 6),
        },
    }


def is_low_information_frame(features: dict[str, Any]) -> bool:
    quality = evaluate_frame_quality(
        features,
        {
            "dark_frame_mean_threshold": DEFAULT_DARK_FRAME_MEAN_THRESHOLD,
            "bright_frame_mean_threshold": DEFAULT_BRIGHT_FRAME_MEAN_THRESHOLD,
            "solid_frame_variance_threshold": DEFAULT_SOLID_FRAME_VARIANCE_THRESHOLD,
            "min_frame_variance": DEFAULT_MIN_FRAME_VARIANCE,
            "min_sharpness_score": DEFAULT_MIN_SHARPNESS_SCORE,
        },
    )
    return not bool(quality["accepted"])


def histogram_difference(left: list[float], right: list[float]) -> float:
    return sum(abs(a - b) for a, b in zip(left, right)) / 2


def average_hash_difference(left: tuple[int, ...], right: tuple[int, ...]) -> float:
    if not left or len(left) != len(right):
        return 0.0
    distance = sum(1 for a, b in zip(left, right) if a != b)
    return distance / len(left)


def visual_difference_score(
    current_features: dict[str, Any],
    previous_features: dict[str, Any],
) -> float:
    return max(
        histogram_difference(
            current_features["histogram"],
            previous_features["histogram"],
        ),
        average_hash_difference(
            current_features["average_hash"],
            previous_features["average_hash"],
        ),
    )


def increment_count(counts: dict[str, int], key: str) -> None:
    counts[key] = counts.get(key, 0) + 1


def make_quality_summary(
    options: dict[str, Any],
    accepted_frame_count: int,
    rejected_frame_count: int,
    rejected_reasons: dict[str, int],
    rejected_frame_samples: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "enabled": True,
        "accepted_frame_count": accepted_frame_count,
        "rejected_frame_count": rejected_frame_count,
        "rejected_reasons": dict(sorted(rejected_reasons.items())),
        "quality_thresholds": frame_quality_thresholds(options),
        "rejected_frame_samples": rejected_frame_samples[:25],
    }


def make_keyframe_selection_summary(
    candidates: list[dict[str, Any]],
    accepted_count: int,
    accepted_frame_count: int,
    first_valid_frame_count: int,
    difference_accepted_count: int,
    duplicate_rejected_count: int,
    duplicate_suppressed_count: int,
    rejected_frame_count: int,
    stable_too_short_rejected_count: int,
    low_difference_rejected_count: int,
    max_keyframes_reached: bool,
    options: dict[str, Any],
) -> dict[str, Any]:
    return {
        "candidate_frame_count": len(candidates),
        "valid_frame_count": accepted_frame_count,
        "first_valid_frame_count": first_valid_frame_count,
        "difference_accepted_count": difference_accepted_count,
        "duplicate_rejected_count": duplicate_rejected_count,
        "duplicate_suppressed_count": duplicate_suppressed_count,
        "quality_rejected_count": rejected_frame_count,
        "stable_too_short_rejected_count": stable_too_short_rejected_count,
        "low_difference_rejected_count": low_difference_rejected_count,
        "stable_segment_count": accepted_count,
        "max_keyframes_reached": max_keyframes_reached,
        "thresholds": {
            "min_visual_difference_score": options.get("min_visual_difference_score"),
            "min_stable_duration_seconds": options.get("min_stable_duration_seconds"),
            "duplicate_similarity_threshold": options.get("duplicate_similarity_threshold"),
            "duplicate_hash_distance_threshold": options.get(
                "duplicate_hash_distance_threshold"
            ),
        },
    }


def empty_animation_collapse_summary(
    options: dict[str, Any],
    original_keyframe_count: int,
    collapsed_keyframe_count: int | None = None,
    enabled: bool | None = None,
) -> dict[str, Any]:
    is_enabled = bool(options.get("animation_collapse_enabled")) if enabled is None else enabled
    collapsed_count = (
        original_keyframe_count
        if collapsed_keyframe_count is None
        else collapsed_keyframe_count
    )
    return {
        "enabled": is_enabled,
        "collapsed_group_count": 0,
        "intermediate_suppressed_count": 0,
        "replaced_intermediate_count": 0,
        "original_keyframe_count": original_keyframe_count,
        "collapsed_keyframe_count": collapsed_count,
        "collapse_window_seconds": options.get("collapse_window_seconds"),
        "build_group_max_gap_seconds": options.get("build_group_max_gap_seconds"),
        "max_intermediate_keyframes_per_group": options.get(
            "max_intermediate_keyframes_per_group"
        ),
        "build_group_similarity_threshold": options.get(
            "build_group_similarity_threshold"
        ),
        "build_group_hash_distance_threshold": options.get(
            "build_group_hash_distance_threshold"
        ),
        "min_scene_change_score": options.get("min_scene_change_score"),
        "final_state_preference": options.get("final_state_preference"),
        "representative_strategy": options.get("final_state_preference"),
        "final_state_preference_details": {
            "fuller_state_scoring_enabled": options.get("fuller_state_scoring_enabled"),
            "fuller_state_weight": options.get("fuller_state_weight"),
            "time_preference_weight": options.get("time_preference_weight"),
            "content_area_weight": options.get("content_area_weight"),
            "detail_density_weight": options.get("detail_density_weight"),
            "layout_richness_weight": options.get("layout_richness_weight"),
            "title_region_max_difference": options.get("title_region_max_difference"),
            "group_fullness_reset_min_delta": options.get(
                "group_fullness_reset_min_delta"
            ),
            "strong_title_region_max_difference": options.get(
                "strong_title_region_max_difference"
            ),
            "strong_title_group_merge_max_gap_seconds": options.get(
                "strong_title_group_merge_max_gap_seconds"
            ),
        },
        "low_content_lookahead": {
            "enabled": options.get("low_content_lookahead_enabled"),
            "detected_count": 0,
            "suppressed_count": 0,
            "inserted_candidate_count": 0,
            "kept_count": 0,
            "decisions": [],
        },
        "final_state_trace": {
            "enabled": options.get("final_state_trace_enabled"),
            "traced_window_count": 0,
            "traced_windows": [],
            "truncated": False,
            "adaptive_rescan": {
                "enabled": options.get("adaptive_rescan_enabled"),
                "interval_seconds": options.get("adaptive_rescan_interval_seconds"),
                "window_seconds": options.get("adaptive_rescan_window_seconds"),
                "status": "disabled_by_default"
                if not bool(options.get("adaptive_rescan_enabled"))
                else "hook_enabled_not_executed",
            },
        },
        "warnings": [],
        "collapse_warnings": [],
        "group_boundary_decision_count": 0,
        "group_boundary_decisions": [],
        "group_boundary_decisions_truncated": False,
        "boundary_break_reasons": {},
        "candidate_pool_diagnostics": {},
        "tail_collapse_check": {},
        "group_summaries": [],
        "group_summary_limit": MAX_COLLAPSE_GROUP_SUMMARIES,
    }


def clamp_unit(value: float) -> float:
    return max(0.0, min(1.0, value))


def feature_region_difference(
    current_features: dict[str, Any],
    previous_features: dict[str, Any],
    region_key: str,
) -> float:
    current_region = current_features.get(region_key) or {}
    previous_region = previous_features.get(region_key) or {}
    if not current_region or not previous_region:
        return 1.0
    return max(
        histogram_difference(
            current_region.get("histogram", []),
            previous_region.get("histogram", []),
        ),
        average_hash_difference(
            current_region.get("average_hash", ()),
            previous_region.get("average_hash", ()),
        ),
    )


def fuller_state_score_details_from_features(
    features: dict[str, Any],
    options: dict[str, Any],
    time_position: float = 0.0,
) -> dict[str, Any]:
    slide_region = features.get("slide_region") or {}
    content_area = float(slide_region.get("content_area_ratio") or 0.0)
    detail_density = float(slide_region.get("detail_density") or 0.0)
    layout_richness = float(slide_region.get("layout_richness") or 0.0)
    content_component = content_area * float(options.get("content_area_weight") or 0.0)
    detail_component = detail_density * float(options.get("detail_density_weight") or 0.0)
    layout_component = layout_richness * float(options.get("layout_richness_weight") or 0.0)
    fuller_component = (
        content_component + detail_component + layout_component
    ) * float(options.get("fuller_state_weight") or 0.0)
    time_component = clamp_unit(time_position) * float(
        options.get("time_preference_weight") or 0.0
    )
    score = fuller_component + time_component
    return {
        "score": round(score, 6),
        "fuller_component": round(fuller_component, 6),
        "time_component": round(time_component, 6),
        "content_area_ratio": round(content_area, 6),
        "detail_density": round(detail_density, 6),
        "layout_richness": round(layout_richness, 6),
        "time_position": round(clamp_unit(time_position), 6),
        "weights": {
            "fuller_state_weight": options.get("fuller_state_weight"),
            "time_preference_weight": options.get("time_preference_weight"),
            "content_area_weight": options.get("content_area_weight"),
            "detail_density_weight": options.get("detail_density_weight"),
            "layout_richness_weight": options.get("layout_richness_weight"),
        },
    }


def keyframe_fuller_state_score_details(
    keyframe: dict[str, Any],
    options: dict[str, Any],
    group_start: float | None = None,
    group_end: float | None = None,
) -> dict[str, Any]:
    features = keyframe.get("features") or {}
    start = (
        float(keyframe["source_frame_time"])
        if group_start is None
        else float(group_start)
    )
    end = float(keyframe["source_frame_time"]) if group_end is None else float(group_end)
    span = max(0.0, end - start)
    time_position = (
        0.0
        if span == 0.0
        else (float(keyframe["source_frame_time"]) - start) / span
    )
    return fuller_state_score_details_from_features(features, options, time_position)


def collapse_pair_metrics(
    previous: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, Any]:
    previous_features = previous.get("features") or {}
    current_features = current.get("features") or {}
    if not previous_features or not current_features:
        return {
            "visual_difference_score": 1.0,
            "hash_distance": 1.0,
            "similarity": 0.0,
            "title_region_difference": 1.0,
            "slide_region_difference": 1.0,
        }
    score = visual_difference_score(current_features, previous_features)
    hash_distance = average_hash_difference(
        current_features.get("average_hash", ()),
        previous_features.get("average_hash", ()),
    )
    return {
        "visual_difference_score": score,
        "hash_distance": hash_distance,
        "similarity": 1 - score,
        "title_region_difference": feature_region_difference(
            current_features,
            previous_features,
            "title_region",
        ),
        "slide_region_difference": feature_region_difference(
            current_features,
            previous_features,
            "slide_region",
        ),
    }


def can_join_build_group(
    group: list[dict[str, Any]],
    candidate: dict[str, Any],
    options: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    previous = group[-1]
    gap = float(candidate["source_frame_time"]) - float(previous["source_frame_time"])
    span = float(candidate["source_frame_time"]) - float(group[0]["source_frame_time"])
    previous_metrics = collapse_pair_metrics(previous, candidate)
    anchor_metrics = collapse_pair_metrics(group[0], candidate)
    group_representative = max(
        group,
        key=lambda item: keyframe_fuller_state_score_details(item, options)["score"],
    )
    representative_metrics = collapse_pair_metrics(group_representative, candidate)
    representative_score = keyframe_fuller_state_score_details(
        group_representative,
        options,
    )
    candidate_score = keyframe_fuller_state_score_details(candidate, options)
    fullness_reset_delta = float(representative_score["score"]) - float(
        candidate_score["score"]
    )
    previous_title_region_difference = float(previous_metrics["title_region_difference"])
    title_region_difference = min(
        previous_title_region_difference,
        float(anchor_metrics["title_region_difference"]),
        float(representative_metrics["title_region_difference"]),
    )
    visual_difference = min(
        float(previous_metrics["visual_difference_score"]),
        float(representative_metrics["visual_difference_score"]),
    )
    hash_distance = min(
        float(previous_metrics["hash_distance"]),
        float(representative_metrics["hash_distance"]),
    )
    gap_risk = gap / max(float(options["group_merge_max_gap_seconds"]), 1.0)
    scene_risk = visual_difference / max(float(options["min_scene_change_score"]), 0.001)
    continuity_score = clamp_unit(
        1.0 - title_region_difference - (0.1 * scene_risk) - (0.05 * gap_risk)
    )
    reasons = []

    if gap > float(options["group_merge_max_gap_seconds"]):
        reasons.append("gap_exceeds_group_merge_max_gap_seconds")
    if previous_title_region_difference > float(options["title_region_max_difference"]):
        reasons.append("title_region_difference_exceeds_threshold")
    if visual_difference >= float(options["min_scene_change_score"]):
        reasons.append("visual_difference_indicates_scene_change")
    if hash_distance > float(options["build_group_hash_distance_threshold"]):
        reasons.append("hash_distance_exceeds_build_group_threshold")
    if (
        span > float(options["collapse_window_seconds"])
        and continuity_score < float(options["group_merge_min_continuity_score"])
    ):
        reasons.append("span_exceeds_soft_limit_without_continuity")
    if previous_metrics["similarity"] < float(options["build_group_similarity_threshold"]):
        reasons.append("similarity_below_build_group_threshold")

    fullness_reset = fullness_reset_delta >= float(
        options["group_fullness_reset_min_delta"]
    )
    if fullness_reset:
        reasons.append("fullness_reset_indicates_new_sequence")

    strong_title_continuity = (
        previous_title_region_difference
        <= float(options["strong_title_region_max_difference"])
        and gap <= float(options["strong_title_group_merge_max_gap_seconds"])
        and visual_difference < float(options["min_scene_change_score"])
        and hash_distance
        <= float(options["strong_title_build_group_hash_distance_threshold"])
        and not fullness_reset
    )
    overridable_reasons = {
        "gap_exceeds_group_merge_max_gap_seconds",
        "hash_distance_exceeds_build_group_threshold",
        "span_exceeds_soft_limit_without_continuity",
    }
    overridden_reasons = []
    if strong_title_continuity:
        overridden_reasons = [
            reason for reason in reasons if reason in overridable_reasons
        ]
        reasons = [reason for reason in reasons if reason not in overridable_reasons]

    return not reasons, {
        "from_source_frame_time": round(float(previous["source_frame_time"]), 3),
        "candidate_source_frame_time": round(float(candidate["source_frame_time"]), 3),
        "anchor_source_frame_time": round(float(group[0]["source_frame_time"]), 3),
        "representative_candidate_source_frame_time": round(
            float(group_representative["source_frame_time"]),
            3,
        ),
        "gap_seconds": round(gap, 3),
        "span_seconds": round(span, 3),
        "visual_difference_score": round(visual_difference, 6),
        "previous_visual_difference_score": round(
            float(previous_metrics["visual_difference_score"]),
            6,
        ),
        "anchor_visual_difference_score": round(
            float(anchor_metrics["visual_difference_score"]),
            6,
        ),
        "representative_visual_difference_score": round(
            float(representative_metrics["visual_difference_score"]),
            6,
        ),
        "hash_distance": round(hash_distance, 6),
        "similarity": round(float(previous_metrics["similarity"]), 6),
        "previous_title_region_difference": round(
            previous_title_region_difference,
            6,
        ),
        "title_region_difference": round(title_region_difference, 6),
        "slide_region_difference": round(
            min(
                float(previous_metrics["slide_region_difference"]),
                float(representative_metrics["slide_region_difference"]),
            ),
            6,
        ),
        "continuity_score": round(continuity_score, 6),
        "representative_fuller_score": representative_score,
        "candidate_fuller_score": candidate_score,
        "fullness_reset_delta": round(fullness_reset_delta, 6),
        "strong_title_continuity": strong_title_continuity,
        "overridden_break_reasons": overridden_reasons,
        "decision": "join" if not reasons else "break",
        "break_reasons": reasons,
    }


def choose_collapse_representatives(
    group: list[dict[str, Any]],
    options: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    max_representatives = int(options["max_intermediate_keyframes_per_group"])
    group_start = float(group[0]["source_frame_time"])
    group_end = float(group[-1]["source_frame_time"])
    ranked_candidates = []
    for item in group:
        score_details = keyframe_fuller_state_score_details(
            item,
            options,
            group_start,
            group_end,
        )
        ranked_candidates.append(
            {
                "source_frame_time": round(float(item["source_frame_time"]), 3),
                "score": score_details["score"],
                "score_details": score_details,
            }
        )
    if len(group) <= max_representatives:
        return list(group), ranked_candidates

    preference = str(options.get("final_state_preference") or DEFAULT_FINAL_STATE_PREFERENCE)
    if (
        preference in {"content_fullness", "fuller_final_state"}
        or bool(options.get("fuller_state_scoring_enabled"))
    ):
        scored = [
            (
                keyframe_fuller_state_score_details(
                    item,
                    options,
                    group_start,
                    group_end,
                )["score"],
                float(item["source_frame_time"]),
                item,
            )
            for item in group
        ]
        ranked = sorted(scored, key=lambda value: (value[0], value[1]), reverse=True)
        selected = sorted(
            [item for _score, _time, item in ranked[:max_representatives]],
            key=lambda item: float(item["source_frame_time"]),
        )
        ranked_candidates = [
            {
                "source_frame_time": round(float(item["source_frame_time"]), 3),
                "score": round(float(score), 6),
                "score_details": keyframe_fuller_state_score_details(
                    item,
                    options,
                    group_start,
                    group_end,
                ),
            }
            for score, _time, item in ranked
        ]
        return selected, ranked_candidates

    if preference == "latest_stable":
        selected = list(group[-max_representatives:])
        ranked_candidates = [
            {
                **candidate,
                "selection_note": "latest_stable_time_order",
            }
            for candidate in ranked_candidates
        ]
        return selected, ranked_candidates

    if preference == "content_fullness_legacy":
        ranked = sorted(
            group,
            key=lambda item: (
                float((item.get("quality_metrics") or {}).get("brightness_variance") or 0.0)
                + float((item.get("quality_metrics") or {}).get("sharpness_score") or 0.0),
                float(item["source_frame_time"]),
            ),
            reverse=True,
        )
        selected = sorted(
            ranked[:max_representatives],
            key=lambda item: float(item["source_frame_time"]),
        )
        return selected, ranked_candidates

    return list(group[-max_representatives:]), ranked_candidates


def merge_suppressed_keyframe_into_representative(
    representative: dict[str, Any],
    suppressed: list[dict[str, Any]],
    group_id: int,
    reason: str,
    score_details: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if score_details is None:
        score_details = {}
    if not suppressed:
        representative["collapse_group_id"] = group_id
        representative["representative_selection_reason"] = reason
        representative["representative_score"] = score_details.get("score")
        representative["representative_score_details"] = score_details
        representative.setdefault("suppressed_intermediate_times", [])
        representative.setdefault("replaced_intermediate_keyframes", [])
        return representative

    covered = list(representative.get("covered_source_frame_times", []))
    replaced = []
    for item in suppressed:
        covered.extend(item.get("covered_source_frame_times", []))
        if float(item["source_frame_time"]) not in covered:
            covered.append(float(item["source_frame_time"]))
        replaced.append(
            {
                "source_frame_time": round(float(item["source_frame_time"]), 3),
                "source_frame_path": str(item["source_frame_path"]),
                "reason": item.get("reason"),
                "visual_difference_score": round(
                    float(item.get("visual_difference_score") or 0.0),
                    6,
                ),
                "replaced_by_later_state": float(item["source_frame_time"])
                < float(representative["source_frame_time"]),
                "replaced_by_source_frame_time": round(
                    float(representative["source_frame_time"]),
                    3,
                ),
            }
        )
    representative["covered_source_frame_times"] = sorted(
        {float(value) for value in covered}
    )
    representative["merged_source_frame_count"] = len(
        representative["covered_source_frame_times"]
    )
    representative["collapse_group_id"] = group_id
    representative["representative_selection_reason"] = reason
    representative["representative_score"] = score_details.get("score")
    representative["representative_score_details"] = score_details
    representative["suppressed_intermediate_times"] = [
        item["source_frame_time"] for item in replaced
    ]
    representative["replaced_intermediate_keyframes"] = replaced
    return representative


def summarize_boundary_decisions(
    boundary_decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    break_reasons: dict[str, int] = {}
    join_count = 0
    break_count = 0
    for decision in boundary_decisions:
        if decision.get("decision") == "join":
            join_count += 1
        else:
            break_count += 1
        for reason in decision.get("break_reasons", []):
            increment_count(break_reasons, str(reason))
    return {
        "join_count": join_count,
        "break_count": break_count,
        "break_reasons": dict(sorted(break_reasons.items())),
    }


def collapse_group_summary(
    group: list[dict[str, Any]],
    representatives: list[dict[str, Any]],
    suppressed: list[dict[str, Any]],
    group_id: int,
    reason: str,
    ranked_candidates: list[dict[str, Any]],
    boundary_decisions: list[dict[str, Any]],
) -> dict[str, Any]:
    representative_time = float(representatives[-1]["source_frame_time"])
    rejected_later_states = [
        {
            "source_frame_time": round(float(item["source_frame_time"]), 3),
            "why_later_state_was_rejected": (
                "lower_representative_score_than_selected_frame"
            ),
        }
        for item in suppressed
        if float(item["source_frame_time"]) > representative_time
    ]
    return {
        "collapse_group_id": group_id,
        "group_id": group_id,
        "group_start_time": round(float(group[0]["source_frame_time"]), 3),
        "group_end_time": round(float(group[-1]["source_frame_time"]), 3),
        "candidate_source_frame_times": [
            round(float(item["source_frame_time"]), 3) for item in group
        ],
        "source_frame_times": [
            round(float(item["source_frame_time"]), 3) for item in group
        ],
        "representative_source_frame_time": round(representative_time, 3),
        "representative_times": [
            round(float(item["source_frame_time"]), 3) for item in representatives
        ],
        "representative_score": representatives[-1].get("representative_score"),
        "representative_score_details": representatives[-1].get(
            "representative_score_details",
            {},
        ),
        "representative_candidates": ranked_candidates,
        "suppressed_intermediate_times": [
            round(float(item["source_frame_time"]), 3) for item in suppressed
        ],
        "suppressed_source_frame_times": [
            round(float(item["source_frame_time"]), 3) for item in suppressed
        ],
        "rejected_later_states": rejected_later_states,
        "why_later_state_was_rejected": rejected_later_states,
        "representative_selection_reason": reason,
        "original_count": len(group),
        "collapsed_count": len(representatives),
        "suppressed_count": len(suppressed),
        "replaced_by_later_state": any(
            float(item["source_frame_time"]) < representative_time for item in suppressed
        ),
        "boundary_decision_summary": summarize_boundary_decisions(boundary_decisions),
    }


def finalize_collapse_group(
    group: list[dict[str, Any]],
    options: dict[str, Any],
    group_id: int,
    boundary_decisions: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any] | None]:
    if not group:
        return [], None
    if boundary_decisions is None:
        boundary_decisions = []

    max_representatives = int(options["max_intermediate_keyframes_per_group"])
    if len(group) <= max_representatives:
        output = []
        for item in group:
            item["collapse_group_id"] = None
            item["representative_selection_reason"] = "single_or_below_group_limit"
            score_details = keyframe_fuller_state_score_details(item, options)
            item["representative_score"] = score_details.get("score")
            item["representative_score_details"] = score_details
            item.setdefault("suppressed_intermediate_times", [])
            item.setdefault("replaced_intermediate_keyframes", [])
            output.append(item)
        return output, None

    representatives, ranked_candidates = choose_collapse_representatives(group, options)
    representative_ids = {id(item) for item in representatives}
    suppressed = [item for item in group if id(item) not in representative_ids]
    reason = (
        "fuller_final_state_score"
        if bool(options.get("fuller_state_scoring_enabled"))
        else str(options.get("final_state_preference") or DEFAULT_FINAL_STATE_PREFERENCE)
    )
    group_start = float(group[0]["source_frame_time"])
    group_end = float(group[-1]["source_frame_time"])
    output = [
        merge_suppressed_keyframe_into_representative(
            representative,
            suppressed,
            group_id,
            reason,
            keyframe_fuller_state_score_details(
                representative,
                options,
                group_start,
                group_end,
            ),
        )
        for representative in representatives
    ]
    summary = collapse_group_summary(
        group,
        output,
        suppressed,
        group_id,
        reason,
        ranked_candidates,
        boundary_decisions,
    )
    return output, summary


def build_initial_collapse_groups(
    accepted: list[dict[str, Any]],
    options: dict[str, Any],
) -> tuple[list[list[dict[str, Any]]], list[list[dict[str, Any]]], list[dict[str, Any]]]:
    groups: list[list[dict[str, Any]]] = []
    group_decisions: list[list[dict[str, Any]]] = []
    all_decisions: list[dict[str, Any]] = []
    group = [accepted[0]]
    decisions_for_group: list[dict[str, Any]] = []

    for keyframe in accepted[1:]:
        can_join, decision = can_join_build_group(group, keyframe, options)
        all_decisions.append(decision)
        if can_join:
            decisions_for_group.append(decision)
            group.append(keyframe)
            continue
        groups.append(group)
        group_decisions.append(decisions_for_group)
        group = [keyframe]
        decisions_for_group = []

    groups.append(group)
    group_decisions.append(decisions_for_group)
    return groups, group_decisions, all_decisions


def merge_adjacent_collapse_groups(
    groups: list[list[dict[str, Any]]],
    group_decisions: list[list[dict[str, Any]]],
    options: dict[str, Any],
) -> tuple[list[list[dict[str, Any]]], list[list[dict[str, Any]]], list[dict[str, Any]]]:
    if not bool(options.get("conservative_group_merge_enabled")) or len(groups) <= 1:
        return groups, group_decisions, []

    merged_groups: list[list[dict[str, Any]]] = [groups[0]]
    merged_decisions: list[list[dict[str, Any]]] = [group_decisions[0]]
    merge_decisions: list[dict[str, Any]] = []

    for next_group, next_decisions in zip(groups[1:], group_decisions[1:]):
        current_group = merged_groups[-1]
        can_merge, decision = can_join_build_group(
            current_group,
            next_group[0],
            options,
        )
        decision["decision_context"] = "adjacent_group_merge"
        merge_decisions.append(decision)
        if can_merge:
            merged_groups[-1] = current_group + next_group
            merged_decisions[-1] = merged_decisions[-1] + [decision] + next_decisions
        else:
            merged_groups.append(next_group)
            merged_decisions.append(next_decisions)

    return merged_groups, merged_decisions, merge_decisions


def collapse_process_state_keyframes(
    accepted: list[dict[str, Any]],
    options: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    if not accepted:
        return accepted, empty_animation_collapse_summary(options, 0)
    if not bool(options.get("animation_collapse_enabled")):
        for keyframe in accepted:
            keyframe["collapse_group_id"] = None
            keyframe["representative_selection_reason"] = "animation_collapse_disabled"
            score_details = keyframe_fuller_state_score_details(keyframe, options)
            keyframe["representative_score"] = score_details.get("score")
            keyframe["representative_score_details"] = score_details
            keyframe.setdefault("suppressed_intermediate_times", [])
            keyframe.setdefault("replaced_intermediate_keyframes", [])
        return accepted, empty_animation_collapse_summary(
            options,
            len(accepted),
            enabled=False,
        )

    collapsed: list[dict[str, Any]] = []
    summaries: list[dict[str, Any]] = []
    groups, group_decisions, initial_decisions = build_initial_collapse_groups(
        accepted,
        options,
    )
    groups, group_decisions, merge_decisions = merge_adjacent_collapse_groups(
        groups,
        group_decisions,
        options,
    )
    all_decisions = initial_decisions + merge_decisions
    group_id = 1

    for group, decisions in zip(groups, group_decisions):
        output, summary = finalize_collapse_group(
            group,
            options,
            group_id,
            decisions,
        )
        collapsed.extend(output)
        if summary is not None:
            summaries.append(summary)
            group_id += 1

    suppressed_count = sum(int(item["suppressed_count"]) for item in summaries)
    warning_messages = []
    pre_last_time = max(float(item["source_frame_time"]) for item in accepted)
    post_last_time = (
        max(float(item["source_frame_time"]) for item in collapsed)
        if collapsed
        else None
    )
    if post_last_time is None or post_last_time < pre_last_time:
        warning_messages.append("tail_representative_would_regress_without_guard")
        last_keyframe = accepted[-1]
        if all(id(item) != id(last_keyframe) for item in collapsed):
            last_keyframe["collapse_group_id"] = None
            last_keyframe["representative_selection_reason"] = "tail_guard_preserved"
            score_details = keyframe_fuller_state_score_details(last_keyframe, options)
            last_keyframe["representative_score"] = score_details.get("score")
            last_keyframe["representative_score_details"] = score_details
            last_keyframe.setdefault("suppressed_intermediate_times", [])
            last_keyframe.setdefault("replaced_intermediate_keyframes", [])
            collapsed.append(last_keyframe)
        post_last_time = max(float(item["source_frame_time"]) for item in collapsed)
    decision_limit = int(options.get("report_group_decisions_limit") or 0)
    summary_payload = empty_animation_collapse_summary(
        options,
        original_keyframe_count=len(accepted),
        collapsed_keyframe_count=len(collapsed),
        enabled=True,
    )
    summary_payload.update(
        {
            "collapsed_group_count": len(summaries),
            "intermediate_suppressed_count": suppressed_count,
            "replaced_intermediate_count": suppressed_count,
            "group_boundary_decision_count": len(all_decisions),
            "group_boundary_decisions": all_decisions[:decision_limit],
            "group_boundary_decisions_truncated": len(all_decisions) > decision_limit,
            "boundary_break_reasons": summarize_boundary_decisions(all_decisions).get(
                "break_reasons",
                {},
            ),
            "tail_collapse_check": {
                "pre_collapse_last_source_frame_time": round(pre_last_time, 3),
                "post_collapse_last_source_frame_time": round(
                    float(post_last_time),
                    3,
                ),
                "regressed": bool(post_last_time < pre_last_time),
            },
            "collapse_warnings": warning_messages,
            "warnings": warning_messages,
            "group_summaries": (
                summaries[:MAX_COLLAPSE_GROUP_SUMMARIES]
                if bool(options.get("collapse_report_enabled"))
                else []
            ),
            "group_summary_truncated": len(summaries) > MAX_COLLAPSE_GROUP_SUMMARIES,
        }
    )
    return collapsed, summary_payload


def can_replace_with_fuller_later_candidate(
    keyframe: dict[str, Any],
    candidate_features: dict[str, Any],
    options: dict[str, Any],
) -> tuple[bool, dict[str, Any]]:
    if not bool(options.get("fuller_state_scoring_enabled")):
        return False, {"reason": "fuller_state_scoring_disabled"}
    current_features = keyframe.get("features") or {}
    if not current_features:
        return False, {"reason": "current_keyframe_missing_features"}
    title_difference = feature_region_difference(
        candidate_features,
        current_features,
        "title_region",
    )
    current_score = fuller_state_score_details_from_features(
        current_features,
        options,
    )
    candidate_score = fuller_state_score_details_from_features(
        candidate_features,
        options,
    )
    score_delta = float(candidate_score["score"]) - float(current_score["score"])
    can_replace = (
        title_difference <= float(options["title_region_max_difference"])
        and score_delta >= float(options["fuller_replacement_min_delta"])
    )
    return can_replace, {
        "title_region_difference": round(title_difference, 6),
        "current_score": current_score,
        "candidate_score": candidate_score,
        "score_delta": round(score_delta, 6),
        "reason": (
            "candidate_is_later_fuller_state"
            if can_replace
            else "candidate_not_fuller_or_title_changed"
        ),
    }


def replace_keyframe_with_later_candidate(
    keyframe: dict[str, Any],
    candidate: dict[str, Any],
    features: dict[str, Any],
    quality: dict[str, Any],
    update_reason: str,
    diagnostic: dict[str, Any],
    score_vs_last_keyframe: float,
) -> None:
    previous_time = float(keyframe["source_frame_time"])
    previous_path = str(keyframe["source_frame_path"])
    covered = list(keyframe.get("covered_source_frame_times", []))
    covered.append(float(candidate["time"]))
    history = list(keyframe.get("candidate_replacement_history", []))
    history.append(
        {
            "previous_source_frame_time": round(previous_time, 3),
            "previous_source_frame_path": previous_path,
            "replacement_source_frame_time": round(float(candidate["time"]), 3),
            "replacement_source_frame_path": str(candidate["path"]),
            "update_reason": update_reason,
            "score_vs_previous_representative": round(score_vs_last_keyframe, 6),
            "fuller_state_decision": diagnostic,
        }
    )
    keyframe.update(
        {
            "source_frame_path": candidate["path"],
            "source_frame_time": float(candidate["time"]),
            "reason": update_reason,
            "visual_difference_score": score_vs_last_keyframe,
            "quality_metrics": quality["metrics"],
            "features": features,
            "covered_source_frame_times": sorted({float(value) for value in covered}),
            "candidate_replacement_history": history,
        }
    )


def maybe_replace_keyframe_with_later_candidate(
    keyframe: dict[str, Any],
    candidate: dict[str, Any],
    features: dict[str, Any],
    quality: dict[str, Any],
    update_reason: str,
    score_vs_last_keyframe: float,
    options: dict[str, Any],
    replacement_samples: list[dict[str, Any]],
) -> bool:
    can_replace, diagnostic = can_replace_with_fuller_later_candidate(
        keyframe,
        features,
        options,
    )
    if not can_replace:
        return False
    replace_keyframe_with_later_candidate(
        keyframe,
        candidate,
        features,
        quality,
        update_reason,
        diagnostic,
        score_vs_last_keyframe,
    )
    if len(replacement_samples) < 25:
        replacement_samples.append(keyframe["candidate_replacement_history"][-1])
    return True


def low_content_state_details(
    keyframe: dict[str, Any],
    options: dict[str, Any],
) -> dict[str, Any]:
    score_details = keyframe_fuller_state_score_details(keyframe, options)
    is_low_content = bool(options.get("title_only_penalty_enabled")) and (
        float(score_details["content_area_ratio"])
        <= float(options["low_content_content_area_threshold"])
        and float(score_details["detail_density"])
        <= float(options["low_content_detail_density_threshold"])
        and float(score_details["layout_richness"])
        <= float(options["low_content_layout_richness_threshold"])
    )
    return {
        "is_low_content_title_frame": is_low_content,
        "score_details": score_details,
        "thresholds": {
            "content_area_ratio": options.get("low_content_content_area_threshold"),
            "detail_density": options.get("low_content_detail_density_threshold"),
            "layout_richness": options.get("low_content_layout_richness_threshold"),
        },
    }


def low_content_context_metrics(
    early_state: dict[str, Any],
    later_state: dict[str, Any],
    options: dict[str, Any],
) -> dict[str, Any]:
    early_features = early_state.get("features") or {}
    later_features = later_state.get("features") or {}
    early_score = keyframe_fuller_state_score_details(early_state, options)
    later_score = keyframe_fuller_state_score_details(later_state, options)
    title_difference = feature_region_difference(
        later_features,
        early_features,
        "title_region",
    )
    slide_difference = feature_region_difference(
        later_features,
        early_features,
        "slide_region",
    )
    score_delta = float(later_score["score"]) - float(early_score["score"])
    return {
        "title_region_difference": round(title_difference, 6),
        "slide_region_difference": round(slide_difference, 6),
        "early_score": early_score,
        "later_score": later_score,
        "score_delta": round(score_delta, 6),
        "same_context": (
            title_difference
            <= float(options["low_content_title_region_max_difference"])
            and slide_difference
            <= float(options["low_content_slide_region_max_difference"])
        ),
        "fuller_enough": score_delta
        >= float(options["fuller_replacement_min_delta"]),
    }


def accepted_keyframe_from_candidate_record(
    candidate_record: dict[str, Any],
    early_state: dict[str, Any],
    diagnostic: dict[str, Any],
) -> dict[str, Any]:
    covered = list(early_state.get("covered_source_frame_times", []))
    covered.append(float(candidate_record["source_frame_time"]))
    return {
        "source_frame_path": candidate_record["source_frame_path"],
        "source_frame_time": float(candidate_record["source_frame_time"]),
        "reason": "low_content_lookahead_fuller_state_update",
        "visual_difference_score": float(
            diagnostic.get("slide_region_difference") or 0.0
        ),
        "quality_metrics": candidate_record.get("quality_metrics", {}),
        "merged_source_frame_count": len({float(value) for value in covered}),
        "covered_source_frame_times": sorted({float(value) for value in covered}),
        "duplicate_suppressed_count": 0,
        "features": candidate_record.get("features") or {},
        "candidate_replacement_history": [],
        "low_content_replacement_history": [
            {
                "previous_source_frame_time": round(
                    float(early_state["source_frame_time"]),
                    3,
                ),
                "replacement_source_frame_time": round(
                    float(candidate_record["source_frame_time"]),
                    3,
                ),
                "update_reason": "low_content_lookahead_fuller_state_update",
                "fuller_state_decision": diagnostic,
            }
        ],
    }


def find_later_fuller_accepted_state(
    early_state: dict[str, Any],
    accepted: list[dict[str, Any]],
    options: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    early_time = float(early_state["source_frame_time"])
    lookahead_seconds = float(options["low_content_lookahead_seconds"])
    best_state = None
    best_diagnostic = None
    last_matching_state = None
    for later_state in accepted:
        later_time = float(later_state["source_frame_time"])
        if later_time <= early_time:
            continue
        if later_time - early_time > lookahead_seconds:
            break
        if last_matching_state is not None and best_state is not None:
            transition = collapse_pair_metrics(last_matching_state, later_state)
            if (
                float(transition["title_region_difference"])
                > float(options["low_content_title_region_max_difference"])
                and float(transition["visual_difference_score"])
                >= float(options["min_visual_difference_score"])
            ):
                break
        diagnostic = low_content_context_metrics(early_state, later_state, options)
        if not bool(diagnostic["same_context"]):
            continue
        last_matching_state = later_state
        if not bool(diagnostic["fuller_enough"]):
            continue
        if (
            best_diagnostic is None
            or float(diagnostic["later_score"]["score"])
            > float(best_diagnostic["later_score"]["score"])
        ):
            best_state = later_state
            best_diagnostic = diagnostic
    return best_state, best_diagnostic


def candidate_record_as_keyframe(candidate_record: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_frame_path": candidate_record["source_frame_path"],
        "source_frame_time": float(candidate_record["source_frame_time"]),
        "features": candidate_record.get("features") or {},
    }


def find_later_fuller_candidate_record(
    early_state: dict[str, Any],
    candidate_records: list[dict[str, Any]],
    options: dict[str, Any],
) -> tuple[dict[str, Any] | None, dict[str, Any] | None]:
    early_time = float(early_state["source_frame_time"])
    lookahead_seconds = float(options["low_content_lookahead_seconds"])
    best_record = None
    best_diagnostic = None
    last_matching_state = None
    for candidate_record in candidate_records:
        later_time = float(candidate_record["source_frame_time"])
        if later_time <= early_time or not bool(candidate_record.get("quality_accepted")):
            continue
        if later_time - early_time > lookahead_seconds:
            break
        later_state = candidate_record_as_keyframe(candidate_record)
        if last_matching_state is not None and best_record is not None:
            transition = collapse_pair_metrics(last_matching_state, later_state)
            if (
                float(transition["title_region_difference"])
                > float(options["low_content_title_region_max_difference"])
                and float(transition["visual_difference_score"])
                >= float(options["min_visual_difference_score"])
            ):
                break
        diagnostic = low_content_context_metrics(early_state, later_state, options)
        if not bool(diagnostic["same_context"]):
            continue
        last_matching_state = later_state
        if not bool(diagnostic["fuller_enough"]):
            continue
        if (
            best_diagnostic is None
            or float(diagnostic["later_score"]["score"])
            > float(best_diagnostic["later_score"]["score"])
        ):
            best_record = candidate_record
            best_diagnostic = diagnostic
    return best_record, best_diagnostic


def find_covering_accepted_keyframe(
    accepted: list[dict[str, Any]],
    source_frame_time: float,
) -> dict[str, Any] | None:
    for keyframe in accepted:
        covered_times = keyframe.get("covered_source_frame_times", [])
        if (
            abs(float(keyframe["source_frame_time"]) - source_frame_time) < 0.001
            or any(abs(float(value) - source_frame_time) < 0.001 for value in covered_times)
        ):
            return keyframe
    return None


def suppress_low_content_early_states(
    accepted: list[dict[str, Any]],
    candidate_records: list[dict[str, Any]],
    options: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    summary = {
        "enabled": bool(options.get("low_content_lookahead_enabled")),
        "lookahead_seconds": options.get("low_content_lookahead_seconds"),
        "title_slide_keep_policy": options.get("title_slide_keep_policy"),
        "detected_count": 0,
        "suppressed_count": 0,
        "inserted_candidate_count": 0,
        "kept_count": 0,
        "decisions": [],
    }
    if not bool(options.get("low_content_lookahead_enabled")):
        return accepted, summary

    suppressed_ids: set[int] = set()
    inserted: list[dict[str, Any]] = []
    for early_state in accepted:
        if id(early_state) in suppressed_ids:
            continue
        low_content = low_content_state_details(early_state, options)
        if not bool(low_content["is_low_content_title_frame"]):
            continue
        summary["detected_count"] += 1
        later_state, diagnostic = find_later_fuller_accepted_state(
            early_state,
            accepted,
            options,
        )
        selected_source = "post_group_collapse_keyframes"
        candidate_record = None
        if later_state is None:
            candidate_record, diagnostic = find_later_fuller_candidate_record(
                early_state,
                candidate_records,
                options,
            )
            selected_source = "candidate_pool"
            if candidate_record is not None:
                covered_by = find_covering_accepted_keyframe(
                    accepted,
                    float(candidate_record["source_frame_time"]),
                )
                if covered_by is not None:
                    later_state = covered_by
                    selected_source = "post_group_collapse_covered_candidate"

        early_time = round(float(early_state["source_frame_time"]), 3)
        if later_state is None and candidate_record is None:
            summary["kept_count"] += 1
            summary["decisions"].append(
                {
                    "current_representative_time": early_time,
                    "low_content_title_frame_warning": True,
                    "fuller_state_found_later": False,
                    "replacement_or_keep_reason": (
                        "kept_low_content_state_no_fuller_same_context_candidate"
                    ),
                    "selected_source": None,
                    "selected_fuller_state_time": None,
                    "classified_root_cause": "human_review_ambiguity",
                    "sampling_miss_warning": True,
                    "diagnostic": low_content,
                }
            )
            continue

        selected_time = float(
            later_state["source_frame_time"]
            if later_state is not None
            else candidate_record["source_frame_time"]
        )
        suppressed_ids.add(id(early_state))
        summary["suppressed_count"] += 1
        if later_state is not None:
            covered = list(later_state.get("covered_source_frame_times", []))
            covered.extend(early_state.get("covered_source_frame_times", []))
            later_state["covered_source_frame_times"] = sorted(
                {float(value) for value in covered}
            )
            later_state["merged_source_frame_count"] = len(
                later_state["covered_source_frame_times"]
            )
            history = list(later_state.get("low_content_replacement_history", []))
            history.append(
                {
                    "previous_source_frame_time": early_time,
                    "replacement_source_frame_time": round(selected_time, 3),
                    "update_reason": "low_content_lookahead_suppressed_early_state",
                    "fuller_state_decision": diagnostic,
                }
            )
            later_state["low_content_replacement_history"] = history
        else:
            inserted.append(
                accepted_keyframe_from_candidate_record(
                    candidate_record,
                    early_state,
                    diagnostic or {},
                )
            )
            summary["inserted_candidate_count"] += 1

        summary["decisions"].append(
            {
                "current_representative_time": early_time,
                "low_content_title_frame_warning": True,
                "fuller_state_found_later": True,
                "replacement_or_keep_reason": (
                    "suppressed_early_state_for_later_fuller_same_context"
                ),
                "selected_source": selected_source,
                "matched_candidate_time": (
                    round(float(candidate_record["source_frame_time"]), 3)
                    if candidate_record is not None
                    else None
                ),
                "selected_fuller_state_time": round(selected_time, 3),
                "classified_root_cause": (
                    "group_boundary_miss"
                    if selected_source
                    in {
                        "post_group_collapse_keyframes",
                        "post_group_collapse_covered_candidate",
                    }
                    else "initial_selection_miss"
                ),
                "sampling_miss_warning": False,
                "diagnostic": diagnostic,
            }
        )

    filtered = [
        keyframe for keyframe in accepted if id(keyframe) not in suppressed_ids
    ]
    filtered.extend(inserted)
    filtered.sort(key=lambda item: float(item["source_frame_time"]))
    return filtered, summary


def is_short_interval_scene_change(
    current_features: dict[str, Any],
    last_features: dict[str, Any],
    score_vs_last_keyframe: float,
    options: dict[str, Any],
) -> bool:
    title_difference = feature_region_difference(
        current_features,
        last_features,
        "title_region",
    )
    return (
        title_difference > float(options["title_region_max_difference"])
        and score_vs_last_keyframe >= float(options["min_visual_difference_score"])
    )


def make_candidate_pool_diagnostics(
    fuller_state_update_count: int,
    replacement_samples: list[dict[str, Any]],
) -> dict[str, Any]:
    return {
        "fuller_state_update_count": fuller_state_update_count,
        "representative_update_samples": replacement_samples,
        "diagnostic_note": (
            "Later candidates with the same title/layout can replace an earlier "
            "accepted state when lightweight fullness scoring improves."
        ),
    }


def time_is_present(items: list[dict[str, Any]], target_time: float | None) -> bool:
    if target_time is None:
        return False
    return any(
        abs(float(item["source_frame_time"]) - float(target_time)) < 0.001
        for item in items
    )


def source_times_in_window(
    items: list[dict[str, Any]],
    start_time: float,
    end_time: float,
    limit: int = 30,
) -> list[float]:
    values = [
        round(float(item["source_frame_time"]), 3)
        for item in items
        if start_time <= float(item["source_frame_time"]) <= end_time
    ]
    return values[:limit]


def collapse_group_for_time(
    animation_collapse: dict[str, Any],
    source_frame_time: float | None,
) -> dict[str, Any] | None:
    if source_frame_time is None:
        return None
    for group in animation_collapse.get("group_summaries", []):
        if any(
            abs(float(candidate_time) - float(source_frame_time)) < 0.001
            for candidate_time in group.get("candidate_source_frame_times", [])
        ):
            return group
    return None


def make_final_state_trace_window(
    case_or_window_id: str,
    current_time: float,
    selected_time: float | None,
    start_time: float,
    end_time: float,
    candidate_records: list[dict[str, Any]],
    initial_accepted: list[dict[str, Any]],
    pre_collapse_accepted: list[dict[str, Any]],
    final_keyframes: list[dict[str, Any]],
    animation_collapse: dict[str, Any],
    classified_root_cause: str,
    replacement_or_keep_reason: str,
    repair_applied: str | None,
    low_content_title_frame_warning: bool,
    sampling_miss_warning: bool,
    initial_selection_miss_warning: bool,
    group_boundary_miss_warning: bool,
    representative_selection_miss_warning: bool = False,
    report_only_ambiguity_warning: bool = False,
    matched_candidate_time: float | None = None,
    selected_source: str | None = None,
) -> dict[str, Any]:
    selected_group = collapse_group_for_time(animation_collapse, selected_time)
    representative_time = (
        float(selected_group["representative_source_frame_time"])
        if selected_group is not None
        else selected_time
    )
    final_output_presence = time_is_present(final_keyframes, representative_time)
    return {
        "case_or_window_id": case_or_window_id,
        "window_start_time": round(start_time, 3),
        "window_end_time": round(end_time, 3),
        "current_representative_time": round(current_time, 3),
        "candidate_presence": time_is_present(candidate_records, selected_time),
        "candidate_frame_times": source_times_in_window(
            candidate_records,
            start_time,
            end_time,
        ),
        "initial_selection_presence": time_is_present(initial_accepted, selected_time),
        "initial_selection_times": source_times_in_window(
            initial_accepted,
            start_time,
            end_time,
        ),
        "pre_collapse_presence": time_is_present(pre_collapse_accepted, selected_time),
        "pre_collapse_times": source_times_in_window(
            pre_collapse_accepted,
            start_time,
            end_time,
        ),
        "collapse_group_presence": selected_group is not None,
        "collapse_group_id": (
            selected_group.get("collapse_group_id")
            if selected_group is not None
            else None
        ),
        "representative_decision": replacement_or_keep_reason,
        "selected_source": selected_source,
        "matched_candidate_time": (
            round(float(matched_candidate_time), 3)
            if matched_candidate_time is not None
            else None
        ),
        "covering_representative_time": (
            round(float(representative_time), 3)
            if matched_candidate_time is not None
            and representative_time is not None
            and abs(float(matched_candidate_time) - float(representative_time)) >= 0.001
            else None
        ),
        "representative_time": (
            round(float(representative_time), 3)
            if representative_time is not None
            else None
        ),
        "final_output_presence": final_output_presence,
        "classified_root_cause": classified_root_cause,
        "sampling_miss_warning": sampling_miss_warning,
        "initial_selection_miss_warning": initial_selection_miss_warning,
        "group_boundary_miss_warning": group_boundary_miss_warning,
        "representative_selection_miss_warning": (
            representative_selection_miss_warning
        ),
        "report_only_ambiguity_warning": report_only_ambiguity_warning,
        "low_content_title_frame_warning": low_content_title_frame_warning,
        "fuller_state_found_later": selected_time is not None,
        "replacement_or_keep_reason": replacement_or_keep_reason,
        "repair_applied": repair_applied,
    }


def build_final_state_trace(
    candidate_records: list[dict[str, Any]],
    initial_accepted: list[dict[str, Any]],
    pre_collapse_accepted: list[dict[str, Any]],
    final_keyframes: list[dict[str, Any]],
    animation_collapse: dict[str, Any],
    low_content_lookahead: dict[str, Any],
    options: dict[str, Any],
) -> dict[str, Any]:
    report_limit = int(options["final_state_trace_report_limit"])
    trace = {
        "enabled": bool(options.get("final_state_trace_enabled")),
        "traced_window_count": 0,
        "traced_windows": [],
        "truncated": False,
        "adaptive_rescan": {
            "enabled": bool(options.get("adaptive_rescan_enabled")),
            "interval_seconds": options.get("adaptive_rescan_interval_seconds"),
            "window_seconds": options.get("adaptive_rescan_window_seconds"),
            "status": (
                "disabled_by_default"
                if not bool(options.get("adaptive_rescan_enabled"))
                else "hook_enabled_not_executed"
            ),
        },
    }
    if not bool(options.get("final_state_trace_enabled")):
        return trace

    traced_windows = []
    lookahead_seconds = float(options["low_content_lookahead_seconds"])
    for index, decision in enumerate(low_content_lookahead.get("decisions", []), start=1):
        current_time = float(decision["current_representative_time"])
        selected_time = decision.get("selected_fuller_state_time")
        selected_source = decision.get("selected_source")
        matched_candidate_time = decision.get("matched_candidate_time")
        classified_root_cause = str(decision.get("classified_root_cause"))
        traced_windows.append(
            make_final_state_trace_window(
                case_or_window_id=f"auto_low_content_{index:03d}",
                current_time=current_time,
                selected_time=(
                    float(selected_time) if selected_time is not None else None
                ),
                start_time=current_time,
                end_time=current_time + lookahead_seconds,
                candidate_records=candidate_records,
                initial_accepted=initial_accepted,
                pre_collapse_accepted=pre_collapse_accepted,
                final_keyframes=final_keyframes,
                animation_collapse=animation_collapse,
                classified_root_cause=classified_root_cause,
                replacement_or_keep_reason=str(
                    decision.get("replacement_or_keep_reason")
                ),
                repair_applied=(
                    "low_content_lookahead"
                    if bool(decision.get("fuller_state_found_later"))
                    else None
                ),
                low_content_title_frame_warning=True,
                sampling_miss_warning=bool(decision.get("sampling_miss_warning")),
                initial_selection_miss_warning=(
                    selected_source == "candidate_pool"
                ),
                group_boundary_miss_warning=(
                    selected_source
                    in {
                        "post_group_collapse_keyframes",
                        "post_group_collapse_covered_candidate",
                    }
                ),
                matched_candidate_time=(
                    float(matched_candidate_time)
                    if matched_candidate_time is not None
                    else None
                ),
                selected_source=(
                    str(selected_source) if selected_source is not None else None
                ),
            )
        )

    for index, decision in enumerate(
        animation_collapse.get("group_boundary_decisions", []),
        start=1,
    ):
        overridden_reasons = decision.get("overridden_break_reasons", [])
        if not overridden_reasons:
            continue
        current_time = float(decision["from_source_frame_time"])
        selected_time = float(decision["candidate_source_frame_time"])
        traced_windows.append(
            make_final_state_trace_window(
                case_or_window_id=f"auto_boundary_override_{index:03d}",
                current_time=current_time,
                selected_time=selected_time,
                start_time=current_time,
                end_time=selected_time,
                candidate_records=candidate_records,
                initial_accepted=initial_accepted,
                pre_collapse_accepted=pre_collapse_accepted,
                final_keyframes=final_keyframes,
                animation_collapse=animation_collapse,
                classified_root_cause="group_boundary_miss",
                replacement_or_keep_reason=(
                    "joined_by_strong_title_continuity_override"
                ),
                repair_applied="strong_title_continuity_boundary_override",
                low_content_title_frame_warning=False,
                sampling_miss_warning=False,
                initial_selection_miss_warning=False,
                group_boundary_miss_warning=True,
            )
        )

    trace["traced_window_count"] = len(traced_windows)
    trace["traced_windows"] = traced_windows[:report_limit]
    trace["truncated"] = len(traced_windows) > report_limit
    return trace


def select_keyframes(
    candidates: list[dict[str, Any]],
    options: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
    Image, ImageStat = import_pillow()
    accepted: list[dict[str, Any]] = []
    previous_valid_features: dict[str, Any] | None = None
    accepted_frame_count = 0
    rejected_frame_count = 0
    rejected_reasons: dict[str, int] = {}
    rejected_frame_samples: list[dict[str, Any]] = []
    first_valid_frame_count = 0
    difference_accepted_count = 0
    duplicate_rejected_count = 0
    duplicate_suppressed_count = 0
    stable_too_short_rejected_count = 0
    low_difference_rejected_count = 0
    max_keyframes_reached = False
    comparison_region: dict[str, Any] | None = None
    fuller_state_update_count = 0
    fuller_state_update_samples: list[dict[str, Any]] = []
    candidate_records: list[dict[str, Any]] = []

    for candidate in candidates:
        features = image_features(candidate["path"], Image, ImageStat, options)
        comparison_region = comparison_region or features.get("comparison_region")
        quality = evaluate_frame_quality(features, options)
        candidate_record = {
            "source_frame_path": candidate["path"],
            "source_frame_time": float(candidate["time"]),
            "features": features,
            "quality_accepted": bool(quality["accepted"]),
            "quality_metrics": quality["metrics"],
            "selection_decision": None,
        }
        candidate_records.append(candidate_record)
        if not quality["accepted"]:
            candidate_record["selection_decision"] = "quality_rejected"
            rejected_frame_count += 1
            for reason in quality["reasons"]:
                increment_count(rejected_reasons, reason)
            if len(rejected_frame_samples) < 25:
                rejected_frame_samples.append(
                    {
                        "source_frame_path": str(candidate["path"]),
                        "source_frame_time": round(float(candidate["time"]), 3),
                        "reasons": quality["reasons"],
                        "metrics": quality["metrics"],
                    }
                )
            continue

        accepted_frame_count += 1
        score = (
            0.0
            if previous_valid_features is None
            else visual_difference_score(features, previous_valid_features)
        )
        previous_valid_features = features

        if not accepted:
            candidate_record["selection_decision"] = "first_accepted_frame"
            accepted.append(
                {
                    "source_frame_path": candidate["path"],
                    "source_frame_time": float(candidate["time"]),
                    "reason": "first_accepted_frame",
                    "visual_difference_score": 0.0,
                    "quality_metrics": quality["metrics"],
                    "merged_source_frame_count": 1,
                    "covered_source_frame_times": [float(candidate["time"])],
                    "duplicate_suppressed_count": 0,
                    "features": features,
                }
            )
            first_valid_frame_count += 1
        else:
            seconds_since_last = float(candidate["time"]) - float(
                accepted[-1]["source_frame_time"]
            )
            last_features = accepted[-1]["features"]
            score_vs_last_keyframe = visual_difference_score(features, last_features)
            hash_distance_vs_last_keyframe = average_hash_difference(
                features["average_hash"],
                last_features["average_hash"],
            )
            duplicate_similarity = 1 - score_vs_last_keyframe
            is_duplicate = (
                duplicate_similarity >= float(options["duplicate_similarity_threshold"])
                and hash_distance_vs_last_keyframe
                <= float(options["duplicate_hash_distance_threshold"])
            )
            if is_duplicate:
                candidate_record["selection_decision"] = "duplicate_suppressed"
                duplicate_rejected_count += 1
                duplicate_suppressed_count += 1
                replaced = maybe_replace_keyframe_with_later_candidate(
                    accepted[-1],
                    candidate,
                    features,
                    quality,
                    "duplicate_fuller_state_update",
                    score_vs_last_keyframe,
                    options,
                    fuller_state_update_samples,
                )
                if replaced:
                    candidate_record["selection_decision"] = (
                        "duplicate_fuller_state_update"
                    )
                    fuller_state_update_count += 1
                accepted[-1]["duplicate_suppressed_count"] += 1
                if not replaced:
                    accepted[-1]["covered_source_frame_times"].append(
                        float(candidate["time"])
                    )
                accepted[-1]["merged_source_frame_count"] = len(
                    accepted[-1]["covered_source_frame_times"]
                )
                continue

            short_interval_scene_change = is_short_interval_scene_change(
                features,
                last_features,
                score_vs_last_keyframe,
                options,
            )
            if (
                seconds_since_last < float(options["min_stable_duration_seconds"])
                and not short_interval_scene_change
            ):
                candidate_record["selection_decision"] = "stable_too_short_rejected"
                stable_too_short_rejected_count += 1
                continue

            if (
                score_vs_last_keyframe >= options["min_visual_difference_score"]
            ):
                candidate_record["selection_decision"] = "visual_difference_threshold"
                accepted.append(
                    {
                        "source_frame_path": candidate["path"],
                        "source_frame_time": float(candidate["time"]),
                        "reason": "visual_difference_threshold",
                        "visual_difference_score": score_vs_last_keyframe,
                        "quality_metrics": quality["metrics"],
                        "merged_source_frame_count": 1,
                        "covered_source_frame_times": [float(candidate["time"])],
                        "duplicate_suppressed_count": 0,
                        "features": features,
                    }
                )
                difference_accepted_count += 1
            else:
                replaced = maybe_replace_keyframe_with_later_candidate(
                    accepted[-1],
                    candidate,
                    features,
                    quality,
                    "low_difference_fuller_state_update",
                    score_vs_last_keyframe,
                    options,
                    fuller_state_update_samples,
                )
                if replaced:
                    candidate_record["selection_decision"] = (
                        "low_difference_fuller_state_update"
                    )
                    fuller_state_update_count += 1
                    accepted[-1]["merged_source_frame_count"] = len(
                        accepted[-1]["covered_source_frame_times"]
                    )
                    continue
                candidate_record["selection_decision"] = "low_difference_rejected"
                low_difference_rejected_count += 1

        if len(accepted) >= options["max_keyframes"]:
            max_keyframes_reached = True
            break

    quality_summary = make_quality_summary(
        options,
        accepted_frame_count,
        rejected_frame_count,
        rejected_reasons,
        rejected_frame_samples,
    )
    quality_summary["comparison_region"] = comparison_region
    candidate_pool_diagnostics = make_candidate_pool_diagnostics(
        fuller_state_update_count,
        fuller_state_update_samples,
    )
    initial_accepted = list(accepted)
    if not accepted:
        animation_collapse = empty_animation_collapse_summary(options, 0)
    else:
        original_accepted_count = len(accepted)
        accepted, animation_collapse = collapse_process_state_keyframes(
            accepted,
            options,
        )
        animation_collapse["original_keyframe_count"] = original_accepted_count
        animation_collapse["collapsed_keyframe_count"] = len(accepted)
    post_group_collapse_keyframe_count = len(accepted)
    accepted, low_content_lookahead = suppress_low_content_early_states(
        accepted,
        candidate_records,
        options,
    )
    animation_collapse["post_group_collapse_keyframe_count"] = (
        post_group_collapse_keyframe_count
    )
    animation_collapse["collapsed_keyframe_count"] = len(accepted)
    animation_collapse["low_content_lookahead"] = low_content_lookahead
    animation_collapse["final_state_trace"] = build_final_state_trace(
        candidate_records,
        initial_accepted,
        initial_accepted,
        accepted,
        animation_collapse,
        low_content_lookahead,
        options,
    )
    animation_collapse["candidate_pool_diagnostics"] = candidate_pool_diagnostics
    quality_summary["animation_collapse"] = animation_collapse
    quality_summary["candidate_pool_diagnostics"] = candidate_pool_diagnostics
    keyframe_selection = make_keyframe_selection_summary(
        candidates=candidates,
        accepted_count=len(accepted),
        accepted_frame_count=accepted_frame_count,
        first_valid_frame_count=first_valid_frame_count,
        difference_accepted_count=difference_accepted_count,
        duplicate_rejected_count=duplicate_rejected_count,
        duplicate_suppressed_count=duplicate_suppressed_count,
        rejected_frame_count=rejected_frame_count,
        stable_too_short_rejected_count=stable_too_short_rejected_count,
        low_difference_rejected_count=low_difference_rejected_count,
        max_keyframes_reached=max_keyframes_reached,
        options=options,
    )
    keyframe_selection["pre_collapse_keyframe_count"] = animation_collapse.get(
        "original_keyframe_count"
    )
    keyframe_selection["post_collapse_keyframe_count"] = animation_collapse.get(
        "collapsed_keyframe_count"
    )
    keyframe_selection["animation_collapse"] = animation_collapse
    keyframe_selection["candidate_pool_diagnostics"] = candidate_pool_diagnostics
    if not accepted:
        raise NoAcceptableKeyframes(
            "No candidate frames passed quality and difference filters.",
            quality_summary=quality_summary,
            keyframe_selection=keyframe_selection,
            comparison_region=comparison_region,
        )
    for keyframe in accepted:
        keyframe.pop("features", None)

    return accepted, quality_summary, keyframe_selection


def copy_keyframes_to_output(
    accepted_keyframes: list[dict[str, Any]],
    keyframe_dir: Path,
) -> list[dict[str, Any]]:
    clear_generated_visual_files(keyframe_dir, ("keyframe_*.jpg",))
    copied = []
    for index, keyframe in enumerate(accepted_keyframes, start=1):
        frame_time = float(keyframe["source_frame_time"])
        keyframe_path = (
            keyframe_dir / f"keyframe_{index:04d}_t{frame_time_token(frame_time)}.jpg"
        )
        shutil.copy2(keyframe["source_frame_path"], keyframe_path)
        copied.append(
            {
                **keyframe,
                "keyframe_path": keyframe_path,
            }
        )
    return copied


def build_ocr_report(
    options: dict[str, Any],
    processed_keyframe_count: int,
    text_hint_count: int,
    warning: str | None,
    status: str | None = None,
    available: bool | None = None,
) -> dict[str, Any]:
    backend = str(options.get("ocr_backend") or DEFAULT_OCR_BACKEND).strip().lower()
    if available is None:
        available = False
    if status is None:
        status = "skipped" if backend == "none" else "unavailable"
    return {
        "backend": backend,
        "available": available,
        "status": status,
        "processed_keyframe_count": processed_keyframe_count,
        "text_hint_count": text_hint_count,
        "warning": warning,
    }


def clean_ocr_text(text: str, max_chars: int) -> str:
    cleaned = re.sub(r"\s+", " ", text).strip()
    if len(cleaned) > max_chars:
        return cleaned[:max_chars].rstrip()
    return cleaned


def title_hint_from_text(text: str, min_length: int) -> str | None:
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        cleaned = re.sub(r"\s+", " ", line).strip()
        if len(cleaned) >= min_length:
            return cleaned
    cleaned = re.sub(r"\s+", " ", text).strip()
    return cleaned if len(cleaned) >= min_length else None


def enrich_keyframes_with_text_hints(
    keyframes: list[dict[str, Any]],
    options: dict[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    backend = str(options.get("ocr_backend") or DEFAULT_OCR_BACKEND).strip().lower()
    max_chars = int(options.get("ocr_max_chars") or DEFAULT_OCR_MAX_CHARS)
    min_text_length = int(options.get("ocr_min_text_length") or DEFAULT_OCR_MIN_TEXT_LENGTH)

    if backend == "none":
        for keyframe in keyframes:
            keyframe["ocr_available"] = False
            keyframe["ocr_text"] = None
            keyframe["title_hint"] = None
            keyframe["title_extraction_status"] = "skipped"
        return keyframes, build_ocr_report(
            options,
            processed_keyframe_count=0,
            text_hint_count=0,
            warning=None,
            status="skipped",
            available=False,
        )

    if backend != "tesseract":
        warning = f"Unsupported ocr_backend: {backend}."
        for keyframe in keyframes:
            keyframe["ocr_available"] = False
            keyframe["ocr_text"] = None
            keyframe["title_hint"] = None
            keyframe["title_extraction_status"] = "unsupported_backend"
        return keyframes, build_ocr_report(
            options,
            processed_keyframe_count=0,
            text_hint_count=0,
            warning=warning,
            status="unsupported_backend",
            available=False,
        )

    tesseract_path = shutil.which("tesseract")
    if tesseract_path is None:
        warning = "tesseract was not found on PATH."
        for keyframe in keyframes:
            keyframe["ocr_available"] = False
            keyframe["ocr_text"] = None
            keyframe["title_hint"] = None
            keyframe["title_extraction_status"] = "unavailable"
        return keyframes, build_ocr_report(
            options,
            processed_keyframe_count=0,
            text_hint_count=0,
            warning=warning,
            status="unavailable",
            available=False,
        )

    processed = 0
    text_hint_count = 0
    warnings = []
    for keyframe in keyframes:
        command = [tesseract_path, str(keyframe["keyframe_path"]), "stdout"]
        language = optional_string(options.get("ocr_language"))
        if language is not None:
            command.extend(["-l", language])
        try:
            result = subprocess.run(
                command,
                capture_output=True,
                text=True,
                timeout=20,
            )
        except Exception as error:
            keyframe["ocr_available"] = True
            keyframe["ocr_text"] = None
            keyframe["title_hint"] = None
            keyframe["title_extraction_status"] = "failed"
            warnings.append(str(error))
            continue

        processed += 1
        if result.returncode != 0:
            keyframe["ocr_available"] = True
            keyframe["ocr_text"] = None
            keyframe["title_hint"] = None
            keyframe["title_extraction_status"] = "failed"
            if result.stderr.strip():
                warnings.append(result.stderr.strip())
            continue

        raw_text = result.stdout or ""
        title_hint = title_hint_from_text(raw_text, min_text_length)
        ocr_text = clean_ocr_text(raw_text, max_chars) if title_hint is not None else None
        if title_hint is not None:
            text_hint_count += 1
        keyframe["ocr_available"] = True
        keyframe["ocr_text"] = ocr_text
        keyframe["title_hint"] = title_hint
        keyframe["title_extraction_status"] = (
            "extracted" if title_hint is not None else "no_text"
        )

    warning = "; ".join(sorted(set(warnings))) if warnings else None
    return keyframes, build_ocr_report(
        options,
        processed_keyframe_count=processed,
        text_hint_count=text_hint_count,
        warning=warning,
        status="success" if warning is None else "partial_success",
        available=True,
    )


def build_visual_segments(
    keyframes: list[dict[str, Any]],
    options: dict[str, Any],
    duration_seconds: float | None,
) -> list[dict[str, Any]]:
    segment_end_limit = (
        options["smoke_seconds"]
        if options["smoke_seconds"] is not None
        else duration_seconds
    )
    segments = []
    for index, keyframe in enumerate(keyframes, start=1):
        start = float(keyframe["source_frame_time"])
        if index < len(keyframes):
            end = float(keyframes[index]["source_frame_time"])
        elif segment_end_limit is not None and float(segment_end_limit) > start:
            end = float(segment_end_limit)
        else:
            end = start + float(options["frame_interval_seconds"])

        segments.append(
            {
                "id": index,
                "start": round(start, 3),
                "end": round(end, 3),
                "keyframe_path": str(keyframe["keyframe_path"]),
                "source_frame_path": str(keyframe["source_frame_path"]),
                "source_frame_time": round(start, 3),
                "reason": keyframe["reason"],
                "visual_difference_score": round(
                    float(keyframe["visual_difference_score"]),
                    6,
                ),
                "quality_metrics": keyframe.get("quality_metrics", {}),
                "merged_source_frame_count": keyframe.get("merged_source_frame_count", 1),
                "covered_source_frame_times": [
                    round(float(value), 3)
                    for value in keyframe.get("covered_source_frame_times", [start])
                ],
                "duplicate_suppressed_count": keyframe.get(
                    "duplicate_suppressed_count",
                    0,
                ),
                "collapse_group_id": keyframe.get("collapse_group_id"),
                "representative_selection_reason": keyframe.get(
                    "representative_selection_reason",
                ),
                "representative_score": keyframe.get("representative_score"),
                "representative_score_details": keyframe.get(
                    "representative_score_details",
                    {},
                ),
                "suppressed_intermediate_times": [
                    round(float(value), 3)
                    for value in keyframe.get("suppressed_intermediate_times", [])
                ],
                "replaced_intermediate_keyframes": keyframe.get(
                    "replaced_intermediate_keyframes",
                    [],
                ),
                "candidate_replacement_history": keyframe.get(
                    "candidate_replacement_history",
                    [],
                ),
                "low_content_replacement_history": keyframe.get(
                    "low_content_replacement_history",
                    [],
                ),
                "comparison_region_mode": options.get("comparison_region_mode"),
                "ocr_available": keyframe.get("ocr_available", False),
                "ocr_text": keyframe.get("ocr_text"),
                "title_hint": keyframe.get("title_hint"),
                "title_extraction_status": keyframe.get(
                    "title_extraction_status",
                    "skipped",
                ),
            }
        )
    return segments


def import_faster_whisper() -> Any:
    try:
        from faster_whisper import WhisperModel
    except ImportError as error:
        raise RuntimeError(
            "faster-whisper is not installed. Install dependencies with: "
            "pip install -r requirements.txt"
        ) from error
    return WhisperModel


def transcribe_with_faster_whisper(
    video_path: Path,
    model_name: str,
    device: str,
    compute_type: str,
    language: str | None,
    smoke_seconds: float | None,
) -> tuple[list[dict[str, Any]], str | None]:
    WhisperModel = import_faster_whisper()
    model = WhisperModel(model_name, device=device, compute_type=compute_type)
    transcribe_options: dict[str, Any] = {}
    if language is not None:
        transcribe_options["language"] = language

    segments_iterable, info = model.transcribe(str(video_path), **transcribe_options)
    segments: list[dict[str, Any]] = []
    for segment in segments_iterable:
        start = float(segment.start)
        end = float(segment.end)
        if smoke_seconds is not None and start > smoke_seconds:
            break
        text = str(segment.text).strip()
        if not text:
            continue
        segments.append(
            {
                "id": len(segments) + 1,
                "start": start,
                "end": end,
                "text": text,
            }
        )

    detected_language = optional_string(getattr(info, "language", None))
    return segments, detected_language


def write_transcription_raw_transcript(
    run_dir: Path,
    run_id: str,
    report_path: Path,
    video_path: Path,
    report: dict[str, Any],
    segments: list[dict[str, Any]],
    smoke_test: bool,
    smoke_seconds: float | None,
) -> None:
    payload = {
        "run_id": run_id,
        "source": {
            "type": "faster_whisper_fallback",
            "model": report["model"],
            "language": report["configured_language"] or report["detected_language"],
            "video_path": str(video_path),
            "transcription_report_path": str(report_path),
            "smoke_test": smoke_test,
            "smoke_seconds": smoke_seconds,
        },
        "fallback_required": True,
        "fallback_reason": "Subtitle fallback transcription.",
        "segments": segments,
        "segment_count": len(segments),
        "created_at": utc_now(),
    }
    write_json(transcript_path_for_transcription(run_dir, smoke_test), payload)


def run_batch_2_5(
    config_path: Path,
    force_transcription: bool = False,
    smoke_seconds_override: float | None = None,
) -> tuple[Path, dict[str, Any]]:
    config = load_config(config_path.resolve())
    run_id = validate_run_id(str(config["run_id"]))
    run_dir = configured_run_dir(config)

    try:
        configured_smoke_seconds = optional_positive_float(
            smoke_seconds_override
            if smoke_seconds_override is not None
            else config.get("transcription_smoke_seconds")
        )
    except Exception as error:
        return run_dir, failure_transcription_report(
            run_dir, run_id, config, None, False, None, error
        )

    smoke_test = configured_smoke_seconds is not None
    formal_transcript_path = transcript_path_for_transcription(run_dir, False)
    if formal_transcript_path.exists() and not (force_transcription and smoke_test):
        return run_dir, skipped_transcription_report(
            run_dir,
            run_id,
            config,
            None,
            smoke_test,
            configured_smoke_seconds,
            "raw_transcript_exists",
        )

    download_report_path = run_dir / "audit" / "download_report.json"
    if not download_report_path.exists():
        error = FileNotFoundError(f"Missing download report: {download_report_path}")
        return run_dir, failure_transcription_report(
            run_dir, run_id, config, None, smoke_test, configured_smoke_seconds, error
        )

    try:
        download_report = read_json(download_report_path)
    except Exception as error:
        return run_dir, failure_transcription_report(
            run_dir, run_id, config, None, smoke_test, configured_smoke_seconds, error
        )

    video_path = find_existing_video_for_run(run_id, download_report)
    video_path_text = str(video_path) if video_path is not None else optional_string(
        download_report.get("video_path")
    )
    if download_report.get("status") != "success":
        error = RuntimeError("download_report.json status is not success.")
        return run_dir, failure_transcription_report(
            run_dir,
            run_id,
            config,
            video_path_text,
            smoke_test,
            configured_smoke_seconds,
            error,
        )

    subtitle_report_path = run_dir / "audit" / "subtitle_report.json"
    if not subtitle_report_path.exists():
        error = FileNotFoundError(f"Missing subtitle report: {subtitle_report_path}")
        return run_dir, failure_transcription_report(
            run_dir,
            run_id,
            config,
            video_path_text,
            smoke_test,
            configured_smoke_seconds,
            error,
        )

    try:
        subtitle_report = read_json(subtitle_report_path)
    except Exception as error:
        return run_dir, failure_transcription_report(
            run_dir,
            run_id,
            config,
            video_path_text,
            smoke_test,
            configured_smoke_seconds,
            error,
        )

    if not subtitle_report.get("fallback_required") and not (
        force_transcription and smoke_test
    ):
        return run_dir, skipped_transcription_report(
            run_dir,
            run_id,
            config,
            video_path_text,
            smoke_test,
            configured_smoke_seconds,
            "fallback_not_required",
        )

    if video_path is None:
        error = FileNotFoundError("No usable downloaded video file was found.")
        return run_dir, failure_transcription_report(
            run_dir,
            run_id,
            config,
            video_path_text,
            smoke_test,
            configured_smoke_seconds,
            error,
        )

    backend = str(
        config.get("transcription_backend") or DEFAULT_TRANSCRIPTION_BACKEND
    ).strip()
    if backend != "faster-whisper":
        error = ValueError("Batch 2.5 currently supports only faster-whisper.")
        return run_dir, failure_transcription_report(
            run_dir,
            run_id,
            config,
            str(video_path),
            smoke_test,
            configured_smoke_seconds,
            error,
        )

    report = base_transcription_report(
        run_id, config, str(video_path), smoke_test, configured_smoke_seconds
    )
    try:
        segments, detected_language = transcribe_with_faster_whisper(
            video_path=video_path,
            model_name=report["model"],
            device=report["device"],
            compute_type=report["compute_type"],
            language=report["configured_language"],
            smoke_seconds=configured_smoke_seconds,
        )
        if not segments:
            raise RuntimeError("Transcription produced no timed text segments.")
    except Exception as error:
        return run_dir, failure_transcription_report(
            run_dir,
            run_id,
            config,
            str(video_path),
            smoke_test,
            configured_smoke_seconds,
            error,
        )

    report["status"] = "smoke_success" if smoke_test else "success"
    report["detected_language"] = detected_language
    report["segment_count"] = len(segments)
    report["created_at"] = utc_now()
    output_report_path = report_path_for_transcription(run_dir, smoke_test)
    write_transcription_report(run_dir, report, smoke_test)
    write_transcription_raw_transcript(
        run_dir,
        run_id,
        output_report_path,
        video_path,
        report,
        segments,
        smoke_test,
        configured_smoke_seconds,
    )
    return run_dir, report


def run_batch_3(
    config_path: Path,
    frame_interval_override: float | None = None,
    frame_smoke_override: float | None = None,
    max_keyframes_override: int | None = None,
) -> tuple[Path, dict[str, Any]]:
    config = load_config(config_path.resolve())
    run_id = validate_run_id(str(config["run_id"]))
    run_dir = configured_run_dir(config)
    audit_dir = run_dir / "audit"
    frame_dir = Path("data") / "frames" / run_id
    keyframe_dir = run_dir / "assets" / "keyframes"
    audit_dir.mkdir(parents=True, exist_ok=True)
    frame_dir.mkdir(parents=True, exist_ok=True)
    keyframe_dir.mkdir(parents=True, exist_ok=True)

    options: dict[str, Any] = {
        "frame_interval_seconds": DEFAULT_FRAME_INTERVAL_SECONDS,
        "smoke_seconds": frame_smoke_override,
        "max_keyframes": max_keyframes_override or DEFAULT_MAX_KEYFRAMES,
        "min_visual_difference_score": DEFAULT_MIN_VISUAL_DIFFERENCE_SCORE,
        "min_stable_duration_seconds": DEFAULT_MIN_STABLE_DURATION_SECONDS,
        "target_video_height": DEFAULT_TARGET_VIDEO_HEIGHT,
        "min_keyframe_height": DEFAULT_MIN_KEYFRAME_HEIGHT,
    }
    video_path: Path | None = None
    video_path_text: str | None = None
    duration_seconds: float | None = None
    ffmpeg_info: dict[str, Any] | None = None
    frame_count = 0
    keyframe_count = 0
    quality_summary: dict[str, Any] | None = None
    keyframe_selection: dict[str, Any] | None = None
    comparison_region: dict[str, Any] | None = None
    ocr_report: dict[str, Any] | None = None
    resolution_report: dict[str, Any] | None = None
    warnings: list[str] = []

    try:
        options = resolve_visual_options(
            config,
            frame_interval_override,
            frame_smoke_override,
            max_keyframes_override,
        )
        ocr_report = build_ocr_report(
            options,
            processed_keyframe_count=0,
            text_hint_count=0,
            warning=None,
            status="skipped" if options.get("ocr_backend") == "none" else "not_started",
            available=False,
        )
        comparison_region = {
            "mode": options.get("comparison_region_mode"),
            "requested": comparison_region_requested(options),
            "effective": None,
            "status": "not_evaluated",
            "warning": None,
        }
        clear_generated_visual_files(frame_dir, ("frame_*.jpg", "_raw_frame_*.jpg"))
        clear_generated_visual_files(keyframe_dir, ("keyframe_*.jpg",))

        download_report_path = audit_dir / "download_report.json"
        if not download_report_path.exists():
            raise FileNotFoundError(f"Missing download report: {download_report_path}")

        download_report = read_json(download_report_path)
        video_path_text = optional_string(download_report.get("video_path"))
        duration_seconds = optional_duration_seconds(
            download_report.get("duration_seconds")
        )
        if download_report.get("status") != "success":
            raise RuntimeError("download_report.json status is not success.")

        video_path = strict_video_path_from_download_report(download_report)
        video_path_text = str(video_path)
        raw_video_resolution = video_resolution_payload(video_path)
        resolution_report = {
            "raw_video_resolution": raw_video_resolution,
            "extracted_frame_resolution": resolution_payload(
                None,
                None,
                "Candidate frames have not been extracted.",
            ),
            "keyframe_resolution": resolution_payload(
                None,
                None,
                "Keyframes have not been selected.",
            ),
            "resolution_check": {
                "status": "unknown",
                "message": "Keyframe resolution has not been evaluated.",
                "target_height": options.get("target_video_height"),
                "min_keyframe_height": options.get("min_keyframe_height"),
                "actual_keyframe_height": None,
                "warnings": [],
                "errors": [],
            },
        }

        try:
            ffmpeg_info = preflight_ffmpeg()
        except FFmpegNotFound as error:
            ffmpeg_info = {
                "available": False,
                "path": None,
                "version": None,
            }
            raise error
        except FFmpegPreflightFailed as error:
            ffmpeg_info = {
                "available": True,
                "path": find_executable("ffmpeg"),
                "version": None,
            }
            raise error

        candidates = extract_candidate_frames(
            ffmpeg_path=str(ffmpeg_info["path"]),
            video_path=video_path,
            frame_dir=frame_dir,
            frame_interval_seconds=float(options["frame_interval_seconds"]),
            smoke_seconds=options["smoke_seconds"],
        )
        frame_count = len(candidates)
        first_candidate_path = Path(candidates[0]["path"]) if candidates else None
        resolution_report["extracted_frame_resolution"] = image_file_resolution(
            first_candidate_path
        )
        selected_keyframes, quality_summary, keyframe_selection = select_keyframes(
            candidates,
            options,
        )
        comparison_region = quality_summary.get("comparison_region")
        if comparison_region and comparison_region.get("warning"):
            warnings.append(str(comparison_region["warning"]))
        copied_keyframes = copy_keyframes_to_output(selected_keyframes, keyframe_dir)
        copied_keyframes, ocr_report = enrich_keyframes_with_text_hints(
            copied_keyframes,
            options,
        )
        if ocr_report.get("warning"):
            warnings.append(str(ocr_report["warning"]))
        keyframe_count = len(copied_keyframes)
        first_keyframe_path = (
            Path(copied_keyframes[0]["keyframe_path"]) if copied_keyframes else None
        )
        keyframe_resolution = image_file_resolution(first_keyframe_path)
        resolution_report["keyframe_resolution"] = keyframe_resolution
        resolution_report["resolution_check"] = keyframe_resolution_check(
            keyframe_resolution,
            options,
        )
        if resolution_report["resolution_check"]["status"] == "failed":
            raise KeyframeResolutionBelowMinimum(
                resolution_report["resolution_check"]["message"]
            )
        segments = build_visual_segments(
            copied_keyframes,
            options,
            duration_seconds,
        )
        write_visual_segments(
            run_dir,
            run_id,
            video_path,
            keyframe_dir,
            segments,
            smoke_test=options["smoke_seconds"] is not None,
            quality_summary=quality_summary,
            comparison_region=comparison_region,
            ocr_report=ocr_report,
            animation_collapse=keyframe_selection.get("animation_collapse")
            if keyframe_selection
            else None,
        )

        status = "smoke_success" if options["smoke_seconds"] is not None else "success"
        report = frame_report_payload(
            run_id=run_id,
            video_path=str(video_path),
            status=status,
            options=options,
            frame_dir=frame_dir,
            frame_count=frame_count,
            keyframe_dir=keyframe_dir,
            keyframe_count=keyframe_count,
            duration_seconds=duration_seconds,
            ffmpeg_info=ffmpeg_info,
            error=None,
            selection_summary={
                "quality_checks": quality_summary,
                "keyframe_selection": keyframe_selection,
            },
            comparison_region=comparison_region,
            ocr_report=ocr_report,
            resolution_report=resolution_report,
            warnings=warnings,
        )
        return run_dir, write_frame_report(run_dir, report)
    except Exception as error:
        if isinstance(error, FFmpegNotFound) and ffmpeg_info is None:
            ffmpeg_info = {
                "available": False,
                "path": None,
                "version": None,
            }
        elif isinstance(error, FFmpegPreflightFailed) and ffmpeg_info is None:
            ffmpeg_info = {
                "available": True,
                "path": find_executable("ffmpeg"),
                "version": None,
            }
        if isinstance(error, NoAcceptableKeyframes):
            quality_summary = error.quality_summary or quality_summary
            keyframe_selection = error.keyframe_selection or keyframe_selection
            comparison_region = error.comparison_region or comparison_region
            warnings.extend(error.warnings)

        report = frame_report_payload(
            run_id=run_id,
            video_path=video_path_text or (str(video_path) if video_path else None),
            status="failed",
            options=options,
            frame_dir=frame_dir,
            frame_count=frame_count,
            keyframe_dir=keyframe_dir,
            keyframe_count=keyframe_count,
            duration_seconds=duration_seconds,
            ffmpeg_info=ffmpeg_info,
            error=error,
            selection_summary={
                "quality_checks": quality_summary,
                "keyframe_selection": keyframe_selection,
            },
            comparison_region=comparison_region,
            ocr_report=ocr_report,
            resolution_report=resolution_report,
            warnings=warnings,
        )
        write_frame_report(run_dir, report)
        write_failed_visual_segments(
            run_dir,
            run_id,
            video_path_text or (str(video_path) if video_path else None),
            keyframe_dir,
            error,
            quality_summary=quality_summary,
            keyframe_selection=keyframe_selection,
            comparison_region=comparison_region,
            ocr_report=ocr_report,
        )
        return run_dir, report


def alignment_input_paths(run_dir: Path) -> dict[str, str]:
    return {
        "raw_transcript_path": str(run_dir / "audit" / "raw_transcript.json"),
        "visual_segments_path": str(run_dir / "audit" / "visual_segments.json"),
        "frame_report_path": str(run_dir / "audit" / "frame_report.json"),
        "keyframe_dir": str(run_dir / "assets" / "keyframes"),
    }


def alignment_report_payload(
    run_id: str,
    status: str,
    inputs: dict[str, str],
    transcript_count: int = 0,
    visual_count: int = 0,
    aligned_count: int = 0,
    unaligned_count: int = 0,
    low_confidence_count: int = 0,
    coverage: dict[str, Any] | None = None,
    gap_summary: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
    errors: list[dict[str, str]] | None = None,
    alignments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    errors = errors or []
    return {
        "run_id": run_id,
        "status": status,
        "created_at": utc_now(),
        "method": ALIGNMENT_METHOD,
        "inputs": inputs,
        "transcript_segment_count": transcript_count,
        "visual_segment_count": visual_count,
        "aligned_segment_count": aligned_count,
        "unaligned_segment_count": unaligned_count,
        "low_confidence_segment_count": low_confidence_count,
        "coverage": coverage or {},
        "gap_summary": gap_summary or {},
        "warnings": warnings or [],
        "errors": errors,
        "error": errors[0] if errors else None,
        "alignments": alignments or [],
    }


def write_alignment_report(run_dir: Path, report: dict[str, Any]) -> dict[str, Any]:
    write_json(run_dir / "audit" / "alignment.json", report)
    return report


def failed_alignment_report(
    run_dir: Path,
    run_id: str,
    inputs: dict[str, str],
    error: BaseException,
    transcript_count: int = 0,
    visual_count: int = 0,
    coverage: dict[str, Any] | None = None,
    gap_summary: dict[str, Any] | None = None,
    warnings: list[str] | None = None,
) -> dict[str, Any]:
    report = alignment_report_payload(
        run_id=run_id,
        status="failed",
        inputs=inputs,
        transcript_count=transcript_count,
        visual_count=visual_count,
        coverage=coverage,
        gap_summary=gap_summary,
        warnings=warnings,
        errors=[error_payload(error)],
        alignments=[],
    )
    return write_alignment_report(run_dir, report)


def required_json_file(path: Path, error_type: type[RuntimeError]) -> dict[str, Any]:
    if not path.exists():
        raise error_type(f"Missing required Batch 4 input: {path}")
    return read_json(path)


def numeric_field(value: Any, field_name: str, error_type: type[RuntimeError]) -> float:
    if isinstance(value, bool) or value is None or value == "":
        raise error_type(f"Missing numeric field `{field_name}`.")
    try:
        return float(value)
    except (TypeError, ValueError) as error:
        raise error_type(f"Invalid numeric field `{field_name}`: {value!r}") from error


def normalize_transcript_segments(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise InvalidTranscriptSegment("raw_transcript.json must contain non-empty segments.")

    segments: list[dict[str, Any]] = []
    for index, segment in enumerate(raw_segments):
        if not isinstance(segment, dict):
            raise InvalidTranscriptSegment(f"Transcript segment {index} is not an object.")
        start = numeric_field(segment.get("start"), "start", InvalidTranscriptSegment)
        end = numeric_field(segment.get("end"), "end", InvalidTranscriptSegment)
        if start >= end:
            raise InvalidTimeline(
                f"Transcript segment {index} has start >= end: {start} >= {end}."
            )
        text = optional_string(segment.get("text"))
        if text is None:
            raise InvalidTranscriptSegment(f"Transcript segment {index} has no text.")
        segments.append(
            {
                "id": segment.get("id") or index + 1,
                "index": index,
                "start": start,
                "end": end,
                "text": text,
            }
        )
    return segments


def normalize_visual_segments(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise InvalidVisualSegment("visual_segments.json must contain non-empty segments.")

    segments: list[dict[str, Any]] = []
    for index, segment in enumerate(raw_segments):
        if not isinstance(segment, dict):
            raise InvalidVisualSegment(f"Visual segment {index} is not an object.")
        start = numeric_field(segment.get("start"), "start", InvalidVisualSegment)
        end = numeric_field(segment.get("end"), "end", InvalidVisualSegment)
        if start >= end:
            raise InvalidTimeline(
                f"Visual segment {index} has start >= end: {start} >= {end}."
            )
        keyframe_text = optional_string(segment.get("keyframe_path"))
        if keyframe_text is None:
            raise InvalidVisualSegment(f"Visual segment {index} has no keyframe_path.")
        keyframe_path = Path(keyframe_text)
        if not keyframe_path.exists():
            raise MissingKeyframeFile(f"Keyframe file not found: {keyframe_path}")
        source_frame_time_value = segment.get("source_frame_time")
        if source_frame_time_value is None or source_frame_time_value == "":
            source_frame_time_value = start
        source_frame_time = numeric_field(
            source_frame_time_value,
            "source_frame_time",
            InvalidVisualSegment,
        )
        segments.append(
            {
                "id": segment.get("id") or index + 1,
                "index": index,
                "start": start,
                "end": end,
                "keyframe_path": keyframe_text,
                "source_frame_time": source_frame_time,
            }
        )
    return segments


def timeline_coverage(
    transcript_segments: list[dict[str, Any]],
    visual_segments: list[dict[str, Any]],
) -> dict[str, Any]:
    transcript_start = min(float(segment["start"]) for segment in transcript_segments)
    transcript_end = max(float(segment["end"]) for segment in transcript_segments)
    visual_start = min(float(segment["start"]) for segment in visual_segments)
    visual_end = max(float(segment["end"]) for segment in visual_segments)
    transcript_duration = max(0.0, transcript_end - transcript_start)
    visual_duration = max(0.0, visual_end - visual_start)
    end_ratio = visual_end / transcript_end if transcript_end > 0 else None
    duration_ratio = (
        visual_duration / transcript_duration if transcript_duration > 0 else None
    )
    return {
        "transcript_start": round(transcript_start, 3),
        "transcript_end": round(transcript_end, 3),
        "visual_start": round(visual_start, 3),
        "visual_end": round(visual_end, 3),
        "visual_to_transcript_end_ratio": (
            round(end_ratio, 6) if end_ratio is not None else None
        ),
        "visual_to_transcript_duration_ratio": (
            round(duration_ratio, 6) if duration_ratio is not None else None
        ),
        "transcript_duration_seconds": round(transcript_duration, 3),
        "visual_duration_seconds": round(visual_duration, 3),
    }


def gap_summary(
    transcript_segments: list[dict[str, Any]],
    visual_segments: list[dict[str, Any]],
) -> dict[str, Any]:
    def summarize(segments: list[dict[str, Any]]) -> tuple[int, float]:
        sorted_segments = sorted(segments, key=lambda item: float(item["start"]))
        gaps = []
        for previous, current in zip(sorted_segments, sorted_segments[1:]):
            gap = float(current["start"]) - float(previous["end"])
            if gap > 0.001:
                gaps.append(gap)
        return len(gaps), round(max(gaps), 3) if gaps else 0.0

    transcript_gap_count, largest_transcript_gap = summarize(transcript_segments)
    visual_gap_count, largest_visual_gap = summarize(visual_segments)
    return {
        "transcript_gap_count": transcript_gap_count,
        "visual_gap_count": visual_gap_count,
        "largest_transcript_gap_seconds": largest_transcript_gap,
        "largest_visual_gap_seconds": largest_visual_gap,
    }


def overlap_seconds(left: dict[str, Any], right: dict[str, Any]) -> float:
    return max(0.0, min(float(left["end"]), float(right["end"])) - max(float(left["start"]), float(right["start"])))


def distance_seconds(transcript: dict[str, Any], visual: dict[str, Any]) -> float:
    transcript_start = float(transcript["start"])
    transcript_end = float(transcript["end"])
    visual_start = float(visual["start"])
    visual_end = float(visual["end"])
    if transcript_end < visual_start:
        boundary_distance = visual_start - transcript_end
    elif visual_end < transcript_start:
        boundary_distance = transcript_start - visual_end
    else:
        boundary_distance = 0.0
    transcript_midpoint = (transcript_start + transcript_end) / 2
    source_distance = abs(transcript_midpoint - float(visual["source_frame_time"]))
    return min(boundary_distance, source_distance)


def build_alignment_items(
    transcript_segments: list[dict[str, Any]],
    visual_segments: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    alignments = []
    for transcript in transcript_segments:
        overlaps = [
            (overlap_seconds(transcript, visual), visual)
            for visual in visual_segments
        ]
        best_overlap, best_visual = max(overlaps, key=lambda item: item[0])
        if best_overlap > 0:
            transcript_duration = float(transcript["end"]) - float(transcript["start"])
            overlap_ratio = best_overlap / transcript_duration if transcript_duration > 0 else 0.0
            confidence = "high" if overlap_ratio >= 0.5 else "medium"
            match_reason = "time_overlap"
            distance = 0.0
            quality_flags: list[str] = []
        else:
            distance, best_visual = min(
                (
                    distance_seconds(transcript, visual),
                    visual,
                )
                for visual in visual_segments
            )
            best_overlap = 0.0
            if distance <= NEAREST_VISUAL_MATCH_MAX_DISTANCE_SECONDS:
                confidence = "low"
                match_reason = "nearest_visual_segment"
                quality_flags = ["no_time_overlap"]
            else:
                alignments.append(
                    {
                        "transcript_segment_id": transcript["id"],
                        "transcript_index": transcript["index"],
                        "transcript_start": round(float(transcript["start"]), 3),
                        "transcript_end": round(float(transcript["end"]), 3),
                        "transcript_text": transcript["text"],
                        "matched_visual_segment_id": None,
                        "visual_start": None,
                        "visual_end": None,
                        "keyframe_path": None,
                        "source_frame_time": None,
                        "match_reason": "unaligned",
                        "overlap_seconds": 0.0,
                        "distance_seconds": round(distance, 3),
                        "confidence": "none",
                        "quality_flags": ["no_visual_segment_match"],
                    }
                )
                continue

        alignments.append(
            {
                "transcript_segment_id": transcript["id"],
                "transcript_index": transcript["index"],
                "transcript_start": round(float(transcript["start"]), 3),
                "transcript_end": round(float(transcript["end"]), 3),
                "transcript_text": transcript["text"],
                "matched_visual_segment_id": best_visual["id"],
                "visual_start": round(float(best_visual["start"]), 3),
                "visual_end": round(float(best_visual["end"]), 3),
                "keyframe_path": best_visual["keyframe_path"],
                "source_frame_time": round(float(best_visual["source_frame_time"]), 3),
                "match_reason": match_reason,
                "overlap_seconds": round(best_overlap, 3),
                "distance_seconds": round(distance, 3),
                "confidence": confidence,
                "quality_flags": quality_flags,
            }
        )
    return alignments


def run_batch_4(config_path: Path) -> tuple[Path, dict[str, Any]]:
    config = load_config(config_path.resolve())
    run_id = validate_run_id(str(config["run_id"]))
    run_dir = configured_run_dir(config)
    audit_dir = run_dir / "audit"
    audit_dir.mkdir(parents=True, exist_ok=True)
    inputs = alignment_input_paths(run_dir)
    transcript_segments: list[dict[str, Any]] = []
    visual_segments: list[dict[str, Any]] = []
    coverage: dict[str, Any] | None = None
    gaps: dict[str, Any] | None = None

    try:
        raw_transcript_path = Path(inputs["raw_transcript_path"])
        visual_segments_path = Path(inputs["visual_segments_path"])
        frame_report_path = Path(inputs["frame_report_path"])

        raw_transcript = required_json_file(raw_transcript_path, MissingRawTranscript)
        visual_payload = required_json_file(visual_segments_path, MissingVisualSegments)
        frame_report = required_json_file(frame_report_path, MissingFrameReport)

        transcript_segments = normalize_transcript_segments(raw_transcript)
        visual_segments = normalize_visual_segments(visual_payload)
        coverage = timeline_coverage(transcript_segments, visual_segments)
        gaps = gap_summary(transcript_segments, visual_segments)

        if frame_report.get("smoke_test") is True:
            raise VisualEvidenceIsSmoke(
                "frame_report.json is smoke visual evidence. "
                "Materialize full-video visual evidence before Batch 4 alignment."
            )
        if visual_payload.get("status") == "smoke_success":
            raise VisualEvidenceIsSmoke(
                "visual_segments.json has status smoke_success. "
                "Materialize full-video visual evidence before Batch 4 alignment."
            )
        if visual_payload.get("status") != "success":
            raise InvalidVisualSegment(
                "visual_segments.json status must be success for Batch 4 alignment."
            )

        ratio = coverage.get("visual_to_transcript_end_ratio")
        if ratio is not None and float(ratio) < MIN_VISUAL_TRANSCRIPT_COVERAGE_RATIO:
            raise VisualCoverageTooShort(
                "visual_segments.json coverage is too short for the transcript timeline. "
                "Materialize full-video visual evidence before Batch 4 alignment."
            )

        alignments = build_alignment_items(transcript_segments, visual_segments)
        unaligned_count = sum(
            1 for item in alignments if item["confidence"] == "none"
        )
        low_confidence_count = sum(
            1 for item in alignments if item["confidence"] == "low"
        )
        report = alignment_report_payload(
            run_id=run_id,
            status="success",
            inputs=inputs,
            transcript_count=len(transcript_segments),
            visual_count=len(visual_segments),
            aligned_count=len(alignments) - unaligned_count,
            unaligned_count=unaligned_count,
            low_confidence_count=low_confidence_count,
            coverage=coverage,
            gap_summary=gaps,
            warnings=[],
            errors=[],
            alignments=alignments,
        )
        return run_dir, write_alignment_report(run_dir, report)
    except Exception as error:
        return run_dir, failed_alignment_report(
            run_dir=run_dir,
            run_id=run_id,
            inputs=inputs,
            error=error,
            transcript_count=len(transcript_segments),
            visual_count=len(visual_segments),
            coverage=coverage,
            gap_summary=gaps,
        )


def run_batch_2(config_path: Path) -> tuple[Path, dict[str, Any]]:
    config, run_dir = initialize_run(config_path)
    download_report, video_info = download_video(config, run_dir)
    if download_report["status"] != "success" or video_info is None:
        return run_dir, download_report
    download_and_parse_subtitles(config, run_dir, video_info)
    return run_dir, download_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run lecture video pipeline batches."
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to the YAML config file.",
    )
    parser.add_argument(
        "--transcribe-fallback-only",
        action="store_true",
        help="Run only Batch 2.5 fallback transcription checks and transcription.",
    )
    parser.add_argument(
        "--force-transcription",
        action="store_true",
        help="Allow smoke-test transcription even when a formal transcript exists.",
    )
    parser.add_argument(
        "--transcription-smoke-seconds",
        type=float,
        help="Limit Batch 2.5 smoke transcription output to the first N seconds.",
    )
    parser.add_argument(
        "--extract-visuals-only",
        action="store_true",
        help="Run only Batch 3 visual evidence extraction.",
    )
    parser.add_argument(
        "--align-transcript-visuals-only",
        action="store_true",
        help="Run only Batch 4 transcript to visual evidence alignment.",
    )
    parser.add_argument(
        "--generate-content-map-only",
        action="store_true",
        help="Run only Batch 5A deterministic content map, review scaffold, and handout skeleton generation.",
    )
    parser.add_argument(
        "--frame-interval-seconds",
        type=float,
        help="Override the Batch 3 candidate frame interval in seconds.",
    )
    parser.add_argument(
        "--frame-smoke-seconds",
        type=float,
        help="Limit Batch 3 visual extraction to the first N seconds.",
    )
    parser.add_argument(
        "--max-keyframes",
        type=int,
        help="Limit the number of Batch 3 keyframes copied to the output directory.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    if (args.force_transcription or args.transcription_smoke_seconds is not None) and (
        not args.transcribe_fallback_only
    ):
        parser.error(
            "--force-transcription and --transcription-smoke-seconds require "
            "--transcribe-fallback-only."
        )
    if (
        args.frame_interval_seconds is not None
        or args.frame_smoke_seconds is not None
        or args.max_keyframes is not None
    ) and not args.extract_visuals_only:
        parser.error(
            "--frame-interval-seconds, --frame-smoke-seconds, and --max-keyframes "
            "require --extract-visuals-only."
        )
    if args.extract_visuals_only and args.transcribe_fallback_only:
        parser.error("--extract-visuals-only cannot be combined with --transcribe-fallback-only.")
    if args.align_transcript_visuals_only and (
        args.extract_visuals_only
        or args.transcribe_fallback_only
        or args.generate_content_map_only
    ):
        parser.error(
            "--align-transcript-visuals-only cannot be combined with "
            "--extract-visuals-only, --transcribe-fallback-only, or "
            "--generate-content-map-only."
        )
    if args.generate_content_map_only and (
        args.extract_visuals_only or args.transcribe_fallback_only
    ):
        parser.error(
            "--generate-content-map-only cannot be combined with "
            "--extract-visuals-only or --transcribe-fallback-only."
        )

    if args.extract_visuals_only:
        run_dir, frame_report = run_batch_3(
            Path(args.config),
            frame_interval_override=args.frame_interval_seconds,
            frame_smoke_override=args.frame_smoke_seconds,
            max_keyframes_override=args.max_keyframes,
        )
        print(f"Batch 3 output directory: {run_dir}")
        if frame_report["status"] == "failed":
            raise SystemExit(1)
        return

    if args.align_transcript_visuals_only:
        run_dir, alignment_report = run_batch_4(Path(args.config))
        print(f"Batch 4 output directory: {run_dir}")
        if alignment_report["status"] == "failed":
            raise SystemExit(1)
        return

    if args.generate_content_map_only:
        from src.batch5_generation import run_batch_5a

        config = load_config(Path(args.config).resolve())
        run_dir = configured_run_dir(config)
        content_map = run_batch_5a(config, run_dir)
        print(f"Batch 5A output directory: {run_dir}")
        if content_map["status"] != "success":
            raise SystemExit(1)
        return

    if args.transcribe_fallback_only:
        run_dir, transcription_report = run_batch_2_5(
            Path(args.config),
            force_transcription=args.force_transcription,
            smoke_seconds_override=args.transcription_smoke_seconds,
        )
        print(f"Batch 2.5 output directory: {run_dir}")
        if transcription_report["status"] == "failed":
            raise SystemExit(1)
        return

    run_dir, download_report = run_batch_2(Path(args.config))
    print(f"Batch 2 output directory: {run_dir}")
    if download_report["status"] != "success":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
