"""Compact advisory outcome metadata shared by workers and job cards."""
from collections import Counter
from pathlib import Path

from safe_files import SafeDirectory
from subtitle_review import review_cues
from web_export import parse_subtitles

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
