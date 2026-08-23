"""Reading the Android boot and vendor_boot image headers.

Only the headers are parsed - they are the one place a dump states its boot
header version and kernel cmdline, neither of which any build.prop property
carries.  Handy detail of the boot format: ``header_version`` sits at offset 40
in every version from v0 to v4, so the field can be read before knowing which
layout follows it.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

BOOT_MAGIC = b"ANDROID!"
VENDOR_BOOT_MAGIC = b"VNDRBOOT"

_MAX_HEADER_VERSION = 4
_DEFAULT_PAGE_SIZE = 4096
#: Enough for either header, including vendor_boot's 2048 byte cmdline.
_HEADER_READ_SIZE = 4096

# boot.img, all versions: header_version at 40.  v0 - v2 additionally declare
# the page size at 36 and split the cmdline in two (512 bytes at 64, another
# 1024 at 608); v3 merged them into one 1536 byte field at 44.
_BOOT_HEADER_VERSION_OFFSET = 40
_BOOT_PAGE_SIZE_OFFSET = 36
_BOOT_CMDLINE = (64, 512)
_BOOT_EXTRA_CMDLINE = (608, 1024)
_BOOT_V3_CMDLINE = (44, 1536)

# vendor_boot.img: magic, then header_version at 8, page size at 12 and a
# single 2048 byte cmdline at 28.
_VENDOR_HEADER_VERSION_OFFSET = 8
_VENDOR_PAGE_SIZE_OFFSET = 12
_VENDOR_CMDLINE = (28, 2048)

#: Where dump tools leave the images, relative to the dump root.
_IMAGE_DIRS: List[str] = ["", "images", "IMAGES", "boot", "firmware"]


@dataclass
class BootImage:
    """The handful of header fields a device tree needs."""

    path: Path
    kind: str
    header_version: int
    page_size: int
    cmdline: str

    def describe(self) -> str:
        return f"header v{self.header_version}, {self.page_size} byte pages"


def _read_u32(header: bytes, offset: int) -> int:
    return int.from_bytes(header[offset : offset + 4], "little")


def _read_string(header: bytes, offset: int, size: int) -> str:
    raw = header[offset : offset + size]
    return raw.split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()


def _join_cmdline(*parts: str) -> str:
    """Merge cmdline fields into one whitespace normalised string."""
    return " ".join(" ".join(parts).split())


def find_image(dump_path: os.PathLike | str, name: str) -> Optional[Path]:
    """Locate an image inside a dump, whichever tool laid it out."""
    root = Path(dump_path)
    for directory in _IMAGE_DIRS:
        candidate = (root / directory / name) if directory else (root / name)
        if candidate.is_file():
            return candidate
    return None


def read_boot_image(path: os.PathLike | str) -> Optional[BootImage]:
    """Parse a boot.img header, or return None if it is not one."""
    path = Path(path)
    header = _read_header(path)
    if header is None or not header.startswith(BOOT_MAGIC):
        return None
    if len(header) < _BOOT_HEADER_VERSION_OFFSET + 4:
        return None

    header_version = _read_u32(header, _BOOT_HEADER_VERSION_OFFSET)
    if header_version > _MAX_HEADER_VERSION:
        return None

    page_size = _DEFAULT_PAGE_SIZE
    if header_version < 3:
        page_size = _page_size(_read_u32(header, _BOOT_PAGE_SIZE_OFFSET))
        cmdline = _join_cmdline(
            _read_string(header, *_BOOT_CMDLINE),
            _read_string(header, *_BOOT_EXTRA_CMDLINE),
        )
    else:
        cmdline = _join_cmdline(_read_string(header, *_BOOT_V3_CMDLINE))

    return BootImage(
        path=path,
        kind="boot",
        header_version=header_version,
        page_size=page_size,
        cmdline=cmdline,
    )


def read_vendor_boot_image(path: os.PathLike | str) -> Optional[BootImage]:
    """Parse a vendor_boot.img header, or return None if it is not one."""
    path = Path(path)
    header = _read_header(path)
    if header is None or not header.startswith(VENDOR_BOOT_MAGIC):
        return None
    if len(header) < sum(_VENDOR_CMDLINE):
        return None

    header_version = _read_u32(header, _VENDOR_HEADER_VERSION_OFFSET)
    if not 3 <= header_version <= _MAX_HEADER_VERSION:
        return None

    return BootImage(
        path=path,
        kind="vendor_boot",
        header_version=header_version,
        page_size=_page_size(_read_u32(header, _VENDOR_PAGE_SIZE_OFFSET)),
        cmdline=_join_cmdline(_read_string(header, *_VENDOR_CMDLINE)),
    )


def load_boot_image(dump_path: os.PathLike | str) -> Optional[BootImage]:
    """Find and parse the dump's boot image, if it ships one."""
    path = find_image(dump_path, "boot.img")
    return read_boot_image(path) if path is not None else None


def load_vendor_boot_image(dump_path: os.PathLike | str) -> Optional[BootImage]:
    """Find and parse the dump's vendor_boot image, if it ships one."""
    path = find_image(dump_path, "vendor_boot.img")
    return read_vendor_boot_image(path) if path is not None else None


def _read_header(path: Path) -> Optional[bytes]:
    try:
        with path.open("rb") as image:
            return image.read(_HEADER_READ_SIZE)
    except OSError:
        return None


def _page_size(declared: int) -> int:
    """Real images use a power of two between 2K and 64K; ignore junk."""
    if 2048 <= declared <= 65536 and declared & (declared - 1) == 0:
        return declared
    return _DEFAULT_PAGE_SIZE
