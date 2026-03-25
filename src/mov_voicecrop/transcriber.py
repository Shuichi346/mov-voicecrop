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


def _repair_broken_utf8(raw: bytes) -> str:
    """whisper.cpp が分割した不正 UTF-8 バイト列を可能な限り復元する。

    whisper.cpp は CJK 文字（3バイト UTF-8）をトークン境界で
    2バイト + 1バイトに分割して JSON に書き出すことがある（Issue #1798）。
    復元できないバイトは U+FFFD に置き換える。
    """
    result: list[str] = []
    index = 0
    length = len(raw)

    while index < length:
        byte = raw[index]

        # ASCII 範囲（0x00-0x7F）: そのまま
        if byte <= 0x7F:
            result.append(chr(byte))
            index += 1
            continue

        # マルチバイトの先頭バイトから必要バイト数を判定
        if 0xC0 <= byte <= 0xDF:
            need = 2
        elif 0xE0 <= byte <= 0xEF:
            need = 3
        elif 0xF0 <= byte <= 0xF7:
            need = 4
        else:
            # 継続バイト（0x80-0xBF）が単独で出現: スキップして蓄積
            result.append("\ufffd")
            index += 1
            continue

        # 必要なバイト数が揃っているか確認
        if index + need <= length:
            chunk = raw[index : index + need]
            try:
                result.append(chunk.decode("utf-8"))
                index += need
                continue
            except UnicodeDecodeError:
                pass

        # バイトが足りない、またはデコード失敗: 置換して進む
        result.append("\ufffd")
        index += 1

    return "".join(result)


def _parse_transcription_json(json_path: Path) -> list[dict[str, Any]]:
    raw_bytes = json_path.read_bytes()
    text = _repair_broken_utf8(raw_bytes)
    payload = json.loads(text)

    transcription = payload.get("transcription")
    if not isinstance(transcription, list):
        raise ValueError("whisper.cpp の JSON に transcription 配列がありません。")

    segments: list[dict[str, Any]] = []
    for item in transcription:
        if not isinstance(item, dict):
            continue

        text_value = str(item.get("text", "")).strip()
        start = _extract_seconds(item, "from")
        end = _extract_seconds(item, "to")

        if end <= start:
            continue

        segments.append(
            {
                "start": start,
                "end": end,
                "text": text_value,
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

    # whisper.cpp は警告レベルでも非ゼロ終了することがある。
    # JSON 出力が生成されていればそちらを優先して読み取る。
    if json_path.exists():
        return _parse_transcription_json(json_path)

    if return_code != 0:
        joined = "\n".join(line for line in combined_lines[-30:] if line)
        raise RuntimeError(
            f"whisper.cpp の実行に失敗しました（終了コード: {return_code}）。\n{joined}"
        )

    raise FileNotFoundError(
        f"whisper.cpp の JSON 出力が見つかりません: {json_path}"
    )
