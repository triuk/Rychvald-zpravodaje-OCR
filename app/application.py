"""Thin native WebUI adapter for the public application request interface."""

import json
import os
from pathlib import Path
import signal
import threading
from urllib.parse import urlparse

from .service import Application


class WebUIApplication:
    def __init__(self, root, *, process_command=None, browser=None, browser_parameters=None, browser_profile=None):
        self.api = Application(root, process_command=process_command)
        self.window = None
        self.browser = browser
        self.browser_parameters = browser_parameters
        self.browser_profile = browser_profile

    def request(self, event):
        try:
            request = json.loads(event.get_string())
            if not isinstance(request, dict) or not isinstance(request.get('operation'), str):
                raise ValueError()
            result = self.api.dispatch(request['operation'], request.get('payload'))
        except (ValueError, TypeError):
            result = {'ok': False, 'data': None, 'event_cursor': self.api._sequence,
                      'error': {'code': 'invalid_request', 'message': 'Request must be a JSON object with an operation.'}}
        event.return_string(json.dumps(result, ensure_ascii=False))

    def run(self, *, serve=False):
        try:
            from webui import webui
        except ImportError:
            raise RuntimeError('Chybí webui2. Nainstalujte requirements-gui.txt.') from None
        window_factory = getattr(webui, 'Window', None) or getattr(webui, 'window', None)
        if window_factory is None:
            raise RuntimeError('Nainstalované WebUI neposkytuje nativní okno.')
        self.window = window_factory()
        self.window.set_public(False)
        self.window.set_size(1280, 900)
        self.window.bind('requestB', self.request)
        self.window.set_root_folder(str(Path(__file__).resolve().parents[1] / 'ui'))
        if self.browser_profile:
            self.window.set_profile('OCR', str(self.browser_profile))
        if self.browser_parameters:
            self.window.set_custom_parameters(self.browser_parameters)
        handlers = {}
        try:
            if serve:
                stopped = threading.Event()
                for name in (signal.SIGINT, signal.SIGTERM):
                    handlers[name] = signal.signal(name, lambda *_: stopped.set())
                webui.set_timeout(0)
                url = self.window.start_server('index.html')
                parsed = urlparse(url)
                if parsed.scheme != 'http' or parsed.hostname not in ('localhost', '127.0.0.1', '::1') or not parsed.port:
                    raise RuntimeError('WebUI nevrátilo platnou loopback URL.')
                print(json.dumps({'operation': 'serve', 'status': 'ready', 'url': url,
                                  'pid': os.getpid()}), flush=True)
                stopped.wait()
            else:
                if self.browser:
                    shown = self.window.show_browser('index.html', getattr(webui.Browser, self.browser))
                else:
                    shown = self.window.show('index.html')
                if shown is False:
                    raise RuntimeError('WebUI nedokázalo otevřít okno aplikace.')
                webui.wait()
        finally:
            self.api.close()
            self.window.destroy()
            for name, handler in handlers.items():
                signal.signal(name, handler)
