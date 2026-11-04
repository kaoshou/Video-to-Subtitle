"""Read-only MCP model inventory using the loader's offline cache inspection."""
import os

from mcp_contracts import _SETTINGS


def backend_for(device):
    return 'mlx-whisper' if device in ('mlx', 'mps') else 'faster-whisper'


def _direct_folder(cache_dir):
    if not cache_dir:
        return False
    # Match inspect_model_cache's direct-model detection without scanning a
    # potentially large cache directory or swallowing access errors.
    for name in ('config.json', 'model.bin', 'weights.npz', 'model.safetensors', 'weights.safetensors'):
        try:
            os.stat(os.path.join(cache_dir, name))
            return True
        except FileNotFoundError:
            pass
    return False


def model_catalog(settings):
    from transcriber import inspect_model_cache, effective_model_cache_root
    cache_dir = settings.get('cache_dir')
    if cache_dir:
        cache_dir = effective_model_cache_root(cache_dir)
    try:
        direct = _direct_folder(cache_dir)
    except OSError:
        direct = None
    rows = []
    for model in _SETTINGS['model']['enum']:
        backends = {}
        for backend, device in (('faster-whisper', 'cpu'), ('mlx-whisper', 'mlx')):
            if direct is None:
                status = 'unavailable'
            elif direct and model != settings['model']:
                # An anonymous direct folder can pass the loader checks for
                # several sizes. It is not evidence that all were downloaded.
                status = 'unknown'
            else:
                status = inspect_model_cache(model, cache_dir, device).state
            backends[backend] = {'status': status,
                'downloaded': None if status in ('unavailable', 'unknown') else status == 'ready'}
        rows.append({'model': model, 'backends': backends})
    return rows
