"""Gradio Web UI。"""

from __future__ import annotations

import shutil
import tempfile
from pathlib import Path

import gradio as gr

from mov_voicecrop.cli import execute_pipeline
from mov_voicecrop.config import AppConfig, build_config_from_overrides, save_settings


WEBUI_CSS = """
body {
    background:
        radial-gradient(circle at top left, rgba(255, 208, 132, 0.25), transparent 40%),
        linear-gradient(135deg, #f6f1e7, #eef3f7);
}

.gradio-container {
    font-family: "Hiragino Sans", "Yu Gothic", sans-serif;
}
"""


def _build_ui_config(
    base_config: AppConfig,
    output_dir: str,
    subtitle_mode: str,
    language: str,
    whisper_cli_path: str,
    whisper_model_path: str,
    whisper_vad_model_path: str,
    whisper_threads: int,
    silence_thresh_db: float,
    min_silence_duration: float,
    padding: float,
    min_confidence: float,
    video_encoder: str,
) -> AppConfig:
    return build_config_from_overrides(
        base_config,
        output_dir=output_dir,
        subtitle_mode=subtitle_mode,
        language=language,
        whisper_cli_path=whisper_cli_path,
        whisper_model_path=whisper_model_path,
        whisper_vad_model_path=whisper_vad_model_path,
        whisper_threads=whisper_threads,
        silence_thresh_db=silence_thresh_db,
        min_silence_duration=min_silence_duration,
        padding=padding,
        min_confidence=min_confidence,
        video_encoder=video_encoder,
    )


def _copy_outputs_to_tempdir(output_paths: list[Path]) -> list[str]:
    """出力ファイルを tempdir にコピーして Gradio が安全に配信できるようにする。"""
    temp_dir = Path(tempfile.mkdtemp(prefix="mov_voicecrop_result_"))
    copied: list[str] = []
    for src in output_paths:
        dst = temp_dir / src.name
        shutil.copy2(src, dst)
        copied.append(str(dst))
    return copied


def launch_webui(config: AppConfig) -> None:
    """Web UI を起動する。"""

    with gr.Blocks(title="mov-voicecrop - 自動無音カットツール") as demo:
        gr.Markdown("# mov-voicecrop")
        gr.Markdown("動画から発話区間だけを残し、字幕付き MP4 / SRT / FCPXML を生成します。")

        with gr.Tab("メイン処理"):
            input_video = gr.File(label="入力動画", type="filepath")
            output_dir = gr.Textbox(
                label="出力ディレクトリ",
                value=str(config.output_dir),
            )
            style = gr.Radio(
                choices=["mp4", "xml", "both"],
                label="出力形式",
                value="both",
            )
            subtitle_mode = gr.Radio(
                choices=["soft", "off"],
                label="字幕モード（soft: ソフトサブ / off: なし）",
                value=config.subtitle_mode,
            )
            process_button = gr.Button("処理開始", variant="primary")
            log_box = gr.Textbox(label="ログ", lines=12, interactive=False)
            output_files = gr.File(label="出力ファイル", file_count="multiple")

        with gr.Tab("設定"):
            with gr.Accordion("音声認識設定", open=True):
                language = gr.Dropdown(
                    choices=["ja", "en", "zh", "ko", "auto"],
                    label="言語",
                    value=config.language,
                )
                whisper_cli_path = gr.Textbox(
                    label="whisper-cli パス",
                    value=str(config.whisper_cli_path),
                )
                whisper_model_path = gr.Textbox(
                    label="Whisper モデルパス",
                    value=str(config.whisper_model_path),
                )
                whisper_vad_model_path = gr.Textbox(
                    label="VAD モデルパス",
                    value=str(config.whisper_vad_model_path),
                )
                whisper_threads = gr.Slider(
                    minimum=1,
                    maximum=16,
                    step=1,
                    label="スレッド数",
                    value=config.whisper_threads,
                )

            with gr.Accordion("無音検出設定", open=True):
                silence_thresh_db = gr.Slider(
                    minimum=-60,
                    maximum=-10,
                    step=1,
                    label="無音閾値 (dB)",
                    value=config.silence_thresh_db,
                )
                min_silence_duration = gr.Slider(
                    minimum=0.1,
                    maximum=3.0,
                    step=0.1,
                    label="最小無音長 (秒)",
                    value=config.min_silence_duration,
                )
                padding = gr.Slider(
                    minimum=0.0,
                    maximum=1.0,
                    step=0.05,
                    label="前後マージン (秒)",
                    value=config.padding,
                )

            with gr.Accordion("信頼度フィルタ設定", open=True):
                min_confidence = gr.Slider(
                    minimum=0.0,
                    maximum=1.0,
                    step=0.05,
                    label="最小信頼度",
                    value=config.min_confidence,
                )

            with gr.Accordion("出力設定", open=True):
                video_encoder = gr.Dropdown(
                    choices=["auto", "libx264", "h264_videotoolbox"],
                    label="映像エンコーダー（auto: HW利用可能なら自動選択）",
                    value=config.video_encoder,
                )

            save_button = gr.Button("設定を保存")
            save_status = gr.Textbox(label="保存結果", interactive=False)

        def process_uploaded_video(
            input_video_path: str | None,
            output_dir_value: str,
            style_value: str,
            subtitle_mode_value: str,
            language_value: str,
            whisper_cli_value: str,
            whisper_model_value: str,
            whisper_vad_value: str,
            whisper_threads_value: int,
            silence_thresh_value: float,
            min_silence_value: float,
            padding_value: float,
            min_confidence_value: float,
            video_encoder_value: str,
            progress: gr.Progress = gr.Progress(),
        ) -> tuple[str, list[str]]:
            if not input_video_path:
                raise gr.Error("入力動画を指定してください。")

            runtime_config = _build_ui_config(
                config,
                output_dir=output_dir_value,
                subtitle_mode=subtitle_mode_value,
                language=language_value,
                whisper_cli_path=whisper_cli_value,
                whisper_model_path=whisper_model_value,
                whisper_vad_model_path=whisper_vad_value,
                whisper_threads=whisper_threads_value,
                silence_thresh_db=silence_thresh_value,
                min_silence_duration=min_silence_value,
                padding=padding_value,
                min_confidence=min_confidence_value,
                video_encoder=video_encoder_value,
            )

            logs: list[str] = []

            def callback(current_progress: float, message: str) -> None:
                logs.append(message)
                progress(current_progress, desc=message)

            outputs = execute_pipeline(
                input_path=Path(input_video_path).expanduser().resolve(),
                output_dir=runtime_config.output_dir.resolve(),
                style=style_value,
                config=runtime_config,
                progress_callback=callback,
            )

            safe_paths = _copy_outputs_to_tempdir(outputs)
            return "\n".join(logs), safe_paths

        def save_ui_settings(
            output_dir_value: str,
            subtitle_mode_value: str,
            language_value: str,
            whisper_cli_value: str,
            whisper_model_value: str,
            whisper_vad_value: str,
            whisper_threads_value: int,
            silence_thresh_value: float,
            min_silence_value: float,
            padding_value: float,
            min_confidence_value: float,
            video_encoder_value: str,
        ) -> str:
            updated_config = _build_ui_config(
                config,
                output_dir=output_dir_value,
                subtitle_mode=subtitle_mode_value,
                language=language_value,
                whisper_cli_path=whisper_cli_value,
                whisper_model_path=whisper_model_value,
                whisper_vad_model_path=whisper_vad_value,
                whisper_threads=whisper_threads_value,
                silence_thresh_db=silence_thresh_value,
                min_silence_duration=min_silence_value,
                padding=padding_value,
                min_confidence=min_confidence_value,
                video_encoder=video_encoder_value,
            )
            saved_path = save_settings(updated_config)
            return f"設定を保存しました: {saved_path}"

        process_button.click(
            fn=process_uploaded_video,
            inputs=[
                input_video,
                output_dir,
                style,
                subtitle_mode,
                language,
                whisper_cli_path,
                whisper_model_path,
                whisper_vad_model_path,
                whisper_threads,
                silence_thresh_db,
                min_silence_duration,
                padding,
                min_confidence,
                video_encoder,
            ],
            outputs=[log_box, output_files],
        )

        save_button.click(
            fn=save_ui_settings,
            inputs=[
                output_dir,
                subtitle_mode,
                language,
                whisper_cli_path,
                whisper_model_path,
                whisper_vad_model_path,
                whisper_threads,
                silence_thresh_db,
                min_silence_duration,
                padding,
                min_confidence,
                video_encoder,
            ],
            outputs=save_status,
        )

    try:
        demo.launch(
            server_name=config.gradio_server_name,
            server_port=config.gradio_server_port,
            css=WEBUI_CSS,
        )
    except OSError as error:
        if "Cannot find empty port" in str(error):
            raise RuntimeError(
                (
                    "Gradio の起動に失敗しました。"
                    f"ポート {config.gradio_server_port} が使用中の可能性があります。"
                    "設定画面か .env で別のポートを指定してください。"
                )
            ) from error
        raise RuntimeError(f"Gradio の起動に失敗しました: {error}") from error
