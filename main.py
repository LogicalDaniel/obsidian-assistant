"""Run the assistant until a blank line or quit.

    uv run python main.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from entry import repl

if __name__ == "__main__":
    repl()
