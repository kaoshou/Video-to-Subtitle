"""Desktop COM boundary tests; these do not simulate a successful Windows launch."""
import ctypes
import importlib.util
from pathlib import Path
import unittest
import uuid
from unittest.mock import patch


class InstallerLaunchTests(unittest.TestCase):
    def load_module(self):
        path = Path(__file__).resolve().parents[1] / 'ui_installer_launch.py'
        self.assertTrue(path.is_file(), 'Desktop Explorer launch implementation is missing')
        spec = importlib.util.spec_from_file_location('installer_launch_under_test', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_non_windows_rejected_before_native_calls(self):
        module = self.load_module()
        with patch.object(module.sys, 'platform', 'darwin'):
            with self.assertRaisesRegex(RuntimeError, 'Windows'):
                module.launch_via_desktop(r'C:\App\app.exe', r'C:\App')

    def test_relative_or_embedded_nul_paths_rejected(self):
        module = self.load_module()
        for exe, directory in [('app.exe', r'C:\App'),
                               (r'C:\App\app.exe', 'C:App'),
                               ('C:\\App\\app.exe\0extra', r'C:\App')]:
            with self.subTest(exe=exe, directory=directory), \
                    patch.object(module.sys, 'platform', 'win32'):
                with self.assertRaisesRegex(RuntimeError, 'fully qualified'):
                    module.launch_via_desktop(exe, directory)

    def test_windows_abi_has_fixed_width_long_and_full_variant(self):
        module = self.load_module()
        self.assertEqual(ctypes.sizeof(module.HRESULT), 4)
        self.assertEqual(ctypes.sizeof(module.LONG), 4)
        self.assertEqual(ctypes.sizeof(module.GUID), 16)
        self.assertEqual(ctypes.sizeof(module.VARIANT),
                         24 if ctypes.sizeof(ctypes.c_void_p) == 8 else 16)
        self.assertEqual(module.VARIANT.value.offset, 8)

    def test_vtable_call_preserves_this_pointer_and_signed_hresult(self):
        module = self.load_module()
        callback_type = getattr(ctypes, 'WINFUNCTYPE', ctypes.CFUNCTYPE)
        seen = []
        @callback_type(ctypes.c_int32, ctypes.c_void_p, ctypes.c_int32)
        def callback(this, value):
            seen.append((this, value))
            return -2147467259
        table = (ctypes.c_void_p * 4)()
        table[3] = ctypes.cast(callback, ctypes.c_void_p).value
        instance = (ctypes.c_void_p * 1)(ctypes.addressof(table))
        pointer = ctypes.c_void_p(ctypes.addressof(instance))
        # On macOS use the native host calling convention only for this in-memory
        # callback. Real Windows COM always uses ctypes.WINFUNCTYPE/stdcall.
        with patch.object(ctypes, 'WINFUNCTYPE', callback_type, create=True):
            result = module._method(pointer, 3, module.HRESULT, module.LONG)(pointer, 7)
        self.assertEqual(result, -2147467259)
        self.assertEqual(seen, [(pointer.value, 7)])

    def exercise_native_boundary(self, failure=None, initialize_result=0):
        module = self.load_module()
        released, freed, calls = [], [], []
        strings = {}
        next_pointer = iter(range(101, 120))
        class Ole:
            def CoInitializeEx(self, reserved, mode):
                self.initialized = (reserved, mode)
                return -2147417850 if failure == 'initialize' else initialize_result
            def CoUninitialize(self):
                calls.append('uninitialize')
            def CoCreateInstance(self, clsid, outer, context, iid, output):
                calls.append('create')
                self.context = context
                self.clsid = ctypes.string_at(clsid, 16)
                self.iid = ctypes.string_at(iid, 16)
                if failure == 'create':
                    return -2147467259
                ctypes.cast(output, ctypes.POINTER(ctypes.c_void_p))[0] = 101
                return 0
        class Automation:
            def SysAllocString(self, value):
                if failure == 'allocate' and strings:
                    return 0
                buffer = ctypes.create_unicode_buffer(value)
                pointer = ctypes.addressof(buffer)
                strings[pointer] = buffer
                return pointer
            def SysFreeString(self, value):
                freed.append(value)
        ole = Ole()
        automation = Automation()
        acquired = [101]
        next(next_pointer)
        def method(pointer, slot, result_type, *argument_types):
            pointer = pointer.value
            def invoke(*arguments):
                self.assertEqual(arguments[0].value, pointer)
                if slot == 2:
                    released.append(pointer)
                    return 0
                stage = {(101, 15): 'find', (102, 0): 'provider',
                         (103, 3): 'browser', (104, 15): 'view',
                         (105, 15): 'background', (106, 0): 'folder',
                         (107, 7): 'application', (108, 0): 'dispatch',
                         (109, 31): 'execute'}[(pointer, slot)]
                calls.append(stage)
                query_iids = {
                    'provider': '6D5140C1-7436-11CE-8034-00AA006009FA',
                    'folder': 'E7A1AF80-4D96-11CF-960C-0080C7F4EE85',
                    'dispatch': 'A4C6892C-3BA9-11D2-9DEA-00C04FB16162',
                }
                if stage in query_iids:
                    self.assertEqual(ctypes.string_at(arguments[1], 16),
                                     uuid.UUID(query_iids[stage]).bytes_le)
                if stage == 'browser':
                    self.assertEqual(ctypes.string_at(arguments[1], 16),
                                     uuid.UUID('4C96BE40-915C-11CF-99D3-00AA004AE837').bytes_le)
                    self.assertEqual(ctypes.string_at(arguments[2], 16),
                                     uuid.UUID('000214E2-0000-0000-C000-000000000046').bytes_le)
                if stage == 'find':
                    self.assertEqual(arguments[3], 8)  # SWC_DESKTOP
                    self.assertEqual(arguments[5], 1)  # SWFO_NEEDDISPATCH
                    self.assertEqual(argument_types[3], ctypes.POINTER(module.LONG))
                    self.assertEqual(ctypes.cast(arguments[1], ctypes.POINTER(module.VARIANT))[0].vt, 0)
                if stage == 'background':
                    self.assertEqual(arguments[1], 0)  # SVGIO_BACKGROUND
                if stage == 'execute':
                    self.assertEqual(slot, 31)
                    self.assertEqual(argument_types, (ctypes.c_void_p, module.VARIANT,
                                     module.VARIANT, module.VARIANT, module.VARIANT))
                    self.assertEqual(strings[arguments[1]].value, r'C:\測試 & App\app.exe')
                    self.assertEqual(arguments[2].vt, 0)  # no arguments, no marker
                    self.assertEqual(arguments[3].vt, 8)
                    self.assertEqual(strings[arguments[3].value.bstrVal].value, r'C:\測試 & App')
                    self.assertEqual(strings[arguments[4].value.bstrVal].value, 'open')
                    self.assertEqual(arguments[5].vt, 3)
                    self.assertEqual(arguments[5].value.lVal, 1)
                if failure == stage:
                    return 1 if stage == 'find' else -2147467259
                if failure == stage + '-null':
                    return 0
                if stage != 'execute':
                    output = next(next_pointer)
                    ctypes.cast(arguments[-1], ctypes.POINTER(ctypes.c_void_p))[0] = output
                    acquired.append(output)
                return 0
            return invoke
        with patch.object(module.sys, 'platform', 'win32'), \
                patch.object(module, '_load_libraries', return_value=(ole, automation)), \
                patch.object(module, '_method', side_effect=method):
            if failure:
                with self.assertRaisesRegex(RuntimeError, 'Start menu|desktop shortcut'):
                    module.launch_via_desktop(r'C:\測試 & App\app.exe', r'C:\測試 & App')
            else:
                module.launch_via_desktop(r'C:\測試 & App\app.exe', r'C:\測試 & App')
        self.assertEqual(released, list(reversed(acquired)) if failure != 'initialize' and failure != 'create' else [])
        self.assertCountEqual(freed, strings)
        self.assertEqual(calls.count('uninitialize'), 0 if failure == 'initialize' else 1)
        if not failure:
            self.assertEqual(ole.context, 4)  # local-server desktop shell
            self.assertEqual(ole.clsid, uuid.UUID('9BA05972-F6A8-11CF-A442-00A0C90A8F39').bytes_le)
            self.assertEqual(ole.iid, uuid.UUID('85CB6900-4D95-11CF-960C-0080C7F4EE85').bytes_le)
            self.assertIn('execute', calls)

    def test_launch_uses_desktop_view_and_structured_shell_arguments(self):
        self.exercise_native_boundary()

    def test_failure_at_every_boundary_releases_resources_without_direct_fallback(self):
        for stage in ['initialize', 'create', 'find', 'provider', 'browser', 'view',
                      'background', 'folder', 'application', 'dispatch', 'allocate', 'execute']:
            with self.subTest(stage=stage):
                self.exercise_native_boundary(stage)

    def test_null_desktop_interfaces_are_rejected_and_released(self):
        for stage in ['find', 'provider', 'browser', 'view', 'background', 'folder',
                      'application', 'dispatch']:
            with self.subTest(stage=stage):
                self.exercise_native_boundary(stage + '-null')

    def test_preinitialized_sta_is_balanced_with_uninitialize(self):
        self.exercise_native_boundary(initialize_result=1)  # CoInitializeEx S_FALSE

    def test_native_argument_failure_has_manual_launch_guidance(self):
        module = self.load_module()
        with patch.object(module.sys, 'platform', 'win32'), \
                patch.object(module, '_load_libraries', side_effect=ctypes.ArgumentError('ABI')):
            with self.assertRaisesRegex(RuntimeError, 'Start menu|desktop shortcut'):
                module.launch_via_desktop(r'C:\App\app.exe', r'C:\App')


if __name__ == '__main__':
    unittest.main()
