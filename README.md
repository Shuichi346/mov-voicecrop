# mov-voicecrop

`mov-voicecrop` は、動画から発話区間だけを残して無音区間を自動でカットし、字幕付き MP4 / SRT / FCPXML を出力するツールです。

## 特徴

- `whisper.cpp` と Silero VAD による文字起こし
- `ffmpeg silencedetect` による無音検出
- カット済み MP4、SRT、DaVinci Resolve 20 向け FCPXML 1.9 を生成
- CLI と Gradio Web UI の両対応
- `.env` と `settings.json` による設定管理

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

## 使い方

CLI:

```bash
uv run python main.py cli -i /path/to/input.mp4 -o ./output --style both
```

Web UI:

```bash
uv run python main.py webui
```

起動後、ブラウザで `http://127.0.0.1:7860` を開きます。

## 出力ファイル

- `*_original.srt`: 元動画タイムライン基準の字幕
- `*_cut.srt`: カット後タイムライン基準の字幕
- `*_cut.mp4`: カット済み動画
- `*.fcpxml`: DaVinci Resolve 20 読み込み用 FCPXML

字幕モードを `both` にした場合は、`*_cut_soft.mp4` と `*_cut_hard.mp4` を出力します。
