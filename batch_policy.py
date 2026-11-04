"""Conservative, unbenchmarked batch estimates after model load. No import I/O.

Memory values are bytes. These activation envelopes are deliberately rounded
heuristics, not model weight sizes or promises of speed/OOM prevention. Decoding
whole audio, other processes and driver allocations can exceed the reserves.
"""
from dataclasses import dataclass

GiB = 1024 ** 3
MiB = 1024 ** 2


@dataclass(frozen=True)
class ResourceSnapshot:
    ram_available: int | None
    ram_total: int | None
    physical_cores: int | None
    vram_available: int | None = None
    vram_total: int | None = None
    note: str = ''


@dataclass(frozen=True)
class BatchDecision:
    size: int | None
    reason: str


def _positive(value):
    return type(value) is int and value > 0


def _memory_valid(available, total):
    return type(available) is int and available >= 0 and _positive(total) and available <= total


def probe_resources(device: str) -> ResourceSnapshot:
    """Lazy resource-only reads; ambiguous CUDA logical device 0 stays unknown."""
    ram = total = cores = free = gpu_total = None
    notes = []
    try:
        import psutil
        memory = psutil.virtual_memory()
        if _memory_valid(memory.available, memory.total):
            ram, total = memory.available, memory.total
        count = psutil.cpu_count(logical=False)
        cores = count if _positive(count) else None
    except Exception:
        notes.append('RAM/physical core probe unavailable')
    if device == 'cuda':
        initialized = False
        try:
            import os
            # CTranslate2 logical device 0 is not necessarily NVML physical 0.
            if any(name in os.environ for name in ('CUDA_VISIBLE_DEVICES', 'NVIDIA_VISIBLE_DEVICES', 'CUDA_DEVICE_ORDER')):
                raise ValueError('CUDA visibility mapping is unknown')
            import pynvml
            pynvml.nvmlInit()
            initialized = True
            if pynvml.nvmlDeviceGetCount() != 1:
                raise ValueError('CUDA physical mapping is ambiguous')
            handle = pynvml.nvmlDeviceGetHandleByIndex(0)
            try:
                mode, pending = pynvml.nvmlDeviceGetMigMode(handle)
                if mode or pending:
                    raise ValueError('MIG mapping is unknown')
            except pynvml.NVMLError_NotSupported:
                pass  # Consumer NVIDIA GPUs commonly do not implement MIG.
            memory = pynvml.nvmlDeviceGetMemoryInfo(handle)
            if _memory_valid(memory.free, memory.total):
                free, gpu_total = memory.free, memory.total
        except Exception:
            notes.append('CUDA VRAM unavailable or device mapping ambiguous')
        finally:
            if initialized:
                try:
                    pynvml.nvmlShutdown()
                except Exception:
                    notes.append('NVML shutdown failed')
    return ResourceSnapshot(ram, total, cores, free, gpu_total, '; '.join(notes))


def choose_batch(model_size: str, device: str, compute_type: str, resources: ResourceSnapshot) -> BatchDecision:
    if device not in ('cpu', 'cuda'):
        return BatchDecision(None, 'Native backend; batch size control unavailable')
    # Fixed host reserve: 2 GiB system + 1 GiB audio preparation. Using
    # available memory (not a total-capacity fraction) keeps policy monotone.
    host_valid = _memory_valid(resources.ram_available, resources.ram_total)
    reserve = 3*GiB
    if host_valid and resources.ram_available < reserve + 256*MiB:
        return BatchDecision(None, 'Measured RAM pressure; standard inference')
    if not host_valid or not _positive(resources.physical_cores):
        return BatchDecision(2, 'Missing/invalid RAM or physical cores; conservative estimate 2')
    # Per item MiB: tiny/base 128, small 256, medium 512, large/turbo 1024.
    # Quantized 1x, fp16/bf16 2x, fp32/unknown 4x. No precision is changed.
    unit = {'tiny': 128, 'base': 128, 'small': 256, 'medium': 512}.get(model_size, 1024)*MiB
    factor = 1 if compute_type in ('int8', 'int8_float16', 'int8_float32') else 2 if compute_type in ('float16', 'bfloat16') else 4
    unit *= factor
    budget = resources.ram_available - reserve
    if device == 'cpu':
        cap = 8 if resources.physical_cores >= 8 else 4 if resources.physical_cores >= 4 else 2
        candidates = [size for size in (2,4,8) if size <= cap and size*unit <= budget]
    else:
        if not _memory_valid(resources.vram_available, resources.vram_total):
            return BatchDecision(2, 'Missing/ambiguous CUDA VRAM; conservative estimate 2')
        gpu_budget = resources.vram_available - GiB
        cap = 16 if resources.physical_cores >= 8 else 8 if resources.physical_cores >= 4 else 2
        candidates = [size for size in (2,4,8,16)
                      if size <= cap and size*128*MiB <= budget and size*unit <= gpu_budget]
    size = max(candidates) if candidates else None
    return BatchDecision(size, f'Conservative {device} memory/core estimate: {size or "standard"}; not benchmarked')


def decision_summary(value):
    """Bound private worker IPC to public primitives; reject paths/free text."""
    if not isinstance(value, dict) or value.get('requested_mode') not in ('auto', 'manual', 'disabled'):
        return None
    size = value.get('effective_size')
    if size is not None and (type(size) is not int or not 2 <= size <= 32):
        return None
    # Reasons are generated locally, not accepted as arbitrary path-bearing text.
    reason = value.get('reason')
    allowed = ('automatic', 'manual', 'disabled', 'native', 'vad_disabled', 'unavailable', 'memory_limit', 'oom', 'quality')
    if reason not in allowed:
        return None
    result = {'requested_mode': value['requested_mode'], 'effective_size': size, 'reason': reason}
    if 'rationale' in value:
        allowed_rationale = (
            'Native backend; batch size control unavailable',
            'Measured RAM pressure; standard inference',
            'Missing/invalid RAM or physical cores; conservative estimate 2',
            'Missing/ambiguous CUDA VRAM; conservative estimate 2',
        ) + tuple(f'Conservative {device} memory/core estimate: {size}; not benchmarked'
                  for device in ('cpu', 'cuda') for size in (2,4,8,16,'standard'))
        if value['rationale'] not in allowed_rationale:
            return None
        result['rationale'] = value['rationale']
    return result
