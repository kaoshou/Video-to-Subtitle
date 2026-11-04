"""Literal binary-byte boundaries; only the OS/driver boundary is substituted."""
import sys
import subprocess
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from batch_policy import ResourceSnapshot, choose_batch, probe_resources

G = 1073741824


class BatchPolicyTests(unittest.TestCase):
    def test_policy_and_thin_import_do_not_import_resource_bindings(self):
        result = subprocess.run([sys.executable, '-c',
            "import sys; import mcp_transport, mcp_entry, mcp_launcher, mcp_contracts; "
            "assert 'batch_policy' not in sys.modules; import batch_policy; "
            "assert all(x not in sys.modules for x in ('psutil','pynvml','torch','transcriber','mcp_service'))"],
            capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
    def test_cpu_available_memory_model_precision_and_core_boundaries(self):
        # small/int8: reserve 3 GiB, 256 MiB/item; eight needs 5 GiB.
        fixtures = [
            ('small', 'int8', 5*G-1, 8*G, 8, 4),
            ('small', 'int8', 5*G, 8*G, 8, 8),
            ('small', 'int8', 4*G, 16*G, 8, 4),
            ('small', 'int8', 8*G, 16*G, 8, 8),
            ('small', 'int8', 8*G, 16*G, 4, 4),
            ('small', 'int8', 8*G, 16*G, 2, 2),
            ('medium', 'int8', 5*G, 8*G, 8, 4),
            ('small', 'float32', 5*G, 8*G, 8, 2),
            ('small', 'int8', 3*G, 8*G, 8, None),
        ]
        for model, precision, available, total, cores, expected in fixtures:
            with self.subTest(fixture=(model, precision, available, cores)):
                decision = choose_batch(model, 'cpu', precision, ResourceSnapshot(available, total, cores))
                self.assertEqual(decision.size, expected)
                self.assertTrue(decision.reason)

    def test_cuda_vram_boundary_and_caps(self):
        # small/fp16: 512 MiB/item plus 1 GiB VRAM reserve on an 8 GiB GPU.
        for free, total, expected in [(5*G-1, 8*G, 4), (5*G, 8*G, 8),
                                       (12*G, 16*G, 16), (64*G, 64*G, 16)]:
            self.assertEqual(choose_batch('small', 'cuda', 'float16',
                ResourceSnapshot(16*G, 32*G, 16, free, total)).size, expected)

    def test_total_capacity_does_not_reverse_available_memory_monotonicity(self):
        for total in (8*G,16*G,32*G,64*G):
            self.assertEqual(choose_batch('small','cpu','int8',ResourceSnapshot(5*G,total,8)).size,8)
            self.assertEqual(choose_batch('small','cuda','float16',ResourceSnapshot(16*G,32*G,8,5*G,total)).size,8)

    def test_safe_metadata_rejects_private_text_invalid_sizes_and_extra_fields(self):
        from batch_policy import decision_summary
        self.assertIsNone(decision_summary({'requested_mode':'auto','effective_size':True,'reason':'automatic'}))
        self.assertIsNone(decision_summary({'requested_mode':'auto','effective_size':8,'reason':'/private/model'}))
        self.assertEqual(decision_summary({'requested_mode':'auto','effective_size':8,'reason':'automatic','path':'/private/model'}),
                         {'requested_mode':'auto','effective_size':8,'reason':'automatic'})
        self.assertIsNone(decision_summary({'requested_mode':'auto','effective_size':8,'reason':'automatic','rationale':'/private/model'}))
        self.assertEqual(decision_summary({'requested_mode':'auto','effective_size':8,'reason':'automatic',
            'rationale':'Conservative cuda memory/core estimate: 8; not benchmarked'})['rationale'],
            'Conservative cuda memory/core estimate: 8; not benchmarked')

    def test_missing_invalid_native_and_severe_ram(self):
        for resources in [ResourceSnapshot(None, None, None), ResourceSnapshot(-1, 8*G, 8),
                          ResourceSnapshot(9*G, 8*G, 8), ResourceSnapshot(8*G, 16*G, None)]:
            self.assertEqual(choose_batch('small', 'cpu', 'int8', resources).size, 2)
        self.assertEqual(choose_batch('small', 'cuda', 'float16', ResourceSnapshot(G, 8*G, 8)).size, None)
        self.assertEqual(choose_batch('small', 'cuda', 'float16', ResourceSnapshot(8*G,16*G,8)).size, 2)
        for device in ('mlx', 'mps'):
            self.assertIsNone(choose_batch('small', device, 'int8', ResourceSnapshot(None,None,None)).size)

    def test_probe_failure_is_nonfatal_and_cpu_never_imports_nvml(self):
        with patch.dict(sys.modules, {'psutil': None, 'pynvml': None}):
            result = probe_resources('cpu')
        self.assertIsNone(result.ram_available)
        self.assertTrue(result.note)

    def test_nvml_pairing_identity_visibility_and_consumer_mig_unsupported(self):
        calls = []
        class Unsupported(Exception): pass
        def mig(handle): raise Unsupported()
        nvml = SimpleNamespace(nvmlInit=lambda: calls.append('init'),
            nvmlShutdown=lambda: calls.append('shutdown'), nvmlDeviceGetCount=lambda: 1,
            nvmlDeviceGetHandleByIndex=lambda index: index,
            nvmlDeviceGetMigMode=mig, NVMLError_NotSupported=Unsupported,
            nvmlDeviceGetMemoryInfo=lambda handle: SimpleNamespace(free=5*G,total=8*G))
        psutil = SimpleNamespace(virtual_memory=lambda: SimpleNamespace(available=8*G,total=16*G),
                                 cpu_count=lambda logical: 8)
        with patch.dict(sys.modules, {'psutil': psutil, 'pynvml': nvml}), patch.dict('os.environ', {}, clear=True):
            self.assertEqual(probe_resources('cuda').vram_available, 5*G)
            self.assertEqual(calls, ['init', 'shutdown'])
            nvml.nvmlDeviceGetCount = lambda: 2
            self.assertIsNone(probe_resources('cuda').vram_available)
            nvml.nvmlDeviceGetCount = lambda: 1
            with patch.dict('os.environ', {'CUDA_VISIBLE_DEVICES': '0'}):
                self.assertIsNone(probe_resources('cuda').vram_available)
            nvml.nvmlDeviceGetMigMode = lambda handle: (1,1)
            self.assertIsNone(probe_resources('cuda').vram_available)
            nvml.nvmlDeviceGetMigMode = lambda handle: (0,0)
            nvml.nvmlDeviceGetMemoryInfo = lambda handle: (_ for _ in ()).throw(RuntimeError('driver'))
            self.assertIsNone(probe_resources('cuda').vram_available)
        self.assertEqual(calls.count('init'), calls.count('shutdown'))
