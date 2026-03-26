"""whisper.cpp による文字起こし。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Callable

from mov_voicecrop.config import AppConfig


ProgressLineCallback = Callable[[str], None]

# whisper.cpp の特殊トークンプレフィックス（タイムスタンプトークンなど）
_SPECIAL_TOKEN_PREFIXES = ("[_", )


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


def _extract_token_seconds(token: dict[str, Any], key: str) -> float:
    """トークンから時刻（秒）を取得する。"""
    offsets = token.get("offsets", {})
    if key in offsets:
        return float(offsets[key]) / 1000.0

    timestamps = token.get("timestamps", {})
    if key in timestamps:
        return _parse_timestamp_string(str(timestamps[key]))

    return 0.0


def _is_special_token(token: dict[str, Any]) -> bool:
    """特殊トークン（[_BEG_], [_TT_xxx] 等）かどうかを判定する。"""
    text = str(token.get("text", ""))
    return any(text.startswith(prefix) for prefix in _SPECIAL_TOKEN_PREFIXES)


def _average_token_probability(segment: dict[str, Any]) -> float:
    tokens = segment.get("tokens", [])
    probabilities = [
        float(token["p"])
        for token in tokens
        if isinstance(token, dict)
        and token.get("p") is not None
        and not _is_special_token(token)
    ]
    if probabilities:
        return sum(probabilities) / len(probabilities)
    return 1.0


def _extract_token_details(
    segment: dict[str, Any],
    segment_start: float,
    segment_end: float,
) -> list[dict[str, Any]]:
    """セグメント内の通常トークン（特殊トークンを除く）の詳細を抽出する。

    各トークンの offsets はセグメント先頭からの相対オフセットなので、
    segment_start を加算して絶対時刻に変換する。
    """
    raw_tokens = segment.get("tokens", [])
    details: list[dict[str, Any]] = []

    for token in raw_tokens:
        if not isinstance(token, dict):
            continue
        if _is_special_token(token):
            continue

        text = str(token.get("text", ""))
        probability = float(token.get("p", 1.0))
        token_from = _extract_token_seconds(token, "from")
        token_to = _extract_token_seconds(token, "to")

        # whisper.cpp のトークンオフセットはセグメント内相対値
        absolute_from = segment_start + token_from
        absolute_to = segment_start + token_to

        # 終了が開始以下のトークンは前のトークンの終了を引き継ぐ
        if absolute_to <= absolute_from:
            if details:
                absolute_from = max(absolute_from, details[-1]["end"])
            absolute_to = absolute_from

        details.append({
            "text": text,
            "start": absolute_from,
            "end": absolute_to,
            "p": probability,
        })

    # トークン時刻をセグメント範囲内に収める
    if details:
        details[0]["start"] = max(segment_start, details[0]["start"])
        details[-1]["end"] = min(segment_end, max(details[-1]["end"], details[-1]["start"]))

        # 終了時刻が不明（0）なトークンの時刻を前後から補間する
        for i, detail in enumerate(details):
            if detail["end"] <= detail["start"]:
                next_start = segment_end
                for j in range(i + 1, len(details)):
                    if details[j]["start"] > detail["start"]:
                        next_start = details[j]["start"]
                        break
                detail["end"] = next_start

    return details


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

        if byte <= 0x7F:
            result.append(chr(byte))
            index += 1
            continue

        if 0xC0 <= byte <= 0xDF:
            need = 2
        elif 0xE0 <= byte <= 0xEF:
            need = 3
        elif 0xF0 <= byte <= 0xF7:
            need = 4
        else:
            result.append("\ufffd")
            index += 1
            continue

        if index + need <= length:
            chunk = raw[index : index + need]
            try:
                result.append(chunk.decode("utf-8"))
                index += need
                continue
            except UnicodeDecodeError:
                pass

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

        token_details = _extract_token_details(item, start, end)

        segments.append(
            {
                "start": start,
                "end": end,
                "text": text_value,
                "avg_token_prob": _average_token_probability(item),
                "tokens": token_details,
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
