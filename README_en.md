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

**mov-voicecrop** is a local tool that leverages `whisper.cpp` and `ffmpeg` to automatically extract only speech segments from video files while simultaneously performing silence cutting and subtitle generation. It provides both an intuitive Gradio Web UI and a CLI convenient for automation.

## ✨ Key Features

- **High-speed, high-accuracy transcription**: Adopts `whisper.cpp` as backend for fast local processing. Automatically utilizes Core ML for optimization in Apple Silicon (Mac) environments.
- **Flexible silence detection**: Uses `ffmpeg` to perform precise silence cutting by specifying silence threshold (dB) and minimum silence duration (seconds).
- **Cutting of unrecognized audio segments**: Features automatic exclusion of low-probability token segments such as noise or screaming that Whisper cannot recognize.
- **Multi-format output**:
  - **MP4**: Cut-edited video files (soft subtitle support).
  - **SRT**: Subtitle files matched to pre-cut (original) and post-cut (re-indexed) timing.
  - **FCPXML**: Timeline files that can be directly imported into DaVinci Resolve 20 or Final Cut Pro 12.

## ⚙️ Prerequisites

The following tools must be installed on your system to run this project:

- Python 3.11 or higher
- `ffmpeg` and `ffprobe` (e.g., `brew install ffmpeg` for macOS)
- `git`, `cmake`, `curl`, `unzip` (required for whisper.cpp build)

## 🚀 Installation Steps

1. **Clone the repository**
   ```bash
   git clone https://github.com/Shuichi346/matome-site-generator
   cd mov-voicecrop
   ```

2. **Set up whisper.cpp**
   Run the dedicated setup script to clone, build `whisper.cpp`, and download necessary models (`large-v3-turbo`, `silero-v6.2.0`).
   ※ For Apple Silicon Macs, Core ML support is automatically enabled.
   ```bash
   bash scripts/setup_whisper.sh
   ```

3. **Set up Python environment**
   Create a virtual environment and install dependencies.
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate  # For Windows: .venv\Scripts\activate
   pip install -e .
   ```

4. **Configure environment variables**
   Copy `.env.example` to create `.env` and edit settings as needed.
   ```bash
   cp .env.example .env
   ```

## 📖 Usage

mov-voicecrop can be used from either Web UI or command line (CLI).

### Running with Web UI

Launch the browser-based UI using Gradio.

```bash
python main.py webui
```

After startup, access the local URL displayed in the console (e.g., `http://127.0.0.1:7860`) with your browser.
The UI allows you to specify input videos, adjust silence detection and speech recognition parameters, specify FCPXML targets, and more.

### Running with CLI

You can also execute processing directly from the command line, which is convenient for batch processing.

```bash
python main.py cli -i /path/to/input.mp4
```

**Main CLI options:**
- `-i`, `--input` (required): Path to input video file
- `-o`, `--output`: Output directory (defaults to same directory as input video if not specified)
- `--style`: Output format (`mp4`, `xml`, `both`) [default: `both`]
- `--lang`: Speech recognition language (e.g., `ja`, `en`)
- `--cut-unrecognized` / `--no-cut-unrecognized`: Whether to cut unrecognized audio segments
- `--video-encoder`: MP4 video encoder (`auto`, `libx264`, `h264_videotoolbox`)
- `--fcpxml-target`: FCPXML output target (`resolve`, `fcp`, `both`)

To see all options, run the help command:
```bash
python main.py cli --help
```

## 📁 Output File Structure

When processing is complete, the following files will be generated in the specified output directory (or same directory as input video) depending on option settings:

- `[filename]_cut.mp4`: Video file with silence and unrecognized segments cut.
- `[filename]_original.srt`: Subtitle file matched to original video timeline before cutting.
- `[filename]_cut.srt`: Subtitle file matched to video timeline after cutting.
- `[filename].fcpxml` or `*_resolve.fcpxml` / `*_fcp.fcpxml`: Timeline data for video editing software.

## 🔧 Environment Variables and Configuration (.env)

You can modify default behavior by editing the `.env` file:

- `WHISPER_THREADS`: Number of CPU threads used for Whisper inference.
- `LANGUAGE`: Default language for transcription (e.g., `ja`).
- `SILENCE_THRESH_DB`: Volume threshold for silence detection (default: `-35` dB).
- `MIN_SILENCE_DURATION`: Minimum silence duration to be cut (default: `0.25` seconds).
- `CUT_UNRECOGNIZED`: Whether to exclude low-probability token segments (`true` / `false`).
- `FCPXML_TARGET`: FCPXML compatibility target (`resolve` / `fcp` / `both`).

## 📄 License

This project is released under the [MIT License](LICENSE).
Copyright (c) 2026 Shuichi