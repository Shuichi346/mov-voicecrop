"""発話区間の統合判定。"""

from __future__ import annotations

from fractions import Fraction
from typing import Any

from mov_voicecrop.config import AppConfig


def _parse_fps_rational(value: str) -> tuple[int, int]:
    """fps の有理数文字列を安全に解析する。"""
    try:
        numerator, denominator = value.split("/", maxsplit=1)
        fps_num = int(numerator)
        fps_den = int(denominator)
        if fps_num <= 0 or fps_den <= 0:
            return 30, 1
        return fps_num, fps_den
    except (AttributeError, ValueError):
        return 30, 1


def _seconds_to_frame_index(seconds: float, fps_num: int, fps_den: int) -> int:
    """秒を最も近いフレーム番号へ変換する。"""
    frames = Fraction(str(max(0.0, seconds))) * Fraction(fps_num, fps_den)
    return int(frames + Fraction(1, 2))


def _frame_index_to_seconds(frame_index: int, fps_num: int, fps_den: int) -> float:
    """フレーム番号を秒へ変換する。"""
    if frame_index <= 0:
        return 0.0
    return float(Fraction(frame_index * fps_den, fps_num))


def _clip_interval_by_silence(
    start: float,
    end: float,
    silence_regions: list[dict[str, float]],
) -> tuple[float, float] | None:
    clipped_start = start
    clipped_end = end

    for region in silence_regions:
        silence_start = region["start"]
        silence_end = region["end"]

        if silence_end <= clipped_start or silence_start >= clipped_end:
            continue

        if silence_start <= clipped_start < silence_end:
            clipped_start = silence_end

        if silence_start < clipped_end <= silence_end:
            clipped_end = silence_start

        if silence_start > clipped_start and silence_end < clipped_end:
            left_length = silence_start - clipped_start
            right_length = clipped_end - silence_end
            if left_length >= right_length:
                clipped_end = silence_start
            else:
                clipped_start = silence_end

        if clipped_end <= clipped_start:
            return None

    return clipped_start, clipped_end


def _merge_text(current_text: str, next_text: str) -> str:
    if not current_text:
        return next_text
    if not next_text or next_text == current_text:
        return current_text
    if next_text in current_text:
        return current_text
    return f"{current_text}\n{next_text}"


def _normalize_to_frame_grid(
    segments: list[dict[str, Any]],
    media_duration: float,
    fps_rational: str,
    source_frame_count: int | None = None,
) -> list[dict[str, Any]]:
    """セグメント境界をフレーム単位へ正規化する。"""
    if not segments:
        return []

    fps_num, fps_den = _parse_fps_rational(fps_rational)

    if source_frame_count is not None and source_frame_count > 0:
        media_end_frame = source_frame_count
    else:
        media_end_frame = _seconds_to_frame_index(media_duration, fps_num, fps_den)

    if media_end_frame <= 0:
        return []

    normalized: list[dict[str, Any]] = []
    previous_end_frame = 0

    for raw_segment in sorted(segments, key=lambda item: float(item["start"])):
        start_seconds = float(raw_segment["start"])
        end_seconds = float(raw_segment["end"])

        start_frame = _seconds_to_frame_index(start_seconds, fps_num, fps_den)
        end_frame = _seconds_to_frame_index(end_seconds, fps_num, fps_den)

        start_frame = max(previous_end_frame, start_frame)
        start_frame = min(start_frame, media_end_frame - 1)
        end_frame = min(media_end_frame, max(start_frame + 1, end_frame))

        if end_frame <= start_frame:
            continue

        segment = raw_segment.copy()
        segment["start"] = _frame_index_to_seconds(start_frame, fps_num, fps_den)
        segment["end"] = _frame_index_to_seconds(end_frame, fps_num, fps_den)
        normalized.append(segment)

        previous_end_frame = end_frame

    return normalized


def analyze_segments(
    whisper_segments: list[dict[str, Any]],
    silence_regions: list[dict[str, float]],
    media_duration: float,
    config: AppConfig,
    fps_rational: str = "30/1",
    source_frame_count: int | None = None,
) -> list[dict[str, Any]]:
    """whisper と無音検出結果を統合して保持区間を返す。"""
    valid_segments: list[dict[str, Any]] = []

    for segment in whisper_segments:
        text = str(segment.get("text", "")).strip()
        avg_token_prob = float(segment.get("avg_token_prob", 0.0))
        if avg_token_prob < config.min_confidence:
            continue

        start = float(segment.get("start", 0.0))
        end = float(segment.get("end", 0.0))
        if end <= start:
            continue

        clipped = _clip_interval_by_silence(start, end, silence_regions)
        if clipped is None:
            continue

        clipped_start, clipped_end = clipped
        padded_start = max(0.0, clipped_start - config.padding)
        padded_end = min(media_duration, clipped_end + config.padding)
        if padded_end <= padded_start:
            continue

        valid_segments.append(
            {
                "start": padded_start,
                "end": padded_end,
                "text": text,
                "avg_token_prob": avg_token_prob,
            }
        )

    if not valid_segments:
        return []

    valid_segments.sort(key=lambda item: item["start"])
    merged_segments: list[dict[str, Any]] = [valid_segments[0].copy()]

    for segment in valid_segments[1:]:
        current = merged_segments[-1]
        if float(current["end"]) >= float(segment["start"]):
            current["end"] = max(float(current["end"]), float(segment["end"]))
            current["text"] = _merge_text(
                str(current.get("text", "")),
                str(segment.get("text", "")),
            )
            current["avg_token_prob"] = max(
                float(current.get("avg_token_prob", 0.0)),
                float(segment.get("avg_token_prob", 0.0)),
            )
            continue

        merged_segments.append(segment.copy())

    for segment in merged_segments:
        segment.pop("avg_token_prob", None)

    return _normalize_to_frame_grid(
        merged_segments,
        media_duration=media_duration,
        fps_rational=fps_rational,
        source_frame_count=source_frame_count,
    )
