# mov-voicecrop

`mov-voicecrop` は、動画から発話区間だけを残して無音区間を自動でカットし、字幕付き MP4 / SRT / FCPXML を出力するツールです。

## 特徴

- `whisper.cpp` と Silero VAD による文字起こし
- `ffmpeg silencedetect` による無音検出
- カット済み MP4、SRT、Final Cut Pro / DaVinci Resolve 向け FCPXML 1.14 を生成
- CLI と Gradio Web UI の両対応
- `.env` と `settings.json` による設定管理
- ハードウェアエンコード（h264_videotoolbox）の自動検出・利用
- 出力先はデフォルトで入力動画と同じディレクトリ（変更可能）

## セットアップ

1. Python 依存を同期します。

```bash
uv sync
```

2. `whisper.cpp` をセットアップします。

```bash
chmod +x scripts/setup_whisper.sh
./scripts/setup_whisper.sh
```

3. 必要なら `.env.example` を `.env` にコピーして調整します。

```bash
cp .env.example .env
```

## 使い方

CLI:

```bash
# 出力先を指定しない場合、入力動画と同じディレクトリに出力されます
uv run python main.py cli -i /path/to/input.mp4 --style both

# 出力先を明示指定する場合
uv run python main.py cli -i /path/to/input.mp4 -o ./output --style both
```

Web UI:

```bash
uv run python main.py webui
```

起動後、ブラウザで `http://127.0.0.1:7860` を開きます。「入力動画のパス」にファイルパスを入力して処理を実行します。

## 出力ファイル

- `*_original.srt`: 元動画タイムライン基準の字幕
- `*_cut.srt`: カット後タイムライン基準の字幕
- `*_cut.mp4`: カット済み動画（字幕モード soft の場合はソフトサブ付き）
- `*.fcpxml`: DaVinci Resolve 20 読み込み用 FCPXML

## 出力ディレクトリ

デフォルトでは入力動画と同じディレクトリに出力ファイルが生成されます。CLI の `-o` オプション、Web UI の「出力ディレクトリ」欄、`.env` の `OUTPUT_DIR`、または `settings.json` で変更できます。

## 字幕モード

- `soft`: ソフトサブ（プレイヤーでオン/オフ切替可能）
- `off`: 字幕なし

## 映像エンコーダー

- `auto`（デフォルト）: Mac の h264_videotoolbox が利用可能なら自動で使用し、高速にエンコードします。利用できない場合は libx264 にフォールバックします。
- `libx264`: CPU ソフトウェアエンコード
- `h264_videotoolbox`: macOS ハードウェアエンコード