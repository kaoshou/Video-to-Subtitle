"""Local CPU/CUDA benchmark with text and word/segment timing checks.

Uses existing model snapshots only. Synthetic Mandarin fixtures use macOS say;
other systems can use --audio and --reference from a previously saved fixture.
No uploads, model changes, or automatic settings changes. Results are evidence,
not an accuracy guarantee or a claim that CUDA was tested without a CUDA device.
"""
import argparse
from dataclasses import asdict
import json
from pathlib import Path
import statistics
import subprocess
import sys
import tempfile
import time
import wave

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from batch_quality import BatchQualityGuard


def normalize(text):
    from opencc import OpenCC
    return ''.join(c.lower() for c in OpenCC('s2t').convert(text) if c.isalnum())


def char_error_rate(reference, hypothesis):
    # Levenshtein CER, not similarity to another recognizer's output.
    reference, hypothesis = normalize(reference), normalize(hypothesis)
    if not reference:
        return None
    row = list(range(len(hypothesis)+1))
    for i, a in enumerate(reference, 1):
        next_row = [i]
        for j, b in enumerate(hypothesis, 1):
            next_row.append(min(next_row[-1]+1, row[j]+1, row[j-1]+(a != b)))
        row = next_row
    return row[-1]/len(reference)


def assess(segments, duration, reference):
    guard = BatchQualityGuard(duration, True)
    issues = []
    for segment in segments:
        try:
            guard.check(segment)
        except RuntimeError as error:
            issues.append(str(error))
    words = [w for s in segments for w in (s.words or [])]
    windows = reference.get('speech_windows', [])
    outside = sum(1 for w in words if windows and not any(
        window['start']-.5 <= (w.start+w.end)/2 <= window['end']+.5
        for window in windows))
    if outside:
        issues.append(f'{outside} 個單字位於已知語音區間之外。')
    anchors = []
    text = ''
    starts, ends = [], []
    for word in words:
        value = normalize(word.word)
        text += value
        starts.extend([word.start]*len(value))
        ends.extend([word.end]*len(value))
    for window in windows:
        anchor = normalize(window['anchor'])
        found = text.find(anchor)
        cursor = found
        inside = False
        while anchor and cursor >= 0:
            if (window['start']-1 <= starts[cursor]
                    and ends[cursor+len(anchor)-1] <= window['end']+1):
                inside = True
                break
            cursor = text.find(anchor, cursor+1)
        anchors.append(dict(anchor=window['anchor'], found=found >= 0,
                            in_expected_window=inside))
        if not inside:
            issues.append('語音錨點未找到或不在已知區間：'+window['anchor'])
    return dict(text=''.join(s.text for s in segments),
                cer=char_error_rate(reference['text'], ''.join(s.text for s in segments)),
                timing_issues=issues, anchors=anchors, words=len(words),
                words_outside_speech_windows=outside,
                segments=[asdict(s) for s in segments])


def repeat_fixture(audio, reference, count):
    import numpy as np
    duration = len(audio)/16000
    windows = [dict(window, start=window['start']+i*duration,
                    end=window['end']+i*duration)
               for i in range(count) for window in reference.get('speech_windows', [])]
    return np.tile(audio, count), dict(reference, text=reference['text']*count,
                                      speech_windows=windows)


def make_fixture(folder):
    import numpy as np
    from faster_whisper.audio import decode_audio
    sentences = [
        '第一段，今天介紹影片字幕工具。老師可以將課程影片放入清單，選擇辨識模型，再開始轉換。字幕產生後，請記得校對專有名詞。',
        '第二段，接下來介紹網頁播放器。學生可以搜尋逐字稿，點選字幕跳到對應時間，也可以使用鍵盤操作播放器。',
        '第三段，最後介紹多語字幕。請將同名字幕放在影片旁邊，使用語系編碼區分繁體中文、英文和日文。',
    ]
    pieces = [np.zeros(16000*4, np.float32)]
    cursor = 4.
    windows = []
    for index, sentence in enumerate(sentences):
        path = folder/f'voice-{index}.aiff'
        subprocess.run(['say', '-v', 'Eddy (中文（台灣）)', '-r', '160',
                        '-o', str(path), sentence], check=True)
        audio = decode_audio(str(path))
        windows.append(dict(start=cursor, end=cursor+len(audio)/16000,
                            anchor=sentence.split('，')[0]))
        pieces.extend((audio, np.zeros(16000*6, np.float32)))
        cursor += len(audio)/16000+6
    waveform = np.concatenate(pieces)
    with wave.open(str(folder/'fixture.wav'), 'wb') as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16000)
        output.writeframes((waveform.clip(-1, 1)*32767).astype('<i2').tobytes())
    reference = dict(text=''.join(sentences), speech_windows=windows)
    (folder/'reference.json').write_text(json.dumps(reference, ensure_ascii=False, indent=2), encoding='utf-8')
    return waveform, reference


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--device', choices=['cpu', 'cuda'], default='cpu')
    parser.add_argument('--threads', type=int, nargs='+', default=[4])
    parser.add_argument('--batches', type=int, nargs='+', default=[2, 4, 8])
    parser.add_argument('--repeats', type=int, default=2)
    parser.add_argument('--repeat-input', type=int, default=1,
                        help='Repeat synthetic fixture 1..8 times, updating reference offsets')
    parser.add_argument('--audio', type=Path)
    parser.add_argument('--reference', type=Path)
    parser.add_argument('--fixture-dir', type=Path,
                        help='Save newly generated synthetic WAV/reference in a new directory')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if (not args.snapshot.is_dir() or args.report.exists() or args.repeats < 1
            or any(t < 1 for t in args.threads) or not 1 <= args.repeat_input <= 8
            or any(b < 2 or b > 32 for b in args.batches)
            or bool(args.audio) != bool(args.reference)
            or (args.fixture_dir and (args.audio or args.fixture_dir.exists()))):
        parser.error('Need local snapshot, unused report path, valid sizes and matching audio/reference')
    import ctranslate2
    from faster_whisper import WhisperModel, BatchedInferencePipeline
    from faster_whisper.audio import decode_audio
    if args.device == 'cuda' and not ctranslate2.get_cuda_device_count():
        parser.error('No CUDA GPU: refusing to substitute CPU for a CUDA benchmark')
    with tempfile.TemporaryDirectory(prefix='vts-cpu-cuda-quality-') as temp:
        folder = Path(temp)
        if args.audio:
            audio = decode_audio(str(args.audio))
            reference = json.loads(args.reference.read_text(encoding='utf-8'))
        else:
            if args.fixture_dir:
                args.fixture_dir.mkdir()
            audio, reference = make_fixture(args.fixture_dir or folder)
        if args.repeat_input > 1:
            audio, reference = repeat_fixture(audio, reference, args.repeat_input)
        rows = []
        for threads in args.threads:
            model = WhisperModel(str(args.snapshot.resolve()), device=args.device,
                                 compute_type='int8' if args.device=='cpu' else 'float16',
                                 cpu_threads=threads, local_files_only=True)
            options = dict(beam_size=5, word_timestamps=True,
                           condition_on_previous_text=False, vad_filter=True,
                           vad_parameters=dict(min_silence_duration_ms=500))
            warm, _ = model.transcribe(audio[:16000*15], **options)
            list(warm)
            # Alternate order to avoid always granting a cache advantage to batch.
            for repeat in range(args.repeats):
                modes = [None]+args.batches if repeat % 2 == 0 else list(reversed(args.batches))+[None]
                for batch in modes:
                    start = time.perf_counter()
                    if batch is None:
                        segments, info = model.transcribe(audio, **options)
                    else:
                        pipeline = BatchedInferencePipeline(model)
                        segments, info = pipeline.transcribe(audio, batch_size=batch,
                                                            without_timestamps=False, **options)
                    segments = list(segments)
                    if batch is not None:
                        del pipeline
                    elapsed = time.perf_counter()-start
                    row = dict(threads=threads, batch_size=batch, repeat=repeat,
                               actual_mode='standard' if batch is None else 'batched',
                               seconds=elapsed, **assess(segments, info.duration, reference))
                    rows.append(row)
                    print(json.dumps({k:v for k,v in row.items() if k not in ('segments', 'text')},
                                     ensure_ascii=False), flush=True)
            del model
        summary = [dict(threads=t, batch_size=b, median_seconds=statistics.median(
                        r['seconds'] for r in rows if r['threads']==t and r['batch_size']==b))
                   for t in args.threads for b in [None]+args.batches]
        report = dict(device=args.device, model_snapshot=str(args.snapshot.resolve()),
                      duration=len(audio)/16000, reference=reference,
                      timing='Warm core inference, VAD and word alignment; excludes decode/load/assessment',
                      results=rows, summary=summary)
        with args.report.open('x', encoding='utf-8') as output:
            json.dump(report, output, ensure_ascii=False, indent=2)


if __name__ == '__main__':
    main()
