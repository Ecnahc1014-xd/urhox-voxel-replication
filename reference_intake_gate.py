"""Compatibility entry point for the canonical scripts implementation."""

from pathlib import Path
import runpy
import sys


if __name__ == "__main__":
    script_path = Path(__file__).resolve().parent / "scripts" / Path(__file__).name
    sys.path.insert(0, str(script_path.parent))
    runpy.run_path(str(script_path), run_name="__main__")
