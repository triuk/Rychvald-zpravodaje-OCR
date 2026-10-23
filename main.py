"""Start the native OCR edition browser; OCR keeps its own process protocol."""

import argparse
import os
from pathlib import Path
import sys

from app.application import WebUIApplication


def main(argv=None):
    parser = argparse.ArgumentParser(description='Projekty vydání — Rychvaldský zpravodaj OCR')
    parser.add_argument('--root', type=Path,
                        help='Adresář evidence se souborem registry.json.')
    process = parser.add_mutually_exclusive_group()
    process.add_argument('--ocr-executable', type=Path,
                         help='Volitelný samostatný OCR proces se stávajícím JSON protokolem.')
    process.add_argument('--ocr-python', type=Path,
                         help='Python ověřeného OCR prostředí pro vývojové spuštění.')
    launch = parser.add_mutually_exclusive_group()
    launch.add_argument('--browser', choices=['Chromium', 'Firefox', 'Chrome'],
                        help='Volitelná volba prohlížeče pro nativní okno WebUI.')
    launch.add_argument('--serve', action='store_true',
                        help='Spustit skutečný WebUI server na loopbacku bez otevření prohlížeče; vypíše JSON URL.')
    args = parser.parse_args(argv)
    root = args.root
    if root is None:
        default_data = Path(os.environ['XDG_DATA_HOME']) if os.environ.get('XDG_DATA_HOME') else Path.home() / '.local/share'
        root = default_data / 'rychvald-ocr'
    command = [str(args.ocr_executable.resolve())] if args.ocr_executable else None
    if args.ocr_python:
        command = [str(args.ocr_python.absolute()), str(Path(__file__).resolve().parent / 'tools/ocr_projects.py')]
    try:
        WebUIApplication(root, process_command=command, browser=args.browser).run(serve=args.serve)
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
