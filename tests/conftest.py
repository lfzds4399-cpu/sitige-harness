"""pytest configuration — add src/ to sys.path."""
from __future__ import annotations

import sys
from pathlib import Path

# Add src/ to sys.path so all test modules can import tetra_harness
HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))
