"""メディア情報取得。"""

from __future__ import annotations

import json
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any


def _safe_float(value: Any) -> float:
    """安全に float へ変換する。"""
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return 0.0


def _safe_int(value: Any) -> int:
    """安全に int へ変換する。"""
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        try:
            return int(float(str(value).strip()))
        except (TypeError, ValueError):
            return 0


def _parse_fraction(value: str) -> Fraction:
    """有理数文字列を Fraction へ変換する。"""
    try:
        numerator, denominator = value.split("/", maxsplit=1)
        numerator_int = int(numerator)
        denominator_int = int(denominator)
        if denominator_int == 0:
            return Fraction(0, 1)
        return Fraction(numerator_int, denominator_int)
    except (AttributeError, ValueError, ZeroDivisionError):
        return Fraction(0, 1)


def _parse_rational(value: str) -> float:
    """有理数文字列を float へ変換する。"""
    fraction = _parse_fraction(value)
    if fraction <= 0:
        return 0.0
    return float(fraction)


def _normalize_fraction_string(value: str) -> str:
    """有理数文字列を正規化する。"""
    fraction = _parse_fraction(value)
    if fraction <= 0:
        return "30/1"
    return f"{fraction.numerator}/{fraction.denominator}"


def _pick_fps_rational(video_stream: dict[str, Any]) -> str:
    """利用する fps 表記を決定する。"""
    candidates = [
        str(video_stream.get("avg_frame_rate", "")),
        str(video_stream.get("r_frame_rate", "")),
    ]
    for candidate in candidates:
        fraction = _parse_fraction(candidate)
        if fraction > 0:
            return _normalize_fraction_string(candidate)
    return "30/1"


def _estimate_video_frame_count(
    video_stream: dict[str, Any],
    fps_rational: str,
) -> int:
    """動画ストリームの実フレーム数を推定する。"""
    for key in ("nb_read_frames", "nb_frames"):
        frame_count = _safe_int(video_stream.get(key))
        if frame_count > 0:
            return frame_count

    duration_ts = _safe_int(video_stream.get("duration_ts"))
    time_base = _parse_fraction(str(video_stream.get("time_base", "0/1")))
    fps_fraction = _parse_fraction(fps_rational)

    if duration_ts > 0 and time_base > 0 and fps_fraction > 0:
        estimated = int(
            Fraction(duration_ts, 1) * time_base * fps_fraction + Fraction(1, 2)
        )
        if estimated > 0:
            return estimated

    stream_duration = _safe_float(video_stream.get("duration"))
    if stream_duration > 0 and fps_fraction > 0:
        estimated = int(
            Fraction(str(stream_duration)) * fps_fraction + Fraction(1, 2)
        )
        if estimated > 0:
            return estimated

    return 0


def get_media_info(video_path: Path) -> dict[str, Any]:
    """ffprobe で動画メタデータを取得する。"""
    command = [
        "ffprobe",
        "-v",
        "quiet",
        "-count_frames",
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

    video_stream = next(
        (stream for stream in streams if stream.get("codec_type") == "video"),
        None,
    )
    audio_stream = next(
        (stream for stream in streams if stream.get("codec_type") == "audio"),
        None,
    )

    if video_stream is None:
        raise ValueError("映像ストリームが見つかりません。")
    if audio_stream is None:
        raise ValueError("音声ストリームが見つかりません。音声付き動画を指定してください。")

    fps_rational = _pick_fps_rational(video_stream)
    fps_fraction = _parse_fraction(fps_rational)
    frame_count = _estimate_video_frame_count(video_stream, fps_rational)

    stream_duration = _safe_float(video_stream.get("duration"))
    format_duration = _safe_float(format_info.get("duration"))

    if frame_count > 0 and fps_fraction > 0:
        video_duration = float(Fraction(frame_count, 1) / fps_fraction)
    elif stream_duration > 0:
        video_duration = stream_duration
    else:
        video_duration = format_duration

    return {
        "duration": video_duration,
        "container_duration": format_duration,
        "frame_count": frame_count,
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
