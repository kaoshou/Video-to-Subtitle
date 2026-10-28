"""Experimental MLX batching benchmark, NOT used by the application.

Only synthetic/consented audio and an existing local model snapshot are used.
Output is a new JSON report, not production subtitles. VAD chunks keep their
original offsets; silence inside a chunk is not concatenated or time-compressed.
"""
import argparse
import difflib
import importlib
import json
from pathlib import Path
import time


def speech_ranges(audio):
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    spans = get_speech_timestamps(audio, VadOptions(
        max_speech_duration_s=28, min_silence_duration_ms=500,
        speech_pad_ms=200))
    merged = []
    for span in spans:
        start, end = span['start'], span['end']
        if merged and end - merged[-1][0] <= 30 * 16000:
            merged[-1] = (merged[-1][0], end)
        else:
            merged.append((start, end))
    assert all(0 <= s < e <= len(audio) and e-s <= 480000 for s, e in merged)
    assert all(a[1] <= b[0] for a, b in zip(merged, merged[1:]))
    return merged


def shifted_segments(segments, offset):
    # Never modify native result objects or cached per-chunk alignment in place.
    return [dict(s, start=s['start']+offset, end=s['end']+offset,
                 words=[dict(w, start=w['start']+offset, end=w['end']+offset)
                        for w in s.get('words', [])]) for s in segments]


def validate(segments, duration):
    previous = 0
    for segment in segments:
        words = segment.get('words', [])
        assert words, 'Missing word alignment'
        for word in words:
            assert 0 <= word['start'] <= word['end'] <= duration + .05
            assert word['start'] >= previous - .05, 'Non-monotonic word times'
            previous = word['end']


def experiment(audio, snapshot, language, batch_sizes):
    import mlx.core as mx
    import mlx_whisper
    from mlx_whisper.audio import log_mel_spectrogram, pad_or_trim, N_FRAMES
    from mlx_whisper.decoding import decode, DecodingOptions
    from mlx_whisper.tokenizer import get_tokenizer
    from mlx_whisper.timing import add_word_timestamps

    native = importlib.import_module('mlx_whisper.transcribe')
    model = native.ModelHolder.get_model(str(snapshot), mx.float16)
    tokenizer = get_tokenizer(model.is_multilingual,
                              num_languages=model.num_languages, language=language,
                              task='transcribe')
    options = DecodingOptions(language=language, task='transcribe',
                              temperature=0, without_timestamps=False)
    # Warm the same native path, including alignment, before either timed mode.
    mlx_whisper.transcribe(mx.array(audio[:480000]), path_or_hf_repo=str(snapshot),
                           language=language, word_timestamps=True,
                           condition_on_previous_text=False, verbose=None)
    mx.synchronize()
    start = time.perf_counter()
    baseline = mlx_whisper.transcribe(mx.array(audio), path_or_hf_repo=str(snapshot),
                                     language=language, word_timestamps=True,
                                     condition_on_previous_text=False, verbose=None)
    mx.synchronize()
    baseline_seconds = time.perf_counter() - start
    validate(baseline['segments'], len(audio)/16000)
    print(f'Native full transcription: {baseline_seconds:.3f}s', flush=True)
    results = []
    for batch_size in batch_sizes:
        started = time.perf_counter()
        ranges = speech_ranges(audio)
        segments = []
        fallbacks = 0
        fallback_details = []
        for index in range(0, len(ranges), batch_size):
            group = ranges[index:index+batch_size]
            mels = []
            for s, e in group:
                mel = log_mel_spectrogram(mx.array(audio[s:e]), n_mels=model.dims.n_mels)
                mels.append(pad_or_trim(mel, N_FRAMES, axis=-2).astype(mx.float16))
            try:
                decoded = decode(model, mx.stack(mels), options)
            except (RuntimeError, MemoryError):
                # Spike only: whole group falls back, never an incomplete result.
                decoded = [None] * len(group)
            for (s, e), mel, result in zip(group, mels, decoded):
                duration = (e-s)/16000
                tokens = result.tokens if result else []
                # Incomplete timestamp endings need native seek/retry behavior.
                suspect = (not tokens or tokens[-1] < tokenizer.timestamp_begin
                           or result.avg_logprob < -1
                           or result.compression_ratio > 2.4)
                if not suspect:
                    local = [dict(start=0., end=duration, seek=0,
                                  text=result.text, tokens=tokens)]
                    add_word_timestamps(segments=local, model=model,
                                        tokenizer=tokenizer, mel=mel,
                                        num_frames=min(N_FRAMES, (e-s)//160),
                                        last_speech_timestamp=0.)
                    try:
                        validate(local, duration)
                    except AssertionError:
                        suspect = True
                if suspect:
                    fallbacks += 1
                    fallback_details.append(dict(offset=s/16000,
                        avg_logprob=result.avg_logprob if result else None,
                        compression_ratio=result.compression_ratio if result else None,
                        no_speech_prob=result.no_speech_prob if result else None,
                        complete_timestamp=bool(tokens and tokens[-1] >= tokenizer.timestamp_begin)))
                    local = mlx_whisper.transcribe(
                        mx.array(audio[s:e]), path_or_hf_repo=str(snapshot),
                        language=language, word_timestamps=True,
                        condition_on_previous_text=False, verbose=None)['segments']
                segments.extend(shifted_segments(local, s/16000))
        mx.synchronize()
        elapsed = time.perf_counter()-started
        validate(segments, len(audio)/16000)
        text = ''.join(s['text'] for s in segments)
        normalize = lambda t: ''.join(c for c in t if c.isalnum())
        similarity = difflib.SequenceMatcher(None, normalize(baseline['text']),
                                             normalize(text), autojunk=False).ratio()
        row = dict(batch_size=batch_size, seconds=round(elapsed, 3),
                   speedup_vs_native=round(baseline_seconds/elapsed, 3),
                   chunks=len(ranges), native_fallback_chunks=fallbacks,
                   fallback_details=fallback_details,
                   similarity_to_native=round(similarity, 4), segments=segments)
        results.append(row)
        print(json.dumps({k:v for k,v in row.items() if k!='segments'}), flush=True)
    return dict(experimental=True, includes_vad_and_word_alignment=True,
                duration=len(audio)/16000, native_seconds=baseline_seconds,
                native_segments=baseline['segments'], results=results,
                warning='Similarity is NOT accuracy; native output is not ground truth.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    parser.add_argument('--language', default='zh')
    parser.add_argument('--repeat', type=int, default=1,
                        help='Repeat synthetic input for a longer benchmark')
    args = parser.parse_args()
    if not args.snapshot.is_dir() or args.report.exists() or not 1 <= args.repeat <= 10:
        parser.error('Need local snapshot, unused report path, repeat 1..10')
    import numpy as np
    from faster_whisper.audio import decode_audio
    audio = decode_audio(str(args.audio))
    if args.repeat > 1:
        audio = np.concatenate([np.concatenate((audio, np.zeros(16000, np.float32)))
                                for _ in range(args.repeat)])
    report = experiment(audio, args.snapshot.resolve(), args.language, (1, 2, 4))
    with args.report.open('x', encoding='utf-8') as stream:
        json.dump(report, stream, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
