"""Start the native OCR edition browser; OCR keeps its own process protocol."""

import argparse
import os
from pathlib import Path
import sys

from app.application import WebUIApplication


def main(argv=None):
    parser = argparse.ArgumentParser(description='Projekty vydání — Rychvaldský zpravodaj OCR')
    default_data = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local/share'))
    parser.add_argument('--root', type=Path, default=default_data / 'rychvald-ocr',
                        help='Adresář evidence se souborem registry.json.')
    process = parser.add_mutually_exclusive_group()
    process.add_argument('--ocr-executable', type=Path,
                         help='Volitelný samostatný OCR proces se stávajícím JSON protokolem.')
    process.add_argument('--ocr-python', type=Path,
                         help='Python ověřeného OCR prostředí pro vývojové spuštění.')
    parser.add_argument('--browser', choices=['Chromium', 'Firefox', 'Chrome'],
                        help='Volitelná volba prohlížeče pro nativní okno WebUI.')
    args = parser.parse_args(argv)
    command = [str(args.ocr_executable.resolve())] if args.ocr_executable else None
    if args.ocr_python:
        command = [str(args.ocr_python.absolute()), str(Path(__file__).resolve().parent / 'tools/ocr_projects.py')]
    try:
        WebUIApplication(args.root, process_command=command, browser=args.browser).run()
    except RuntimeError as error:
        print(str(error), file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
