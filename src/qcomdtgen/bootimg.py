"""Reading the Android boot image header.

Only the header is parsed - it is the one place a dump states its boot header
version, which no build.prop property carries.  Handy detail of the format:
``header_version`` sits at offset 40 in every version from v0 to v4, so the
field can be read before knowing which layout follows it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

BOOT_MAGIC = b"ANDROID!"

#: Offsets shared by every boot header version.
_HEADER_VERSION_OFFSET = 40
#: Page size only exists as a field in v0 - v2; v3 and v4 fixed it at 4096.
_PAGE_SIZE_OFFSET = 36
_DEFAULT_PAGE_SIZE = 4096
_MAX_HEADER_VERSION = 4

#: Where dump tools leave the boot image, relative to the dump root.
_BOOT_IMAGE_NAMES: List[str] = [
    "boot.img",
    "images/boot.img",
    "IMAGES/boot.img",
    "boot/boot.img",
    "firmware/boot.img",
]


@dataclass
class BootImage:
    """The handful of header fields a device tree needs."""

    path: Path
    header_version: int
    page_size: int

    def describe(self) -> str:
        return f"header v{self.header_version}, {self.page_size} byte pages"


def find_boot_image(dump_path: os.PathLike | str) -> Optional[Path]:
    """Locate boot.img inside a dump, whichever tool laid it out."""
    root = Path(dump_path)
    for name in _BOOT_IMAGE_NAMES:
        candidate = root / name
        if candidate.is_file():
            return candidate
    return None


def read_boot_image(path: os.PathLike | str) -> Optional[BootImage]:
    """Parse a boot image header, or return None if it is not one."""
    path = Path(path)
    try:
        with path.open("rb") as image:
            header = image.read(64)
    except OSError:
        return None

    if len(header) < _HEADER_VERSION_OFFSET + 4 or not header.startswith(BOOT_MAGIC):
        return None

    header_version = int.from_bytes(
        header[_HEADER_VERSION_OFFSET : _HEADER_VERSION_OFFSET + 4], "little"
    )
    if header_version > _MAX_HEADER_VERSION:
        return None

    page_size = _DEFAULT_PAGE_SIZE
    if header_version < 3:
        declared = int.from_bytes(
            header[_PAGE_SIZE_OFFSET : _PAGE_SIZE_OFFSET + 4], "little"
        )
        # Real images use a power of two between 2K and 64K; ignore junk.
        if 2048 <= declared <= 65536 and declared & (declared - 1) == 0:
            page_size = declared

    return BootImage(path=path, header_version=header_version, page_size=page_size)


def load_boot_image(dump_path: os.PathLike | str) -> Optional[BootImage]:
    """Find and parse the dump's boot image, if it ships one."""
    path = find_boot_image(dump_path)
    return read_boot_image(path) if path is not None else None
