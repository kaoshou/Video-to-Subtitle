"""Generate synthetic media and exercise real export; no transcription models needed."""
from pathlib import Path
import sys

if not getattr(sys, 'frozen', False):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from web_export import export_package, load_package
from web_export_model import ExportRequest, Metadata, SubtitleSource


def run_smoke(parent):
    import av
    parent = Path(parent)
    video = parent / 'demo.mp4'
    with av.open(str(video), 'w', format='mp4') as output:
        stream = output.add_stream('libx264', rate=10)
        stream.width, stream.height, stream.pix_fmt = 640, 360, 'yuv420p'
        for index in range(100):
            frame = av.VideoFrame(640, 360, 'yuv420p')
            for plane in frame.planes: plane.update(bytes([80 + index]) * plane.buffer_size)
            for packet in stream.encode(frame): output.mux(packet)
        for packet in stream.encode(): output.mux(packet)
    tracks = []
    for language, text in [('zh-TW','一般影片字幕測試'), ('en','Standalone subtitle test')]:
        path = parent / f'demo.{language}.srt'
        path.write_text(f'1\n00:00:00,000 --> 00:00:09,000\n{text}\n', encoding='utf-8')
        tracks.append(SubtitleSource(path, language))
    request = ExportRequest(video, tuple(tracks), Metadata('一般影片＋字幕示範', '測試講者', '測試課程',
                            '這是合成測試影片。\n不包含私人資料。'), parent, 'demo-web', 'zh-TW')
    result = export_package(request,app_version='development',progress=lambda n,t:None,cancelled=lambda:False)
    assert load_package(result.folder).issues == []
    assert (result.folder / 'media.mp4').read_bytes() == video.read_bytes()
    assert not (result.folder / 'config.js').exists()
    return result


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('output_parent', type=Path, help='existing empty test directory')
    args = parser.parse_args()
    print(run_smoke(args.output_parent).index_path)
