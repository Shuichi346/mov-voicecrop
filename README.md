<table>
  <thead>
    <tr>
      <th style="text-align:center"><a href="README_en.md">English</a></th>
      <th style="text-align:center"><a href="README.md">日本語</a></th>
    </tr>
  </thead>
</table>

# mov-voicecrop

[![Python Version](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**mov-voicecrop** は、`whisper.cpp` と `ffmpeg` を活用して、動画ファイルから発話区間のみを自動で抽出し、無音カットと字幕生成を同時に行うローカルツールです。Gradioによる直感的なWeb UIと、自動化に便利なCLIの両方を提供します。

## ✨ 主な機能

- **高速・高精度な文字起こし**: `whisper.cpp` をバックエンドに採用し、ローカル環境で高速に処理を実行。Apple Silicon (Mac) 環境では Core ML を自動的に利用して最適化します。
- **柔軟な無音検出**: `ffmpeg` を用いて、無音閾値 (dB) や最小無音長 (秒) を指定して精緻な無音カットを行います。
- **音声未認識区間のカット**: Whisperが認識できなかったノイズや叫び声など、低確率なトークン区間を自動的に除外する機能を搭載。
- **マルチフォーマット出力**:
  - **MP4**: カット編集済みの動画ファイル（ソフトサブ対応）。
  - **SRT**: カット前（オリジナル）およびカット後（再インデックス）のタイミングに合わせた字幕ファイル。
  - **FCPXML**: DaVinci Resolve 20 や Final Cut Pro 12 に直接読み込めるタイムラインファイル。

## ⚙️ 前提条件

本プロジェクトを動作させるためには、以下のツールがシステムにインストールされている必要があります。

- Python 3.11 以上
- `ffmpeg` および `ffprobe` (例: macOSの場合は `brew install ffmpeg`)
- `git`, `cmake`, `curl`, `unzip` (whisper.cpp のビルドに必要)

## 🚀 インストール手順

1. **リポジトリのクローン**
   ```bash
   git clone https://github.com/Shuichi346/matome-site-generator
   cd mov-voicecrop
   ```

2. **whisper.cpp のセットアップ**
   専用のセットアップスクリプトを実行して、`whisper.cpp` のクローン、ビルド、および必要なモデル（`large-v3-turbo`, `silero-v6.2.0`）のダウンロードを行います。
   ※ Apple Silicon搭載Macの場合、Core MLサポートが自動的に有効化されます。
   ```bash
   bash scripts/setup_whisper.sh
   ```

3. **Python 環境の構築**
   仮想環境を作成し、依存関係をインストールします。
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # Windowsの場合は .venv\Scripts\activate
   pip install -e .
   ```

4. **環境変数の設定**
   `.env.example` をコピーして `.env` を作成し、必要に応じて設定を編集します。
   ```bash
   cp .env.example .env
   ```

## 📖 使い方

mov-voicecrop は、Web UI または コマンドライン (CLI) のどちらからでも利用可能です。

### Web UI での実行

Gradio を使用したブラウザベースのUIを起動します。

```bash
python main.py webui
```

起動後、コンソールに表示されるローカルURL (例: `http://127.0.0.1:7860`) にブラウザでアクセスしてください。
UI上から入力動画の指定、無音検出・音声認識のパラメータ調整、FCPXMLのターゲット指定などが行えます。

### CLI での実行

コマンドラインから直接処理を実行することも可能です。バッチ処理などに便利です。

```bash
python main.py cli -i /path/to/input.mp4
```

**主なCLIオプション:**
- `-i`, `--input` (必須): 入力動画ファイルのパス
- `-o`, `--output`: 出力ディレクトリ（未指定時は入力動画と同じディレクトリ）
- `--style`: 出力形式 (`mp4`, `xml`, `both`)[デフォルト: `both`]
- `--lang`: 音声認識言語 (例: `ja`, `en`)
- `--cut-unrecognized` / `--no-cut-unrecognized`: 音声未認識区間もカットするかどうか
- `--video-encoder`: MP4映像エンコーダー (`auto`, `libx264`, `h264_videotoolbox`)
- `--fcpxml-target`: FCPXML 出力ターゲット (`resolve`, `fcp`, `both`)

すべてのオプションを確認するには、ヘルプコマンドを実行してください：
```bash
python main.py cli --help
```

## 📁 出力ファイル構成

処理が完了すると、指定した出力ディレクトリ（または入力動画と同じディレクトリ）に以下のファイルが生成されます（オプション設定に依存します）。

- `[ファイル名]_cut.mp4`: 無音および未認識区間がカットされた動画ファイル。
- `[ファイル名]_original.srt`: カット前の元動画のタイムラインに合わせた字幕ファイル。
- `[ファイル名]_cut.srt`: カット後の動画のタイムラインに合わせた字幕ファイル。
- `[ファイル名].fcpxml` または `*_resolve.fcpxml` / `*_fcp.fcpxml`: 動画編集ソフト用のタイムラインデータ。

## 🔧 環境変数と設定 (.env)

`.env` ファイルを編集することで、デフォルトの挙動を変更できます。

- `WHISPER_THREADS`: Whisperの推論に使用するCPUスレッド数。
- `LANGUAGE`: 文字起こしのデフォルト言語（例: `ja`）。
- `SILENCE_THRESH_DB`: 無音と判定する音量の閾値（デフォルト: `-35` dB）。
- `MIN_SILENCE_DURATION`: カット対象となる最小の無音長さ（デフォルト: `0.25` 秒）。
- `CUT_UNRECOGNIZED`: 低確率トークン区間を除外するかどうか（`true` / `false`）。
- `FCPXML_TARGET`: FCPXMLの互換ターゲット（`resolve` / `fcp` / `both`）。

## 📄 ライセンス

このプロジェクトは [MIT License](LICENSE) のもとで公開されています。
Copyright (c) 2026 Shuichi