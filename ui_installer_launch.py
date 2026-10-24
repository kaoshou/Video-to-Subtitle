"""Ask the existing desktop Explorer to launch the installed application.

Follows Microsoft's Windows-classic-samples ExecInExplorer example. This is a
launch-context workaround, not a claim that Inno's RedirectionGuard is inherited.
No direct-process fallback is allowed: callers can offer the installed shortcut.

ABI references: microsoft/win32metadata, generation/WinSDK/RecompiledIdlHeaders/
um/{ExDisp.h,ShObjIdl_core.h,ShlDisp.h}; SDK IServiceProvider::QueryService.
"""
import ctypes
import ntpath
import sys
import uuid


# Windows LONG/HRESULT remain 32-bit even on LLP64. Do not use host c_long.
HRESULT = ctypes.c_int32
LONG = ctypes.c_int32
ULONG = ctypes.c_uint32
PVOID = ctypes.c_void_p
PPVOID = ctypes.POINTER(PVOID)


class GUID(ctypes.Structure):
    _fields_ = [('data1', ctypes.c_uint32), ('data2', ctypes.c_uint16),
                ('data3', ctypes.c_uint16), ('data4', ctypes.c_ubyte * 8)]

    @classmethod
    def parse(cls, value):
        return cls.from_buffer_copy(uuid.UUID(value).bytes_le)


class _Record(ctypes.Structure):
    _fields_ = [('record', PVOID), ('info', PVOID)]


class _VariantValue(ctypes.Union):
    _fields_ = [('lVal', LONG), ('bstrVal', PVOID), ('llVal', ctypes.c_int64),
                ('record', _Record)]


class VARIANT(ctypes.Structure):
    # BRECORD's two pointers make the union 16 bytes on Win64 (VARIANT = 24).
    _fields_ = [('vt', ctypes.c_uint16), ('reserved1', ctypes.c_uint16),
                ('reserved2', ctypes.c_uint16), ('reserved3', ctypes.c_uint16),
                ('value', _VariantValue)]


PGUID = ctypes.POINTER(GUID)
PVARIANT = ctypes.POINTER(VARIANT)
_SHELL_WINDOWS = GUID.parse('9BA05972-F6A8-11CF-A442-00A0C90A8F39')
_ISHELL_WINDOWS = GUID.parse('85CB6900-4D95-11CF-960C-0080C7F4EE85')
_ISERVICE_PROVIDER = GUID.parse('6D5140C1-7436-11CE-8034-00AA006009FA')
_TOP_LEVEL_BROWSER = GUID.parse('4C96BE40-915C-11CF-99D3-00AA004AE837')
_ISHELL_BROWSER = GUID.parse('000214E2-0000-0000-C000-000000000046')
_IDISPATCH = GUID.parse('00020400-0000-0000-C000-000000000046')
_IFOLDER_VIEW_DUAL = GUID.parse('E7A1AF80-4D96-11CF-960C-0080C7F4EE85')
_ISHELL_DISPATCH2 = GUID.parse('A4C6892C-3BA9-11D2-9DEA-00C04FB16162')
_FALLBACK = 'Please open Video to Subtitle from the Start menu or desktop shortcut.'


def _load_libraries():
    ole = ctypes.WinDLL('ole32', use_last_error=True)
    automation = ctypes.WinDLL('oleaut32', use_last_error=True)
    ole.CoInitializeEx.argtypes = [PVOID, ULONG]
    ole.CoInitializeEx.restype = HRESULT
    ole.CoUninitialize.argtypes = []
    ole.CoUninitialize.restype = None
    ole.CoCreateInstance.argtypes = [PGUID, PVOID, ULONG, PGUID, PPVOID]
    ole.CoCreateInstance.restype = HRESULT
    automation.SysAllocString.argtypes = [ctypes.c_wchar_p]
    automation.SysAllocString.restype = PVOID
    automation.SysFreeString.argtypes = [PVOID]
    automation.SysFreeString.restype = None
    return ole, automation


def _method(pointer, slot, result_type, *argument_types):
    table = ctypes.cast(pointer, ctypes.POINTER(ctypes.POINTER(PVOID))).contents
    return ctypes.WINFUNCTYPE(result_type, PVOID, *argument_types)(table[slot])


def _check(result, operation, exact_success=False):
    signed = HRESULT(result).value
    if signed < 0 or (exact_success and signed != 0):
        raise RuntimeError(f'{operation} failed (HRESULT 0x{signed & 0xffffffff:08X}).')


def _launch(executable, working_directory):
    ole, automation = _load_libraries()
    initialized = False
    pointers = []
    strings = []

    def output_call(operation, invoke, exact_success=False):
        output = PVOID()
        result = invoke(ctypes.byref(output))
        # Retain even an unexpected non-null failure output for cleanup.
        if output.value:
            pointers.append(output)
        _check(result, operation, exact_success)
        if not output.value:
            raise RuntimeError(f'{operation} returned no desktop interface.')
        return output

    def query(pointer, iid, operation):
        return output_call(operation, lambda output:
                           _method(pointer, 0, HRESULT, PGUID, PPVOID)(
                               pointer, ctypes.byref(iid), output))

    def bstr(value):
        allocated = automation.SysAllocString(value)
        if not allocated:
            raise RuntimeError('Cannot allocate desktop launch arguments.')
        strings.append(allocated)
        return allocated

    try:
        _check(ole.CoInitializeEx(None, 2), 'Initialize desktop COM')  # STA
        initialized = True  # S_OK and S_FALSE both require CoUninitialize.
        windows = output_call('Find desktop shell', lambda output:
                              ole.CoCreateInstance(ctypes.byref(_SHELL_WINDOWS), None,
                                                   4, ctypes.byref(_ISHELL_WINDOWS), output))
        empty, hwnd = VARIANT(), LONG()
        desktop = output_call('Find desktop window', lambda output:
                              _method(windows, 15, HRESULT, PVARIANT, PVARIANT,
                                      LONG, ctypes.POINTER(LONG), LONG, PPVOID)(
                                          windows, ctypes.byref(empty), ctypes.byref(empty),
                                          8, ctypes.byref(hwnd), 1, output), True)
        provider = query(desktop, _ISERVICE_PROVIDER, 'Get desktop service provider')
        browser = output_call('Get desktop browser', lambda output:
                              _method(provider, 3, HRESULT, PGUID, PGUID, PPVOID)(
                                  provider, ctypes.byref(_TOP_LEVEL_BROWSER),
                                  ctypes.byref(_ISHELL_BROWSER), output))
        view = output_call('Get desktop view', lambda output:
                           _method(browser, 15, HRESULT, PPVOID)(browser, output))
        background = output_call('Get desktop background', lambda output:
                                 _method(view, 15, HRESULT, ULONG, PGUID, PPVOID)(
                                     view, 0, ctypes.byref(_IDISPATCH), output))
        folder = query(background, _IFOLDER_VIEW_DUAL, 'Get desktop automation view')
        application = output_call('Get desktop application', lambda output:
                                  _method(folder, 7, HRESULT, PPVOID)(folder, output))
        dispatch = query(application, _ISHELL_DISPATCH2, 'Get desktop launch interface')
        file = bstr(executable)
        directory, operation, show = VARIANT(), VARIANT(), VARIANT()
        directory.vt, directory.value.bstrVal = 8, bstr(working_directory)
        operation.vt, operation.value.bstrVal = 8, bstr('open')
        show.vt, show.value.lVal = 3, 1
        _check(_method(dispatch, 31, HRESULT, PVOID, VARIANT, VARIANT, VARIANT, VARIANT)(
            dispatch, file, VARIANT(), directory, operation, show), 'Launch through desktop')
    finally:
        for value in reversed(strings):
            automation.SysFreeString(value)
        for pointer in reversed(pointers):
            _method(pointer, 2, ULONG)(pointer)
        if initialized:
            ole.CoUninitialize()


def launch_via_desktop(executable: str, working_directory: str) -> None:
    """Submit one EXE to desktop Explorer, with no arguments or direct fallback.

    Successful submission does not certify that the new application's startup
    completed. Paths remain separate BSTR values; they are never a command line.
    """
    if sys.platform != 'win32':
        raise RuntimeError(f'Desktop launch requires Windows. {_FALLBACK}')
    for value in (executable, working_directory):
        drive, tail = ntpath.splitdrive(value) if isinstance(value, str) else ('', '')
        if not drive or not tail.startswith(('\\', '/')) or '\0' in value:
            raise RuntimeError(f'Desktop launch requires fully qualified paths. {_FALLBACK}')
    try:
        _launch(executable, working_directory)
    except Exception as error:
        raise RuntimeError(f'Could not launch through desktop Explorer: {error} {_FALLBACK}') from error
