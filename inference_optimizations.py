"""Per-job audio preparation only; no persistent audio or inference changes."""
import tempfile
from pathlib import Path

from safe_files import ExportCancelled


def as_mlx_audio(audio):
    """Avoid retaining the NumPy waveform in the native transcribe frame.

    Use public MLX operations only; sample values and precision stay unchanged.
    Real mlx-whisper already requires mlx.core; the import fallback also allows
    optional recognizer adapters that do not expose that dependency.
    """
    try:
        import mlx.core as mx
    except ImportError:
        return audio
    prepared = mx.array(audio)
    mx.eval(prepared)
    return prepared


class PreparedAudio:
    def __init__(self, path, log=None, cancel_check=None, memory_limit=64 * 1024 * 1024):
        self.path = path
        self.log = log or (lambda message: None)
        self.cancel_check = cancel_check or (lambda: False)
        self.memory_limit = memory_limit
        self.audio = None
        self.directory = None
        self.attempted = False

    def __enter__(self):
        return self

    def get(self):
        if self.cancel_check():
            raise ExportCancelled('作業已取消。')
        if self.attempted:
            return self.audio if self.audio is not None else self.path
        self.attempted = True
        try:
            from faster_whisper.audio import decode_audio
            import numpy as np
            self.log('準備可重用的音訊；重試時不重複解碼。')
            audio = decode_audio(self.path)
            if self.cancel_check():
                raise ExportCancelled('作業已取消。')
            if audio.nbytes > self.memory_limit:
                self.directory = tempfile.TemporaryDirectory(prefix='vts-audio-')
                cached = Path(self.directory.name) / 'audio.npy'
                np.save(cached, audio, allow_pickle=False)
                self.audio = np.load(cached, mmap_mode='r', allow_pickle=False)
            else:
                self.audio = audio
            if self.cancel_check():
                raise ExportCancelled('作業已取消。')
        except ExportCancelled:
            raise
        except (ImportError, OSError, RuntimeError, MemoryError, ValueError):
            # Preparation is optional: retain the recognizer's established path
            # decoder/error handling if it is unavailable or temporary space is low.
            self.log('無法建立音訊暫存，沿用原有解碼流程。')
        return self.audio if self.audio is not None else self.path

    def __exit__(self, *args):
        mapping = getattr(self.audio, '_mmap', None)
        self.audio = None
        if mapping is not None:
            mapping.close()
        if self.directory is not None:
            self.directory.cleanup()
            self.directory = None
