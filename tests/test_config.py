import os
import shutil
import subprocess
import sys
import uuid
from pathlib import Path

import pytest


PROJECT_ROOT = Path(__file__).parents[1]


@pytest.fixture
def workspace_tmp_dir():
    path = PROJECT_ROOT / 'tests' / '.tmp' / uuid.uuid4().hex
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def test_config_loads_local_dotenv_without_overriding_process_environment(workspace_tmp_dir):
    env_file = workspace_tmp_dir / '.env'
    env_file.write_text(
        'PLATFORM_ADMIN_EMAILS=dotenv@example.com\n'
        'PLATFORM_ADMIN_PASSWORD=DotenvPassword123!\n',
        encoding='utf-8',
    )
    environment = os.environ.copy()
    environment['PYTHONPATH'] = str(PROJECT_ROOT)
    environment['PLATFORM_ADMIN_EMAILS'] = 'process@example.com'
    environment.pop('PLATFORM_ADMIN_PASSWORD', None)

    result = subprocess.run(
        [
            sys.executable,
            '-c',
            (
                'import os; import config; '
                'print(os.environ["PLATFORM_ADMIN_EMAILS"]); '
                'print(os.environ["PLATFORM_ADMIN_PASSWORD"])'
            ),
        ],
        cwd=workspace_tmp_dir,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    assert result.stdout.splitlines() == [
        'process@example.com',
        'DotenvPassword123!',
    ]
