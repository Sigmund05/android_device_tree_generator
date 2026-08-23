import struct

import pytest

from qcomdtgen.bootimg import find_image, load_boot_image, read_boot_image
from qcomdtgen.context import build_context
from qcomdtgen.dump import AndroidDump
from qcomdtgen.templates_engine import render


def write_boot_image(path, header_version, page_size=4096, magic=b"ANDROID!"):
    """A boot image header; only the fields the parser reads are filled in."""
    header = bytearray(4096)
    header[0:8] = magic
    if header_version < 3:
        struct.pack_into("<I", header, 36, page_size)
    struct.pack_into("<I", header, 40, header_version)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(header))
    return path


@pytest.mark.parametrize("version", [0, 1, 2, 3, 4])
def test_reads_every_header_version(tmp_path, version):
    boot = read_boot_image(write_boot_image(tmp_path / "boot.img", version))
    assert boot is not None
    assert boot.header_version == version


def test_page_size_comes_from_the_header_before_v3(tmp_path):
    boot = read_boot_image(write_boot_image(tmp_path / "boot.img", 2, page_size=2048))
    assert boot.page_size == 2048


def test_page_size_is_fixed_from_v3(tmp_path):
    """v3 dropped the field, so a stale value in that slot is ignored."""
    boot = read_boot_image(write_boot_image(tmp_path / "boot.img", 3, page_size=2048))
    assert boot.page_size == 4096


def test_bogus_page_size_falls_back(tmp_path):
    boot = read_boot_image(write_boot_image(tmp_path / "boot.img", 1, page_size=1234))
    assert boot.page_size == 4096


def test_not_a_boot_image(tmp_path):
    assert read_boot_image(write_boot_image(tmp_path / "x.img", 2, magic=b"NOTBOOT!")) is None
    assert read_boot_image(tmp_path / "missing.img") is None
    (tmp_path / "short.img").write_bytes(b"ANDROID!")
    assert read_boot_image(tmp_path / "short.img") is None


def test_unknown_header_version(tmp_path):
    assert read_boot_image(write_boot_image(tmp_path / "boot.img", 9)) is None


@pytest.mark.parametrize("location", ["boot.img", "images/boot.img", "IMAGES/boot.img"])
def test_finds_the_boot_image_in_common_layouts(tmp_path, location):
    write_boot_image(tmp_path / location, 4)
    assert find_image(tmp_path, "boot.img") == tmp_path / location
    assert load_boot_image(tmp_path).header_version == 4


def test_board_config_uses_the_boot_header_version(dump_dir):
    write_boot_image(dump_dir / "boot.img", 3)
    dump = AndroidDump(dump_dir)
    assert dump.boot_image.header_version == 3
    assert "header v3" in dump.summary()["boot image"]

    rendered = render("BoardConfig.mk", build_context(dump))
    assert "BOARD_BOOT_HEADER_VERSION := 3" in rendered
    assert "BOARD_KERNEL_PAGESIZE := 4096" in rendered
    assert "BOARD_FLASH_BLOCK_SIZE := 262144" in rendered


def test_page_size_drives_the_flash_block_size(dump_dir):
    write_boot_image(dump_dir / "boot.img", 2, page_size=2048)
    rendered = render("BoardConfig.mk", build_context(AndroidDump(dump_dir)))
    assert "BOARD_KERNEL_PAGESIZE := 2048" in rendered
    assert "BOARD_FLASH_BLOCK_SIZE := 131072" in rendered


def test_without_a_boot_image_the_version_is_a_todo(dump_dir):
    dump = AndroidDump(dump_dir)
    assert dump.boot_image is None
    assert dump.summary()["boot image"] == "not found in dump"

    rendered = render("BoardConfig.mk", build_context(dump))
    assert "BOARD_BOOT_HEADER_VERSION := 4 # TODO" in rendered


VENDOR_BOOT_CMDLINE = "console=ttyMSM0,115200n8 androidboot.hardware=qcom loop.max_part=7"


def write_vendor_boot_image(path, header_version=4, page_size=4096, cmdline="", magic=b"VNDRBOOT"):
    header = bytearray(4096)
    header[0:8] = magic
    struct.pack_into("<I", header, 8, header_version)
    struct.pack_into("<I", header, 12, page_size)
    encoded = cmdline.encode()
    header[28 : 28 + len(encoded)] = encoded
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(bytes(header))
    return path


def test_reads_the_vendor_boot_cmdline(tmp_path):
    from qcomdtgen.bootimg import load_vendor_boot_image, read_vendor_boot_image

    path = write_vendor_boot_image(tmp_path / "vendor_boot.img", cmdline=VENDOR_BOOT_CMDLINE)
    image = read_vendor_boot_image(path)
    assert image.kind == "vendor_boot"
    assert image.header_version == 4
    assert image.cmdline == VENDOR_BOOT_CMDLINE
    assert load_vendor_boot_image(tmp_path).cmdline == VENDOR_BOOT_CMDLINE


def test_rejects_a_boot_image_as_vendor_boot(tmp_path):
    from qcomdtgen.bootimg import read_vendor_boot_image

    assert read_vendor_boot_image(write_boot_image(tmp_path / "boot.img", 4)) is None


def test_boot_cmdline_before_v3_joins_both_fields(tmp_path):
    header = bytearray(4096)
    header[0:8] = b"ANDROID!"
    struct.pack_into("<I", header, 36, 4096)
    struct.pack_into("<I", header, 40, 2)
    first, extra = b"console=ttyMSM0,115200n8", b"androidboot.hardware=x"
    header[64 : 64 + len(first)] = first
    header[608 : 608 + len(extra)] = extra
    path = tmp_path / "boot.img"
    path.write_bytes(bytes(header))
    assert read_boot_image(path).cmdline == "console=ttyMSM0,115200n8 androidboot.hardware=x"


def test_vendor_boot_cmdline_wins_over_boot(dump_dir):
    write_boot_image(dump_dir / "boot.img", 4)
    write_vendor_boot_image(dump_dir / "vendor_boot.img", cmdline=VENDOR_BOOT_CMDLINE)
    dump = AndroidDump(dump_dir)
    assert dump.kernel_cmdline == VENDOR_BOOT_CMDLINE

    rendered = render("BoardConfig.mk", build_context(dump))
    assert "BOARD_KERNEL_CMDLINE := \\\n" in rendered
    assert "    console=ttyMSM0,115200n8 \\\n" in rendered
    assert "    loop.max_part=7\n" in rendered


def test_cmdline_falls_back_to_boot(dump_dir):
    header = bytearray(4096)
    header[0:8] = b"ANDROID!"
    struct.pack_into("<I", header, 40, 3)
    cmdline = b"buildvariant=userdebug"
    header[44 : 44 + len(cmdline)] = cmdline
    (dump_dir / "boot.img").write_bytes(bytes(header))
    assert AndroidDump(dump_dir).kernel_cmdline == "buildvariant=userdebug"


def test_no_cmdline_leaves_a_todo(dump_dir):
    write_boot_image(dump_dir / "boot.img", 4)
    rendered = render("BoardConfig.mk", build_context(AndroidDump(dump_dir)))
    assert "BOARD_KERNEL_CMDLINE := # TODO" in rendered
