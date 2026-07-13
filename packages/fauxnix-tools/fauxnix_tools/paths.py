from __future__ import annotations

import os
from pathlib import Path


FAUXNIX_ROOT = Path(os.getenv("FAUXNIX_ROOT", "/home/chxk/Projects/fauxnix-core"))
FAUXNIX_ROOT_STR = str(FAUXNIX_ROOT)

WSCI_BOOT_BIND = f"{FAUXNIX_ROOT_STR}:/fauxnix-core"

NEXUS_PYTHONPATH = ":".join([
    f"{FAUXNIX_ROOT_STR}/packages/nexus",
    f"{FAUXNIX_ROOT_STR}/packages/fauxnix-tools",
])

FENNIX_PYTHONPATH = ":".join([
    f"{FAUXNIX_ROOT_STR}/packages/fennix",
    f"{FAUXNIX_ROOT_STR}/packages/fauxnix-tools",
])

ARCHIVIST_PYTHONPATH = ":".join([
    f"{FAUXNIX_ROOT_STR}/packages/archivist",
    f"{FAUXNIX_ROOT_STR}/packages/fauxnix-tools",
])
