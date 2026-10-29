#!/bin/sh
set -eu

project_dir=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd -P)
python="$project_dir/.venv/bin/python"

if [ ! -x "$python" ]; then
    printf '%s\n' \
        'Chybí místní Python prostředí .venv. Připravte ho jednorázově:' \
        "  python3.14 -m venv \"$project_dir/.venv\"" \
        "  \"$python\" -m pip install -r \"$project_dir/requirements.txt\" -r \"$project_dir/requirements-gui.txt\"" >&2
    exit 1
fi

exec "$python" "$project_dir/main.py" "$@"
