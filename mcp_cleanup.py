"""Explicit local-only reset of the closed private work graph.

Never an MCP tool. All dependent work namespaces are reset together; there is
no partial source/draft garbage collection. Connections, backups, launchers,
policy and lock inodes are outside this fixed scope. A durable marker blocks
activation/content until an interrupted reset is explicitly resumed.
"""
import contextlib
import hashlib
import json
import os
import stat

from mcp_state import MCPError, ProcessLock, _private_directory, _write_json
from safe_files import _retry_sharing_violation

SCOPE = ('assets', 'jobs', 'sources', 'drafts', 'tracks', 'requests', 'workspaces', 'locations')


def _safe(info):
    if (info is None or stat.S_ISLNK(info.st_mode) or
            getattr(info, 'st_file_attributes', 0) & 0x400 or
            not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)) or
            (stat.S_ISREG(info.st_mode) and info.st_nlink != 1)):
        raise MCPError('UNSAFE_PATH', 'Unsafe private work entry; cleanup stopped without following it.')


def preview_cleanup(state):
    """Read only; include exact bytes/location/scope and a version fingerprint."""
    entries = []
    def walk(parent, name, relative, depth=0):
        info = parent.info(name)
        _safe(info)
        if depth > 32 or len(entries) >= 200000:
            raise MCPError('STORAGE_LIMIT', 'Private cleanup inventory exceeds its safe bound.')
        entries.append([relative, info.st_dev, info.st_ino, info.st_size,
                        info.st_mtime_ns, info.st_ctime_ns, stat.S_ISREG(info.st_mode)])
        if stat.S_ISDIR(info.st_mode):
            with parent.child(name) as child:
                for leaf in sorted(child.names()):
                    walk(child, leaf, relative + '/' + leaf, depth + 1)
    try:
        with _private_directory(state.path) as directory:
            resume = directory.info('cleanup.json') is not None
            for name in SCOPE:
                if directory.info(name) is not None:
                    walk(directory, name, name)
    except FileNotFoundError:
        resume = False
    return {'location': str(state.path), 'bytes': sum(e[3] for e in entries if e[6]),
            'scope': list(SCOPE), 'resume': resume,
            'fingerprint': hashlib.sha256(json.dumps(entries).encode()).hexdigest()}


def _remove_tree(parent, name):
    """Only fixed-scope, pinned, no-follow private entries; never recurse links."""
    before = parent.info(name)
    _safe(before)
    if stat.S_ISDIR(before.st_mode):
        with parent.child(name) as child:
            for leaf in child.names():
                _remove_tree(child, leaf)
        current = parent.info(name)
        _safe(current)
        if (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino):
            raise MCPError('UNSAFE_PATH', 'Private directory changed during cleanup.')
        _retry_sharing_violation(lambda: os.rmdir(name, dir_fd=parent.fd) if parent.fd is not None
                                else os.rmdir(parent._path(name)))
    else:
        with parent.open_read(name) as stream:
            opened = os.fstat(stream.fileno())
            if (before.st_dev, before.st_ino) != (opened.st_dev, opened.st_ino):
                raise MCPError('UNSAFE_PATH', 'Private file changed during cleanup.')
        current = parent.info(name)
        _safe(current)
        if (before.st_dev, before.st_ino) != (current.st_dev, current.st_ino):
            raise MCPError('UNSAFE_PATH', 'Private file changed during cleanup.')
        _retry_sharing_violation(lambda: os.unlink(name, dir_fd=parent.fd) if parent.fd is not None
                                else os.unlink(parent._path(name)))


def apply_cleanup(state, plan, *, consent=False):
    if consent is not True:
        raise MCPError('CONSENT_REQUIRED', 'Confirm removal of all private transcripts, unfinished translations, history and retry IDs.')
    if state.policy()['enabled']:
        raise MCPError('WORK_ACTIVE', 'Disable MCP and wait for accepted work before cleanup.')
    with contextlib.ExitStack() as stack:
        # Same order as broker/model administration. Policy is last; inventory
        # and recursive deletion run after policy is released, with exclusive
        # owners and a durable fail-closed reset marker protecting the graph.
        for name in ('broker', 'service-owner', 'inference', 'model-residency', 'cleanup-control'):
            lock = ProcessLock(state.path / 'locks', name)
            if not lock.acquire():
                raise MCPError('WORK_ACTIVE', 'Work or model ownership is active; wait for normal completion/exit.')
            stack.callback(lock.release)
        current = preview_cleanup(state)
        if plan != current:
            raise MCPError('CLEANUP_CHANGED', 'Private work changed; review its size and scope again before confirming.')
        with ProcessLock(state.path / 'locks', 'policy'):
            if state.policy()['enabled']:
                raise MCPError('WORK_ACTIVE', 'MCP was enabled; disable before cleanup.')
            with _private_directory(state.path, create=True) as directory:
                _write_json(directory, 'cleanup.json', b'{"version":1,"scope":"all-private-work"}')
        # No live broker/service/model owner exists. Nonterminal records now
        # represent interrupted work, and are included in the consented reset.
        with _private_directory(state.path) as directory:
            for name in SCOPE:
                if directory.info(name) is not None:
                    _remove_tree(directory, name)
            if directory.fd is not None:
                os.unlink('cleanup.json', dir_fd=directory.fd)
                os.fsync(directory.fd)
            else:
                _retry_sharing_violation(lambda: os.unlink(directory._path('cleanup.json')))
    return {'removed_bytes': current['bytes'], 'location': current['location']}
