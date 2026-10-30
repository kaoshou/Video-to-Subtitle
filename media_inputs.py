"""Expand selected files/projects using real filesystem types, never suffixes alone."""
import os

import evercam_integration as evercam
import opencam_integration as opencam


def collect_media_inputs(paths, extensions):
    """Return ordered unique media and rejected explicit filenames.

    Project entry files can identify their directory. Folder scans skip links
    and never execute project JavaScript; OpenCam selects its associated video.
    """
    files, rejected = [], []
    seen_files, seen_directories = set(), set()
    pending = [(os.fspath(path).strip().strip('"').strip("'"), True) for path in reversed(paths)]
    while pending:
        path, explicit = pending.pop()
        if not path or not os.path.exists(path):
            continue
        path = os.path.abspath(path)
        is_oc, oc_folder = opencam.detect_opencam_project(path)
        if is_oc:
            path = os.path.join(oc_folder, 'media.mp4')
        elif os.path.isdir(path):
            identity = os.path.normcase(os.path.realpath(path))
            if identity in seen_directories:
                continue
            seen_directories.add(identity)
            try:
                with os.scandir(path) as scan:
                    entries = sorted(scan, key=lambda entry: entry.name.casefold())
                children = []
                for entry in entries:
                    if entry.is_symlink():
                        continue
                    if entry.is_dir(follow_symlinks=False) or (
                            entry.is_file(follow_symlinks=False) and
                            os.path.splitext(entry.name)[1].lower() in extensions):
                        children.append((entry.path, False))
                pending.extend(reversed(children))
            except OSError:
                if explicit:
                    rejected.append(os.path.basename(path))
            continue
        elif explicit and os.path.isfile(path) and os.path.basename(path).lower() in ('config.js', 'index.html'):
            folder = os.path.dirname(path)
            if evercam.is_evercam_folder(folder):
                pending.append((folder, False))
                continue

        # This check is deliberately after directory expansion, including
        # directories named *.mp4 inside genuine EverCam course folders.
        if os.path.isfile(path) and os.path.splitext(path)[1].lower() in extensions:
            identity = os.path.normcase(os.path.abspath(path))
            if identity not in seen_files:
                seen_files.add(identity)
                files.append(path)
        elif explicit:
            rejected.append(os.path.basename(path))
    return files, rejected
