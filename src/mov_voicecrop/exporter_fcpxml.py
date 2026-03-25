"""FCPXML エクスポーター（DaVinci Resolve 20 向け）。"""

from __future__ import annotations

import uuid
import xml.etree.ElementTree as element_tree
from fractions import Fraction
from pathlib import Path
from typing import Any
from urllib.parse import quote
from xml.dom import minidom


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


def _fraction_to_string(value: Fraction) -> str:
    """Fraction を FCPXML の時間文字列へ変換する。"""
    if value.numerator == 0:
        return "0s"
    if value.denominator == 1:
        return f"{value.numerator}s"
    return f"{value.numerator}/{value.denominator}s"


def _audio_rate_label(sample_rate: int) -> str:
    """サンプルレートを FCPXML 向け表記へ変換する。"""
    known_labels = {
        32000: "32k",
        44100: "44.1k",
        48000: "48k",
        88200: "88.2k",
        96000: "96k",
        176400: "176.4k",
        192000: "192k",
    }
    if sample_rate in known_labels:
        return known_labels[sample_rate]
    if sample_rate > 0:
        return f"{sample_rate / 1000:g}k"
    return "48k"


def _seconds_to_frame_index(seconds: float, fps_num: int, fps_den: int) -> int:
    """秒を最も近いフレーム番号へ変換する。"""
    frames = Fraction(str(max(0.0, seconds))) * Fraction(fps_num, fps_den)
    return int(frames + Fraction(1, 2))


def _frame_index_to_fraction(frame_index: int, fps_num: int, fps_den: int) -> Fraction:
    """フレーム番号を秒の Fraction に変換する。"""
    if frame_index <= 0:
        return Fraction(0, 1)
    return Fraction(frame_index * fps_den, fps_num)


def _frame_count_to_fraction(frame_count: int, fps_num: int, fps_den: int) -> Fraction:
    """フレーム数を秒の Fraction に変換する。"""
    if frame_count <= 0:
        return Fraction(0, 1)
    return Fraction(frame_count * fps_den, fps_num)


def _pretty_xml(root: element_tree.Element) -> str:
    rough = element_tree.tostring(root, encoding="utf-8")
    parsed = minidom.parseString(rough)
    pretty = parsed.toprettyxml(indent="    ", encoding="UTF-8").decode("utf-8")
    lines = [line for line in pretty.splitlines() if line.strip()]
    return "\n".join([lines[0], "<!DOCTYPE fcpxml>", *lines[1:]])


def _file_url_for_resolve(video_path: Path) -> str:
    """DaVinci Resolve が読み取りやすい file URL を生成する。"""
    resolved = video_path.expanduser().resolve()
    return f"file://{quote(str(resolved), safe='/')}"


def _resolve_asset_frame_count(
    media_info: dict[str, Any],
    fps_num: int,
    fps_den: int,
) -> int:
    """アセット全体の実フレーム数を決定する。"""
    frame_count = int(media_info.get("frame_count", 0) or 0)
    if frame_count > 0:
        return frame_count

    duration_seconds = float(media_info.get("duration", 0.0) or 0.0)
    estimated = _seconds_to_frame_index(duration_seconds, fps_num, fps_den)
    return max(0, estimated)


def _build_spine_clips(
    spine: element_tree.Element,
    segments: list[dict[str, Any]],
    fps_num: int,
    fps_den: int,
    asset_ref: str,
    clip_name: str,
    asset_total_frames: int,
) -> int:
    """spine 内の asset-clip を構築し、総フレーム数を返す。"""
    timeline_frame_offset = 0
    total_timeline_frames = 0

    for segment in segments:
        start_seconds = float(segment["start"])
        end_seconds = float(segment["end"])

        start_frame = _seconds_to_frame_index(start_seconds, fps_num, fps_den)
        end_frame = _seconds_to_frame_index(end_seconds, fps_num, fps_den)

        if asset_total_frames > 0:
            start_frame = min(max(0, start_frame), asset_total_frames - 1)
            end_frame = min(asset_total_frames, max(start_frame + 1, end_frame))
        else:
            start_frame = max(0, start_frame)
            end_frame = max(start_frame + 1, end_frame)

        clip_frames = end_frame - start_frame
        if clip_frames <= 0:
            continue

        element_tree.SubElement(
            spine,
            "asset-clip",
            {
                "ref": asset_ref,
                "offset": _fraction_to_string(
                    _frame_count_to_fraction(timeline_frame_offset, fps_num, fps_den)
                ),
                "name": clip_name,
                "start": _fraction_to_string(
                    _frame_index_to_fraction(start_frame, fps_num, fps_den)
                ),
                "duration": _fraction_to_string(
                    _frame_count_to_fraction(clip_frames, fps_num, fps_den)
                ),
                "tcFormat": "NDF",
                "enabled": "1",
            },
        )

        timeline_frame_offset += clip_frames
        total_timeline_frames += clip_frames

    return total_timeline_frames


def export_fcpxml(
    video_path: Path,
    segments: list[dict[str, Any]],
    media_info: dict[str, Any],
    output_path: Path,
) -> Path:
    """DaVinci Resolve 20 読み込み向け FCPXML を生成する。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fps_rational = str(media_info.get("fps_rational", "30/1"))
    fps_num, fps_den = _parse_fps_rational(fps_rational)
    frame_duration = f"{fps_den}/{fps_num}s"

    asset_uid = uuid.uuid4().hex.upper()
    sample_rate = int(media_info.get("audio_sample_rate", 0) or 0)
    audio_rate_label = _audio_rate_label(sample_rate)
    audio_channels = int(media_info.get("audio_channels", 0) or 2)
    audio_layout = "mono" if audio_channels == 1 else "stereo"
    clip_name = video_path.name
    asset_src = _file_url_for_resolve(video_path)
    asset_total_frames = _resolve_asset_frame_count(media_info, fps_num, fps_den)

    root = element_tree.Element("fcpxml", version="1.10")
    resources = element_tree.SubElement(root, "resources")

    element_tree.SubElement(
        resources,
        "format",
        {
            "id": "r1",
            "name": (
                f"FFVideoFormat{int(media_info['height'])}p"
                f"{round(float(media_info['fps']) or 30)}"
            ),
            "frameDuration": frame_duration,
            "width": str(int(media_info["width"])),
            "height": str(int(media_info["height"])),
        },
    )

    element_tree.SubElement(
        resources,
        "asset",
        {
            "id": "r2",
            "name": clip_name,
            "uid": asset_uid,
            "src": asset_src,
            "start": "0s",
            "duration": _fraction_to_string(
                _frame_count_to_fraction(asset_total_frames, fps_num, fps_den)
            ),
            "hasVideo": "1",
            "format": "r1",
            "hasAudio": "1",
            "audioSources": "1",
            "audioChannels": str(audio_channels),
            "audioRate": audio_rate_label,
        },
    )

    library = element_tree.SubElement(root, "library")
    event = element_tree.SubElement(library, "event", {"name": "mov-voicecrop Export"})
    project = element_tree.SubElement(
        event,
        "project",
        {"name": f"{media_info['filename']}_cut"},
    )
    sequence = element_tree.SubElement(
        project,
        "sequence",
        {
            "format": "r1",
            "tcStart": "0s",
            "tcFormat": "NDF",
            "audioLayout": audio_layout,
            "audioRate": audio_rate_label,
        },
    )
    spine = element_tree.SubElement(sequence, "spine")

    total_timeline_frames = _build_spine_clips(
        spine=spine,
        segments=segments,
        fps_num=fps_num,
        fps_den=fps_den,
        asset_ref="r2",
        clip_name=clip_name,
        asset_total_frames=asset_total_frames,
    )

    sequence.set(
        "duration",
        _fraction_to_string(
            _frame_count_to_fraction(total_timeline_frames, fps_num, fps_den)
        ),
    )

    output_path.write_text(_pretty_xml(root), encoding="utf-8")
    return output_path
