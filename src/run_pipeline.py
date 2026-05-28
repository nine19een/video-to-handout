from __future__ import annotations

import argparse
import ast
import html
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUIRED_CONFIG_FIELDS = ("video_url", "run_id", "output_dir")
DEFAULT_SUBTITLE_LANGUAGES = ("en", "zh-Hans", "zh", "zh-CN")
DEFAULT_OUTPUT_LANGUAGE = "zh-CN"
SUBTITLE_SUFFIXES = {".vtt", ".srt"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_scalar(value: str) -> Any:
    stripped = value.strip()
    if not stripped:
        return ""
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
        field for field in REQUIRED_CONFIG_FIELDS if not str(config.get(field, "")).strip()
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


def run_batch_2(config_path: Path) -> tuple[Path, dict[str, Any]]:
    config, run_dir = initialize_run(config_path)
    download_report, video_info = download_video(config, run_dir)
    if download_report["status"] != "success" or video_info is None:
        return run_dir, download_report
    download_and_parse_subtitles(config, run_dir, video_info)
    return run_dir, download_report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run Batch 2 raw video and subtitle acquisition."
    )
    parser.add_argument(
        "--config",
        required=True,
        help="Path to the YAML config file.",
    )
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    run_dir, download_report = run_batch_2(Path(args.config))
    print(f"Batch 2 output directory: {run_dir}")
    if download_report["status"] != "success":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
