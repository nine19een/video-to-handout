from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any


CONTENT_MAP_METHOD = "deterministic_content_map_skeleton_v1"
PROMPT_PACK_SCHEMA_VERSION = "handout_prompt_pack_v1"
DEFAULT_PROMPT_PACK_PATH = "audit/handout_prompt_pack.jsonl"
SUPPORTED_BATCH5A_BACKENDS = {"none"}
FUTURE_BACKENDS = {"openai_compatible", "deepseek", "openrouter", "anthropic", "local"}


class Batch5AInputError(RuntimeError):
    pass


class UnsupportedContentGenerationBackend(RuntimeError):
    pass


class NetworkCallsDisabled(RuntimeError):
    pass


class MissingApiKeyEnvironmentVariable(RuntimeError):
    pass


class InvalidGenerationResponse(RuntimeError):
    pass


class EmptyGenerationResponse(RuntimeError):
    pass


class GenerationTimeout(RuntimeError):
    pass


class GenerationRateLimited(RuntimeError):
    pass


class SourceArtifactModified(RuntimeError):
    pass


class UnsafePromptPackPath(RuntimeError):
    pass


def utc_now() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8-sig") as file:
        payload = json.load(file)
    if not isinstance(payload, dict):
        raise Batch5AInputError(f"Expected JSON object in {path}.")
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)
        file.write("\n")


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as file:
        file.write(text.rstrip() + "\n")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def optional_string(value: Any) -> str | None:
    if value is None:
        return None
    normalized = str(value).strip()
    return normalized or None


def string_or_default(value: Any, default: str) -> str:
    normalized = optional_string(value)
    return normalized if normalized is not None else default


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


def positive_float_or_default(value: Any, default: float, field_name: str) -> float:
    if value is None or value == "":
        return default
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


def normalize_string_list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        items = value
    else:
        items = str(value).split(",")
    return [str(item).strip() for item in items if str(item).strip()]


def clip_text(text: str, max_chars: int) -> str:
    normalized = re.sub(r"\s+", " ", text).strip()
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max(0, max_chars - 3)].rstrip() + "..."


def format_timestamp(seconds: float) -> str:
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"


def resolve_batch5_options(config: dict[str, Any]) -> dict[str, Any]:
    options = {
        "generate_content_map": bool_or_default(config.get("generate_content_map"), True),
        "generate_review_report": bool_or_default(
            config.get("generate_review_report"), True
        ),
        "generate_lecture_handout": bool_or_default(
            config.get("generate_lecture_handout"), True
        ),
        "content_generation_backend": string_or_default(
            config.get("content_generation_backend"), "none"
        ).lower(),
        "content_generation_backend_mode": string_or_default(
            config.get("content_generation_backend_mode"), "skeleton"
        ).lower(),
        "generate_llm_prompt_pack": bool_or_default(
            config.get("generate_llm_prompt_pack"), True
        ),
        "llm_prompt_pack_path": string_or_default(
            config.get("llm_prompt_pack_path"), DEFAULT_PROMPT_PACK_PATH
        ),
        "content_unit_max_gap_seconds": positive_float_or_default(
            config.get("content_unit_max_gap_seconds"),
            45.0,
            "content_unit_max_gap_seconds",
        ),
        "content_unit_max_duration_seconds": positive_float_or_default(
            config.get("content_unit_max_duration_seconds"),
            240.0,
            "content_unit_max_duration_seconds",
        ),
        "content_unit_min_transcript_chars": positive_int_or_default(
            config.get("content_unit_min_transcript_chars"),
            80,
            "content_unit_min_transcript_chars",
        ),
        "handout_max_images_per_unit": positive_int_or_default(
            config.get("handout_max_images_per_unit"),
            1,
            "handout_max_images_per_unit",
        ),
        "handout_near_duplicate_image_policy": string_or_default(
            config.get("handout_near_duplicate_image_policy"),
            "keep_one_representative",
        ),
        "handout_prefer_fuller_state": bool_or_default(
            config.get("handout_prefer_fuller_state"), True
        ),
        "handout_include_timestamps": bool_or_default(
            config.get("handout_include_timestamps"), True
        ),
        "handout_include_generated_notice": bool_or_default(
            config.get("handout_include_generated_notice"), True
        ),
        "handout_min_image_spacing_seconds": nonnegative_float_or_default(
            config.get("handout_min_image_spacing_seconds"),
            45.0,
            "handout_min_image_spacing_seconds",
        ),
        "handout_near_duplicate_max_gap_seconds": positive_float_or_default(
            config.get("handout_near_duplicate_max_gap_seconds"),
            40.0,
            "handout_near_duplicate_max_gap_seconds",
        ),
        "handout_near_duplicate_max_difference": nonnegative_float_or_default(
            config.get("handout_near_duplicate_max_difference"),
            0.20,
            "handout_near_duplicate_max_difference",
        ),
        "handout_rapid_burst_window_seconds": positive_float_or_default(
            config.get("handout_rapid_burst_window_seconds"),
            60.0,
            "handout_rapid_burst_window_seconds",
        ),
        "handout_rapid_burst_min_frames": positive_int_or_default(
            config.get("handout_rapid_burst_min_frames"),
            3,
            "handout_rapid_burst_min_frames",
        ),
        "llm_api_style": string_or_default(config.get("llm_api_style"), "none"),
        "llm_base_url": string_or_default(config.get("llm_base_url"), ""),
        "llm_model": string_or_default(config.get("llm_model"), ""),
        "llm_api_key_env": string_or_default(config.get("llm_api_key_env"), ""),
        "llm_temperature": nonnegative_float_or_default(
            config.get("llm_temperature"), 0.2, "llm_temperature"
        ),
        "llm_max_input_chars_per_unit": positive_int_or_default(
            config.get("llm_max_input_chars_per_unit"),
            6000,
            "llm_max_input_chars_per_unit",
        ),
        "llm_max_excerpt_chars_per_item": positive_int_or_default(
            config.get("llm_max_excerpt_chars_per_item"),
            800,
            "llm_max_excerpt_chars_per_item",
        ),
        "llm_max_output_tokens": positive_int_or_default(
            config.get("llm_max_output_tokens"), 1200, "llm_max_output_tokens"
        ),
        "llm_timeout_seconds": positive_float_or_default(
            config.get("llm_timeout_seconds"), 60.0, "llm_timeout_seconds"
        ),
        "llm_max_retries": int(config.get("llm_max_retries") or 0),
        "llm_concurrency": positive_int_or_default(
            config.get("llm_concurrency"), 1, "llm_concurrency"
        ),
        "llm_save_raw_responses": bool_or_default(
            config.get("llm_save_raw_responses"), False
        ),
        "llm_allow_network_calls": bool_or_default(
            config.get("llm_allow_network_calls"), False
        ),
        "unsupported_backend_behavior": string_or_default(
            config.get("unsupported_backend_behavior"), "fail_closed"
        ),
        "output_language": string_or_default(config.get("output_language"), "zh-CN"),
        "content_map_known_issues": normalize_string_list(
            config.get("content_map_known_issues")
        ),
    }
    if options["llm_max_retries"] < 0:
        raise ValueError("llm_max_retries must be greater than or equal to 0.")
    if options["handout_near_duplicate_image_policy"] != "keep_one_representative":
        raise ValueError(
            "Batch 5A only supports handout_near_duplicate_image_policy="
            "keep_one_representative."
        )
    if options["handout_max_images_per_unit"] != 1:
        raise ValueError("Batch 5A currently supports handout_max_images_per_unit=1 only.")
    return options


class ContentGenerationBackend:
    name = "abstract"

    def validate_config(self, options: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError

    def generate_section(self, request: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class NoneBackend(ContentGenerationBackend):
    name = "none"

    def validate_config(self, options: dict[str, Any]) -> dict[str, Any]:
        if options["content_generation_backend_mode"] != "skeleton":
            raise ValueError("NoneBackend only supports content_generation_backend_mode=skeleton.")
        return {
            "status": "success",
            "backend": self.name,
            "mode": "skeleton",
            "network_calls": False,
            "api_key_required": False,
        }

    def generate_section(self, request: dict[str, Any]) -> dict[str, Any]:
        return {
            "status": "skipped",
            "skip_reason": "backend_none_skeleton_mode",
            "source_unit_id": request["unit_id"],
            "section_title": None,
            "section_summary": None,
            "key_points": [],
            "examples": [],
            "cited_transcript_item_ids": [],
            "cited_visual_segment_ids": [],
            "selected_keyframe_paths": [],
            "warnings": [],
            "model_metadata": {},
            "usage": {},
            "error": None,
        }


BACKEND_REGISTRY: dict[str, type[ContentGenerationBackend]] = {
    "none": NoneBackend,
}


def resolve_content_generation_backend(options: dict[str, Any]) -> ContentGenerationBackend:
    backend_name = options["content_generation_backend"]
    if options["llm_allow_network_calls"]:
        raise NetworkCallsDisabled("Batch 5A does not permit network calls.")
    if backend_name not in SUPPORTED_BATCH5A_BACKENDS:
        if not options["llm_api_key_env"]:
            raise MissingApiKeyEnvironmentVariable(
                "Future LLM backends require llm_api_key_env to name an environment variable."
            )
        raise UnsupportedContentGenerationBackend(
            f"Batch 5A does not implement backend {backend_name!r}; fail closed."
        )
    backend = BACKEND_REGISTRY[backend_name]()
    backend.validate_config(options)
    return backend


def batch5_source_paths(run_dir: Path) -> dict[str, Path]:
    return {
        "raw_transcript": run_dir / "audit" / "raw_transcript.json",
        "visual_segments": run_dir / "audit" / "visual_segments.json",
        "frame_report": run_dir / "audit" / "frame_report.json",
        "alignment": run_dir / "audit" / "alignment.json",
    }


def validate_resolved_prompt_pack_path(run_dir: Path, path: Path) -> Path:
    field_name = "llm_prompt_pack_path"
    resolved_run_dir = run_dir.resolve(strict=False)
    allowed_root = (resolved_run_dir / "audit").resolve(strict=False)
    try:
        allowed_root.relative_to(resolved_run_dir)
    except ValueError as error:
        raise UnsafePromptPackPath(
            f"{field_name} is unsafe because the audit output directory resolves "
            "outside the run output directory."
        ) from error

    resolved_path = path.resolve(strict=False)
    try:
        resolved_path.relative_to(allowed_root)
        resolved_path.parent.resolve(strict=False).relative_to(allowed_root)
    except ValueError as error:
        raise UnsafePromptPackPath(
            f"{field_name} must resolve inside the run audit output directory."
        ) from error
    if resolved_path == allowed_root:
        raise UnsafePromptPackPath(f"{field_name} must name a JSONL file, not a directory.")
    if resolved_path.suffix.lower() != ".jsonl":
        raise UnsafePromptPackPath(f"{field_name} must use the .jsonl suffix.")
    if resolved_path.exists() and resolved_path.is_dir():
        raise UnsafePromptPackPath(f"{field_name} must not resolve to a directory.")
    return resolved_path


def resolve_prompt_pack_path(run_dir: Path, configured_path: str | None) -> Path:
    field_name = "llm_prompt_pack_path"
    raw_path = optional_string(configured_path) or DEFAULT_PROMPT_PACK_PATH
    if "\x00" in raw_path:
        raise UnsafePromptPackPath(f"{field_name} contains an invalid null byte.")

    # Normalize separators explicitly so traversal checks behave consistently on all hosts.
    normalized_path = raw_path.replace("\\", "/")
    if re.match(r"^[A-Za-z]:", normalized_path):
        raise UnsafePromptPackPath(f"{field_name} must not use a Windows drive path.")
    configured = Path(normalized_path)
    if configured.is_absolute() or normalized_path.startswith("/"):
        raise UnsafePromptPackPath(f"{field_name} must be relative to the run output directory.")

    resolved_run_dir = run_dir.resolve(strict=False)
    return validate_resolved_prompt_pack_path(resolved_run_dir, resolved_run_dir / configured)


def batch5_output_paths(run_dir: Path, options: dict[str, Any]) -> dict[str, Path]:
    prompt_pack_path = resolve_prompt_pack_path(
        run_dir,
        options["llm_prompt_pack_path"],
    )
    return {
        "content_map": run_dir / "audit" / "content_map.json",
        "review_report": run_dir / "audit" / "review_report.md",
        "lecture_handout": run_dir / "lecture_handout.md",
        "prompt_pack": prompt_pack_path,
    }


def clear_batch5_outputs(run_dir: Path, paths: dict[str, Path]) -> None:
    validate_resolved_prompt_pack_path(run_dir, paths["prompt_pack"])
    for path in paths.values():
        if path.exists() and path.is_file():
            path.unlink()


def required_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        raise Batch5AInputError(f"Missing required Batch 5A input: {path}")
    if ".smoke." in path.name:
        raise Batch5AInputError(f"Batch 5A cannot consume smoke artifact: {path}")
    return read_json(path)


def normalize_transcript_segments(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise Batch5AInputError("raw_transcript.json must contain non-empty segments.")
    normalized = []
    seen_ids = set()
    for index, segment in enumerate(raw_segments):
        if not isinstance(segment, dict):
            raise Batch5AInputError(f"Transcript segment {index} is not an object.")
        segment_id = segment.get("id") or index + 1
        if segment_id in seen_ids:
            raise Batch5AInputError(f"Duplicate transcript segment ID: {segment_id}")
        seen_ids.add(segment_id)
        try:
            start = float(segment["start"])
            end = float(segment["end"])
        except (KeyError, TypeError, ValueError) as error:
            raise Batch5AInputError(f"Invalid transcript timing at segment {index}.") from error
        text = optional_string(segment.get("text"))
        if start >= end or text is None:
            raise Batch5AInputError(f"Invalid transcript segment {segment_id}.")
        normalized.append(
            {
                "id": segment_id,
                "index": index,
                "start": start,
                "end": end,
                "text": text,
            }
        )
    return normalized


def normalize_visual_segments(payload: dict[str, Any]) -> list[dict[str, Any]]:
    raw_segments = payload.get("segments")
    if not isinstance(raw_segments, list) or not raw_segments:
        raise Batch5AInputError("visual_segments.json must contain non-empty segments.")
    normalized = []
    seen_ids = set()
    for index, segment in enumerate(raw_segments):
        if not isinstance(segment, dict):
            raise Batch5AInputError(f"Visual segment {index} is not an object.")
        segment_id = segment.get("id") or index + 1
        if segment_id in seen_ids:
            raise Batch5AInputError(f"Duplicate visual segment ID: {segment_id}")
        seen_ids.add(segment_id)
        try:
            start = float(segment["start"])
            end = float(segment["end"])
            source_frame_time = float(segment.get("source_frame_time", start))
        except (KeyError, TypeError, ValueError) as error:
            raise Batch5AInputError(f"Invalid visual timing at segment {index}.") from error
        keyframe_path = Path(str(segment.get("keyframe_path") or ""))
        if start >= end or not keyframe_path.exists():
            raise Batch5AInputError(f"Invalid visual segment or keyframe path: {segment_id}")
        normalized.append(
            {
                **segment,
                "id": segment_id,
                "index": index,
                "start": start,
                "end": end,
                "source_frame_time": source_frame_time,
                "keyframe_path": str(keyframe_path),
            }
        )
    return normalized


def preflight_batch5_inputs(run_dir: Path) -> dict[str, Any]:
    source_paths = batch5_source_paths(run_dir)
    source_hashes = {name: sha256_file(path) for name, path in source_paths.items() if path.exists()}
    if len(source_hashes) != len(source_paths):
        missing = [str(path) for path in source_paths.values() if not path.exists()]
        raise Batch5AInputError(f"Missing required Batch 5A input(s): {', '.join(missing)}")

    raw_transcript = required_json(source_paths["raw_transcript"])
    visual_payload = required_json(source_paths["visual_segments"])
    frame_report = required_json(source_paths["frame_report"])
    alignment = required_json(source_paths["alignment"])

    if frame_report.get("smoke_test") is True or frame_report.get("status") != "success":
        raise Batch5AInputError("frame_report.json must be formal status=success evidence.")
    if visual_payload.get("status") != "success":
        raise Batch5AInputError("visual_segments.json must be formal status=success evidence.")
    if alignment.get("status") != "success":
        raise Batch5AInputError("alignment.json must have status=success.")
    if alignment.get("method") != "transcript_visual_time_alignment_v1":
        raise Batch5AInputError("alignment.json method is not supported by Batch 5A.")
    if any(".smoke." in str(value) for value in (alignment.get("inputs") or {}).values()):
        raise Batch5AInputError("alignment.json references smoke artifacts.")

    transcripts = normalize_transcript_segments(raw_transcript)
    visuals = normalize_visual_segments(visual_payload)
    transcript_by_id = {item["id"]: item for item in transcripts}
    visual_by_id = {item["id"]: item for item in visuals}
    alignments = alignment.get("alignments")
    if not isinstance(alignments, list) or not alignments:
        raise Batch5AInputError("alignment.json must contain non-empty alignments.")

    aligned_ids = []
    for item in alignments:
        if not isinstance(item, dict):
            raise Batch5AInputError("alignment.json contains a non-object alignment item.")
        transcript_id = item.get("transcript_segment_id")
        visual_id = item.get("matched_visual_segment_id")
        if transcript_id not in transcript_by_id:
            raise Batch5AInputError(f"Unknown transcript segment ID in alignment: {transcript_id}")
        if visual_id not in visual_by_id:
            raise Batch5AInputError(f"Unknown visual segment ID in alignment: {visual_id}")
        keyframe_path = Path(str(item.get("keyframe_path") or ""))
        if not keyframe_path.exists():
            raise Batch5AInputError(f"Missing alignment keyframe path: {keyframe_path}")
        if item.get("confidence") in {"none", "low"}:
            raise Batch5AInputError("Batch 5A requires reviewed alignment without low-confidence items.")
        aligned_ids.append(transcript_id)

    if len(aligned_ids) != len(transcripts) or set(aligned_ids) != set(transcript_by_id):
        raise Batch5AInputError("alignment.json does not reference every transcript segment exactly once.")

    return {
        "source_paths": {name: str(path) for name, path in source_paths.items()},
        "source_hashes": source_hashes,
        "raw_transcript": raw_transcript,
        "frame_report": frame_report,
        "alignment": alignment,
        "transcripts": transcripts,
        "visuals": visuals,
        "transcript_by_id": transcript_by_id,
        "visual_by_id": visual_by_id,
        "alignments": alignments,
        "input_health": {
            "status": "success",
            "formal_non_smoke_inputs": True,
            "transcript_segment_count": len(transcripts),
            "visual_segment_count": len(visuals),
            "alignment_item_count": len(alignments),
            "aligned_segment_count": alignment.get("aligned_segment_count"),
            "unaligned_segment_count": alignment.get("unaligned_segment_count"),
            "low_confidence_segment_count": alignment.get("low_confidence_segment_count"),
            "missing_keyframe_count": 0,
        },
    }


def transcript_char_count(items: list[dict[str, Any]]) -> int:
    return sum(len(item["transcript_text"]) for item in items)


def make_block(items: list[dict[str, Any]], visual_ids: list[Any]) -> dict[str, Any]:
    return {
        "alignments": list(items),
        "visual_segment_ids": list(dict.fromkeys(visual_ids)),
        "start_time": min(float(item["transcript_start"]) for item in items),
        "end_time": max(float(item["transcript_end"]) for item in items),
        "transcript_char_count": transcript_char_count(items),
    }


def split_alignment_items(
    items: list[dict[str, Any]],
    visual_id: Any,
    max_duration: float,
) -> list[dict[str, Any]]:
    chunks: list[list[dict[str, Any]]] = []
    current: list[dict[str, Any]] = []
    for item in items:
        if current and float(item["transcript_end"]) - float(current[0]["transcript_start"]) > max_duration:
            chunks.append(current)
            current = []
        current.append(item)
    if current:
        chunks.append(current)
    return [make_block(chunk, [visual_id]) for chunk in chunks]


def can_merge_blocks(
    left: dict[str, Any],
    right: dict[str, Any],
    visual_positions: dict[Any, int],
    options: dict[str, Any],
) -> bool:
    gap = float(right["start_time"]) - float(left["end_time"])
    duration = float(right["end_time"]) - float(left["start_time"])
    left_last = left["visual_segment_ids"][-1]
    right_first = right["visual_segment_ids"][0]
    visually_contiguous = visual_positions[right_first] - visual_positions[left_last] in {0, 1}
    target_duration = min(float(options["content_unit_max_duration_seconds"]), 120.0)
    short_text = (
        int(left["transcript_char_count"]) < int(options["content_unit_min_transcript_chars"])
        or int(right["transcript_char_count"]) < int(options["content_unit_min_transcript_chars"])
    )
    return (
        gap <= float(options["content_unit_max_gap_seconds"])
        and duration <= float(options["content_unit_max_duration_seconds"])
        and visually_contiguous
        and (duration <= target_duration or short_text)
    )


def merge_blocks(
    blocks: list[dict[str, Any]],
    visual_positions: dict[Any, int],
    options: dict[str, Any],
) -> list[dict[str, Any]]:
    merged: list[dict[str, Any]] = []
    for block in blocks:
        if merged and can_merge_blocks(merged[-1], block, visual_positions, options):
            previous = merged.pop()
            merged.append(
                make_block(
                    previous["alignments"] + block["alignments"],
                    previous["visual_segment_ids"] + block["visual_segment_ids"],
                )
            )
        else:
            merged.append(block)
    return merged


def pick_excerpt_items(items: list[dict[str, Any]], max_items: int = 3) -> list[dict[str, Any]]:
    if len(items) <= max_items:
        selected = items
    else:
        selected = [items[0], items[len(items) // 2], items[-1]]
    result = []
    seen = set()
    for item in selected:
        transcript_id = item["transcript_segment_id"]
        if transcript_id in seen:
            continue
        seen.add(transcript_id)
        result.append(
            {
                "transcript_item_id": transcript_id,
                "start_time": float(item["transcript_start"]),
                "end_time": float(item["transcript_end"]),
                "text": clip_text(str(item["transcript_text"]), 280),
            }
        )
    return result


def public_keyframe_candidate(visual: dict[str, Any]) -> dict[str, Any]:
    return {
        "visual_segment_id": visual["id"],
        "keyframe_path": visual["keyframe_path"],
        "source_frame_time": round(float(visual["source_frame_time"]), 3),
        "ocr_text": optional_string(visual.get("ocr_text")),
        "title_hint": optional_string(visual.get("title_hint")),
        "representative_score": visual.get("representative_score"),
        "quality_metrics": visual.get("quality_metrics") or {},
    }


def build_content_units(inputs: dict[str, Any], options: dict[str, Any]) -> list[dict[str, Any]]:
    alignments_by_visual: dict[Any, list[dict[str, Any]]] = {}
    for item in inputs["alignments"]:
        alignments_by_visual.setdefault(item["matched_visual_segment_id"], []).append(item)
    for items in alignments_by_visual.values():
        items.sort(key=lambda item: float(item["transcript_start"]))

    visual_positions = {visual["id"]: visual["index"] for visual in inputs["visuals"]}
    blocks = []
    for visual in inputs["visuals"]:
        items = alignments_by_visual.get(visual["id"], [])
        if items:
            blocks.extend(
                split_alignment_items(
                    items,
                    visual["id"],
                    float(options["content_unit_max_duration_seconds"]),
                )
            )
    blocks = merge_blocks(blocks, visual_positions, options)

    units = []
    for index, block in enumerate(blocks, start=1):
        alignments = block["alignments"]
        excerpts = pick_excerpt_items(alignments)
        candidates = [
            public_keyframe_candidate(inputs["visual_by_id"][visual_id])
            for visual_id in block["visual_segment_ids"]
        ]
        summary = " / ".join(excerpt["text"] for excerpt in excerpts)
        units.append(
            {
                "unit_id": f"unit_{index:03d}",
                "start_time": round(float(block["start_time"]), 3),
                "end_time": round(float(block["end_time"]), 3),
                "topic_hint": f"教学单元 {index:03d}",
                "topic_hint_source": "deterministic_sequence_label",
                "transcript_item_ids": [
                    item["transcript_segment_id"] for item in alignments
                ],
                "transcript_excerpt_ids": [
                    excerpt["transcript_item_id"] for excerpt in excerpts
                ],
                "transcript_excerpts": excerpts,
                "transcript_text_summary": clip_text(summary, 700),
                "summary_mode": "excerpt_based_not_semantic_summary",
                "key_points": [],
                "examples": [],
                "visual_segment_ids": list(block["visual_segment_ids"]),
                "candidate_keyframes": candidates,
                "selected_keyframes": [],
                "dropped_near_duplicate_keyframes": [],
                "image_selection_reason": None,
                "warnings": [],
                "review_required": False,
                "confidence": "deterministic_scaffold",
                "provenance": {
                    "alignment_method": inputs["alignment"]["method"],
                    "transcript_item_count": len(alignments),
                    "visual_segment_count": len(block["visual_segment_ids"]),
                    "transcript_char_count": int(block["transcript_char_count"]),
                },
            }
        )
    return units


def import_pillow() -> Any:
    try:
        from PIL import Image
    except ImportError as error:
        raise RuntimeError(
            "Pillow is required for Batch 5A handout-level image selection."
        ) from error
    return Image


def normalized_histogram(histogram: list[int]) -> list[float]:
    total = float(sum(histogram)) or 1.0
    return [value / total for value in histogram]


def average_hash(pixels: list[int]) -> tuple[int, ...]:
    average = sum(pixels) / len(pixels)
    return tuple(1 if pixel > average else 0 for pixel in pixels)


def hash_difference(left: tuple[int, ...], right: tuple[int, ...]) -> float:
    if not left or len(left) != len(right):
        return 1.0
    return sum(1 for a, b in zip(left, right) if a != b) / len(left)


def histogram_difference(left: list[float], right: list[float]) -> float:
    return sum(abs(a - b) for a, b in zip(left, right)) / 2


def image_pixels(image: Any) -> list[int]:
    if hasattr(image, "get_flattened_data"):
        return list(image.get_flattened_data())
    return list(image.getdata())


def describe_keyframe(path: Path) -> dict[str, Any]:
    Image = import_pillow()
    with Image.open(path) as image:
        resample = Image.Resampling.LANCZOS if hasattr(Image, "Resampling") else Image.LANCZOS
        width, height = image.size
        slide = image.crop((0, int(height * 0.08), int(width * 0.86), height)).convert("L")
        thumbnail = slide.resize((64, 64), resample)
        pixels = image_pixels(thumbnail)
        small_pixels = image_pixels(thumbnail.resize((8, 8), resample))
    content_area = sum(1 for pixel in pixels if pixel < 245) / len(pixels)
    detail = 0
    comparisons = 0
    for y in range(64):
        for x in range(64):
            current = pixels[(y * 64) + x]
            if x + 1 < 64:
                detail += 1 if abs(current - pixels[(y * 64) + x + 1]) > 12 else 0
                comparisons += 1
            if y + 1 < 64:
                detail += 1 if abs(current - pixels[((y + 1) * 64) + x]) > 12 else 0
                comparisons += 1
    detail_density = detail / comparisons if comparisons else 0.0
    image_score = (0.65 * content_area) + (0.35 * detail_density)
    return {
        "histogram": normalized_histogram(thumbnail.histogram()),
        "average_hash": average_hash(small_pixels),
        "content_area_ratio": round(content_area, 6),
        "detail_density": round(detail_density, 6),
        "image_score": round(image_score, 6),
    }


def image_difference(left: dict[str, Any], right: dict[str, Any]) -> float:
    return max(
        histogram_difference(left["histogram"], right["histogram"]),
        hash_difference(left["average_hash"], right["average_hash"]),
    )


def candidate_with_descriptor(candidate: dict[str, Any]) -> dict[str, Any]:
    descriptor = describe_keyframe(Path(candidate["keyframe_path"]))
    return {**candidate, "descriptor": descriptor}


def choose_group_representative(
    candidates: list[dict[str, Any]],
    options: dict[str, Any],
) -> dict[str, Any]:
    if not options["handout_prefer_fuller_state"]:
        return max(candidates, key=lambda item: float(item["source_frame_time"]))
    return max(
        candidates,
        key=lambda item: (
            float(item["descriptor"]["image_score"]),
            float(item["source_frame_time"]),
        ),
    )


def make_image_group(
    group_id: str,
    group_type: str,
    candidates: list[dict[str, Any]],
    options: dict[str, Any],
) -> dict[str, Any]:
    representative = choose_group_representative(candidates, options)
    return {
        "group_id": group_id,
        "group_type": group_type,
        "representative_keyframe_path": representative["keyframe_path"],
        "representative_source_frame_time": representative["source_frame_time"],
        "candidate_keyframes": [item["keyframe_path"] for item in candidates],
        "candidate_source_frame_times": [item["source_frame_time"] for item in candidates],
        "dropped_keyframes": [
            {
                "keyframe_path": item["keyframe_path"],
                "source_frame_time": item["source_frame_time"],
                "reason": f"{group_type}_keep_one_representative",
            }
            for item in candidates
            if item["keyframe_path"] != representative["keyframe_path"]
        ],
        "review_required": group_type == "rapid_visual_burst",
    }


def detect_handout_image_groups(
    candidates: list[dict[str, Any]],
    options: dict[str, Any],
) -> list[dict[str, Any]]:
    ordered = sorted(candidates, key=lambda item: float(item["source_frame_time"]))
    groups: list[dict[str, Any]] = []
    consumed: set[str] = set()
    index = 0
    while index < len(ordered):
        burst = [ordered[index]]
        next_index = index + 1
        while next_index < len(ordered):
            previous = burst[-1]
            current = ordered[next_index]
            gap = float(current["source_frame_time"]) - float(previous["source_frame_time"])
            span = float(current["source_frame_time"]) - float(burst[0]["source_frame_time"])
            if (
                gap > float(options["handout_near_duplicate_max_gap_seconds"])
                or span > float(options["handout_rapid_burst_window_seconds"])
            ):
                break
            burst.append(current)
            next_index += 1
        if len(burst) >= int(options["handout_rapid_burst_min_frames"]):
            group = make_image_group(
                f"image_group_{len(groups) + 1:03d}",
                "rapid_visual_burst",
                burst,
                options,
            )
            groups.append(group)
            consumed.update(item["keyframe_path"] for item in burst)
            index = next_index
        else:
            index += 1

    remaining = [item for item in ordered if item["keyframe_path"] not in consumed]
    index = 0
    while index < len(remaining) - 1:
        cluster = [remaining[index]]
        next_index = index + 1
        while next_index < len(remaining):
            previous = cluster[-1]
            current = remaining[next_index]
            gap = float(current["source_frame_time"]) - float(previous["source_frame_time"])
            if gap > float(options["handout_near_duplicate_max_gap_seconds"]):
                break
            if image_difference(previous["descriptor"], current["descriptor"]) > float(
                options["handout_near_duplicate_max_difference"]
            ):
                break
            cluster.append(current)
            next_index += 1
        if len(cluster) > 1:
            group = make_image_group(
                f"image_group_{len(groups) + 1:03d}",
                "near_duplicate_visual_pair",
                cluster,
                options,
            )
            groups.append(group)
            consumed.update(item["keyframe_path"] for item in cluster)
            index = next_index
        else:
            index += 1
    return groups


def public_descriptor_candidate(candidate: dict[str, Any]) -> dict[str, Any]:
    descriptor = candidate["descriptor"]
    return {
        key: value for key, value in candidate.items() if key != "descriptor"
    } | {
        "handout_image_score": descriptor["image_score"],
        "content_area_ratio": descriptor["content_area_ratio"],
        "detail_density": descriptor["detail_density"],
    }


def apply_handout_image_selection(
    units: list[dict[str, Any]],
    options: dict[str, Any],
) -> list[dict[str, Any]]:
    unique_candidates = {}
    for unit in units:
        for candidate in unit["candidate_keyframes"]:
            unique_candidates.setdefault(candidate["keyframe_path"], candidate)
    enriched = {
        path: candidate_with_descriptor(candidate)
        for path, candidate in unique_candidates.items()
    }
    groups = detect_handout_image_groups(list(enriched.values()), options)
    dropped_to_group = {}
    for group in groups:
        for dropped in group["dropped_keyframes"]:
            dropped_to_group[dropped["keyframe_path"]] = {
                **dropped,
                "group_id": group["group_id"],
                "group_type": group["group_type"],
            }

    selected_paths = set()
    previous_selected: tuple[dict[str, Any], dict[str, Any]] | None = None
    for unit in units:
        candidates = [enriched[item["keyframe_path"]] for item in unit["candidate_keyframes"]]
        unit["candidate_keyframes"] = [public_descriptor_candidate(item) for item in candidates]
        eligible = []
        for candidate in candidates:
            dropped = dropped_to_group.get(candidate["keyframe_path"])
            if dropped:
                unit["dropped_near_duplicate_keyframes"].append(dropped)
                if dropped["group_type"] == "rapid_visual_burst":
                    unit["review_required"] = True
                    unit["warnings"].append("rapid_visual_burst_review_required")
                continue
            if candidate["keyframe_path"] in selected_paths:
                unit["dropped_near_duplicate_keyframes"].append(
                    {
                        "keyframe_path": candidate["keyframe_path"],
                        "source_frame_time": candidate["source_frame_time"],
                        "reason": "keyframe_already_selected_for_previous_unit",
                    }
                )
                continue
            eligible.append(candidate)

        if not eligible:
            unit["warnings"].append("no_selected_handout_image")
            unit["review_required"] = True
            continue
        selected = choose_group_representative(eligible, options)
        if (
            previous_selected is not None
            and float(selected["source_frame_time"])
            - float(previous_selected[1]["source_frame_time"])
            < float(options["handout_min_image_spacing_seconds"])
        ):
            unit["dropped_near_duplicate_keyframes"].append(
                {
                    "keyframe_path": selected["keyframe_path"],
                    "source_frame_time": selected["source_frame_time"],
                    "reason": "handout_image_density_limit",
                }
            )
            unit["warnings"].append("no_selected_handout_image")
            unit["review_required"] = True
            continue
        public_selected = public_descriptor_candidate(selected)
        unit["selected_keyframes"] = [public_selected][
            : int(options["handout_max_images_per_unit"])
        ]
        unit["image_selection_reason"] = "best_available_handout_representative"
        selected_paths.add(selected["keyframe_path"])
        previous_selected = (unit, selected)
    return groups


def build_topic_groups(units: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups = []
    current = []
    for unit in units:
        if current and (
            len(current) >= 4
            or float(unit["end_time"]) - float(current[0]["start_time"]) > 720.0
        ):
            groups.append(current)
            current = []
        current.append(unit)
    if current:
        groups.append(current)
    return [
        {
            "topic_group_id": f"topic_group_{index:03d}",
            "title": f"章节 {index:03d}",
            "title_source": "deterministic_sequence_label",
            "start_time": group[0]["start_time"],
            "end_time": group[-1]["end_time"],
            "content_unit_ids": [unit["unit_id"] for unit in group],
            "review_required": any(unit["review_required"] for unit in group),
        }
        for index, group in enumerate(groups, start=1)
    ]


GENERATION_OUTPUT_SCHEMA = {
    "source_unit_id": "string",
    "section_title": "string",
    "section_summary": "string",
    "key_points": ["string"],
    "examples": ["string"],
    "cited_transcript_item_ids": ["existing transcript item ID"],
    "cited_visual_segment_ids": ["existing visual segment ID"],
    "selected_keyframe_paths": ["existing selected keyframe path"],
    "warnings": ["string"],
}


class PromptBuilder:
    def __init__(self, options: dict[str, Any]) -> None:
        self.options = options

    def build_section_request(self, unit: dict[str, Any]) -> dict[str, Any]:
        excerpts = []
        total_chars = 0
        max_total = int(self.options["llm_max_input_chars_per_unit"])
        max_item = int(self.options["llm_max_excerpt_chars_per_item"])
        for excerpt in unit["transcript_excerpts"]:
            text = clip_text(excerpt["text"], max_item)
            remaining = max_total - total_chars
            if remaining <= 0:
                break
            text = clip_text(text, remaining)
            excerpts.append({**excerpt, "text": text})
            total_chars += len(text)
        return {
            "schema_version": PROMPT_PACK_SCHEMA_VERSION,
            "unit_id": unit["unit_id"],
            "time_range": {
                "start_time": unit["start_time"],
                "end_time": unit["end_time"],
            },
            "topic_hint": unit["topic_hint"],
            "transcript_excerpts": excerpts,
            "transcript_item_ids": unit["transcript_item_ids"],
            "visual_segment_ids": unit["visual_segment_ids"],
            "selected_keyframe_metadata": unit["selected_keyframes"],
            "warnings": unit["warnings"],
            "style_constraints": {
                "output_language": self.options["output_language"],
                "format": "structured_json",
                "audience": "course learner",
                "max_output_tokens": self.options["llm_max_output_tokens"],
            },
            "grounding_rules": [
                "Only use the supplied transcript excerpts and visual metadata.",
                "Do not invent unsupported definitions, examples, or conclusions.",
                "Cite transcript item IDs and visual segment IDs from this unit only.",
                "Omit claims that cannot be grounded in supplied evidence.",
                "Return structured JSON; Markdown rendering happens later.",
            ],
            "desired_output_schema": GENERATION_OUTPUT_SCHEMA,
        }

    def build_prompt_pack_item(self, request: dict[str, Any]) -> dict[str, Any]:
        return request


def write_prompt_pack(
    run_dir: Path,
    path: Path,
    units: list[dict[str, Any]],
    options: dict[str, Any],
) -> dict[str, Any]:
    path = validate_resolved_prompt_pack_path(run_dir, path)
    builder = PromptBuilder(options)
    path.parent.mkdir(parents=True, exist_ok=True)
    item_count = 0
    with path.open("w", encoding="utf-8") as file:
        for unit in units:
            request = builder.build_section_request(unit)
            file.write(json.dumps(builder.build_prompt_pack_item(request), ensure_ascii=False))
            file.write("\n")
            item_count += 1
    return {
        "generated": True,
        "path": str(path),
        "item_count": item_count,
        "schema_version": PROMPT_PACK_SCHEMA_VERSION,
        "contains_full_raw_transcript": False,
        "contains_secrets": False,
        "network_calls": False,
    }


def make_prompt_pack_disabled(path: Path) -> dict[str, Any]:
    return {
        "generated": False,
        "path": str(path),
        "item_count": 0,
        "schema_version": PROMPT_PACK_SCHEMA_VERSION,
        "contains_full_raw_transcript": False,
        "contains_secrets": False,
        "network_calls": False,
    }


def validate_source_hashes(inputs: dict[str, Any]) -> None:
    current = {
        name: sha256_file(Path(path))
        for name, path in inputs["source_paths"].items()
    }
    if current != inputs["source_hashes"]:
        raise SourceArtifactModified("A Batch 4.5A/B source artifact changed during Batch 5A.")


def content_map_validation_summary(
    units: list[dict[str, Any]],
    topic_groups: list[dict[str, Any]],
    image_groups: list[dict[str, Any]],
) -> dict[str, Any]:
    monotonic = all(
        float(left["start_time"]) <= float(right["start_time"])
        for left, right in zip(units, units[1:])
    )
    return {
        "content_unit_count": len(units),
        "topic_group_count": len(topic_groups),
        "units_monotonic_by_time": monotonic,
        "selected_keyframe_count": sum(len(unit["selected_keyframes"]) for unit in units),
        "dropped_keyframe_count": sum(
            len(unit["dropped_near_duplicate_keyframes"]) for unit in units
        ),
        "near_duplicate_image_group_count": len(image_groups),
        "review_required_unit_count": sum(1 for unit in units if unit["review_required"]),
    }


def markdown_image_path(path: str) -> str:
    return f"assets/keyframes/{Path(path).name}"


class HandoutRenderer:
    def __init__(self, options: dict[str, Any]) -> None:
        self.options = options

    def render_skeleton(self, content_map: dict[str, Any]) -> str:
        lines = [f"# 课程讲义骨架：{content_map['run_id']}", ""]
        if self.options["handout_include_generated_notice"]:
            lines.extend(
                [
                    "> 本文件是机器生成的讲义骨架草稿，尚未经过人工审核，也不是最终润色后的课程讲义。",
                    "",
                ]
            )
        lines.extend(
            [
            "## 课程概览",
            "",
            f"- 运行标识：`{content_map['run_id']}`",
            "- 内容来源：公开视频字幕与视频关键截图。",
            f"- 原始字幕语言：`{content_map['source_metadata']['transcript_language']}`",
            "- 当前版本用于核对内容结构、时间范围和代表截图。",
            "- 字幕摘录保留原始语言，后续需要基于可追溯证据整理为自然中文讲义。",
            "",
            ]
        )
        unit_by_id = {unit["unit_id"]: unit for unit in content_map["content_units"]}
        for group in content_map["topic_groups"]:
            lines.extend([f"## {group['title']}", ""])
            for unit_id in group["content_unit_ids"]:
                unit = unit_by_id[unit_id]
                lines.append(f"### {unit['topic_hint']}")
                lines.append("")
                if self.options["handout_include_timestamps"]:
                    lines.append(
                        f"- 时间范围：{format_timestamp(unit['start_time'])} - "
                        f"{format_timestamp(unit['end_time'])}"
                    )
                lines.append("- 当前状态：待后续内容整理与人工复核。")
                lines.append("")
                for keyframe in unit["selected_keyframes"]:
                    lines.append(
                        f"![{unit['topic_hint']} 代表截图]"
                        f"({markdown_image_path(keyframe['keyframe_path'])})"
                    )
                    lines.append("")
                lines.append("字幕摘录（原文，供后续整理）：")
                lines.append("")
                for excerpt in unit["transcript_excerpts"][:3]:
                    lines.append(f"- {excerpt['text']}")
                lines.append("")
        lines.extend(
            [
                "## 后续整理说明",
                "",
                "当前文件仅提供可追溯的章节骨架、截图和有限字幕摘录。自然中文表达、概念归并和示例整理将在后续阶段完成。",
            ]
        )
        return "\n".join(lines)


def render_review_report(content_map: dict[str, Any]) -> str:
    units = content_map["content_units"]
    summary = content_map["validation_summary"]
    no_images = [unit for unit in units if not unit["selected_keyframes"]]
    too_many_candidates = [unit for unit in units if len(unit["candidate_keyframes"]) > 2]
    long_text_little_visual = [
        unit
        for unit in units
        if unit["provenance"]["transcript_char_count"] > 1800
        and len(unit["visual_segment_ids"]) <= 1
    ]
    visual_change_little_text = [
        unit
        for unit in units
        if len(unit["visual_segment_ids"]) > 1
        and unit["provenance"]["transcript_char_count"] < 160
    ]
    lines = [
        "# Batch 5A Review Report",
        "",
        "> This report is machine-generated engineering review material. It is not human-approved.",
        "",
        "## Artifact Summary",
        "",
        f"- Run ID: `{content_map['run_id']}`",
        f"- Method: `{content_map['method']}`",
        f"- Content units: `{len(units)}`",
        f"- Topic groups: `{len(content_map['topic_groups'])}`",
        f"- Selected handout images: `{summary['selected_keyframe_count']}`",
        f"- Dropped handout-level candidates: `{summary['dropped_keyframe_count']}`",
        "",
        "## Input Artifact Health",
        "",
    ]
    for key, value in content_map["input_health"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(["", "## Source Hashes", ""])
    for key, value in content_map["source_hashes"].items():
        lines.append(f"- `{key}`: `{value}`")
    lines.extend(
        [
            "",
            "## Time Coverage",
            "",
            f"- Start: `{format_timestamp(units[0]['start_time'])}`",
            f"- End: `{format_timestamp(units[-1]['end_time'])}`",
            "",
            "## Image Selection Summary",
            "",
            f"- Near-duplicate or density-control groups: `{len(content_map['near_duplicate_image_groups'])}`",
            f"- Units without a selected image: `{len(no_images)}`",
            f"- Units with more than two candidate images: `{len(too_many_candidates)}`",
            "",
            "## Near-Duplicate Image Groups",
            "",
        ]
    )
    if not content_map["near_duplicate_image_groups"]:
        lines.append("- None detected.")
    for group in content_map["near_duplicate_image_groups"]:
        lines.append(
            f"- `{group['group_id']}` `{group['group_type']}`: keep "
            f"`{group['representative_keyframe_path']}`; dropped "
            f"`{len(group['dropped_keyframes'])}` candidate(s)."
        )
    lines.extend(["", "## Dropped Candidate Keyframes", ""])
    dropped = [
        (unit["unit_id"], item)
        for unit in units
        for item in unit["dropped_near_duplicate_keyframes"]
    ]
    if not dropped:
        lines.append("- None.")
    for unit_id, item in dropped:
        lines.append(
            f"- `{unit_id}`: `{item['keyframe_path']}` - `{item['reason']}`"
        )
    lines.extend(
        [
            "",
            "## Automated Review Points",
            "",
            f"- Units without selected image: `{', '.join(unit['unit_id'] for unit in no_images) or 'none'}`",
            f"- Units with too many image candidates: `{', '.join(unit['unit_id'] for unit in too_many_candidates) or 'none'}`",
            f"- Long transcript with little visual change: `{', '.join(unit['unit_id'] for unit in long_text_little_visual) or 'none'}`",
            f"- Visual change with little transcript: `{', '.join(unit['unit_id'] for unit in visual_change_little_text) or 'none'}`",
            "",
            "## Known Issues",
            "",
        ]
    )
    if not content_map["known_issues"]:
        lines.append("- No operator-supplied known issues.")
    for issue in content_map["known_issues"]:
        lines.append(f"- {issue}")
    lines.extend(
        [
            "",
            "## Prompt Pack Summary",
            "",
            f"- Generated: `{content_map['prompt_pack']['generated']}`",
            f"- Path: `{content_map['prompt_pack']['path']}`",
            f"- Item count: `{content_map['prompt_pack']['item_count']}`",
            f"- Schema: `{content_map['prompt_pack']['schema_version']}`",
            "- Purpose: manual review or future Batch 5B grounded generation. No model call was made.",
            "",
            "## Human Review Checklist",
            "",
            "- Check whether content units are too fragmented or too coarse.",
            "- Check whether each selected screenshot supports the nearby transcript excerpts.",
            "- Review near-duplicate groups and confirm that useful teaching states were not hidden.",
            "- Review units without selected images and decide whether another representative is needed.",
            "- Confirm that the handout skeleton is not mistaken for final polished notes.",
            "",
            "## Next-Step Recommendation",
            "",
            "Run an independent Validation Agent review and a human spot-check before proceeding to any LLM-backed generation stage.",
        ]
    )
    return "\n".join(lines)


def run_batch_5a(config: dict[str, Any], run_dir: Path) -> dict[str, Any]:
    options = resolve_batch5_options(config)
    output_paths = batch5_output_paths(run_dir, options)
    clear_batch5_outputs(run_dir, output_paths)
    backend = resolve_content_generation_backend(options)
    inputs = preflight_batch5_inputs(run_dir)

    units = build_content_units(inputs, options)
    if not units:
        raise Batch5AInputError("Batch 5A generated no content units.")
    image_groups = apply_handout_image_selection(units, options)
    topic_groups = build_topic_groups(units)
    prompt_pack = (
        write_prompt_pack(run_dir, output_paths["prompt_pack"], units, options)
        if options["generate_llm_prompt_pack"]
        else make_prompt_pack_disabled(output_paths["prompt_pack"])
    )
    generation_results = [
        backend.generate_section(PromptBuilder(options).build_section_request(unit))
        for unit in units
    ]
    validate_source_hashes(inputs)

    content_map = {
        "run_id": str(config["run_id"]),
        "status": "success",
        "review_status": "human_review_required",
        "generated_at": utc_now(),
        "method": CONTENT_MAP_METHOD,
        "source_artifacts": inputs["source_paths"],
        "source_hashes": inputs["source_hashes"],
        "source_metadata": {
            "transcript_source_type": (
                inputs["raw_transcript"].get("source") or {}
            ).get("type"),
            "transcript_language": (
                inputs["raw_transcript"].get("source") or {}
            ).get("language"),
            "visual_segment_count": len(inputs["visuals"]),
        },
        "input_health": inputs["input_health"],
        "content_units": units,
        "topic_groups": topic_groups,
        "near_duplicate_image_groups": image_groups,
        "global_warnings": [
            "Batch 5A creates a deterministic skeleton, not final polished lecture notes."
        ],
        "known_issues": options["content_map_known_issues"],
        "validation_summary": content_map_validation_summary(
            units, topic_groups, image_groups
        ),
        "content_generation_backend": {
            "name": backend.name,
            "mode": options["content_generation_backend_mode"],
            "network_calls": False,
            "api_key_read": False,
            "generation_results": generation_results,
        },
        "prompt_pack": prompt_pack,
    }
    if options["generate_content_map"]:
        write_json(output_paths["content_map"], content_map)
    if options["generate_review_report"]:
        write_text(output_paths["review_report"], render_review_report(content_map))
    if options["generate_lecture_handout"]:
        write_text(
            output_paths["lecture_handout"],
            HandoutRenderer(options).render_skeleton(content_map),
        )
    validate_source_hashes(inputs)
    return content_map
