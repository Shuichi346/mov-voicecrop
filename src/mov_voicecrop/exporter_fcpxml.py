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


def _seconds_to_frame_fraction(seconds: float, fps_num: int, fps_den: int) -> Fraction:
    """秒を最も近いフレーム境界の Fraction に変換する。"""
    if seconds <= 0:
        return Fraction(0, 1)

    frame_count = int(Fraction(str(seconds)) * Fraction(fps_num, fps_den) + Fraction(1, 2))
    if frame_count <= 0:
        return Fraction(0, 1)

    return Fraction(frame_count * fps_den, fps_num)


def _frame_count_to_fraction(frame_count: int, fps_num: int, fps_den: int) -> Fraction:
    """フレーム数を秒の Fraction に変換する。"""
    if frame_count <= 0:
        return Fraction(0, 1)
    return Fraction(frame_count * fps_den, fps_num)


def seconds_to_rational(seconds: float, fps_rational: str) -> str:
    """秒を FCPXML の有理数表記へ変換する。"""
    fps_num, fps_den = _parse_fps_rational(fps_rational)
    return _fraction_to_string(_seconds_to_frame_fraction(seconds, fps_num, fps_den))


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


def _build_spine_clips(
    spine: element_tree.Element,
    segments: list[dict[str, Any]],
    fps_num: int,
    fps_den: int,
    asset_ref: str,
    clip_name: str,
) -> Fraction:
    """spine 内の asset-clip を構築し、総尺を返す。"""
    timeline_frame_offset = 0
    total_duration = Fraction(0, 1)

    for segment in segments:
        start_seconds = float(segment["start"])
        end_seconds = float(segment["end"])

        start_fraction = _seconds_to_frame_fraction(start_seconds, fps_num, fps_den)
        end_fraction = _seconds_to_frame_fraction(end_seconds, fps_num, fps_den)

        clip_duration = end_fraction - start_fraction
        if clip_duration <= 0:
            continue

        offset_fraction = _frame_count_to_fraction(timeline_frame_offset, fps_num, fps_den)

        element_tree.SubElement(
            spine,
            "asset-clip",
            {
                "ref": asset_ref,
                "offset": _fraction_to_string(offset_fraction),
                "name": clip_name,
                "start": _fraction_to_string(start_fraction),
                "duration": _fraction_to_string(clip_duration),
                "tcFormat": "NDF",
                "enabled": "1",
            },
        )

        clip_frames = int(clip_duration * Fraction(fps_num, fps_den))
        timeline_frame_offset += clip_frames
        total_duration += clip_duration

    return total_duration


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
            "duration": seconds_to_rational(float(media_info["duration"]), fps_rational),
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

    total_cut_duration = _build_spine_clips(
        spine=spine,
        segments=segments,
        fps_num=fps_num,
        fps_den=fps_den,
        asset_ref="r2",
        clip_name=clip_name,
    )
    sequence.set("duration", _fraction_to_string(total_cut_duration))

    output_path.write_text(_pretty_xml(root), encoding="utf-8")
    return output_path
