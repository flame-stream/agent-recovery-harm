#!/usr/bin/env python3
"""Unpack data/protected/protected.bundle into data/protected/ (needs `pip install appworld`).

The bundle is encrypted with AppWorld's own bundle key, as AppWorld distributes its data;
the key is taken from the installed appworld package and is not stored in this repository.
Do not re-publish the unpacked files in plain text (see DATA_POLICY.md)."""
import pathlib

from appworld.common.constants import PASSWORD, SALT
from appworld.common.crypto import unpack_bundle

ROOT = pathlib.Path(__file__).resolve().parents[1]
files = unpack_bundle(bundle_file_path=str(ROOT / "data/protected/protected.bundle"),
                      base_directory=str(ROOT / "data"), password=PASSWORD, salt=SALT)
print(f"unpacked {len(files)} files into data/protected/")
# scripts that embed protected content travel in the bundle; put them back into scripts/
import shutil
src = ROOT / "data/protected/scripts"
for f in src.rglob("*"):
    if f.is_file():
        dst = ROOT / "scripts" / f.relative_to(src)
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(f, dst)
        print("restored", dst.relative_to(ROOT))
