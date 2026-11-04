"""Dependency acknowledgements and build-time collection of upstream notices."""

COMPONENTS = (
    ('faster-whisper', 'MIT', 'https://github.com/SYSTRAN/faster-whisper'),
    ('CTranslate2', 'MIT', 'https://github.com/OpenNMT/CTranslate2'),
    ('MLX / mlx-whisper', 'MIT', 'https://github.com/ml-explore/mlx-examples/tree/main/whisper'),
    ('CustomTkinter', 'MIT', 'https://github.com/TomSchimansky/CustomTkinter'),
    ('tkinterdnd2 / TkDND', 'MIT / Tcl/Tk-style BSD', 'https://github.com/pmgagne/tkinterdnd2'),
    ('PyAV (av)', 'BSD-3-Clause', 'https://github.com/PyAV-Org/PyAV'),
    ('Pillow', 'MIT-CMU / PIL Software License', 'https://github.com/python-pillow/Pillow'),
    ('sounddevice / PortAudio', 'MIT', 'https://github.com/spatialaudio/python-sounddevice'),
    ('OpenCC', 'Apache-2.0', 'https://github.com/BYVoid/OpenCC'),
    ('tomli', 'MIT', 'https://github.com/hukkin/tomli'),
    ('huggingface-hub', 'Apache-2.0', 'https://github.com/huggingface/huggingface_hub'),
    ('MCP Python SDK', 'MIT', 'https://github.com/modelcontextprotocol/python-sdk'),
    ('tomlkit', 'MIT', 'https://github.com/python-poetry/tomlkit'),
    ('psutil', 'BSD-3-Clause', 'https://github.com/giampaolo/psutil'),
    ('nvidia-ml-py', 'BSD-2-Clause', 'https://pypi.org/project/nvidia-ml-py/'),
    ('NumPy', 'BSD-3-Clause and bundled notices', 'https://numpy.org/doc/stable/license.html'),
    ('FFmpeg libraries', 'LGPL / GPL, depending on build', 'https://ffmpeg.org/legal.html'),
    ('Python / Tcl / Tk', 'PSF / Tcl-Tk licenses', 'https://docs.python.org/3/license.html'),
    ('PyInstaller', 'GPL with bootloader exception', 'https://pyinstaller.org/en/stable/license.html'),
    ('evercam-subtitle-player', '', 'https://github.com/kaoshou/evercam-subtitle-player'),
)


def collect_license_datas():
    """Keep the actual installed versions' license/notice files in each build.

    No network or new dependency is involved. Include installed dependency
    notices rather than assume a license name covers all bundled native code.
    """
    import importlib.metadata
    from pathlib import Path
    import re
    result = []
    for dist in importlib.metadata.distributions():
        name = re.sub(r'[^A-Za-z0-9_.-]', '_', dist.metadata.get('Name', 'unknown'))
        for entry in dist.files or ():
            path = Path(str(entry))
            if path.is_absolute() or '..' in path.parts:
                continue
            filename = path.name.lower()
            if not (filename.startswith(('license', 'licence', 'copying', 'copyright', 'thirdpartynotice', 'third_party_notice'))
                    or filename == 'notice' or filename.startswith('notice.')):
                continue
            source = Path(dist.locate_file(entry))
            if source.is_file():
                destination = Path('licenses') / name / dist.version / path.parent
                result.append((str(source), str(destination)))
    return result
