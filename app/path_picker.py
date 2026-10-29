"""Validate desktop-selected paths before presenting them to existing operations."""

import os
from pathlib import Path
import shutil
import subprocess
import threading


class PathSelectionError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


PATH_KINDS = {
    'registry_directory': ('Adresář evidence', None),
    'source_directory': ('Složka se vstupními PDF', None),
    'source_pdf': ('Vstupní PDF', ('.pdf',)),
    'profile': ('Profil průchodu OCR', ('.json',)),
    'environment_manifest': ('Manifest prostředí OCR', ('.json',)),
    'image': ('Obrázek pro ověření modelu', ('.png', '.jpg', '.jpeg', '.webp')),
}


class DesktopPathPicker:
    """Linux native dialogs, with a stdlib Tk fallback for development installs.

    KDE/GTK helpers are argument-list subprocesses; cancellation returns None.
    Tk owns its root entirely on the calling WebUI callback thread. A second
    request never opens another modal picker on top of the first.
    """

    def __init__(self):
        self._active = threading.Lock()

    def __call__(self, kind, current):
        if not self._active.acquire(blocking=False):
            raise PathSelectionError('path_picker_active', 'Dokončete nejprve otevřený výběr cesty.')
        try:
            title, extensions = PATH_KINDS[kind]
            initial = Path(current).expanduser() if current else Path.home()
            if not initial.exists():
                initial = initial.parent
            if not initial.exists():
                initial = Path.home()
            kde = shutil.which('kdialog')
            gtk = shutil.which('zenity')
            if kde:
                command = [kde, '--title', title]
                command += ['--getexistingdirectory', str(initial)] if extensions is None else [
                    '--getopenfilename', str(initial), ' '.join('*' + extension for extension in extensions)]
            elif gtk:
                command = [gtk, '--file-selection', '--title', title, '--filename',
                           str(initial) + (os.sep if initial.is_dir() else '')]
                if extensions is None:
                    command.append('--directory')
                else:
                    command += ['--file-filter', title + ' | ' + ' '.join('*' + extension for extension in extensions)]
            else:
                return self._tk_dialog(title, extensions, initial)
            result = subprocess.run(command, capture_output=True, text=True)
            if result.returncode == 1:
                return None
            if result.returncode != 0:
                raise PathSelectionError('path_picker_unavailable', 'Systémový dialog pro výběr cesty se nepodařilo otevřít.')
            # Helpers append one newline; do not strip spaces from real paths.
            return result.stdout.removesuffix('\n') or None
        finally:
            self._active.release()

    @staticmethod
    def _tk_dialog(title, extensions, initial):
        try:
            import tkinter
            from tkinter import filedialog
        except ImportError:
            raise PathSelectionError('path_picker_unavailable', 'Systémový výběr cest vyžaduje Tk nebo nástroj zenity/kdialog.') from None
        root = None
        try:
            root = tkinter.Tk()
            root.withdraw()
            options = {'parent': root, 'title': title,
                       'initialdir': str(initial if initial.is_dir() else initial.parent)}
            if extensions is None:
                return filedialog.askdirectory(mustexist=True, **options) or None
            options['filetypes'] = [(title, tuple('*' + extension for extension in extensions))]
            if initial.is_file():
                options['initialfile'] = initial.name
            return filedialog.askopenfilename(**options) or None
        except tkinter.TclError:
            raise PathSelectionError('path_picker_unavailable', 'Systémový dialog vyžaduje dostupné grafické prostředí.') from None
        finally:
            if root is not None:
                root.destroy()


def select_path(payload, picker):
    if not isinstance(payload, dict):
        raise PathSelectionError('invalid_request', 'Výběr cesty vyžaduje typ dialogu.')
    kind = payload.get('kind')
    current = payload.get('current_path', '')
    if not isinstance(kind, str) or kind not in PATH_KINDS or not isinstance(current, str):
        raise PathSelectionError('invalid_request', 'Neplatný typ dialogu nebo dosavadní cesta.')
    if picker is None:
        raise PathSelectionError('path_picker_unavailable', 'Systémový výběr cest není v tomto spuštění dostupný.')
    chosen = picker(kind, current)
    if chosen is None or chosen == '':
        return {'kind': kind, 'path': current, 'cancelled': True}
    if not isinstance(chosen, (str, Path)):
        raise PathSelectionError('path_invalid', 'Dialog nevrátil platnou cestu.')
    try:
        path = Path(chosen).expanduser().resolve(strict=True)
    except OSError:
        raise PathSelectionError('path_invalid', 'Vybraná cesta není dostupná. Vyberte existující soubor nebo adresář.') from None
    extensions = PATH_KINDS[kind][1]
    if extensions is None:
        valid = path.is_dir() and os.access(path, os.R_OK | os.X_OK)
        expected = 'přístupný adresář'
    else:
        valid = path.is_file() and path.suffix.lower() in extensions and os.access(path, os.R_OK)
        expected = 'čitelný soubor ' + ', '.join(extensions)
    if not valid:
        raise PathSelectionError('path_invalid', f'Vyberte {expected}.')
    return {'kind': kind, 'path': str(path), 'cancelled': False}
