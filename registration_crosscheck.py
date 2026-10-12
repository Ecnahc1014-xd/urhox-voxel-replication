"""Compatibility entry point for the canonical scripts implementation."""

from pathlib import Path
import runpy


if __name__ == "__main__":
    script_path = Path(__file__).resolve().parent / "scripts" / Path(__file__).name
    runpy.run_path(str(script_path), run_name="__main__")
