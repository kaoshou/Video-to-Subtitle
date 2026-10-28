"""Opt-in real-model comparison; never uploads audio or changes model caches.

Run with a synthetic/test audio file and a local model snapshot. CPU/CUDA compare
standard and batched output; MLX checks native word times and batch fallback.
"""
import argparse
import contextlib
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from transcriber import SubtitleTranscriber


def reported_mode(device, requested_batch, logs):
    if device == 'mlx':
        return 'mlx-native'
    if requested_batch is None:
        return 'standard'
    return 'standard-fallback' if '使用標準推論。' in logs else 'batched'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--audio', type=Path, required=True)
    parser.add_argument('--snapshot', type=Path, required=True)
    parser.add_argument('--device', choices=['cpu', 'cuda', 'mlx'], default='cpu')
    parser.add_argument('--force-zh-tw', action='store_true')
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    worker = SubtitleTranscriber(device=args.device,
                                compute_type='int8' if args.device == 'cpu' else 'float16')
    if args.device == 'mlx':
        worker.model_type = 'mlx-whisper'
        worker.mlx_model_path = str(args.snapshot.resolve())
    else:
        from faster_whisper import WhisperModel
        worker.model = WhisperModel(str(args.snapshot.resolve()), device=args.device,
                                    compute_type=worker.compute_type, cpu_threads=4,
                                    local_files_only=True)
    rows = []
    with tempfile.TemporaryDirectory(prefix='vts-native-batch-') as folder:
        audio = Path(folder) / ('media' + args.audio.suffix)
        shutil.copyfile(args.audio, audio)
        for batch in (None, 2, 4):
            logs, progress = [], []
            start = time.monotonic()
            with contextlib.redirect_stdout(io.StringIO()):
                output = worker.run(str(audio), batch_acceleration=batch is not None,
                                    batch_size=batch or 4, output_format='json',
                                    force_zh_tw=args.force_zh_tw,
                                    word_timestamps=True, clean_punctuation='none',
                                    log_callback=logs.append, progress_callback=progress.append)
            elapsed = time.monotonic() - start
            segments = json.loads(Path(output).read_text(encoding='utf-8'))
            if not segments:
                raise AssertionError('Test speech produced no subtitles')
            previous = 0
            for item in segments:
                if not 0 <= item['start'] <= item['end'] or item['start'] < previous - .05:
                    raise AssertionError(f'Invalid or non-monotonic cue: {item}')
                previous = item['end']
            if progress[-1] != 1:
                raise AssertionError('Success was not reported after output')
            actual_mode = reported_mode(args.device, batch, logs)
            rows.append(dict(requested_batch=batch, actual_mode=actual_mode, seconds=round(elapsed, 3),
                             cues=len(segments), segments=segments, logs=logs))
            print(f'{args.device} requested_batch={batch}, mode={actual_mode}: {elapsed:.3f}s, {len(segments)} cues', flush=True)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(dict(device=args.device, force_zh_tw=args.force_zh_tw,
                                          first_call_may_include_model_warmup=True,
                                          results=rows), ensure_ascii=False, indent=2),
                           encoding='utf-8')


if __name__ == '__main__':
    main()
