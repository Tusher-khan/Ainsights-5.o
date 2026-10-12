"""WSGI entry point for gunicorn (e.g. on Render).

This project has both app.py (the Flask entry point, which builds
`app = create_app()`) and an app/ package (app/routes/, app/services/, ...)
in the same directory. A bare `import app` is ambiguous — Python's import
system resolves it to the app/ package, not the app.py file — so
`gunicorn app:app` fails with:

    AttributeError: module 'app' has no attribute 'app'

This file loads app.py directly by its file path instead of by module name,
which sidesteps the collision. Point gunicorn at this file instead:

    gunicorn wsgi:app --bind 0.0.0.0:$PORT
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_spec = importlib.util.spec_from_file_location("ainsight_entry", Path(__file__).parent / "app.py")
_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

app = _module.app
