import pytest

from qcomdtgen.dump import AndroidDump
from qcomdtgen.errors import DumpError


def test_detects_partitions_and_props(dump_dir):
    dump = AndroidDump(dump_dir)
    assert set(dump.partitions) >= {"system", "vendor", "product"}
    assert dump.device == "venus"
    assert dump.manufacturer == "Xiaomi"
    assert dump.vendor == "xiaomi"
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
