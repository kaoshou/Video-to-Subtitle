"""Bounded translation data operations. Timings always come from the source."""
import re
import secrets
import unicodedata

from mcp_state import MCPError


def _normalized(text):
    return ' '.join(unicodedata.normalize('NFKC', text).casefold().split())


def _contains(text, term):
    text, term = _normalized(text), _normalized(term)
    if re.fullmatch(r'[a-z0-9_ +.#-]+', term):
        return re.search(r'(?<!\w)' + re.escape(term) + r'(?!\w)', text) is not None
    return term in text


def quality_report(cues, translations, source_language, target_language, glossary_terms, *, cursor=0, limit=200):
    """Conservative editorial hints, not a semantic translation verdict.

    All cues contribute to totals; only a bounded page of warning references
    is returned. Structural completeness is mandatory even for advisory use.
    """
    if set(translations) != {cue['cue_id'] for cue in cues}:
        raise MCPError('TRANSLATION_INCOMPLETE', 'Every source cue requires translation text.')
    items, reason_counts, count = [], {}, 0
    different = (source_language or 'und').split('-')[0] != (target_language or 'und').split('-')[0]
    known_source = source_language not in (None, '', 'und')
    for index, cue in enumerate(cues):
        text = translations[cue['cue_id']]
        if not isinstance(text, str) or not text.strip():
            raise MCPError('TRANSLATION_INCOMPLETE', 'Every source cue requires translation text.')
        reasons = []
        length = len(re.sub(r'\s', '', text))
        duration = cue['end'] - cue['start']
        if length > 120:
            reasons.append('long_text')
        if duration > 0 and length / duration > 25:
            reasons.append('reading_speed')
        original = _normalized(cue['text'])
        sentence = len(original.split()) >= 4 or bool(re.search(r'[。！？]', original))
        if known_source and different and len(original) >= 20 and sentence and original == _normalized(text):
            reasons.append('possibly_untranslated')
        if any(_contains(cue['text'], term['source']) and not _contains(text, term['target']) for term in glossary_terms):
            reasons.append('glossary_mismatch')
        if not reasons:
            continue
        if cursor <= count < cursor + min(max(limit, 1), 200):
            items.append({'cue_id': cue['cue_id'], 'cue_number': index + 1,
                          'start': cue['start'], 'end': cue['end'], 'reasons': reasons})
        count += 1
        for reason in reasons:
            reason_counts[reason] = reason_counts.get(reason, 0) + 1
    next_cursor = cursor + len(items)
    return {'review_count': count, 'reason_counts': reason_counts, 'items': items,
            'truncated': count > len(items), 'next_cursor': next_cursor if next_cursor < count else None,
            'review_status': 'ai_translation_needs_review', 'semantic_accuracy_verified': False}


def batches(cues):
    result, current, characters = [], [], 0
    for cue in cues:
        size = len(cue['text'])
        if size > 8000:
            raise MCPError('INVALID_SUBTITLE', 'A source cue exceeds the 8,000 character batch limit.')
        if current and (len(current) == 50 or characters + size > 8000):
            result.append({'batch_id': secrets.token_hex(16), 'cue_ids': current})
            current, characters = [], 0
        current.append(cue['cue_id'])
        characters += size
    if current:
        result.append({'batch_id': secrets.token_hex(16), 'cue_ids': current})
    return result


def validate_batch(batch, translations):
    if not isinstance(translations, list) or not 1 <= len(translations) <= 50:
        raise MCPError('INVALID_TRANSLATION', 'Expected one complete bounded translation batch.')
    result, size = {}, 0
    for entry in translations:
        if not isinstance(entry, dict) or set(entry) != {'cue_id', 'text'}:
            raise MCPError('INVALID_TRANSLATION', 'Only cue_id and plain text are accepted.')
        cue_id, text = entry['cue_id'], entry['text']
        if not isinstance(cue_id, str) or cue_id in result:
            raise MCPError('INVALID_TRANSLATION', 'Duplicate or invalid cue ID.')
        if (not isinstance(text, str) or not text.strip() or len(text) > 8000 or
                '\r' in text or '\x00' in text or '\n\n' in text or '-->' in text or
                re.search(r'<[!/]?[A-Za-z][^>]*>', text)):
            raise MCPError('INVALID_TRANSLATION', 'Translation must be nonempty bounded plain subtitle text.')
        size += len(text)
        result[cue_id] = text
    if size > 8000 or set(result) != set(batch['cue_ids']):
        raise MCPError('INVALID_TRANSLATION', 'The batch must contain exactly its cue IDs and at most 8,000 characters.')
    return result


def render_srt(cues, translations=None):
    def stamp(seconds):
        milliseconds = round(seconds * 1000)
        hours, rest = divmod(milliseconds, 3600000)
        minutes, rest = divmod(rest, 60000)
        seconds, milliseconds = divmod(rest, 1000)
        return f'{hours:02}:{minutes:02}:{seconds:02},{milliseconds:03}'
    blocks = []
    for number, cue in enumerate(cues, 1):
        text = cue['text'] if translations is None else translations.get(cue['cue_id'])
        if not isinstance(text, str) or not text.strip():
            raise MCPError('TRANSLATION_INCOMPLETE', 'Every source cue requires translation text.')
        blocks.append(f"{number}\n{stamp(cue['start'])} --> {stamp(cue['end'])}\n{text}")
    return '\n\n'.join(blocks) + '\n'
