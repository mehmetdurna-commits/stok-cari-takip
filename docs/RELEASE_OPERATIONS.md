# Release Operations

## Shared Environment

The application and updater services use `/opt/stokcari/shared/.venv`.
Create it during the first server setup:

```bash
python3 -m venv /opt/stokcari/shared/.venv
/opt/stokcari/shared/.venv/bin/pip install -r requirements.txt
```

Before applying a release that changes `requirements.txt`, update the shared
environment and run staging smoke tests.

## Release Package

Build a package with:

```bash
python scripts/build_release.py --version 2026.06.02-001 --out dist/stokcari-2026.06.02-001.zip
```

The updater verifies archive paths, archive size, required files, manifest
checksums, database migrations and `/health`. A migration failure prevents the
release switch. A failed health check triggers rollback.

## Pending Production Gate

Do not enable automated production updates until PostgreSQL migrations exist
and the update plus rollback workflow passes on Linux staging.
