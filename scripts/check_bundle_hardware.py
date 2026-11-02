"""Exercise the bundle's native pieces on real hardware, using the bundled Python.

CI runs this on x64 and Windows ARM runners, where the x64 bundle is emulated.
It presses keys and replaces the clipboard, so run it only on a disposable
computer. It opens no microphone and sends no speech or text anywhere.
"""
import argparse
import ctypes
import platform
import ssl
import sys
import sysconfig
import threading
import time
import tkinter
import traceback
import urllib.request
from ctypes import wintypes

TIMEOUT_SECONDS = 5
TEXT = 'Mirabel Voice café'
EARLIER_CLIPBOARD = 'already on the clipboard'
MACHINES = {0x8664: 'AMD64', 0xAA64: 'ARM64'}
WINDOW_TITLE = 'Mirabel Voice hardware check'
SIGN_IN_PROMPT = 'Microsoft account'
WM_CLOSE = 0x0010


def native_machine():
    # platform.machine() can answer for the process. This answers for the CPU.
    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    kernel32.GetCurrentProcess.restype = wintypes.HANDLE
    kernel32.IsWow64Process2.argtypes = (wintypes.HANDLE, ctypes.POINTER(wintypes.USHORT), ctypes.POINTER(wintypes.USHORT))
    process, native = wintypes.USHORT(), wintypes.USHORT()
    if not kernel32.IsWow64Process2(kernel32.GetCurrentProcess(), ctypes.byref(process), ctypes.byref(native)):
        raise ctypes.WinError(ctypes.get_last_error())
    return MACHINES.get(native.value, hex(native.value))


def foreground_title():
    user32 = ctypes.WinDLL('user32')
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowTextW.argtypes = (wintypes.HWND, wintypes.LPWSTR, ctypes.c_int)
    title = ctypes.create_unicode_buffer(256)
    user32.GetWindowTextW(user32.GetForegroundWindow(), title, 256)
    return title.value


def take_focus(root, box):
    from pynput.keyboard import Controller, Key
    keyboard = Controller()
    user32 = ctypes.WinDLL('user32')
    user32.SetForegroundWindow.argtypes = (wintypes.HWND,)
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.PostMessageW.argtypes = (wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM)
    for _ in range(5):
        # Windows lets a background process take the foreground right after a key press.
        keyboard.press(Key.alt)
        keyboard.release(Key.alt)
        user32.SetForegroundWindow(int(root.wm_frame(), 16))
        root.update()
        box.focus_force()
        root.update()
        time.sleep(0.2)
        if foreground_title() == WINDOW_TITLE:
            return
        # The windows-11-arm image opens this sign-in prompt over everything.
        if foreground_title() == SIGN_IN_PROMPT:
            user32.PostMessageW(user32.GetForegroundWindow(), WM_CLOSE, 0, 0)
        time.sleep(1)
    raise AssertionError(f'The check window never got the foreground; {foreground_title()!r} has it')


def wait_until(condition, root):
    deadline = time.monotonic() + TIMEOUT_SECONDS
    while time.monotonic() < deadline:
        root.update()
        if condition():
            return True
        time.sleep(0.02)
    return False


def check_runtime(cpu):
    from mirabel_voice.runtime import bundle_problem
    native = native_machine()
    assert native == cpu, f'Expected a {cpu} CPU, found {native}'
    assert sysconfig.get_platform() == 'win-amd64', sysconfig.get_platform()
    problem = bundle_problem()
    assert problem is None, problem
    return f'CPU {native}, platform.machine() {platform.machine()}, Python {sysconfig.get_platform()}'


def check_audio_libraries():
    import sounddevice
    hosts = [host['name'] for host in sounddevice.query_hostapis()]
    assert hosts, 'PortAudio found no audio systems'
    return f'{sounddevice.get_portaudio_version()[1]}, {len(sounddevice.query_devices())} devices, {", ".join(hosts)}'


def check_secure_connection():
    import truststore
    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    with urllib.request.urlopen('https://github.com', context=context, timeout=15) as response:
        return f'HTTP {response.status} through the Windows certificate store'


def check_shortcut(root, box):
    from pynput.keyboard import Controller, Key
    from mirabel_voice.hotkey import HotkeyListener
    started, stopped = threading.Event(), threading.Event()
    listener = HotkeyListener('insert', 'hold', started.set, stopped.set)
    listener.start()
    try:
        time.sleep(0.5)
        keyboard = Controller()
        keyboard.press(Key.insert)
        assert wait_until(started.is_set, root), 'The key press never reached the listener'
        keyboard.release(Key.insert)
        assert wait_until(stopped.is_set, root), 'The key release never reached the listener'
    finally:
        listener.stop()
    return 'Insert press and release reached the app listener'


def check_injection(root, box, method):
    import pyperclip
    from pynput import keyboard
    from mirabel_voice.inject import CLIPBOARD_RESTORE_SECONDS, TextInjector
    pyperclip.copy(EARLIER_CLIPBOARD)
    box.delete(0, 'end')
    take_focus(root, box)
    # Counting presses separates input that was never made from input sent elsewhere.
    presses = []
    listener = keyboard.Listener(on_press=presses.append)
    listener.start()
    time.sleep(0.5)
    injector = TextInjector(method=method)
    try:
        injector.send(TEXT)
        arrived = wait_until(lambda: box.get() == TEXT, root)
    finally:
        listener.stop()
    assert arrived, (f'The text box holds {box.get()!r}. {len(presses)} key presses were seen. '
                     f'The foreground window is {foreground_title()!r}, Tk focus is {root.focus_get()}.')
    injector.flush_restore(CLIPBOARD_RESTORE_SECONDS + 2)
    assert pyperclip.paste() == EARLIER_CLIPBOARD, 'The clipboard was not restored'
    return f'{method} put the text in a real window'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cpu', required=True, choices=sorted(MACHINES.values()))
    args = parser.parse_args()

    checks = [
        ('runtime', lambda: check_runtime(args.cpu)),
        ('audio libraries', check_audio_libraries),
        ('secure connection', check_secure_connection),
    ]
    root = tkinter.Tk()
    root.title(WINDOW_TITLE)
    root.attributes('-topmost', True)
    box = tkinter.Entry(root, width=40)
    box.pack()
    root.update()
    root.focus_force()
    box.focus_force()
    root.update()
    checks += [
        ('global shortcut', lambda: check_shortcut(root, box)),
        ('paste injection', lambda: check_injection(root, box, 'paste')),
        ('typed injection', lambda: check_injection(root, box, 'type')),
    ]

    failed = 0
    for name, check in checks:
        try:
            print(f'PASS {name}: {check()}', flush=True)
        except Exception:  # noqa: BLE001 - report every check, not only the first failure
            failed += 1
            print(f'FAIL {name}', flush=True)
            traceback.print_exc(file=sys.stdout)
    root.destroy()
    return 1 if failed else 0


if __name__ == '__main__':
    sys.exit(main())
