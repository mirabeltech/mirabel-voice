"""The approved bundle runtime contract travels in the endorsed source package."""
import json
import platform
import sys
import sysconfig
from pathlib import Path

CONTRACT = json.loads((Path(__file__).parent / 'data' / 'runtime.json').read_text(encoding='utf-8'))


def bundle_problem():
    # A development checkout may use another interpreter. Installed/source-update
    # proof commands must reject runtime changes, including older --config probes.
    if Path(__file__).resolve().parent.parent.name.lower() != 'site-packages':
        return None
    runtime = Path(__file__).resolve().parent.parent.parent.parent
    if not list(runtime.glob('python*._pth')):
        return None
    marker = runtime / 'bundle-format.txt'
    if not marker.exists() or marker.read_text(encoding='utf-8').strip() != str(CONTRACT['bundle_format']):
        return 'This source update needs the latest full Python ZIP, including its launch and recovery files.'
    # platform.machine() names the CPU, which is ARM64 when Windows emulates this
    # x64 runtime. The contract is about the runtime, so ask what Python was built for.
    if platform.python_version() != CONTRACT['python'] or sysconfig.get_platform() != f"win-{CONTRACT['architecture'].lower()}":
        return 'This release requires a new full Python ZIP from the company drive. The current runtime cannot use this source update.'
    return None
