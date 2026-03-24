#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
WHISPER_DIR="${ROOT_DIR}/whisper.cpp"

if [[ ! -d "${WHISPER_DIR}" ]]; then
  git clone --depth 1 https://github.com/ggml-org/whisper.cpp.git "${WHISPER_DIR}"
fi

cmake -S "${WHISPER_DIR}" -B "${WHISPER_DIR}/build" -DWHISPER_METAL=ON
cmake --build "${WHISPER_DIR}/build" --config Release -j

"${WHISPER_DIR}/models/download-ggml-model.sh" large-v3-turbo

if [[ -x "${WHISPER_DIR}/models/download-vad-model.sh" ]]; then
  "${WHISPER_DIR}/models/download-vad-model.sh" silero-v6.2.0
fi
