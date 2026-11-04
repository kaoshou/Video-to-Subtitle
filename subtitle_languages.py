"""Language metadata shared by transcription and local player export."""
import re
from pathlib import Path
from web_export_model import canonical_language


def output_language(detected=None, *, task='transcribe', force_zh_tw=False):
    if task == 'translate':
        return 'en'
    if force_zh_tw:
        return 'zh-TW'
    try:
        return canonical_language((detected or 'und').replace('_', '-'))
    except (ValueError, AttributeError):
        return 'und'


def subtitle_language(path, video=None):
    stem = Path(path).stem
    if video is not None:
        prefix = Path(video).stem + '.'
        if not stem.startswith(prefix):
            return 'und'
        code = stem[len(prefix):]
    else:
        code = stem.rsplit('.', 1)[-1] if '.' in stem else 'und'
    code = re.sub(r'_\d+$', '', code)
    try:
        return canonical_language(code)
    except ValueError:
        return 'und'


def matching_media(subtitle):
    """Exact legacy match first; then strip only a valid language suffix."""
    path = Path(subtitle)
    stems = [path.stem]
    if '.' in path.stem:
        suffix = path.stem.rsplit('.', 1)[-1]
        try:
            canonical_language(re.sub(r'_\d+$', '', suffix))
            stems.append(path.stem.rsplit('.', 1)[0])
        except ValueError:
            pass
    for stem in stems:
        for extension in ('.mp4', '.mkv', '.mov', '.avi', '.webm', '.flv', '.m4v', '.ts', '.mp3', '.wav'):
            candidate = path.parent / (stem + extension)
            if candidate.is_file():
                return candidate
    return None
