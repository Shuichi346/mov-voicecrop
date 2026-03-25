#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WHISPER_DIR="${ROOT_DIR}/whisper.cpp"

# whisper.cpp リポジトリのクローン
if [[ ! -d "${WHISPER_DIR}" ]]; then
  git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git "${WHISPER_DIR}"
fi

# Apple Silicon かどうか判定
IS_APPLE_SILICON=false
if [[ "$(uname -s)" == "Darwin" && "$(uname -m)" == "arm64" ]]; then
  IS_APPLE_SILICON=true
fi

# ビルドオプションの組み立て
CMAKE_OPTIONS=(-DWHISPER_METAL=ON)
if [[ "${IS_APPLE_SILICON}" == true ]]; then
  CMAKE_OPTIONS+=(-DWHISPER_COREML=1)
  echo "Apple Silicon を検出しました。Core ML サポートを有効にしてビルドします。"
fi

cmake -S "${WHISPER_DIR}" -B "${WHISPER_DIR}/build" "${CMAKE_OPTIONS[@]}"
cmake --build "${WHISPER_DIR}/build" --config Release -j

# ggml モデルのダウンロード
MODEL_NAME="large-v3-turbo"
"${WHISPER_DIR}/models/download-ggml-model.sh" "${MODEL_NAME}"

# VAD モデルのダウンロード（スクリプトが存在する場合）
if [[ -x "${WHISPER_DIR}/models/download-vad-model.sh" ]]; then
  "${WHISPER_DIR}/models/download-vad-model.sh" silero-v6.2.0
fi

# Apple Silicon の場合、Core ML エンコーダーモデルを用意する
if [[ "${IS_APPLE_SILICON}" == true ]]; then
  COREML_DIR="${WHISPER_DIR}/models/ggml-${MODEL_NAME}-encoder.mlmodelc"

  if [[ -d "${COREML_DIR}" ]]; then
    echo "Core ML モデルは既に存在します: ${COREML_DIR}"
  else
    echo "Core ML エンコーダーモデルをダウンロードしています..."

    COREML_ZIP="${WHISPER_DIR}/models/ggml-${MODEL_NAME}-encoder.mlmodelc.zip"
    COREML_URL="https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-${MODEL_NAME}-encoder.mlmodelc.zip"

    curl -L -o "${COREML_ZIP}" "${COREML_URL}"
    unzip -o "${COREML_ZIP}" -d "${WHISPER_DIR}/models/"
    rm -f "${COREML_ZIP}"

    echo "Core ML モデルの準備が完了しました: ${COREML_DIR}"
    echo "※ 初回実行時は ANE がモデルをコンパイルするため時間がかかります。2回目以降は高速です。"
  fi
fi
