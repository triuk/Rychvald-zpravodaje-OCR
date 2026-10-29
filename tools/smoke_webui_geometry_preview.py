"""Native geometry preview, logical order and character boundaries after repair."""
import sys
from smoke_webui_reading_preview import main


if __name__ == '__main__':
    sys.argv.extend(['--phase', 'geometry'])
    raise SystemExit(main())
