import pytest

from qcomdtgen.dump import AndroidDump
from qcomdtgen.errors import DumpError


def test_detects_partitions_and_props(dump_dir):
    dump = AndroidDump(dump_dir)
    assert set(dump.partitions) >= {"system", "vendor", "product"}
    assert dump.device == "venus"
    assert dump.manufacturer == "Xiaomi"
    assert dump.manufacturer_dir == "xiaomi"
    assert dump.model == "Mi 11"
    assert dump.platform == "lahaina"
    assert dump.arch == "arm64"
    assert dump.api_level == 33
    assert dump.is_qualcomm


def test_system_root_layout(tmp_path):
    """A dump where system/ is the partition root, not system/system/."""
    root = tmp_path / "dump"
    (root / "system" / "etc").mkdir(parents=True)
    (root / "system" / "build.prop").write_text("ro.product.device=foo\n")
    dump = AndroidDump(root)
    assert dump.device == "foo"


def test_missing_path(tmp_path):
    with pytest.raises(DumpError):
        AndroidDump(tmp_path / "nope")


def test_empty_dir_is_rejected(tmp_path):
    with pytest.raises(DumpError):
        AndroidDump(tmp_path)


def test_x86_dump_is_rejected(tmp_path):
    root = tmp_path / "dump"
    (root / "system" / "etc").mkdir(parents=True)
    (root / "system" / "build.prop").write_text(
        "ro.product.device=emulator\nro.product.cpu.abilist=x86_64,x86\n"
    )
    with pytest.raises(DumpError, match="only handles ARM"):
        AndroidDump(root)


def test_arm32_only_dump_is_rejected(tmp_path):
    root = tmp_path / "dump"
    (root / "system" / "etc").mkdir(parents=True)
    (root / "system" / "build.prop").write_text(
        "ro.product.device=foo\nro.product.cpu.abilist=armeabi-v7a,armeabi\n"
    )
    with pytest.raises(DumpError, match="only handles 64-bit"):
        AndroidDump(root)


def test_64_bit_only_dump(tmp_path):
    root = tmp_path / "dump"
    (root / "system" / "etc").mkdir(parents=True)
    (root / "system" / "build.prop").write_text(
        "ro.product.device=foo\nro.product.cpu.abilist=arm64-v8a\n"
    )
    dump = AndroidDump(root)
    assert dump.arch == "arm64"
    assert not dump.supports_32_bit_apps


def test_manufacturer_dir_is_lowercased(tmp_path):
    root = tmp_path / "dump"
    (root / "system" / "etc").mkdir(parents=True)
    (root / "system" / "build.prop").write_text(
        "ro.product.device=foo\n"
        "ro.product.manufacturer=INFINIX MOBILITY LIMITED\n"
        "ro.product.cpu.abilist=arm64-v8a\n"
    )
    dump = AndroidDump(root)
    assert dump.manufacturer == "INFINIX MOBILITY LIMITED"
    assert dump.manufacturer_dir == "infinix_mobility_limited"


def test_manufacturer_falls_back_to_the_brand(tmp_path):
    root = tmp_path / "dump"
    (root / "system" / "etc").mkdir(parents=True)
    (root / "system" / "build.prop").write_text(
        "ro.product.device=foo\nro.product.brand=FCNT\nro.product.cpu.abilist=arm64-v8a\n"
    )
    dump = AndroidDump(root)
    assert dump.manufacturer == "FCNT"
    assert dump.manufacturer_dir == "fcnt"
