"""Advisory diagnostics only: never change recognition, text or timestamps."""
import math
import re


def _field(value, name, default=None):
    return value.get(name, default) if isinstance(value, dict) else getattr(value, name, default)


def _finite(value):
    try:
        return not isinstance(value, bool) and math.isfinite(float(value))
    except (TypeError, ValueError, OverflowError):
        return False


def _text(value):
    return re.sub(r'\s+', '', str(_field(value, 'text', '')))


def _range(value):
    start, end = _field(value, 'start'), _field(value, 'end')
    if not (_finite(start) and _finite(end)):
        return None
    start, end = float(start), float(end)
    return (start, end) if 0 <= start < end else None


def collect_segment_review(segment):
    reasons = []
    for field, threshold, reason, below in (
        ('avg_logprob', -1., '辨識信心偏低', True),
        ('compression_ratio', 2.4, '疑似重複內容', False),
    ):
        value = _field(segment, field)
        if _finite(value) and ((float(value) < threshold) if below else (float(value) > threshold)):
            reasons.append(reason)
    span = _range(segment)
    if not reasons or span is None or not _text(segment):
        return []
    return [dict(start=span[0], end=span[1], text=_field(segment, 'text'), reasons=reasons)]


def review_cues(cues, evidence=()):
    """Return zero-based cue indices. Ignore stale evidence after text changes.

    Match connected, overlapping groups, so splitting or merging unchanged text
    does not attach a model warning to the wrong row. Pauses aren't errors.
    """
    result = {}

    def add(index, reasons):
        for reason in reasons:
            if reason not in result.setdefault(index, []):
                result[index].append(reason)

    spans = [_range(cue) for cue in cues]
    for index, cue in enumerate(cues):
        if spans[index] is None:
            add(index, ['時間軸異常'])
        if index:
            previous = index - 1
            if _text(cue) and _text(cue) == _text(cues[previous]):
                add(previous, ['疑似相鄰重複'])
                add(index, ['疑似相鄰重複'])
            if spans[index] and spans[previous] and spans[index][0] < spans[previous][1] - .001:
                add(previous, ['時間軸重疊'])
                add(index, ['時間軸重疊'])

    evidence = [entry for entry in evidence if _range(entry) and _text(entry)
                and isinstance(_field(entry, 'reasons'), (tuple, list))]
    evidence_spans = [_range(entry) for entry in evidence]
    # Each component includes every connected cue/evidence interval. Comparing
    # the complete text avoids carrying confidence over a partial manual edit.
    links = {i: set() for i in range(len(cues))}
    reverse = {j: set() for j in range(len(evidence))}
    events = []
    for kind, intervals in ((0, spans), (1, evidence_spans)):
        for index, span in enumerate(intervals):
            if span:
                events.extend(((span[0], 1, kind, index), (span[1], 0, kind, index)))
    active = (set(), set())
    for _, opening, kind, index in sorted(events):
        if not opening:
            active[kind].discard(index)
            continue
        for other in active[1 - kind]:
            i, j = (index, other) if kind == 0 else (other, index)
            if min(spans[i][1], evidence_spans[j][1]) - max(spans[i][0], evidence_spans[j][0]) <= .001:
                continue  # SRT/VTT millisecond rounding is not meaningful overlap.
            links[i].add(j)
            reverse[j].add(i)
        active[kind].add(index)
    pending = {i for i, connected in links.items() if connected}
    while pending:
        cue_ids = set()
        evidence_ids = set()
        stack = [pending.pop()]
        while stack:
            i = stack.pop()
            if i in cue_ids:
                continue
            cue_ids.add(i)
            for j in links[i] - evidence_ids:
                evidence_ids.add(j)
                stack.extend(reverse[j] - cue_ids)
        pending -= cue_ids
        if ''.join(_text(cues[i]) for i in sorted(cue_ids)) != ''.join(
                _text(evidence[j]) for j in sorted(evidence_ids, key=lambda j: _range(evidence[j]))):
            continue
        reasons = list(dict.fromkeys(reason for j in sorted(evidence_ids)
                                     for reason in evidence[j]['reasons'] if isinstance(reason, str)))
        for i in sorted(cue_ids):
            add(i, reasons)
    return result
