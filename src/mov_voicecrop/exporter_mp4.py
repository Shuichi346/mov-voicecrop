"""MP4 エクスポーター。"""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

from mov_voicecrop.config import AppConfig
from mov_voicecrop.media_info import get_media_info


def _run_ffmpeg(command: list[str], error_message: str) -> None:
    try:
        subprocess.run(command, check=True, capture_output=True, text=True)
    except FileNotFoundError as error:
        raise FileNotFoundError(
            "ffmpeg が見つかりません。ffmpeg をインストールしてください: brew install ffmpeg"
        ) from error
    except subprocess.CalledProcessError as error:
        raise RuntimeError(f"{error_message}: {error.stderr.strip()}") from error


def _video_codec_args(config: AppConfig) -> list[str]:
    if config.video_encoder == "h264_videotoolbox":
        return ["-c:v", "h264_videotoolbox", "-b:v", "5M"]
    return ["-c:v", "libx264", "-preset", "medium", "-crf", "23"]


def _build_filter_complex(segments: list[dict[str, Any]]) -> str:
    filters: list[str] = []
    concat_inputs: list[str] = []

    for index, segment in enumerate(segments):
        start = float(segment["start"])
        end = float(segment["end"])
        filters.append(
            f"[0:v]trim=start={start:.6f}:end={end:.6f},setpts=PTS-STARTPTS[v{index}]"
        )
        filters.append(
            f"[0:a]atrim=start={start:.6f}:end={end:.6f},asetpts=PTS-STARTPTS[a{index}]"
        )
        concat_inputs.append(f"[v{index}][a{index}]")

    filters.append(
        f"{''.join(concat_inputs)}concat=n={len(segments)}:v=1:a=1[outv][outa]"
    )
    return ";".join(filters)


def _render_base_with_filter_complex(
    video_path: Path,
    segments: list[dict[str, Any]],
    output_path: Path,
    config: AppConfig,
) -> Path:
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-filter_complex",
        _build_filter_complex(segments),
        "-map",
        "[outv]",
        "-map",
        "[outa]",
        *_video_codec_args(config),
        "-c:a",
        "aac",
        "-b:a",
        "192k",
        "-movflags",
        "+faststart",
        str(output_path),
    ]
    _run_ffmpeg(command, "カット済み動画の生成に失敗しました")
    return output_path


def _cut_segment_file(
    video_path: Path,
    segment: dict[str, Any],
    output_path: Path,
    config: AppConfig,
) -> Path:
    duration = max(0.0, float(segment["end"]) - float(segment["start"]))
    command = [
        "ffmpeg",
        "-y",
        "-ss",
        f"{float(segment['start']):.6f}",
        "-i",
        str(video_path),
        "-t",
        f"{duration:.6f}",
        *_video_codec_args(config),
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


def _render_base_with_concat_files(
    video_path: Path,
    segments: list[dict[str, Any]],
    output_path: Path,
    config: AppConfig,
) -> Path:
    with tempfile.TemporaryDirectory(prefix="mov_voicecrop_concat_") as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        segment_paths: list[Path] = []

        for index, segment in enumerate(segments):
            segment_path = temp_dir / f"segment_{index:04}.mp4"
            _cut_segment_file(video_path, segment, segment_path, config)
            segment_paths.append(segment_path)

        concat_list_path = temp_dir / "concat.txt"
        concat_lines = [f"file '{segment_path.as_posix()}'" for segment_path in segment_paths]
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

    return output_path


def _render_placeholder_video(
    video_path: Path,
    output_path: Path,
    config: AppConfig,
) -> Path:
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
        *_video_codec_args(config),
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
    config: AppConfig,
) -> Path:
    if not segments:
        return _render_placeholder_video(video_path, output_path, config)
    if len(segments) <= 100:
        return _render_base_with_filter_complex(video_path, segments, output_path, config)
    return _render_base_with_concat_files(video_path, segments, output_path, config)


def _attach_soft_subtitles(
    base_video_path: Path,
    srt_path: Path,
    output_path: Path,
) -> Path:
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


def _load_subtitle_font(font_size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = [
        "/System/Library/Fonts/ヒラギノ角ゴシック W3.ttc",
        "/System/Library/Fonts/ヒラギノ角ゴシック W6.ttc",
        "/System/Library/Fonts/Supplemental/Arial Unicode.ttf",
        "/System/Library/Fonts/Supplemental/Arial Unicode MS.ttf",
    ]

    for candidate in candidates:
        font_path = Path(candidate)
        if not font_path.exists():
            continue
        try:
            return ImageFont.truetype(str(font_path), font_size)
        except OSError:
            continue

    return ImageFont.load_default()


def _render_subtitle_image(
    text: str,
    output_path: Path,
    width: int,
    height: int,
    font_size: int = 24,
) -> Path:
    image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    font = _load_subtitle_font(font_size)
    spacing = 8
    stroke_width = 3

    text_box = draw.multiline_textbbox(
        (0, 0),
        text,
        font=font,
        spacing=spacing,
        stroke_width=stroke_width,
        align="center",
    )
    text_width = text_box[2] - text_box[0]
    text_height = text_box[3] - text_box[1]
    x = (width - text_width) / 2
    y = height - text_height - 40

    background_padding_x = 18
    background_padding_y = 12
    draw.rounded_rectangle(
        [
            x - background_padding_x,
            y - background_padding_y,
            x + text_width + background_padding_x,
            y + text_height + background_padding_y,
        ],
        radius=18,
        fill=(0, 0, 0, 140),
    )
    draw.multiline_text(
        (x, y),
        text,
        font=font,
        fill=(255, 255, 255, 255),
        spacing=spacing,
        align="center",
        stroke_width=stroke_width,
        stroke_fill=(0, 0, 0, 255),
    )
    image.save(output_path)
    return output_path


def _build_overlay_assets(
    segments: list[dict[str, Any]],
    media_info: dict[str, Any],
    temp_dir: Path,
) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    timeline_offset = 0.0

    for index, segment in enumerate(sorted(segments, key=lambda item: item["start"])):
        duration = max(0.0, float(segment["end"]) - float(segment["start"]))
        if duration <= 0:
            continue

        text = str(segment.get("text", "")).strip()
        if not text:
            timeline_offset += duration
            continue

        start = timeline_offset
        end = timeline_offset + duration
        image_path = temp_dir / f"subtitle_{index:04}.png"
        _render_subtitle_image(
            text=text,
            output_path=image_path,
            width=int(media_info["width"]),
            height=int(media_info["height"]),
        )
        assets.append(
            {
                "path": image_path,
                "start": start,
                "end": end,
            }
        )
        timeline_offset = end

    return assets


def _burn_hard_subtitles(
    base_video_path: Path,
    segments: list[dict[str, Any]],
    output_path: Path,
    config: AppConfig,
) -> Path:
    media_info = get_media_info(base_video_path)
    overlay_assets = _build_overlay_assets(segments, media_info, base_video_path.parent)
    if not overlay_assets:
        command = [
            "ffmpeg",
            "-y",
            "-i",
            str(base_video_path),
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
        _run_ffmpeg(command, "ハードサブ付き MP4 の生成に失敗しました")
        return output_path

    total_duration = float(media_info["duration"])
    command = [
        "ffmpeg",
        "-y",
        "-i",
        str(base_video_path),
    ]

    for asset in overlay_assets:
        command.extend(
            [
                "-loop",
                "1",
                "-t",
                f"{total_duration:.6f}",
                "-i",
                str(asset["path"]),
            ]
        )

    filter_parts: list[str] = []
    previous_label = "0:v"

    for index, asset in enumerate(overlay_assets, start=1):
        next_label = f"v{index}"
        filter_parts.append(
            f"[{previous_label}][{index}:v]"
            "overlay="
            "x=(main_w-overlay_w)/2:"
            "y=main_h-overlay_h:"
            f"enable='between(t,{asset['start']:.6f},{asset['end']:.6f})':"
            f"eof_action=pass[{next_label}]"
        )
        previous_label = next_label

    command.extend(
        [
            "-filter_complex",
            ";".join(filter_parts),
            "-map",
            f"[{previous_label}]",
            "-map",
            "0:a:0",
            *_video_codec_args(config),
            "-c:a",
            "copy",
            "-movflags",
            "+faststart",
            str(output_path),
        ]
    )
    _run_ffmpeg(command, "ハードサブ付き MP4 の生成に失敗しました")
    return output_path


def export_mp4(
    video_path: Path,
    segments: list[dict[str, Any]],
    srt_path: Path,
    output_path: Path,
    subtitle_mode: str,
    config: AppConfig,
) -> list[Path]:
    """カット済み MP4 を生成する。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="mov_voicecrop_mp4_") as temp_dir_str:
        temp_dir = Path(temp_dir_str)
        base_cut_path = temp_dir / f"{output_path.stem}_base.mp4"
        _render_base_cut_video(video_path, segments, base_cut_path, config)

        if subtitle_mode == "soft":
            return [_attach_soft_subtitles(base_cut_path, srt_path, output_path)]

        if subtitle_mode == "hard":
            return [_burn_hard_subtitles(base_cut_path, segments, output_path, config)]

        if subtitle_mode == "both":
            soft_path = output_path.with_name(f"{output_path.stem}_soft{output_path.suffix}")
            hard_path = output_path.with_name(f"{output_path.stem}_hard{output_path.suffix}")
            return [
                _attach_soft_subtitles(base_cut_path, srt_path, soft_path),
                _burn_hard_subtitles(base_cut_path, segments, hard_path, config),
            ]

        raise ValueError(f"未対応の字幕モードです: {subtitle_mode}")
