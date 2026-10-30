"""Prepare exactly the public platform packages after native build/smoke tests."""
import argparse
from pathlib import Path
import platform
import re
import shutil
import tomllib
import zipfile


def package_release(dist, version, system, machine):
    """Preserve compiled payloads; reject wrong labels and existing destinations."""
    if not re.fullmatch(r'\d+\.\d+\.\d+', version):
        raise ValueError('Release version must be major.minor.patch')
    dist = Path(dist)
    prefix = f'VideoToSubtitle_v{version}'
    architecture = machine.lower()
    if system == 'Windows' and architecture in ('amd64', 'x86_64'):
        sources = [dist / 'VideoToSubtitle.exe', dist / f'installer/VideoToSubtitle-Setup-v{version}.exe']
        names = [f'{prefix}_Windows_x64_Portable.zip', f'{prefix}_Windows_x64_Setup.exe']
    elif system == 'Darwin' and architecture in ('arm64', 'aarch64'):
        sources = [dist / 'VideoToSubtitle.dmg']
        names = [f'{prefix}_macOS_arm64.dmg']
    else:
        raise ValueError(f'Unsupported release platform/architecture: {system}/{machine}')
    if any(not source.is_file() or source.stat().st_size == 0 for source in sources):
        raise ValueError('Missing or empty compiled release payload')
    output = dist / 'release'
    targets = [output / name for name in names]
    if any(target.exists() for target in targets):
        raise FileExistsError('Refusing to overwrite prepared release packages')
    output.mkdir(parents=True, exist_ok=True)
    for source, target in zip(sources, targets):
        if target.suffix == '.zip':
            with zipfile.ZipFile(target, 'x', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
                archive.write(source, arcname='VideoToSubtitle.exe')
        else:
            with source.open('rb') as incoming, target.open('xb') as outgoing:
                shutil.copyfileobj(incoming, outgoing)
    return targets


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dist', type=Path, default=Path('dist'))
    args = parser.parse_args()
    with (Path(__file__).resolve().parents[1] / 'pyproject.toml').open('rb') as stream:
        version = tomllib.load(stream)['project']['version']
    for path in package_release(args.dist, version, platform.system(), platform.machine()):
        print(path)
