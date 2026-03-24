"""whisper.cpp による文字起こし。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Callable

from mov_voicecrop.config import AppConfig


ProgressLineCallback = Callable[[str], None]


def _parse_timestamp_string(value: str) -> float:
    hours, minutes, seconds = value.replace(",", ".").split(":")
    return (int(hours) * 3600) + (int(minutes) * 60) + float(seconds)


def _extract_seconds(segment: dict[str, Any], key: str) -> float:
    offsets = segment.get("offsets", {})
    if key in offsets:
        return float(offsets[key]) / 1000.0

    timestamps = segment.get("timestamps", {})
    if key in timestamps:
        return _parse_timestamp_string(str(timestamps[key]))

    return 0.0


def _average_token_probability(segment: dict[str, Any]) -> float:
    tokens = segment.get("tokens", [])
    probabilities = [
        float(token["p"])
        for token in tokens
        if isinstance(token, dict) and token.get("p") is not None
    ]
    if probabilities:
        return sum(probabilities) / len(probabilities)
    return 1.0


def _parse_transcription_json(json_path: Path) -> list[dict[str, Any]]:
    with json_path.open("r", encoding="utf-8") as file:
        payload = json.load(file)

    transcription = payload.get("transcription")
    if not isinstance(transcription, list):
        raise ValueError("whisper.cpp の JSON に transcription 配列がありません。")

    segments: list[dict[str, Any]] = []
    for item in transcription:
        if not isinstance(item, dict):
            continue

        text = str(item.get("text", "")).strip()
        start = _extract_seconds(item, "from")
        end = _extract_seconds(item, "to")

        if end <= start:
            continue

        segments.append(
            {
                "start": start,
                "end": end,
                "text": text,
                "avg_token_prob": _average_token_probability(item),
            }
        )

    return segments


def transcribe(
    wav_path: Path,
    config: AppConfig,
    progress_callback: ProgressLineCallback | None = None,
) -> list[dict[str, Any]]:
    """whisper.cpp を実行してセグメント一覧を返す。"""
    output_prefix = wav_path.parent / f"{wav_path.stem}_whisper"
    json_path = output_prefix.with_suffix(".json")

    command = [
        str(config.whisper_cli_path),
        "-m",
        str(config.whisper_model_path),
        "--vad",
        "-vm",
        str(config.whisper_vad_model_path),
        "-l",
        config.language,
        "-t",
        str(config.whisper_threads),
        "--output-json-full",
        "--print-progress",
        "-of",
        str(output_prefix),
        "-f",
        str(wav_path),
    ]

    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except FileNotFoundError as error:
        raise FileNotFoundError(
            f"whisper-cli が見つかりません: {config.whisper_cli_path}"
        ) from error

    combined_lines: list[str] = []
    assert process.stdout is not None
    for line in process.stdout:
        stripped = line.strip()
        combined_lines.append(stripped)
        if stripped and progress_callback is not None:
            progress_callback(stripped)

    return_code = process.wait()
    if return_code != 0:
        joined = "\n".join(line for line in combined_lines[-20:] if line)
        raise RuntimeError(
            f"whisper.cpp の実行に失敗しました。\n{joined}"
        )

    if not json_path.exists():
        raise FileNotFoundError(
            f"whisper.cpp の JSON 出力が見つかりません: {json_path}"
        )

    return _parse_transcription_json(json_path)
