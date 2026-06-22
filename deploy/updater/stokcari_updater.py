#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import zipfile
from datetime import datetime, timezone
from urllib.error import URLError
from urllib.request import urlopen


MAX_RELEASE_FILES = int(os.environ.get("STOKCARI_MAX_RELEASE_FILES", "5000"))
MAX_RELEASE_UNCOMPRESSED_BYTES = int(os.environ.get("STOKCARI_MAX_RELEASE_UNCOMPRESSED_BYTES", str(256 * 1024 * 1024)))


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def read_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return default


def atomic_write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def safe_zip_members(zipf):
    total_size = 0
    members = zipf.infolist()
    if len(members) > MAX_RELEASE_FILES:
        raise ValueError("Release zip contains too many files")
    for member in members:
        name = member.filename.replace("\\", "/")
        if name.startswith("/") or name.startswith("../") or "/../" in name:
            raise ValueError(f"Unsafe zip path: {member.filename}")
        unix_mode = member.external_attr >> 16
        if unix_mode and unix_mode & 0o170000 == 0o120000:
            raise ValueError(f"Symlink is not allowed in release zip: {member.filename}")
        total_size += member.file_size
        if total_size > MAX_RELEASE_UNCOMPRESSED_BYTES:
            raise ValueError("Release zip is too large after extraction")
        yield member


def extract_zip(zip_path, dest_dir):
    with zipfile.ZipFile(zip_path, "r") as z:
        os.makedirs(dest_dir, exist_ok=True)
        for member in safe_zip_members(z):
            z.extract(member, dest_dir)


def ensure_expected_layout(release_dir):
    required = ["app.py", "wsgi.py", "requirements.txt", "manifest.json", "migrations/env.py"]
    missing = [p for p in required if not os.path.exists(os.path.join(release_dir, p))]
    if missing:
        raise ValueError(f"Release missing required files: {', '.join(missing)}")


def safe_version(value):
    version = (value or "").strip()
    if not version or not re.fullmatch(r"[A-Za-z0-9._-]+", version):
        raise ValueError("Release VERSION must contain only letters, numbers, dot, dash or underscore")
    return version


def verify_manifest(release_dir):
    manifest_path = os.path.join(release_dir, "manifest.json")
    manifest = read_json(manifest_path, default={}) or {}
    files = manifest.get("files")
    if not isinstance(files, list) or not files:
        raise ValueError("Release manifest is missing file checksums")

    declared_paths = set()
    for entry in files:
        relative_path = str(entry.get("path") or "").replace("\\", "/")
        expected_sha = str(entry.get("sha256") or "").lower().strip()
        if not relative_path or relative_path.startswith("/") or relative_path.startswith("../") or "/../" in relative_path:
            raise ValueError(f"Unsafe manifest path: {relative_path}")
        file_path = os.path.join(release_dir, relative_path)
        if not os.path.isfile(file_path):
            raise ValueError(f"Manifest file is missing: {relative_path}")
        if not expected_sha or sha256_file(file_path) != expected_sha:
            raise ValueError(f"Manifest checksum mismatch: {relative_path}")
        declared_paths.add(relative_path)

    extracted_paths = {
        os.path.relpath(os.path.join(dirpath, filename), release_dir).replace("\\", "/")
        for dirpath, _, filenames in os.walk(release_dir)
        for filename in filenames
        if os.path.relpath(os.path.join(dirpath, filename), release_dir).replace("\\", "/") != "manifest.json"
    }
    unexpected_paths = sorted(extracted_paths - declared_paths)
    if unexpected_paths:
        raise ValueError(f"Release contains files missing from manifest: {', '.join(unexpected_paths[:5])}")


def run_cmd(cmd, check=True, cwd=None):
    return subprocess.run(cmd, check=check, cwd=cwd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def run_database_upgrade(release_dir, shared_venv):
    shared_python = os.path.join(shared_venv, "bin", "python")
    if not os.path.isfile(shared_python):
        raise FileNotFoundError(f"Shared virtual environment python not found: {shared_python}")
    run_cmd([shared_python, "-m", "flask", "--app", "app", "db", "upgrade"], cwd=release_dir)


def systemctl_state(unit_name):
    try:
        proc = run_cmd(["systemctl", "is-active", unit_name], check=False)
        return (proc.stdout or "").strip()
    except FileNotFoundError:
        return "unknown"


def healthcheck(health_url, timeout_sec=10):
    try:
        with urlopen(health_url, timeout=timeout_sec) as response:
            return 200 <= response.status < 300
    except (OSError, URLError):
        return False


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--base-dir", default=os.environ.get("STOKCARI_BASE_DIR", "/opt/stokcari"))
    p.add_argument("--service-name", default=os.environ.get("STOKCARI_SERVICE", "stokcari"))
    p.add_argument("--health-url", default=os.environ.get("STOKCARI_HEALTH_URL", "http://127.0.0.1:8000/health"))
    p.add_argument("--keep-releases", type=int, default=int(os.environ.get("STOKCARI_KEEP_RELEASES", "10")))
    args = p.parse_args()

    base_dir = os.path.abspath(args.base_dir)
    shared_venv = os.path.join(base_dir, "shared", ".venv")
    shared_instance = os.path.join(base_dir, "shared", "instance")
    updates_dir = os.path.join(shared_instance, "updates")
    incoming_dir = os.path.join(updates_dir, "incoming")
    requests_dir = os.path.join(updates_dir, "requests")
    status_path = os.path.join(updates_dir, "status.json")
    heartbeat_path = os.path.join(updates_dir, "heartbeat.json")

    releases_dir = os.path.join(base_dir, "releases")
    current_link = os.path.join(base_dir, "current")

    os.makedirs(incoming_dir, exist_ok=True)
    os.makedirs(requests_dir, exist_ok=True)
    os.makedirs(releases_dir, exist_ok=True)

    # Always write a heartbeat so the UI can tell updater is installed/running.
    atomic_write_json(heartbeat_path, {
        "updated_at": utc_now_iso(),
        "timer": {
            "name": "stokcari-updater.timer",
            "state": systemctl_state("stokcari-updater.timer"),
        },
        "service": {
            "name": args.service_name,
            "state": systemctl_state(args.service_name),
        },
    })

    req_files = sorted([f for f in os.listdir(requests_dir) if f.endswith(".json")])
    if not req_files:
        return 0

    req_file = req_files[0]
    req_path = os.path.join(requests_dir, req_file)
    req = read_json(req_path, default={}) or {}
    request_id = req.get("id") or os.path.splitext(req_file)[0]
    zip_path = req.get("zip_path") or os.path.join(incoming_dir, f"{request_id}.zip")
    expected_sha = (req.get("sha256") or "").lower().strip()

    status = {
        "updated_at": utc_now_iso(),
        "request_id": request_id,
        "state": "running",
        "message": "Update started",
    }
    atomic_write_json(status_path, status)

    try:
        if not os.path.exists(zip_path):
            raise FileNotFoundError(f"Zip not found: {zip_path}")
        actual_sha = sha256_file(zip_path)
        if expected_sha and actual_sha != expected_sha:
            raise ValueError("Zip sha256 mismatch")

        # Determine version from VERSION inside zip (optional; fallback request id).
        version = None
        with zipfile.ZipFile(zip_path, "r") as z:
            if "VERSION" in z.namelist():
                version = z.read("VERSION").decode("utf-8", errors="replace").strip()
        version = safe_version(version or f"release-{request_id}")
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        release_dir = os.path.join(releases_dir, f"{version}-{stamp}")

        extract_zip(zip_path, release_dir)
        ensure_expected_layout(release_dir)
        verify_manifest(release_dir)
        run_database_upgrade(release_dir, shared_venv)

        # Ensure shared instance exists and is used by current release.
        os.makedirs(shared_instance, exist_ok=True)
        release_instance = os.path.join(release_dir, "instance")
        if not os.path.exists(release_instance):
            os.symlink(shared_instance, release_instance, target_is_directory=True)

        # Switch current -> new release atomically (keep previous for rollback).
        previous_target = None
        try:
            if os.path.islink(current_link):
                previous_target = os.readlink(current_link)
        except OSError:
            previous_target = None

        tmp_link = os.path.join(base_dir, f".current_tmp_{request_id}")
        if os.path.exists(tmp_link):
            os.unlink(tmp_link)
        os.symlink(release_dir, tmp_link, target_is_directory=True)
        os.replace(tmp_link, current_link)

        # Restart app service.
        run_cmd(["systemctl", "restart", args.service_name], check=True)
        time.sleep(1.5)

        if not healthcheck(args.health_url):
            raise RuntimeError("Health check failed after restart")

        # Cleanup request and zip
        os.remove(req_path)
        if os.path.exists(zip_path):
            os.remove(zip_path)

        status = {
            "updated_at": utc_now_iso(),
            "request_id": request_id,
            "state": "success",
            "message": f"Updated to {os.path.basename(release_dir)}",
            "active_release": os.path.basename(release_dir),
            "sha256": actual_sha,
        }
        atomic_write_json(status_path, status)

        # Trim old releases
        releases = sorted(os.listdir(releases_dir))
        if len(releases) > args.keep_releases:
            for old in releases[: max(0, len(releases) - args.keep_releases)]:
                old_path = os.path.join(releases_dir, old)
                try:
                    if os.path.islink(old_path) or os.path.isfile(old_path):
                        os.remove(old_path)
                    else:
                        shutil.rmtree(old_path, ignore_errors=True)
                except Exception:
                    pass

        return 0

    except Exception as e:
        # Rollback if we switched current already and we know the previous target.
        try:
            previous_target
        except NameError:
            previous_target = None
        if previous_target and os.path.islink(current_link):
            try:
                tmp_link = os.path.join(base_dir, f".current_tmp_rollback_{request_id}")
                if os.path.exists(tmp_link):
                    os.unlink(tmp_link)
                os.symlink(previous_target, tmp_link, target_is_directory=True)
                os.replace(tmp_link, current_link)
                run_cmd(["systemctl", "restart", args.service_name], check=False)
            except Exception:
                pass

        status = {
            "updated_at": utc_now_iso(),
            "request_id": request_id,
            "state": "failed",
            "message": str(e),
        }
        atomic_write_json(status_path, status)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
