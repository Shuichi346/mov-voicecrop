"""設定管理。"""

from __future__ import annotations

import argparse
import json
import os
import shlex
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from dotenv import dotenv_values


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SETTINGS_PATH = PROJECT_ROOT / "settings.json"
ENV_PATH = PROJECT_ROOT / ".env"


@dataclass(slots=True)
class AppConfig:
    """アプリケーション設定。

    output_dir が None の場合は入力動画と同じディレクトリに出力する。
    """

    whisper_cli_path: Path = field(
        default_factory=lambda: PROJECT_ROOT / "whisper.cpp" / "build" / "bin" / "whisper-cli"
    )
    whisper_model_path: Path = field(
        default_factory=lambda: PROJECT_ROOT / "whisper.cpp" / "models" / "ggml-large-v3-turbo.bin"
    )
    whisper_vad_model_path: Path = field(
        default_factory=lambda: PROJECT_ROOT / "whisper.cpp" / "models" / "ggml-silero-v6.2.0.bin"
    )
    language: str = "ja"
    whisper_threads: int = 8
    silence_thresh_db: float = -35.0
    min_silence_duration: float = 0.25
    padding: float = 0.15
    min_confidence: float = 0.35
    subtitle_mode: str = "soft"
    video_encoder: str = "auto"
    fcpxml_target: str = "resolve"
    gradio_server_name: str = "127.0.0.1"
    gradio_server_port: int = 7860
    output_dir: Path | None = None


PERSISTENT_KEYS = {
    "whisper_cli_path",
    "whisper_model_path",
    "whisper_vad_model_path",
    "language",
    "whisper_threads",
    "silence_thresh_db",
    "min_silence_duration",
    "padding",
    "min_confidence",
    "subtitle_mode",
    "video_encoder",
    "fcpxml_target",
    "gradio_server_name",
    "gradio_server_port",
    "output_dir",
}

ENV_KEY_MAP = {
    "WHISPER_CLI_PATH": "whisper_cli_path",
    "WHISPER_MODEL_PATH": "whisper_model_path",
    "WHISPER_VAD_MODEL_PATH": "whisper_vad_model_path",
    "LANGUAGE": "language",
    "WHISPER_THREADS": "whisper_threads",
    "SILENCE_THRESH_DB": "silence_thresh_db",
    "MIN_SILENCE_DURATION": "min_silence_duration",
    "PADDING": "padding",
    "MIN_CONFIDENCE": "min_confidence",
    "MIN_AVG_LOGPROB": "min_confidence",
    "SUBTITLE_MODE": "subtitle_mode",
    "VIDEO_ENCODER": "video_encoder",
    "FCPXML_TARGET": "fcpxml_target",
    "GRADIO_SERVER_NAME": "gradio_server_name",
    "GRADIO_SERVER_PORT": "gradio_server_port",
    "OUTPUT_DIR": "output_dir",
}

PATH_FIELDS = {
    "whisper_cli_path",
    "whisper_model_path",
    "whisper_vad_model_path",
    "output_dir",
}

INT_FIELDS = {"whisper_threads", "gradio_server_port"}
FLOAT_FIELDS = {
    "silence_thresh_db",
    "min_silence_duration",
    "padding",
    "min_confidence",
}

CLI_ARG_MAP = {
    "output": "output_dir",
    "lang": "language",
    "silence_thresh": "silence_thresh_db",
    "min_silence": "min_silence_duration",
    "threads": "whisper_threads",
    "whisper_cli": "whisper_cli_path",
    "whisper_model": "whisper_model_path",
    "vad_model": "whisper_vad_model_path",
}


def normalize_user_path(value: str | Path) -> str:
    """Web UI などで入力されたパス文字列を正規化する。

    macOS のターミナルからコピーした shell 形式のパス
    例: '/Users/name/My\ File.mp4'
    を通常のパス文字列へ戻す。
    """
    text = str(value).strip()
    if not text:
        return text

    while len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1].strip()

    shell_like = (
        ("/" in text or text.startswith(("~", ".")))
        and ("\\" in text or "'" in text or '"' in text)
    )
    if not shell_like:
        return text

    try:
        tokens = shlex.split(text, posix=True)
    except ValueError:
        tokens = []

    if len(tokens) == 1:
        return tokens[0]

    unescaped: list[str] = []
    escaping = False

    for char in text:
        if escaping:
            unescaped.append(char)
            escaping = False
            continue

        if char == "\\":
            escaping = True
            continue

        unescaped.append(char)

    if escaping:
        unescaped.append("\\")

    return "".join(unescaped)


def _resolve_path(value: str | Path) -> Path:
    normalized = normalize_user_path(value)
    path = Path(normalized).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path.resolve()


def _path_to_storage(value: Path) -> str:
    try:
        return str(value.resolve().relative_to(PROJECT_ROOT))
    except ValueError:
        return str(value.resolve())


def _coerce_value(key: str, value: Any) -> Any:
    if value is None:
        return None
    if key in PATH_FIELDS:
        return _resolve_path(value)
    if key in INT_FIELDS:
        return int(value)
    if key in FLOAT_FIELDS:
        return float(value)
    return value


def _collect_env_values() -> dict[str, Any]:
    env_values = dict(dotenv_values(ENV_PATH))
    env_values.update({key: os.environ[key] for key in ENV_KEY_MAP if key in os.environ})
    normalized: dict[str, Any] = {}
    for env_key, config_key in ENV_KEY_MAP.items():
        if env_key not in env_values or env_values[env_key] in (None, ""):
            continue
        normalized[config_key] = _coerce_value(config_key, env_values[env_key])
    return normalized


def load_settings() -> dict[str, Any]:
    """settings.json を読み込む。"""
    if not SETTINGS_PATH.exists():
        return {}

    with SETTINGS_PATH.open("r", encoding="utf-8") as file:
        raw_settings = json.load(file)

    settings: dict[str, Any] = {}
    for key, value in raw_settings.items():
        if key in PERSISTENT_KEYS:
            settings[key] = _coerce_value(key, value)
    return settings


def _cli_to_dict(cli_args: argparse.Namespace | None) -> dict[str, Any]:
    if cli_args is None:
        return {}

    cli_values: dict[str, Any] = {}
    for key, value in vars(cli_args).items():
        if value is None:
            continue
        config_key = CLI_ARG_MAP.get(key, key)
        if config_key in AppConfig.__dataclass_fields__:
            cli_values[config_key] = _coerce_value(config_key, value)
    return cli_values


def load_config(cli_args: argparse.Namespace | None = None) -> AppConfig:
    """設定を優先順位に従って読み込む。

    output_dir は .env / settings.json / CLI のいずれかで明示指定されない限り
    None のまま保持し、実行時に入力動画の親ディレクトリをデフォルトとして使う。
    """
    merged: dict[str, Any] = asdict(AppConfig())

    for source in (_collect_env_values(), load_settings(), _cli_to_dict(cli_args)):
        for key, value in source.items():
            if key in merged and value is not None:
                merged[key] = value

    for key in PATH_FIELDS:
        if merged[key] is not None:
            merged[key] = _coerce_value(key, merged[key])

    return AppConfig(**merged)


def resolve_output_dir(config: AppConfig, input_path: Path) -> Path:
    """実際に使用する出力ディレクトリを決定する。

    config.output_dir が設定されていればそれを使い、
    未設定（None）なら入力動画と同じディレクトリを返す。
    """
    if config.output_dir is not None:
        return config.output_dir.resolve()
    return input_path.expanduser().resolve().parent


def save_settings(config: AppConfig) -> Path:
    """現在の設定を settings.json に保存する。"""
    serializable: dict[str, Any] = {}
    for key in PERSISTENT_KEYS:
        value = getattr(config, key)
        if value is None:
            continue
        if isinstance(value, Path):
            serializable[key] = _path_to_storage(value)
        else:
            serializable[key] = value

    with SETTINGS_PATH.open("w", encoding="utf-8") as file:
        json.dump(serializable, file, ensure_ascii=False, indent=2)

    return SETTINGS_PATH


def build_config_from_overrides(base_config: AppConfig, **overrides: Any) -> AppConfig:
    """既存設定に UI などの上書きを適用する。"""
    merged = asdict(base_config)
    for key, value in overrides.items():
        if value is None or key not in merged:
            continue
        merged[key] = _coerce_value(key, value)
    return AppConfig(**merged)
