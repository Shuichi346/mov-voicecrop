"""CLI インターフェース。"""

from __future__ import annotations

import argparse
import shutil
import tempfile
from pathlib import Path
from typing import Callable

from mov_voicecrop.config import (
    AppConfig,
    PROJECT_ROOT,
    load_config,
    resolve_output_dir,
)
from mov_voicecrop.exporter_fcpxml import export_fcpxml
from mov_voicecrop.exporter_mp4 import export_mp4
from mov_voicecrop.exporter_srt import export_srt
from mov_voicecrop.media_info import extract_audio_wav, get_media_info
from mov_voicecrop.segment_analyzer import analyze_segments
from mov_voicecrop.silence_detector import detect_silence
from mov_voicecrop.transcriber import transcribe


ProgressCallback = Callable[[float, str], None]
TEMP_ROOT = PROJECT_ROOT / "temp"


def _report_progress(
    progress_callback: ProgressCallback | None,
    progress: float,
    message: str,
) -> None:
    if progress_callback is not None:
        progress_callback(progress, message)


def _validate_runtime_paths(config: AppConfig) -> None:
    required_paths = {
        "whisper-cli": config.whisper_cli_path,
        "Whisper モデル": config.whisper_model_path,
        "VAD モデル": config.whisper_vad_model_path,
    }
    for label, path in required_paths.items():
        if not path.exists():
            raise FileNotFoundError(f"{label} が見つかりません: {path}")


def _create_job_temp_dir(base_name: str) -> Path:
    """ジョブごとの一時ディレクトリを作成する。"""
    TEMP_ROOT.mkdir(parents=True, exist_ok=True)
    safe_prefix = "".join(
        char if char.isalnum() else "_"
        for char in base_name
    ).strip("_")
    if not safe_prefix:
        safe_prefix = "job"
    return Path(tempfile.mkdtemp(prefix=f"{safe_prefix}_", dir=TEMP_ROOT))


def execute_pipeline(
    input_path: Path,
    output_dir: Path,
    style: str,
    config: AppConfig,
    progress_callback: ProgressCallback | None = None,
) -> list[Path]:
    """共通の動画処理パイプラインを実行する。"""
    if not input_path.exists():
        raise FileNotFoundError(f"入力動画が見つかりません: {input_path}")

    output_dir.mkdir(parents=True, exist_ok=True)
    _validate_runtime_paths(config)

    base_name = input_path.stem
    job_temp_dir = _create_job_temp_dir(base_name)
    outputs: list[Path] = []

    # ジョブ専用ディレクトリに一時 WAV と whisper 出力をまとめる
    wav_path = job_temp_dir / f"{base_name}.wav"

    try:
        _report_progress(progress_callback, 0.05, "メディア情報を取得しています")
        media = get_media_info(input_path)

        _report_progress(progress_callback, 0.15, "音声を WAV に変換しています")
        extract_audio_wav(input_path, wav_path)

        _report_progress(progress_callback, 0.30, "whisper.cpp で文字起こししています")
        whisper_segments = transcribe(
            wav_path,
            config,
            progress_callback=lambda line: _report_progress(
                progress_callback,
                0.45,
                f"whisper.cpp: {line}",
            ),
        )

        _report_progress(progress_callback, 0.55, "無音区間を検出しています")
        silence_regions = detect_silence(
            input_path,
            config,
            media_duration=float(media["duration"]),
        )

        _report_progress(progress_callback, 0.70, "保持区間を統合しています")
        segments = analyze_segments(
            whisper_segments,
            silence_regions,
            float(media["duration"]),
            config,
        )

        original_srt_path = output_dir / f"{base_name}_original.srt"
        outputs.append(export_srt(segments, original_srt_path, mode="original"))

        if style in {"mp4", "both"}:
            _report_progress(progress_callback, 0.80, "カット後字幕を生成しています")
            cut_srt_path = output_dir / f"{base_name}_cut.srt"
            outputs.append(export_srt(segments, cut_srt_path, mode="reindexed"))

            _report_progress(progress_callback, 0.90, "MP4 を出力しています")
            mp4_path = output_dir / f"{base_name}_cut.mp4"
            outputs.extend(
                export_mp4(
                    input_path=input_path,
                    segments=segments,
                    srt_path=cut_srt_path,
                    output_path=mp4_path,
                    subtitle_mode=config.subtitle_mode,
                    config=config,
                    temp_dir=job_temp_dir,
                )
            )

        if style in {"xml", "both"}:
            _report_progress(progress_callback, 0.95, "FCPXML を出力しています")
            fcpxml_path = output_dir / f"{base_name}.fcpxml"
            outputs.append(export_fcpxml(input_path, segments, media, fcpxml_path))
    finally:
        shutil.rmtree(job_temp_dir, ignore_errors=True)

    _report_progress(progress_callback, 1.0, "処理が完了しました")
    return outputs


def build_parser() -> argparse.ArgumentParser:
    """CLI パーサーを構築する。"""
    parser = argparse.ArgumentParser(
        description="mov-voicecrop - 自動無音カット＆字幕生成ツール",
    )
    parser.add_argument("-i", "--input", required=True, help="入力動画ファイルのパス")
    parser.add_argument(
        "-o",
        "--output",
        default=None,
        help="出力ディレクトリ（デフォルト: 入力動画と同じディレクトリ）",
    )
    parser.add_argument(
        "--style",
        choices=["mp4", "xml", "both"],
        default="both",
        help="出力形式",
    )
    parser.add_argument("--lang", default=None, help="音声認識言語")
    parser.add_argument("--silence-thresh", type=float, default=None, help="無音判定閾値 dB")
    parser.add_argument("--min-silence", type=float, default=None, help="無音の最小長さ 秒")
    parser.add_argument("--padding", type=float, default=None, help="カット前後のマージン 秒")
    parser.add_argument("--min-confidence", type=float, default=None, help="最小信頼度")
    parser.add_argument(
        "--subtitle-mode",
        choices=["soft", "off"],
        default=None,
        help="字幕モード（soft: ソフトサブ / off: 字幕なし）",
    )
    parser.add_argument("--whisper-cli", default=None, help="whisper-cli のパス")
    parser.add_argument("--whisper-model", default=None, help="Whisper モデルのパス")
    parser.add_argument("--vad-model", default=None, help="VAD モデルのパス")
    parser.add_argument("--threads", type=int, default=None, help="whisper.cpp スレッド数")
    parser.add_argument(
        "--video-encoder",
        choices=["auto", "libx264", "h264_videotoolbox"],
        default=None,
        help="MP4 映像エンコーダー（auto: HW利用可能なら自動選択）",
    )
    return parser


def run_cli(args: argparse.Namespace) -> None:
    """CLI 処理を実行する。"""
    config = load_config(cli_args=args)
    input_path = Path(args.input).expanduser().resolve()
    if not input_path.exists():
        raise FileNotFoundError(f"入力動画が見つかりません: {input_path}")

    output_dir = resolve_output_dir(config, input_path)
    style = args.style

    outputs = execute_pipeline(
        input_path=input_path,
        output_dir=output_dir,
        style=style,
        config=config,
        progress_callback=lambda _, message: print(message),
    )

    print("出力ファイル:")
    for output in outputs:
        print(f" - {output}")