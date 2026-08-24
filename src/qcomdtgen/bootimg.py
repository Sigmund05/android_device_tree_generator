"""Reading the Android boot and vendor_boot image headers.

Only the headers are parsed - they are the one place a dump states its boot
header version, kernel cmdline and load addresses, none of which any
build.prop property carries.

Field layout and decoding follow AOSP's mkbootimg:
``system/tools/mkbootimg/include/bootimg/bootimg.h`` for the packed structs
and ``unpack_bootimg.py`` for how they are read back.  Handy detail of the
boot format: ``header_version`` is the ninth uint32 after the magic in every
version from v0 to v4, so it can be read before the layout is known.
"""

from __future__ import annotations

import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

BOOT_MAGIC = b"ANDROID!"
VENDOR_BOOT_MAGIC = b"VNDRBOOT"

_MAX_HEADER_VERSION = 4
#: v3 dropped the page size field: "all entities in the boot image are
#: 4096-byte aligned in flash" (bootimg.h).
_V3_PAGE_SIZE = 4096
#: Enough for either header, including boot v2's trailing dtb fields.
_HEADER_READ_SIZE = 4096

#: mkbootimg's default --kernel_offset, i.e. kernel_addr - base.  Load
#: addresses are stored absolute, so this is what turns them back into the
#: base plus offsets a BoardConfig.mk is written with.
KERNEL_OFFSET = 0x00008000

# boot_img_hdr_v0 - v2: magic[8] then nine uint32, header_version last.
_BOOT_HEAD = struct.Struct("<8s9I")
# ... for v0 - v2 those nine are:
_BOOT_V2_FIELDS = (
    "kernel_size",
    "kernel_address",
    "ramdisk_size",
    "ramdisk_address",
    "second_size",
    "second_address",
    "tags_address",
    "page_size",
    "header_version",
)
# ... and for v3 - v4 only the first three and the last are used:
_BOOT_V3_FIELDS = ("kernel_size", "ramdisk_size", "os_version_patch_level")
_HEADER_VERSION_INDEX = 8

# Trailing fields, all little endian and unaligned (the structs are packed).
_BOOT_V2_OS_VERSION = 44
_BOOT_V2_CMDLINE = (64, 512)  # BOOT_ARGS_SIZE
_BOOT_V2_EXTRA_CMDLINE = (608, 1024)  # BOOT_EXTRA_ARGS_SIZE
_BOOT_V1_RECOVERY_DTBO_SIZE = 1632
_BOOT_V2_DTB = 1648  # uint32 dtb_size, then uint64 dtb_addr
_BOOT_V3_CMDLINE = (44, 512 + 1024)

# vendor_boot_img_hdr_v3: magic[8], header_version, page_size, kernel_addr,
# ramdisk_addr, vendor_ramdisk_size, cmdline[2048], tags_addr, name[16],
# header_size, dtb_size, dtb_addr.
_VENDOR_HEAD = struct.Struct("<8s5I")
_VENDOR_CMDLINE = (28, 2048)  # VENDOR_BOOT_ARGS_SIZE
_VENDOR_TAIL = struct.Struct("<I16sIIQ")
_VENDOR_TAIL_OFFSET = 2076

#: Where dump tools leave the images, relative to the dump root.
_IMAGE_DIRS: List[str] = ["", "images", "IMAGES", "boot", "firmware"]


@dataclass
class BootImage:
    """The header fields of a boot or vendor_boot image."""

    path: Path
    kind: str
    header_version: int
    page_size: int
    cmdline: str = ""
    #: "13.0.0" and "2023-08", decoded from the packed os_version field.
    os_version: str = ""
    os_patch_level: str = ""
    #: Absolute load addresses; zero when the format does not carry them.
    kernel_address: int = 0
    ramdisk_address: int = 0
    second_address: int = 0
    tags_address: int = 0
    dtb_address: int = 0
    #: Only the recovery dtbo size is read back: it decides whether the tree
    #: sets BOARD_INCLUDE_RECOVERY_DTBO.
    recovery_dtbo_size: int = 0

    # -- derived -----------------------------------------------------------

    @property
    def has_load_addresses(self) -> bool:
        """boot v3 dropped them; they live in vendor_boot from then on.

        A kernel address below the offset mkbootimg puts it at cannot have
        come from a base plus that offset, so it is treated as absent rather
        than turned into a negative base.
        """
        return self.kernel_address >= KERNEL_OFFSET

    @property
    def base_address(self) -> Optional[int]:
        """The BOARD_KERNEL_BASE the load addresses were built from."""
        if not self.has_load_addresses:
            return None
        return self.kernel_address - KERNEL_OFFSET

    def offset_of(self, address: int) -> Optional[int]:
        """Turn an absolute load address back into an offset from the base."""
        base = self.base_address
        if base is None or address == 0 or address < base:
            return None
        return address - base

    def describe(self) -> str:
        parts = [f"header v{self.header_version}", f"{self.page_size} byte pages"]
        if self.os_version:
            parts.append(f"Android {self.os_version}")
        if self.os_patch_level:
            parts.append(f"patch {self.os_patch_level}")
        if self.base_address is not None:
            parts.append(f"base {self.base_address:#010x}")
        return ", ".join(parts)


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
    if len(header) < _BOOT_HEAD.size:
        return None

    values = _BOOT_HEAD.unpack_from(header)[1:]
    header_version = values[_HEADER_VERSION_INDEX]
    if header_version > _MAX_HEADER_VERSION:
        return None

    if header_version < 3:
        return _boot_image_v2(path, header, header_version, values)
    return _boot_image_v3(path, header, header_version, values)


def read_vendor_boot_image(path: os.PathLike | str) -> Optional[BootImage]:
    """Parse a vendor_boot.img header, or return None if it is not one."""
    path = Path(path)
    header = _read_header(path)
    if header is None or not header.startswith(VENDOR_BOOT_MAGIC):
        return None
    if len(header) < _VENDOR_TAIL_OFFSET + _VENDOR_TAIL.size:
        return None

    _, header_version, page_size, kernel_address, ramdisk_address, _ = (
        _VENDOR_HEAD.unpack_from(header)
    )
    if not 3 <= header_version <= _MAX_HEADER_VERSION:
        return None
    tags_address, _name, _header_size, _dtb_size, dtb_address = (
        _VENDOR_TAIL.unpack_from(header, _VENDOR_TAIL_OFFSET)
    )

    return BootImage(
        path=path,
        kind="vendor_boot",
        header_version=header_version,
        page_size=_page_size(page_size),
        cmdline=_cstr(header, *_VENDOR_CMDLINE),
        kernel_address=kernel_address,
        ramdisk_address=ramdisk_address,
        tags_address=tags_address,
        dtb_address=dtb_address,
    )


def load_boot_image(dump_path: os.PathLike | str) -> Optional[BootImage]:
    """Find and parse the dump's boot image, if it ships one."""
    path = find_image(dump_path, "boot.img")
    return read_boot_image(path) if path is not None else None


def load_vendor_boot_image(dump_path: os.PathLike | str) -> Optional[BootImage]:
    """Find and parse the dump's vendor_boot image, if it ships one."""
    path = find_image(dump_path, "vendor_boot.img")
    return read_vendor_boot_image(path) if path is not None else None


# -- boot image layouts ----------------------------------------------------


def _boot_image_v2(
    path: Path, header: bytes, header_version: int, values: Tuple[int, ...]
) -> BootImage:
    fields = dict(zip(_BOOT_V2_FIELDS, values))
    image = BootImage(
        path=path,
        kind="boot",
        header_version=header_version,
        page_size=_page_size(fields["page_size"]),
        cmdline=_join(
            _cstr(header, *_BOOT_V2_CMDLINE), _cstr(header, *_BOOT_V2_EXTRA_CMDLINE)
        ),
        kernel_address=fields["kernel_address"],
        ramdisk_address=fields["ramdisk_address"],
        second_address=fields["second_address"],
        tags_address=fields["tags_address"],
    )
    _set_os_version(image, _u32(header, _BOOT_V2_OS_VERSION))
    if header_version >= 1:
        image.recovery_dtbo_size = _u32(header, _BOOT_V1_RECOVERY_DTBO_SIZE)
    if header_version == 2 and len(header) >= _BOOT_V2_DTB + 12:
        # dtb_size is followed by the uint64 dtb_addr
        image.dtb_address = int.from_bytes(
            header[_BOOT_V2_DTB + 4 : _BOOT_V2_DTB + 12], "little"
        )
    return image


def _boot_image_v3(
    path: Path, header: bytes, header_version: int, values: Tuple[int, ...]
) -> BootImage:
    fields = dict(zip(_BOOT_V3_FIELDS, values))
    image = BootImage(
        path=path,
        kind="boot",
        header_version=header_version,
        page_size=_V3_PAGE_SIZE,
        cmdline=_join(_cstr(header, *_BOOT_V3_CMDLINE)),
    )
    _set_os_version(image, fields["os_version_patch_level"])
    return image


# -- field decoding --------------------------------------------------------


def _set_os_version(image: BootImage, packed: int) -> None:
    """Split the packed os_version field, as unpack_bootimg.py does.

    ``os_version = A[31:25] B[24:18] C[17:11] (Y-2000)[10:4] M[3:0]``
    """
    version, patch_level = packed >> 11, packed & ((1 << 11) - 1)
    if version:
        image.os_version = ".".join(
            str(part)
            for part in (version >> 14, (version >> 7) & 0x7F, version & 0x7F)
        )
    if patch_level:
        image.os_patch_level = f"{2000 + (patch_level >> 4):04}-{patch_level & 0xF:02}"


def _cstr(header: bytes, offset: int, size: int) -> str:
    """A NUL terminated ascii field."""
    raw = header[offset : offset + size]
    return raw.split(b"\x00", 1)[0].decode("ascii", errors="replace").strip()


def _join(*parts: str) -> str:
    """Merge cmdline fields into one whitespace normalised string."""
    return " ".join(" ".join(parts).split())


def _u32(header: bytes, offset: int) -> int:
    if len(header) < offset + 4:
        return 0
    return int.from_bytes(header[offset : offset + 4], "little")


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
    return _V3_PAGE_SIZE
