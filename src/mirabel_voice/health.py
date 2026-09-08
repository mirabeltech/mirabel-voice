"""Offline checks for a produced bundle; never opens a microphone or provider connection."""
def check():
    import importlib
    for name in ('mirabel_voice.app', 'mirabel_voice.tray', 'mirabel_voice.flyout',
                 'mirabel_voice.signin', 'mirabel_voice.updater', 'sounddevice',
                 'soundfile', 'numpy', 'pynput', 'PIL.Image', 'openai', 'anthropic', 'tkinter'):
        importlib.import_module(name)
    import tkinter
    interp = tkinter.Tcl()
    try:
        interp.eval('info patchlevel')
    finally:
        # Release Tcl on its owner thread, including support export workers.
        interp.tk = None
    from .audio import check_encoder
    ok, message = check_encoder()
    if not ok:
        raise RuntimeError(message)
    return 'App imports, Tcl and audio encoder passed. No microphone or network was used.'
