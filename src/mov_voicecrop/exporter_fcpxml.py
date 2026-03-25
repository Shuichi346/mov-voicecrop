"""FCPXML 1.13 エクスポーター（DaVinci Resolve 20 対応）。"""

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


def _path_to_file_uri(path: Path) -> str:
    """パスを DaVinci Resolve 互換の file URI に変換する。

    Python の Path.as_uri() は RFC 8089 準拠だが、DaVinci Resolve は
    $, #, &, @ 等の特殊文字を含む URI を正しく解釈できないことがある。
    urllib.parse.quote でパス各部分を確実にパーセントエンコードする。
    """
    absolute_path = str(path.resolve())
    encoded_path = quote(absolute_path, safe="/")
    return f"file://{encoded_path}"


def seconds_to_rational(seconds: float, fps_rational: str) -> str:
    """秒を FCPXML の有理数表記へ変換する。"""
    if seconds <= 0:
        return "0s"

    fps_num, fps_den = _parse_fps_rational(fps_rational)
    frame_count = round(seconds * fps_num / fps_den)
    if frame_count <= 0:
        return _fraction_to_string(Fraction(str(seconds)).limit_denominator(30_000 * 1001))

    return _fraction_to_string(Fraction(frame_count * fps_den, fps_num))


def _sanitize_name(name: str) -> str:
    """DaVinci Resolve のファイル検索で問題を起こす特殊文字を除去する。

    Resolve はクリップ名をファイル名と照合して再リンクを試みるため、
    name 属性に XML/URI で問題になる文字が含まれると検索に失敗する。
    元のファイル名から問題文字を置換して安全な表示名を作成する。
    """
    replacements = {
        "$": "",
        "#": "",
        "&": "and",
        "@": "",
        "!": "",
        "%": "",
        "^": "",
        "=": "-",
        "+": "",
        "{": "(",
        "}": ")",
        "[": "(",
        "]": ")",
        "|": "-",
        "\\": "-",
        "<": "",
        ">": "",
        "`": "",
        "~": "",
    }
    result = name
    for char, replacement in replacements.items():
        result = result.replace(char, replacement)
    # 連続するスペースを1つにまとめる
    while "  " in result:
        result = result.replace("  ", " ")
    return result.strip()


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
    """DaVinci Resolve 20 読み込み向け FCPXML 1.13 を生成する。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fps_rational = str(media_info.get("fps_rational", "30/1"))
    fps_num, fps_den = _parse_fps_rational(fps_rational)
    frame_duration = f"{fps_den}/{fps_num}s"

    asset_uid = uuid.uuid4().hex.upper()
    sample_rate = int(media_info.get("audio_sample_rate", 0) or 0)
    audio_rate_label = _audio_rate_label(sample_rate)
    audio_channels = int(media_info.get("audio_channels", 0) or 2)
    audio_layout = "mono" if audio_channels == 1 else "stereo"

    original_filename = str(media_info["filename"])
    safe_clip_name = _sanitize_name(original_filename)

    total_cut_duration = sum(
        max(0.0, float(segment["end"]) - float(segment["start"]))
        for segment in segments
    )

    root = element_tree.Element("fcpxml", version="1.13")
    resources = element_tree.SubElement(root, "resources")

    element_tree.SubElement(
        resources,
        "format",
        {
            "id": "r1",
            "name": (
                f"FFVideoFormat{media_info['height']}p"
                f"{round(float(media_info['fps']) or 30)}"
            ),
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
            "name": safe_clip_name,
            "uid": asset_uid,
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

    element_tree.SubElement(
        asset,
        "media-rep",
        {
            "kind": "original-media",
            "src": _path_to_file_uri(video_path),
        },
    )

    library = element_tree.SubElement(root, "library")
    event = element_tree.SubElement(library, "event", {"name": "mov-voicecrop Export"})
    project = element_tree.SubElement(
        event,
        "project",
        {"name": f"{safe_clip_name}_cut"},
    )
    sequence = element_tree.SubElement(
        project,
        "sequence",
        {
            "format": "r1",
            "duration": seconds_to_rational(total_cut_duration, fps_rational),
            "tcStart": "0s",
            "tcFormat": "NDF",
            "audioLayout": audio_layout,
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
                "name": safe_clip_name,
                "start": seconds_to_rational(float(segment["start"]), fps_rational),
                "duration": seconds_to_rational(clip_duration, fps_rational),
                "tcFormat": "NDF",
                "audioRole": "dialogue",
            },
        )
        timeline_offset += clip_duration

    output_path.write_text(_pretty_xml(root), encoding="utf-8")
    return output_path
