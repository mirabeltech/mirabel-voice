"""The program that PyInstaller packs.

This exists so the import below is an absolute one. Pointing PyInstaller
straight at src/mirabel_voice/__main__.py does not work: it reads that
file as a loose script, its "from .app import ..." lines cannot be
resolved, and the build then silently contains none of the app.
"""

from mirabel_voice.__main__ import main

if __name__ == "__main__":
    raise SystemExit(main())
