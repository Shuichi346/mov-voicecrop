"""FCPXML エクスポーター。"""

from __future__ import annotations

import uuid
import xml.etree.ElementTree as element_tree
from fractions import Fraction
from pathlib import Path
from typing import Any, Literal
from urllib.parse import quote
from xml.dom import minidom


FCPXMLTarget = Literal["resolve", "fcp", "both"]

_FCP_COLOR_SPACE_REC709 = "1-1-1 (Rec. 709)"
_KNOWN_AUDIO_RATE_LABELS = {
    32000: "32k",
    44100: "44.1k",
    48000: "48k",
    88200: "88.2k",
    96000: "96k",
    176400: "176.4k",
    192000: "192k",
}
_FCP_FRAME_RATE_SUFFIXES = {
    Fraction(24000, 1001): "2398",
    Fraction(24, 1): "24",
    Fraction(25, 1): "25",
    Fraction(30000, 1001): "2997",
    Fraction(30, 1): "30",
    Fraction(48, 1): "48",
    Fraction(50, 1): "50",
    Fraction(60000, 1001): "5994",
    Fraction(60, 1): "60",
    Fraction(120000, 1001): "11988",
    Fraction(120, 1): "120",
}


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


def _supported_audio_rate_label(sample_rate: int) -> str | None:
    """FCPXML DTD で許可される audioRate ラベルのみ返す。"""
    return _KNOWN_AUDIO_RATE_LABELS.get(sample_rate)


def _seconds_to_frame_index(seconds: float, fps_num: int, fps_den: int) -> int:
    """秒を最も近いフレーム番号へ変換する。"""
    frames = Fraction(str(max(0.0, seconds))) * Fraction(fps_num, fps_den)
    return int(frames + Fraction(1, 2))


def _frame_count_to_fraction(frame_count: int, fps_num: int, fps_den: int) -> Fraction:
    """フレーム数を秒の Fraction に変換する。"""
    if frame_count <= 0:
        return Fraction(0, 1)
    return Fraction(frame_count * fps_den, fps_num)


def _pretty_xml(root: element_tree.Element) -> str:
    """見やすい XML 文字列へ整形する。"""
    rough = element_tree.tostring(root, encoding="utf-8")
    parsed = minidom.parseString(rough)
    pretty = parsed.toprettyxml(indent="    ", encoding="UTF-8").decode("utf-8")
    lines = [line for line in pretty.splitlines() if line.strip()]
    return "\n".join([lines[0], "<!DOCTYPE fcpxml>", *lines[1:]])


def _file_url(video_path: Path) -> str:
    """FCPXML 用の file URL を生成する。"""
    resolved = video_path.expanduser().resolve()
    return f"file://{quote(str(resolved), safe='/')}"


def _audio_layout_label(audio_channels: int) -> str:
    """チャンネル数に応じた audioLayout を返す。"""
    if audio_channels <= 1:
        return "mono"
    if audio_channels == 2:
        return "stereo"
    return "surround"


def _resolve_asset_frame_count(
    media_info: dict[str, Any],
    fps_num: int,
    fps_den: int,
) -> int:
    """アセット全体のフレーム数を決定する。"""
    frame_count = int(media_info.get("frame_count", 0) or 0)
    if frame_count > 0:
        return frame_count

    duration_seconds = float(media_info.get("duration", 0.0) or 0.0)
    estimated = _seconds_to_frame_index(duration_seconds, fps_num, fps_den)
    return max(0, estimated)


def _normalize_audio_channels(media_info: dict[str, Any]) -> int:
    """音声チャンネル数を FCPXML 向けに正規化する。"""
    audio_channels = int(media_info.get("audio_channels", 0) or 0)
    if audio_channels > 0:
        return audio_channels
    return 2


def _set_optional_attribute(
    attributes: dict[str, str],
    key: str,
    value: str | None,
) -> None:
    """None でない属性だけを追加する。"""
    if value is not None and value != "":
        attributes[key] = value


def _build_fcp_format_name(
    width: int,
    height: int,
    fps_num: int,
    fps_den: int,
) -> str | None:
    """Final Cut が受け入れやすい format 名を生成する。"""
    if width <= 0 or height <= 0:
        return None

    fps_fraction = Fraction(fps_num, fps_den)
    rate_suffix = _FCP_FRAME_RATE_SUFFIXES.get(fps_fraction)
    if rate_suffix is None:
        return None

    # 縦動画や特殊ラスタでは name を推測しない方が安全
    if height > width:
        return None

    return f"FFVideoFormat{height}p{rate_suffix}"


def _build_format_element(
    resources: element_tree.Element,
    media_info: dict[str, Any],
    format_id: str,
    fps_num: int,
    fps_den: int,
) -> None:
    """format リソース要素を生成する。"""
    width = int(media_info.get("width", 0) or 0)
    height = int(media_info.get("height", 0) or 0)

    attributes = {
        "id": format_id,
        "frameDuration": f"{fps_den}/{fps_num}s",
        "width": str(width),
        "height": str(height),
        "fieldOrder": "progressive",
        "colorSpace": _FCP_COLOR_SPACE_REC709,
    }

    format_name = _build_fcp_format_name(width, height, fps_num, fps_den)
    _set_optional_attribute(attributes, "name", format_name)

    element_tree.SubElement(resources, "format", attributes)


def _build_asset(
    resources: element_tree.Element,
    variant: Literal["resolve", "fcp"],
    asset_id: str,
    asset_name: str,
    asset_uid: str,
    asset_duration: str,
    format_id: str,
    audio_channels: int,
    audio_rate_label: str | None,
    asset_url: str,
) -> None:
    """variant ごとの asset 要素を生成する。"""
    common_attrs = {
        "id": asset_id,
        "name": asset_name,
        "start": "0s",
        "duration": asset_duration,
        "hasVideo": "1",
        "format": format_id,
        "hasAudio": "1",
        "audioSources": "1",
        "audioChannels": str(audio_channels),
    }

    _set_optional_attribute(common_attrs, "audioRate", audio_rate_label)

    if variant == "resolve":
        common_attrs["uid"] = asset_uid
        element_tree.SubElement(
            resources,
            "asset",
            {
                **common_attrs,
                "src": asset_url,
            },
        )
        return

    asset = element_tree.SubElement(resources, "asset", common_attrs)
    element_tree.SubElement(
        asset,
        "media-rep",
        {
            "kind": "original-media",
            "src": asset_url,
            "suggestedFilename": asset_name,
        },
    )


def _build_spine_clips(
    spine: element_tree.Element,
    segments: list[dict[str, Any]],
    fps_num: int,
    fps_den: int,
    asset_ref: str,
    clip_name: str,
    asset_total_frames: int,
    format_id: str,
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
                "format": format_id,
                "offset": _fraction_to_string(
                    _frame_count_to_fraction(timeline_frame_offset, fps_num, fps_den)
                ),
                "name": clip_name,
                "start": _fraction_to_string(
                    _frame_count_to_fraction(start_frame, fps_num, fps_den)
                ),
                "duration": _fraction_to_string(
                    _frame_count_to_fraction(clip_frames, fps_num, fps_den)
                ),
                "tcFormat": "NDF",
                "enabled": "1",
                "audioRole": "dialogue",
            },
        )

        timeline_frame_offset += clip_frames
        total_timeline_frames += clip_frames

    return total_timeline_frames


def _variant_version(variant: Literal["resolve", "fcp"]) -> str:
    """variant ごとの FCPXML version を返す。"""
    if variant == "fcp":
        return "1.13"
    return "1.10"


def _build_single_fcpxml(
    video_path: Path,
    segments: list[dict[str, Any]],
    media_info: dict[str, Any],
    output_path: Path,
    variant: Literal["resolve", "fcp"],
) -> Path:
    """variant ごとの FCPXML を1本生成する。"""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    fps_rational = str(media_info.get("fps_rational", "30/1"))
    fps_num, fps_den = _parse_fps_rational(fps_rational)

    asset_uid = uuid.uuid4().hex.upper()
    sample_rate = int(media_info.get("audio_sample_rate", 0) or 0)
    audio_rate = _supported_audio_rate_label(sample_rate)
    audio_channels = _normalize_audio_channels(media_info)
    audio_layout = _audio_layout_label(audio_channels)
    asset_name = video_path.name
    asset_url = _file_url(video_path)
    asset_total_frames = _resolve_asset_frame_count(media_info, fps_num, fps_den)
    asset_duration = _fraction_to_string(
        _frame_count_to_fraction(asset_total_frames, fps_num, fps_den)
    )

    format_id = "r1"
    asset_id = "r2"

    root = element_tree.Element("fcpxml", version=_variant_version(variant))
    resources = element_tree.SubElement(root, "resources")

    _build_format_element(
        resources=resources,
        media_info=media_info,
        format_id=format_id,
        fps_num=fps_num,
        fps_den=fps_den,
    )

    _build_asset(
        resources=resources,
        variant=variant,
        asset_id=asset_id,
        asset_name=asset_name,
        asset_uid=asset_uid,
        asset_duration=asset_duration,
        format_id=format_id,
        audio_channels=audio_channels,
        audio_rate_label=audio_rate,
        asset_url=asset_url,
    )

    library = element_tree.SubElement(root, "library")
    event = element_tree.SubElement(library, "event", {"name": "mov-voicecrop Export"})
    project = element_tree.SubElement(
        event,
        "project",
        {"name": f"{media_info['filename']}_cut"},
    )

    sequence_attrs = {
        "format": format_id,
        "tcStart": "0s",
        "tcFormat": "NDF",
        "audioLayout": audio_layout,
    }
    _set_optional_attribute(sequence_attrs, "audioRate", audio_rate)

    sequence = element_tree.SubElement(project, "sequence", sequence_attrs)
    spine = element_tree.SubElement(sequence, "spine")

    total_timeline_frames = _build_spine_clips(
        spine=spine,
        segments=segments,
        fps_num=fps_num,
        fps_den=fps_den,
        asset_ref=asset_id,
        clip_name=asset_name,
        asset_total_frames=asset_total_frames,
        format_id=format_id,
    )

    sequence.set(
        "duration",
        _fraction_to_string(
            _frame_count_to_fraction(total_timeline_frames, fps_num, fps_den)
        ),
    )

    output_path.write_text(_pretty_xml(root), encoding="utf-8")
    return output_path


def _build_output_paths(
    output_path: Path,
    target: FCPXMLTarget,
) -> list[tuple[Literal["resolve", "fcp"], Path]]:
    """target に応じた出力パス一覧を返す。"""
    if target == "resolve":
        return [("resolve", output_path)]

    if target == "fcp":
        return [("fcp", output_path)]

    suffix = output_path.suffix or ".fcpxml"
    stem = output_path.stem
    return [
        ("resolve", output_path.with_name(f"{stem}_resolve{suffix}")),
        ("fcp", output_path.with_name(f"{stem}_fcp{suffix}")),
    ]


def export_fcpxml(
    video_path: Path,
    segments: list[dict[str, Any]],
    media_info: dict[str, Any],
    output_path: Path,
    target: FCPXMLTarget = "resolve",
) -> list[Path]:
    """FCPXML をターゲット別に生成する。"""
    output_paths: list[Path] = []

    for variant, variant_output_path in _build_output_paths(output_path, target):
        output_paths.append(
            _build_single_fcpxml(
                video_path=video_path,
                segments=segments,
                media_info=media_info,
                output_path=variant_output_path,
                variant=variant,
            )
        )

    return output_paths
