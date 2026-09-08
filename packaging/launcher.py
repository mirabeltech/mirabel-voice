"""Stable entry point outside the replaceable application package."""
from pathlib import Path
import runpy
import sys
import time
sys.path.insert(0, str(Path(__file__).resolve().parent))
from recovery import InstallLock, UpdateBusy, recover

root = Path(__file__).resolve().parent
# The PowerShell launcher first recovers the runtime, then this handles source.
for attempt in range(60):
    try:
        with InstallLock(root):
            recover(root / 'python' / 'Lib' / 'site-packages' / 'mirabel_voice')
        break
    except UpdateBusy:
        time.sleep(1)
else:
    raise SystemExit('An update is still running. Start Mirabel Voice again shortly.')
sys.argv = ['mirabel_voice'] + sys.argv[1:]
runpy.run_module('mirabel_voice', run_name='__main__')
