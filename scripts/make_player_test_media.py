"""Create an owned, synthetic 270-second MP4 for browser release checks."""
import argparse
from pathlib import Path


def make_media(path):
    import av
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise FileExistsError(f'Refusing to overwrite test media: {path}')
    with av.open(str(path), 'w', format='mp4') as output:
        stream = output.add_stream('libx264', rate=1)
        stream.width, stream.height, stream.pix_fmt = 320, 180, 'yuv420p'
        for index in range(270):
            frame = av.VideoFrame(320, 180, 'yuv420p')
            for plane in frame.planes:
                plane.update(bytes([70 + index % 30]) * plane.buffer_size)
            for packet in stream.encode(frame):
                output.mux(packet)
        for packet in stream.encode():
            output.mux(packet)
    return path


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('output', type=Path)
    print(make_media(parser.parse_args().output))
