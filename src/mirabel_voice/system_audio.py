"""Read the Windows default capture endpoint identity without opening a microphone."""
import sys


def default_input_id():
    if sys.platform != 'win32':
        return None
    import ctypes as c
    import uuid
    class GUID(c.Structure):
        _fields_ = [('data', c.c_ubyte * 16)]
    def guid(value):
        return GUID.from_buffer_copy(uuid.UUID(value).bytes_le)
    ole = c.OleDLL('ole32')
    ole.CoInitializeEx.argtypes = [c.c_void_p, c.c_ulong]
    ole.CoCreateInstance.argtypes = [c.POINTER(GUID), c.c_void_p, c.c_ulong, c.POINTER(GUID), c.POINTER(c.c_void_p)]
    ole.CoTaskMemFree.argtypes = [c.c_void_p]
    initialized = False
    enumerator, device, identifier = c.c_void_p(), c.c_void_p(), c.c_void_p()
    def method(pointer, index, *args):
        table = c.cast(pointer, c.POINTER(c.POINTER(c.c_void_p))).contents
        return c.WINFUNCTYPE(c.c_long, c.c_void_p, *args)(table[index])
    try:
        ole.CoInitializeEx(None, 0)
        initialized = True
        ole.CoCreateInstance(c.byref(guid('BCDE0395-E52F-467C-8E3D-C4579291692E')), None, 1,
                             c.byref(guid('A95664D2-9614-4F35-A746-DE8DB63617E6')), c.byref(enumerator))
        # eCapture=1, eConsole=0, IMMDeviceEnumerator::GetDefaultAudioEndpoint.
        if method(enumerator, 4, c.c_int, c.c_int, c.POINTER(c.c_void_p))(enumerator, 1, 0, c.byref(device)) < 0:
            return None
        if method(device, 5, c.POINTER(c.c_void_p))(device, c.byref(identifier)) < 0:
            return None
        return c.wstring_at(identifier)
    except OSError:
        return None
    finally:
        if identifier.value:
            ole.CoTaskMemFree(identifier)
        for pointer in (device, enumerator):
            if pointer.value:
                method(pointer, 2)(pointer)
        if initialized:
            ole.CoUninitialize()
