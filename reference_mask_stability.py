from pathlib import Path
import runpy
import sys

SCRIPT_ROOT = Path(__file__).resolve().parent / 'scripts'
sys.path.insert(0, str(SCRIPT_ROOT))
runpy.run_path(str(SCRIPT_ROOT / 'reference_mask_stability.py'), run_name='__main__')
