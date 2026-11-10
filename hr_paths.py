"""Separate replaceable program files from settings and logs in the packaged app."""
import os
from pathlib import Path
import sys

FROZEN = bool(getattr(sys, 'frozen', False))
PROGRAM_DIR = Path(__file__).resolve().parent
if FROZEN:
    DATA_DIR = Path(os.environ.get('LOCALAPPDATA', Path.home()/'AppData/Local'))/'FishHeartHitData'/'profile'
else:
    DATA_DIR = PROGRAM_DIR


def process_args(script, *args, console=False, source_dir=PROGRAM_DIR):
    executable = Path(sys.executable)
    if FROZEN:
        roles = {'heartrate_live.py': '--service-child', 'heartrate_hud.py': '--hud-child',
                 'app_launcher.py': '--launcher-child'}
        return [str(executable), roles[script], *args]
    if console and executable.name.lower() == 'pythonw.exe':
        executable = executable.with_name('python.exe')
    return [str(executable), str(source_dir/script), *args]
