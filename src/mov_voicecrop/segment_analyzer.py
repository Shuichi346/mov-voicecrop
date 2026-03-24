"""発話区間の統合判定。"""

from __future__ import annotations

from typing import Any

from mov_voicecrop.config import AppConfig


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


def analyze_segments(
    whisper_segments: list[dict[str, Any]],
    silence_regions: list[dict[str, float]],
    media_duration: float,
    config: AppConfig,
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

    return merged_segments
