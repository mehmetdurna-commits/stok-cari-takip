#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import fnmatch
import hashlib
import json
import os
import zipfile
from datetime import datetime, timezone


DEFAULT_EXCLUDES = [
    ".git/**",
    ".venv/**",
    ".pytest_cache/**",
    ".pytest-tmp/**",
    "__pycache__/**",
    "pytest-cache-files-*/**",
    "dist/**",
    "instance/**",
    "backups/**",
    "static/support_uploads/**",
    "templates/instance/**",
    "tests/**",
    "*.backup",
    "*.pyc",
    "*.pyo",
    "*.log",
]


def utc_now_iso():
    return datetime.now(timezone.utc).isoformat()


def matches_any(path, patterns):
    for pat in patterns:
        if fnmatch.fnmatch(path, pat):
            return True
    return False


def sha256_bytes(data: bytes) -> str:
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--version", required=True)
    p.add_argument("--out", required=True, help="Output zip path")
    p.add_argument("--root", default=".", help="Project root")
    p.add_argument("--exclude", action="append", default=[], help="Extra exclude glob (can repeat)")
    args = p.parse_args()

    root = os.path.abspath(args.root)
    excludes = DEFAULT_EXCLUDES + (args.exclude or [])

    manifest = {
        "version": args.version,
        "created_at": utc_now_iso(),
        "files": [],
    }

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)

    with zipfile.ZipFile(args.out, "w", compression=zipfile.ZIP_DEFLATED) as z:
        # VERSION marker
        z.writestr("VERSION", args.version + "\n")
        manifest["files"].append({"path": "VERSION", "sha256": sha256_bytes((args.version + "\n").encode("utf-8"))})

        for dirpath, dirnames, filenames in os.walk(root):
            rel_dir = os.path.relpath(dirpath, root).replace("\\", "/")
            if rel_dir == ".":
                rel_dir = ""

            # prune excluded directories
            pruned = []
            for d in list(dirnames):
                rel = (f"{rel_dir}/{d}" if rel_dir else d).replace("\\", "/")
                if matches_any(rel + "/", excludes) or matches_any(rel + "/**", excludes):
                    pruned.append(d)
            for d in pruned:
                dirnames.remove(d)

            for name in filenames:
                rel = (f"{rel_dir}/{name}" if rel_dir else name).replace("\\", "/")
                if matches_any(rel, excludes):
                    continue
                abs_path = os.path.join(dirpath, name)
                if not os.path.isfile(abs_path):
                    continue
                with open(abs_path, "rb") as f:
                    data = f.read()
                z.writestr(rel, data)
                manifest["files"].append({"path": rel, "sha256": sha256_bytes(data)})

        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2).encode("utf-8"))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
