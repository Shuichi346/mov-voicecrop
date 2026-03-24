from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

from mov_voicecrop.config import AppConfig, PROJECT_ROOT
from mov_voicecrop.media_info import get_media_info


TEMP_DIR = PROJECT_ROOT / "temp"


def _run_ffmpeg(command: list[str], error_message: str) -> None:
    """ffmpeg コマンドを実行し、失敗時は例外を送出する。"""
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as error:
        raise FileNotFoundError(
            "ffmpeg が見つかりません。ffmpeg をインストールしてください: brew install ffmpeg"
        ) from error
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f"{error_message}: {error.stderr.strip()}") from error


def _is_videotoolbox_available() -> bool:
    """ffmpeg が h264_videotoolbox エンコーダーをサポートしているか確認する。"""
    try:
        result = subprocess.run(
            ["ffmpeg", "-hide_banner", "-encoders"],
            capture_output=True,
            text=True,
            check=False,
        )
        return "h264_videotoolbox" in result.stdout
    except FileNotFoundError:
        return False


def _resolve_video_encoder(config: AppConfig) -> str:
    """設定に応じて使用する映像エンコーダーを決定する。

    "auto" の場合は h264_videotoolbox が使えればそちらを、
    使えなければ libx264 にフォールバックする。
    """
    if config.video_encoder == "auto":
        if _is_videotoolbox_available():
            return "h264_videotoolbox"
        return "libx264"
    return config.video_encoder


def _video_codec_args(encoder: str) -> list[str]:
    """エンコーダー名に対応する ffmpeg 引数リストを返す。"""
    if encoder == "h264_videotoolbox":
        return ["-c:v", "h264_videotoolbox", "-b:v", "5M"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "23"]


def _ensure_temp_dir() -> Path:
    """プロジェクトルート直下の temp/ ディレクトリを作成して返す。"""
    TEMP_DIR.mkdir(parents=True, exist_ok=True)
    return TEMP_DIR


def _cut_segment_file(
    video_path: Path,
    segment: dict[str, Any],
    output_path: Path,
    encoder: str,
) -> Path:
    """1つのセグメントを入力動画から切り出す。"""
    start = float(segment["start"])
    duration = max(0.0, float(segment["end"]) - start)
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-ss",
        f"{start:.6f}",
        "-t",
        f"{duration:.6f}",
        *_video_codec_args(encoder),
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    _run_ffmpeg(command, f"セグメント {output_path.name} の切り出しに失敗しました")
    return output_path


def _render_placeholder_video(
    video_path: Path,
    output_path: Path,
    encoder: str,
) -> Path:
    """セグメントが0件の場合に空動画を生成する。"""
    media_info = get_media_info(video_path)
    duration = "0.1"
    command = [
        "ffmpeg",
        "-y",
        "-f",
        "lavfi",
        "-i",
        (
            f"color=c=black:s={media_info['width']}x{media_info['height']}:"
            f"r={media_info['fps'] or 30}:d={duration}"
        ),
        "-f",
        "lavfi",
        "-i",
        "anullsrc=r=48000:cl=stereo",
        "-shortest",
        *_video_codec_args(encoder),
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    _run_ffmpeg(command, "空動画の生成に失敗しました")
    return output_path


def _render_base_cut_video(
    video_path: Path,
    segments: list[dict[str, Any]],
    output_path: Path,
    encoder: str,
) -> Path:
    """セグメントを個別に切り出し、concat demuxer で結合する。"""
    if not segments:
        return _render_placeholder_video(video_path, output_path, encoder)

    temp_dir = _ensure_temp_dir()
    segment_paths: list[Path] = []

    try:
        for index, segment in enumerate(segments):
            segment_path = temp_dir / f"segment_{index:04}.mp4"
            _cut_segment_file(video_path, segment, segment_path, encoder)
            segment_paths.append(segment_path)

        concat_list_path = temp_dir / "concat.txt"
        concat_lines = [
            f"file '{path.as_posix()}'" for path in segment_paths
        ]
        concat_list_path.write_text("\n".join(concat_lines), encoding="utf-8")

        command = [
            "ffmpeg",
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_list_path),
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        _run_ffmpeg(command, "セグメント結合に失敗しました")
    finally:
        for path in segment_paths:
            path.unlink(missing_ok=True)
        (temp_dir / "concat.txt").unlink(missing_ok=True)

    return output_path


def _attach_soft_subtitles(
    base_video_path: Path,
    srt_path: Path,
    output_path: Path,
) -> Path:
    """ソフトサブ（mov_text）を付与する。"""
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(base_video_path),
        "-i",
        str(srt_path),
        "-map",
        "0:v:0",
        "-map",
        "0:a:0",
        "-map",
        "1:0",
        "-c:v",
        "copy",
        "-c:a",
        "copy",
        "-c:s",
        "mov_text",
        "-metadata:s:s:0",
        "language=jpn",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    _run_ffmpeg(command, "ソフトサブ付き MP4 の生成に失敗しました")
    return output_path


def export_mp4(
    video_path: Path,
    segments: list[dict[str, Any]],
    srt_path: Path,
    output_path: Path,
    subtitle_mode: str,
    config: AppConfig,
) -> list[Path]:
    """カット済み MP4 を生成する。

    subtitle_mode:
        "soft" — ソフトサブ（mov_text）を付与
        "off"  — 字幕なし
    """
    output_path.parent.mkdir(parents=True, exist_ok=True)
    encoder = _resolve_video_encoder(config)

    temp_dir = _ensure_temp_dir()
    base_cut_path = temp_dir / f"{output_path.stem}_base.mp4"

    try:
        _render_base_cut_video(video_path, segments, base_cut_path, encoder)

        if subtitle_mode == "soft":
            return [_attach_soft_subtitles(base_cut_path, srt_path, output_path)]

        if subtitle_mode == "off":
            command = [
                "ffmpeg",
                "-y",
                "-i",
                str(base_cut_path),
                "-c",
                "copy",
                "-movflags",
                "+faststart",
                str(output_path),
            ]
            _run_ffmpeg(command, "字幕なし MP4 の生成に失敗しました")
            return [output_path]

        raise ValueError(f"未対応の字幕モードです: {subtitle_mode}")
    finally:
        base_cut_path.unlink(missing_ok=True)