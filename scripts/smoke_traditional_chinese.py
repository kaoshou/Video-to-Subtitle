"""Check bundled OpenCC through actual subtitle output, without speech models.

Only recognition is replayed from synthetic text. Dictionaries, post-processing,
file serialization and timestamp handling are the real packaged implementation.
"""
import contextlib
import io
from pathlib import Path
import tempfile
from types import SimpleNamespace

from transcriber import SubtitleTranscriber, require_traditional_converter


class RecordedRecognition:
    def transcribe(self, file_path, **options):
        return iter([
            SimpleNamespace(text='這是原本就是繁體的字幕', start=0, end=5, words=None),
            SimpleNamespace(text='这是软件与数据库课程', start=55.25, end=63.15, words=None),
            SimpleNamespace(text='English recording.', start=70, end=75, words=None),
        ]), SimpleNamespace(duration=75, language='zh', language_probability=1)


def run_smoke():
    require_traditional_converter()
    with tempfile.TemporaryDirectory(prefix='vts-traditional-smoke-') as folder:
        for format in ('srt', 'vtt', 'txt', 'tsv', 'json'):
            for prompt in ('以下是使用台灣繁體中文撰寫的字幕。', '请用简体中文输出。'):
                worker = SubtitleTranscriber()
                worker.model = RecordedRecognition()
                with contextlib.redirect_stdout(io.StringIO()):
                    output = worker.run(str(Path(folder) / 'media.mp4'), force_zh_tw=True,
                                        initial_prompt=prompt, output_format=format,
                                        clean_punctuation='none', spacing=False)
                text = Path(output).read_text(encoding='utf-8')
                if ('這是原本就是繁體的字幕' not in text or
                        '這是軟體與資料庫課程' not in text or
                        'English recording.' not in text or '这是' in text):
                    raise AssertionError(f'{format}: packaged Traditional Chinese conversion failed')
                if format == 'srt' and '00:00:55,250 --> 00:01:03,150' not in text:
                    raise AssertionError('Packaged transcription altered timestamps')
    print('Traditional Chinese subtitle smoke passed (5 formats, 2 prompts).')


if __name__ == '__main__':
    run_smoke()
