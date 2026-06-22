import hashlib
import importlib.util
import json
import shutil
import stat
import uuid
import zipfile
from pathlib import Path

import pytest


UPDATER_PATH = Path(__file__).parents[1] / 'deploy' / 'updater' / 'stokcari_updater.py'
SPEC = importlib.util.spec_from_file_location('stokcari_updater', UPDATER_PATH)
updater = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(updater)


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def write_release_zip(path, files):
    manifest = {
        'version': 'test-1',
        'files': [
            {'path': name, 'sha256': sha256_bytes(content)}
            for name, content in files.items()
        ],
    }
    with zipfile.ZipFile(path, 'w') as archive:
        for name, content in files.items():
            archive.writestr(name, content)
        archive.writestr('manifest.json', json.dumps(manifest))


@pytest.fixture
def workspace_tmp_dir():
    path = Path('tests') / '.tmp' / uuid.uuid4().hex
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_release_manifest_is_verified(workspace_tmp_dir):
    zip_path = workspace_tmp_dir / 'release.zip'
    release_dir = workspace_tmp_dir / 'release'
    write_release_zip(zip_path, {
        'VERSION': b'test-1\n',
        'app.py': b'app = object()\n',
        'wsgi.py': b'application = object()\n',
        'requirements.txt': b'Flask>=2.3\n',
        'migrations/env.py': b'# migration environment\n',
    })

    updater.extract_zip(zip_path, release_dir)
    updater.ensure_expected_layout(release_dir)
    updater.verify_manifest(release_dir)


def test_release_manifest_rejects_modified_file(workspace_tmp_dir):
    zip_path = workspace_tmp_dir / 'release.zip'
    release_dir = workspace_tmp_dir / 'release'
    write_release_zip(zip_path, {
        'VERSION': b'test-1\n',
        'app.py': b'app = object()\n',
        'wsgi.py': b'application = object()\n',
        'requirements.txt': b'Flask>=2.3\n',
        'migrations/env.py': b'# migration environment\n',
    })

    updater.extract_zip(zip_path, release_dir)
    (release_dir / 'app.py').write_text('changed = True\n', encoding='utf-8')

    with pytest.raises(ValueError, match='checksum mismatch'):
        updater.verify_manifest(release_dir)


def test_release_manifest_rejects_untracked_file(workspace_tmp_dir):
    zip_path = workspace_tmp_dir / 'release.zip'
    release_dir = workspace_tmp_dir / 'release'
    write_release_zip(zip_path, {
        'VERSION': b'test-1\n',
        'app.py': b'app = object()\n',
        'wsgi.py': b'application = object()\n',
        'requirements.txt': b'Flask>=2.3\n',
        'migrations/env.py': b'# migration environment\n',
    })

    updater.extract_zip(zip_path, release_dir)
    (release_dir / 'untracked.py').write_text('unsafe = True\n', encoding='utf-8')

    with pytest.raises(ValueError, match='missing from manifest'):
        updater.verify_manifest(release_dir)


def test_release_zip_rejects_path_traversal(workspace_tmp_dir):
    zip_path = workspace_tmp_dir / 'release.zip'
    with zipfile.ZipFile(zip_path, 'w') as archive:
        archive.writestr('../outside.txt', 'unsafe')

    with zipfile.ZipFile(zip_path) as archive:
        with pytest.raises(ValueError, match='Unsafe zip path'):
            list(updater.safe_zip_members(archive))


def test_release_zip_rejects_symlink(workspace_tmp_dir):
    zip_path = workspace_tmp_dir / 'release.zip'
    symlink = zipfile.ZipInfo('linked-app.py')
    symlink.create_system = 3
    symlink.external_attr = (stat.S_IFLNK | 0o777) << 16
    with zipfile.ZipFile(zip_path, 'w') as archive:
        archive.writestr(symlink, 'app.py')

    with zipfile.ZipFile(zip_path) as archive:
        with pytest.raises(ValueError, match='Symlink'):
            list(updater.safe_zip_members(archive))


def test_release_version_rejects_path_characters():
    with pytest.raises(ValueError, match='Release VERSION'):
        updater.safe_version('../../release')


def test_database_upgrade_uses_shared_virtual_environment(workspace_tmp_dir, monkeypatch):
    shared_venv = workspace_tmp_dir / 'shared' / '.venv'
    shared_python = shared_venv / 'bin' / 'python'
    shared_python.parent.mkdir(parents=True)
    shared_python.write_text('', encoding='utf-8')
    calls = []

    def record(command, check=True, cwd=None):
        calls.append((command, cwd))

    monkeypatch.setattr(updater, 'run_cmd', record)

    updater.run_database_upgrade(workspace_tmp_dir, shared_venv)

    assert calls == [([
        str(shared_python), '-m', 'flask', '--app', 'app', 'db', 'upgrade'
    ], workspace_tmp_dir)]


def test_healthcheck_fails_closed(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError('offline')

    monkeypatch.setattr(updater, 'urlopen', fail)

    assert updater.healthcheck('http://127.0.0.1:8000/health') is False
