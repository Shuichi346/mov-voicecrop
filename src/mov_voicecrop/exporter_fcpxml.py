"""FCPXML 1.9 エクスポーター。"""

from __future__ import annotations

import uuid
import xml.etree.ElementTree as element_tree
from fractions import Fraction
from pathlib import Path
from typing import Any
from xml.dom import minidom


def _parse_fps_rational(value: str) -> tuple[int, int]:
    numerator, denominator = value.split("/", maxsplit=1)
    return int(numerator), int(denominator)


def _fraction_to_string(value: Fraction) -> str:
    if value.numerator == 0:
        return "0s"
    if value.denominator == 1:
        return f"{value.numerator}s"
    return f"{value.numerator}/{value.denominator}s"


def seconds_to_rational(seconds: float, fps_rational: str) -> str:
    """秒を FCPXML の有理数表記へ変換する。"""
    if seconds <= 0:
        return "0s"

    fps_num, fps_den = _parse_fps_rational(fps_rational)
    if fps_num == 0:
        return _fraction_to_string(Fraction(seconds).limit_denominator(30_000 * 1001))

    frame_count = round(seconds * fps_num / fps_den)
    return _fraction_to_string(Fraction(frame_count * fps_den, fps_num))


def _pretty_xml(root: element_tree.Element) -> str:
    rough = element_tree.tostring(root, encoding="utf-8")
    parsed = minidom.parseString(rough)
    pretty = parsed.toprettyxml(indent="    ", encoding="UTF-8").decode("utf-8")
    lines = [line for line in pretty.splitlines() if line.strip()]
    return "\n".join([lines[0], "<!DOCTYPE fcpxml>", *lines[1:]])


def export_fcpxml(
    video_path: Path,
    segments: list[dict[str, Any]],
    media_info: dict[str, Any],
    output_path: Path,
) -> Path:
    """DaVinci Resolve 20 読み込み向け FCPXML を生成する。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)
    fps_rational = str(media_info["fps_rational"])
    fps_num, fps_den = _parse_fps_rational(fps_rational)
    frame_duration = f"{fps_den}/{fps_num}s"
    asset_uid = uuid.uuid4().hex.upper()
    sample_rate = int(media_info["audio_sample_rate"])
    audio_rate_label = f"{sample_rate / 1000:g}k" if sample_rate else "48k"
    total_cut_duration = sum(
        max(0.0, float(segment["end"]) - float(segment["start"]))
        for segment in segments
    )

    root = element_tree.Element("fcpxml", version="1.9")
    resources = element_tree.SubElement(root, "resources")
    element_tree.SubElement(
        resources,
        "format",
        {
            "id": "r1",
            "name": f"FFVideoFormat{media_info['height']}p{round(float(media_info['fps']) or 30)}",
            "frameDuration": frame_duration,
            "width": str(media_info["width"]),
            "height": str(media_info["height"]),
        },
    )

    asset = element_tree.SubElement(
        resources,
        "asset",
        {
            "id": "r2",
            "name": str(media_info["filename"]),
            "uid": asset_uid,
            "start": "0s",
            "duration": seconds_to_rational(float(media_info["duration"]), fps_rational),
            "hasVideo": "1",
            "format": "r1",
            "hasAudio": "1",
            "audioSources": "1",
            "audioChannels": str(media_info["audio_channels"]),
            "audioRate": str(sample_rate),
        },
    )
    element_tree.SubElement(
        asset,
        "media-rep",
        {
            "kind": "original-media",
            "src": video_path.resolve().as_uri(),
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
            "duration": seconds_to_rational(total_cut_duration, fps_rational),
            "tcStart": "0s",
            "tcFormat": "NDF",
            "audioLayout": "stereo",
            "audioRate": audio_rate_label,
        },
    )
    spine = element_tree.SubElement(sequence, "spine")

    timeline_offset = 0.0
    for segment in segments:
        clip_duration = max(0.0, float(segment["end"]) - float(segment["start"]))
        if clip_duration <= 0:
            continue

        element_tree.SubElement(
            spine,
            "asset-clip",
            {
                "ref": "r2",
                "offset": seconds_to_rational(timeline_offset, fps_rational),
                "name": str(media_info["filename"]),
                "start": seconds_to_rational(float(segment["start"]), fps_rational),
                "duration": seconds_to_rational(clip_duration, fps_rational),
                "tcFormat": "NDF",
                "audioRole": "dialogue",
            },
        )
        timeline_offset += clip_duration

    output_path.write_text(_pretty_xml(root), encoding="utf-8")
    return output_path
