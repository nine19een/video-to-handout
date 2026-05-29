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


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_scalar(value: str) -> Any:
    stripped = value.strip()
    if not stripped:
        return ""
    if stripped.lower() in {"null", "none", "~"}:
        return None
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
        "error": None,
        "created_at": utc_now(),
    }

    try:
        YoutubeDL = import_yt_dlp()
        ydl_opts = {
            "format": "best[ext=mp4]/best",
            "outtmpl": str(video_dir / "%(id)s.%(ext)s"),
            "noplaylist": True,
            "quiet": False,
            "no_warnings": False,
            "hls_prefer_native": True,
            "nopart": False,
        }
        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(video_url, download=True)
    except Exception as error:
        base_report["error"] = error_payload(error)
        write_json(report_path, base_report)
        return base_report, None

    video_path = find_downloaded_video(info, video_dir)
    if video_path is None:
        base_report["error"] = {
            "type": "MissingDownloadedFile",
            "message": "yt-dlp completed but no downloaded video file was found.",
        }
        write_json(report_path, base_report)
        return base_report, info

    report = {
        **base_report,
        "status": "success",
        "video_path": str(video_path),
        "video_id": info.get("id"),
        "title": info.get("title"),
        "duration_seconds": info.get("duration"),
        "ext": video_path.suffix.lstrip(".") or info.get("ext"),
        "extractor": info.get("extractor"),
        "extractor_key": info.get("extractor_key"),
        "webpage_url": info.get("webpage_url") or video_url,
        "error": None,
        "created_at": utc_now(),
    }
    write_json(report_path, report)
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
    ffmpeg_path = shutil.which("ffmpeg")
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
        "comparison_region": comparison_region,
        "ocr": ocr_report,
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
            total = float(sum(histogram)) or 1.0
            small = thumbnail.resize((8, 8), resample)
            pixels = list(small.getdata())
            sharpness_score = estimate_sharpness_score(thumbnail)
    except Exception as error:
        raise PillowFrameReadFailed(f"Pillow could not read frame {path}: {error}") from error

    average = sum(pixels) / len(pixels)
    return {
        "mean": float(stat.mean[0]),
        "variance": float(stat.var[0]),
        "sharpness_score": sharpness_score,
        "histogram": [value / total for value in histogram],
        "average_hash": tuple(1 if pixel > average else 0 for pixel in pixels),
        "comparison_region": comparison_region,
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

    for candidate in candidates:
        features = image_features(candidate["path"], Image, ImageStat, options)
        comparison_region = comparison_region or features.get("comparison_region")
        quality = evaluate_frame_quality(features, options)
        if not quality["accepted"]:
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
                duplicate_rejected_count += 1
                duplicate_suppressed_count += 1
                accepted[-1]["duplicate_suppressed_count"] += 1
                accepted[-1]["merged_source_frame_count"] += 1
                accepted[-1]["covered_source_frame_times"].append(float(candidate["time"]))
                continue

            if seconds_since_last < float(options["min_stable_duration_seconds"]):
                stable_too_short_rejected_count += 1
                continue

            if (
                score_vs_last_keyframe >= options["min_visual_difference_score"]
            ):
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
                "path": shutil.which("ffmpeg"),
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
                "path": shutil.which("ffmpeg"),
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
        args.extract_visuals_only or args.transcribe_fallback_only
    ):
        parser.error(
            "--align-transcript-visuals-only cannot be combined with "
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
