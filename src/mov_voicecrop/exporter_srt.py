"""SRT エクスポーター。"""

from __future__ import annotations

from pathlib import Path
from typing import Any


def _format_timestamp(seconds: float) -> str:
    total_milliseconds = max(0, int(round(seconds * 1000)))
    hours, remainder = divmod(total_milliseconds, 3_600_000)
    minutes, remainder = divmod(remainder, 60_000)
    secs, milliseconds = divmod(remainder, 1000)
    return f"{hours:02}:{minutes:02}:{secs:02},{milliseconds:03}"


def export_srt(
    segments: list[dict[str, Any]],
    output_path: Path,
    mode: str = "original",
) -> Path:
    """セグメントを SRT に書き出す。"""
    if mode not in {"original", "reindexed"}:
        raise ValueError(f"未対応の SRT モードです: {mode}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    timeline_offset = 0.0
    subtitle_index = 1

    for segment in sorted(segments, key=lambda item: item["start"]):
        original_start = float(segment["start"])
        original_end = float(segment["end"])
        duration = max(0.0, original_end - original_start)
        if duration <= 0:
            continue

        if mode == "original":
            start = original_start
            end = original_end
        else:
            start = timeline_offset
            end = timeline_offset + duration
            timeline_offset = end

        text = str(segment.get("text", "")).strip()
        lines.extend(
            [
                str(subtitle_index),
                f"{_format_timestamp(start)} --> {_format_timestamp(end)}",
                text,
                "",
            ]
        )
        subtitle_index += 1

    output_path.write_text("\n".join(lines), encoding="utf-8-sig")
    return output_path
