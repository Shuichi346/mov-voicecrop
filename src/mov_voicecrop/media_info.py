"""メディア情報取得。"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any


def _parse_rational(value: str) -> float:
    numerator, denominator = value.split("/", maxsplit=1)
    if float(denominator) == 0:
        return 0.0
    return float(numerator) / float(denominator)


def get_media_info(video_path: Path) -> dict[str, Any]:
    """ffprobe で動画メタデータを取得する。"""
    command = [
        "ffprobe",
        "-v",
        "quiet",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        str(video_path),
    ]

    try:
        completed = subprocess.run(
            command,
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as error:
        raise FileNotFoundError(
            "ffprobe が見つかりません。ffmpeg をインストールしてください: brew install ffmpeg"
        ) from error
    except subprocess.CalledProcessError as error:
        raise RuntimeError(
            f"ffprobe の実行に失敗しました: {error.stderr.strip()}"
        ) from error

    payload = json.loads(completed.stdout)
    streams = payload.get("streams", [])
    format_info = payload.get("format", {})

    video_stream = next((stream for stream in streams if stream.get("codec_type") == "video"), None)
    audio_stream = next((stream for stream in streams if stream.get("codec_type") == "audio"), None)

    if video_stream is None:
        raise ValueError("映像ストリームが見つかりません。")
    if audio_stream is None:
        raise ValueError("音声ストリームが見つかりません。音声付き動画を指定してください。")

    fps_rational = video_stream.get("r_frame_rate", "0/1")

    return {
        "duration": float(format_info.get("duration", 0.0)),
        "width": int(video_stream.get("width", 0)),
        "height": int(video_stream.get("height", 0)),
        "fps": _parse_rational(fps_rational),
        "fps_rational": fps_rational,
        "video_codec": video_stream.get("codec_name", ""),
        "audio_codec": audio_stream.get("codec_name", ""),
        "audio_sample_rate": int(audio_stream.get("sample_rate", 0)),
        "audio_channels": int(audio_stream.get("channels", 0)),
        "absolute_path": str(video_path.resolve()),
        "filename": video_path.stem,
    }


def extract_audio_wav(video_path: Path, output_wav: Path) -> Path:
    """動画から 16kHz mono の WAV を抽出する。"""
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ar",
        "16000",
        "-ac",
        "1",
        str(output_wav),
    ]

    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as error:
        raise FileNotFoundError(
            "ffmpeg が見つかりません。ffmpeg をインストールしてください: brew install ffmpeg"
        ) from error
    except subprocess.CalledProcessError as error:
        raise RuntimeError(
            f"WAV 変換に失敗しました: {error.stderr.strip()}"
        ) from error

    return output_wav
