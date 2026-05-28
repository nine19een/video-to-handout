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
SUBTITLE_SUFFIXES = {".vtt", ".srt"}
VISUAL_EXTRACTION_METHOD = "ffmpeg_interval_plus_pillow_difference_v1"


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
            key = key.strip()
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
    with path.open("r", encoding="utf-8") as file:
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
) -> dict[str, Any]:
    ffmpeg_info = ffmpeg_info or {}
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
) -> None:
    payload = {
        "run_id": run_id,
        "video_path": video_path,
        "method": VISUAL_EXTRACTION_METHOD,
        "status": "failed",
        "segments": [],
        "segment_count": 0,
        "keyframe_dir": str(keyframe_dir),
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
) -> dict[str, Any]:
    payload = {
        "run_id": run_id,
        "video_path": str(video_path),
        "method": VISUAL_EXTRACTION_METHOD,
        "status": "smoke_success" if smoke_test else "success",
        "segments": segments,
        "segment_count": len(segments),
        "keyframe_dir": str(keyframe_dir),
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


def image_features(path: Path, Image: Any, ImageStat: Any) -> dict[str, Any]:
    try:
        with Image.open(path) as image:
            gray = image.convert("L")
            resample = pillow_resampling_filter(Image)
            thumbnail = gray.resize((64, 64), resample)
            stat = ImageStat.Stat(thumbnail)
            histogram = thumbnail.histogram()
            total = float(sum(histogram)) or 1.0
            small = thumbnail.resize((8, 8), resample)
            pixels = list(small.getdata())
    except Exception as error:
        raise PillowFrameReadFailed(f"Pillow could not read frame {path}: {error}") from error

    average = sum(pixels) / len(pixels)
    return {
        "mean": float(stat.mean[0]),
        "variance": float(stat.var[0]),
        "histogram": [value / total for value in histogram],
        "average_hash": tuple(1 if pixel > average else 0 for pixel in pixels),
    }


def is_low_information_frame(features: dict[str, Any]) -> bool:
    mean = float(features["mean"])
    variance = float(features["variance"])
    if mean <= 5 and variance <= 100:
        return True
    if mean >= 250 and variance <= 25:
        return True
    return variance <= 2


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


def select_keyframes(
    candidates: list[dict[str, Any]],
    options: dict[str, Any],
) -> list[dict[str, Any]]:
    Image, ImageStat = import_pillow()
    accepted: list[dict[str, Any]] = []
    previous_valid_features: dict[str, Any] | None = None

    for candidate in candidates:
        features = image_features(candidate["path"], Image, ImageStat)
        if is_low_information_frame(features):
            continue

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
                }
            )
        else:
            seconds_since_last = float(candidate["time"]) - float(
                accepted[-1]["source_frame_time"]
            )
            if (
                score >= options["min_visual_difference_score"]
                and seconds_since_last >= options["min_stable_duration_seconds"]
            ):
                accepted.append(
                    {
                        "source_frame_path": candidate["path"],
                        "source_frame_time": float(candidate["time"]),
                        "reason": "visual_difference_threshold",
                        "visual_difference_score": score,
                    }
                )

        if len(accepted) >= options["max_keyframes"]:
            break

    if not accepted:
        raise NoAcceptableKeyframes(
            "No candidate frames passed quality and difference filters."
        )
    return accepted


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

    try:
        options = resolve_visual_options(
            config,
            frame_interval_override,
            frame_smoke_override,
            max_keyframes_override,
        )

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
        selected_keyframes = select_keyframes(candidates, options)
        copied_keyframes = copy_keyframes_to_output(selected_keyframes, keyframe_dir)
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
        )
        write_frame_report(run_dir, report)
        write_failed_visual_segments(
            run_dir,
            run_id,
            video_path_text or (str(video_path) if video_path else None),
            keyframe_dir,
            error,
        )
        return run_dir, report


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
