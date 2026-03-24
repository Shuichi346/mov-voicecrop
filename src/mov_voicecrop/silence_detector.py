"""無音区間検出。"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from mov_voicecrop.config import AppConfig
from mov_voicecrop.media_info import get_media_info


SILENCE_START_PATTERN = re.compile(r"silence_start:\s*([0-9.]+)")
SILENCE_END_PATTERN = re.compile(
    r"silence_end:\s*([0-9.]+)\s*\|\s*silence_duration:\s*([0-9.]+)"
)


def detect_silence(video_path: Path, config: AppConfig) -> list[dict[str, float]]:
    """ffmpeg silencedetect で無音区間を抽出する。"""
    command = [
        "ffmpeg",
        "-i",
        str(video_path),
        "-af",
        (
            "silencedetect="
            f"noise={config.silence_thresh_db}dB:"
            f"d={config.min_silence_duration}"
        ),
        "-f",
        "null",
        "-",
    ]

    try:
        completed = subprocess.run(
            command,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as error:
        raise FileNotFoundError(
            "ffmpeg が見つかりません。ffmpeg をインストールしてください: brew install ffmpeg"
        ) from error

    stderr = completed.stderr
    media_duration = get_media_info(video_path)["duration"]
    regions: list[dict[str, float]] = []
    current_start: float | None = None

    for line in stderr.splitlines():
        start_match = SILENCE_START_PATTERN.search(line)
        if start_match:
            current_start = float(start_match.group(1))
            continue

        end_match = SILENCE_END_PATTERN.search(line)
        if end_match and current_start is not None:
            end_value = float(end_match.group(1))
            duration = float(end_match.group(2))
            regions.append(
                {
                    "start": current_start,
                    "end": end_value,
                    "duration": duration,
                }
            )
            current_start = None

    if current_start is not None and media_duration > current_start:
        regions.append(
            {
                "start": current_start,
                "end": media_duration,
                "duration": media_duration - current_start,
            }
        )

    total_silence = sum(region["duration"] for region in regions)
    print(f"無音区間: {len(regions)} 個 / 合計 {total_silence:.2f} 秒")
    return regions
