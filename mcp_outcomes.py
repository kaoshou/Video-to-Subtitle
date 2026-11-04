"""Compact advisory outcome metadata shared by workers and job cards."""
from collections import Counter
from pathlib import Path
import json

from safe_files import SafeDirectory
from subtitle_review import review_cues
from web_export import parse_subtitles
from web_export_model import canonical_language

REVIEW_REASONS = {'long_text': '單段文字偏長', 'reading_speed': '閱讀速度偏快',
                  'possibly_untranslated': '疑似未翻譯', 'glossary_mismatch': '專有名詞與指定譯法不符'}


def transcription_review(output, expected, evidence):
    """Read only the fixed private output; never follow a worker-supplied path."""
    output, expected = Path(output), Path(expected)
    if output != expected:
        return None
    with SafeDirectory(expected.parent) as directory, directory.open_read(expected.name) as stream:
        raw = stream.read(8 * 1024 * 1024 + 1)
    if len(raw) > 8 * 1024 * 1024:
        return None
    cues = parse_subtitles(raw.decode('utf-8-sig'), '.srt', expected.name)
    flags = review_cues(cues, evidence if isinstance(evidence, (tuple, list)) else ())
    counts = Counter(reason for reasons in flags.values() for reason in reasons)
    return {'review_count': len(flags), 'reason_counts': dict(counts),
            'review_status': 'transcription_needs_review', 'details_available': False}


def review_summary(report):
    if report is None:
        return {'review_count': None, 'reason_counts': {}, 'review_status': 'not_checked'}
    return {key: report[key] for key in ('review_count', 'reason_counts', 'review_status', 'details_available') if key in report}


def track_review(track, source):
    if track.get('review') is not None:
        return track['review']
    if track.get('review_status') == 'original':
        return source.get('review')
    return None  # A legacy translation cannot inherit its original's ASR checks.


def player_inventory(folder, kind):
    """Describe the finished package, including native preserved languages."""
    with SafeDirectory(folder) as directory:
        if kind == 'opencam':
            from opencam_integration import _read_project
            tracks = (_read_project(directory).data.get('subtitles') or {}).get('tracks', [])
        else:
            with directory.open_read('subtitles-data.js') as stream:
                raw = stream.read(32 * 1024 * 1024 + 1)
            if len(raw) > 32 * 1024 * 1024:
                raise ValueError('Player subtitle data exceeds its bound.')
            text = raw.decode('utf-8')
            prefix = 'window.EVERCAM_SUBTITLES = '
            if not text.startswith(prefix):
                raise ValueError('Unsupported player subtitle data.')
            tracks = json.loads(text[len(prefix):].strip().removesuffix(';'))['tracks']
        if len(tracks) > 32:
            raise ValueError('Player exceeds 32 subtitle languages.')
        return {canonical_language(track['language']): len(track.get('cues', [])) for track in tracks}
