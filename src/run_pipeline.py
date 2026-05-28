from __future__ import annotations

import argparse
import json
import ast
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


REQUIRED_CONFIG_FIELDS = ("video_url", "run_id", "output_dir")


def parse_scalar(value: str) -> str:
    stripped = value.strip()
    if not stripped:
        return ""
    if stripped[0] in {"'", '"'}:
        try:
            parsed = ast.literal_eval(stripped)
        except (SyntaxError, ValueError):
            return stripped.strip("'\"")
        return str(parsed)
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


def validate_run_id(run_id: str) -> str:
    normalized = run_id.strip()
    if normalized in {"", ".", ".."}:
        raise ValueError("run_id must be a non-empty directory name.")
    if any(separator in normalized for separator in ("/", "\\")):
        raise ValueError("run_id must not contain path separators.")
    return normalized


def initialize_run(config_path: Path) -> Path:
    resolved_config_path = config_path.resolve()
    config = load_config(resolved_config_path)

    run_id = validate_run_id(str(config["run_id"]))
    video_url = str(config["video_url"]).strip()
    output_dir = Path(str(config["output_dir"]).strip())

    run_dir = output_dir / run_id
    keyframes_dir = run_dir / "assets" / "keyframes"
    audit_dir = run_dir / "audit"

    keyframes_dir.mkdir(parents=True, exist_ok=True)
    audit_dir.mkdir(parents=True, exist_ok=True)

    metadata = {
        "run_id": run_id,
        "video_url": video_url,
        "output_dir": str(output_dir),
        "config_path": str(resolved_config_path),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "initialized",
    }

    metadata_path = audit_dir / "run_metadata.json"
    with metadata_path.open("w", encoding="utf-8") as file:
        json.dump(metadata, file, indent=2, ensure_ascii=False)
        file.write("\n")

    return run_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Initialize the minimal run directory skeleton for Batch 1."
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

    run_dir = initialize_run(Path(args.config))
    print(f"Initialized run directory: {run_dir}")


if __name__ == "__main__":
    main()
