"""Thin source-checkout forwarder for the ``code2play`` CLI."""

from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from code2play.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
