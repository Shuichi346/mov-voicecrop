"""mov-voicecrop のエントリポイント。"""

from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
SRC_DIR = PROJECT_ROOT / "src"

if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from mov_voicecrop.cli import build_parser, run_cli
from mov_voicecrop.config import load_config


def main() -> None:
    """CLI と Web UI の起動を切り替える。"""
    argv = sys.argv[1:]

    if argv and argv[0] == "webui":
        from mov_voicecrop.webui import launch_webui

        config = load_config()
        launch_webui(config)
        return

    if argv and argv[0] == "cli":
        argv = argv[1:]

    parser = build_parser()
    if not argv:
        parser.print_help()
        return
    args = parser.parse_args(argv)
    run_cli(args)


if __name__ == "__main__":
    main()
