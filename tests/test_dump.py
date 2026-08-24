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
    assert dump.is_supported_platform


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


def test_manufacturer_punctuation_is_folded_away(tmp_path):
    """"TCL Communication Ltd." must not become a path ending in a dot."""
    root = tmp_path / "dump"
    (root / "system" / "etc").mkdir(parents=True)
    (root / "system" / "build.prop").write_text(
        "ro.product.device=foo\n"
        "ro.product.manufacturer=TCL Communication Ltd.\n"
        "ro.product.cpu.abilist=arm64-v8a\n"
    )
    assert AndroidDump(root).manufacturer_dir == "tcl_communication_ltd"


def test_device_codename_keeps_its_case(tmp_path):
    root = tmp_path / "dump"
    (root / "system" / "etc").mkdir(parents=True)
    (root / "system" / "build.prop").write_text(
        "ro.product.device=M06\n"
        "ro.product.manufacturer=FCNT\n"
        "ro.product.cpu.abilist=arm64-v8a\n"
    )
    dump = AndroidDump(root)
    assert dump.device == "M06"
    # only the manufacturer directory is lowercased
    assert dump.manufacturer_dir == "fcnt"


def test_device_codename_cannot_escape_the_tree(tmp_path):
    root = tmp_path / "dump"
    (root / "system" / "etc").mkdir(parents=True)
    (root / "system" / "build.prop").write_text(
        "ro.product.device=../escape\nro.product.cpu.abilist=arm64-v8a\n"
    )
    assert AndroidDump(root).device == "escape"


def _platform_dump(tmp_path, platform):
    root = tmp_path / platform
    (root / "system" / "etc").mkdir(parents=True)
    (root / "system" / "build.prop").write_text(
        f"ro.product.device=foo\nro.board.platform={platform}\n"
        "ro.product.cpu.abilist=arm64-v8a\n"
    )
    return root


@pytest.mark.parametrize(
    "platform",
    ["msmnile", "kona", "lahaina", "parrot", "sun", "LAHAINA"],  # case must not matter
)
def test_supported_platforms_come_from_qcom_caf_common(tmp_path, platform):
    assert AndroidDump(_platform_dump(tmp_path, platform)).is_supported_platform


@pytest.mark.parametrize("platform", ["mt6893", "exynos2200", "ums512", "sm8450"])
def test_a_platform_off_the_list_is_refused(tmp_path, platform):
    with pytest.raises(DumpError, match="unsupported platform"):
        AndroidDump(_platform_dump(tmp_path, platform))


@pytest.mark.parametrize("platform", ["msm8996", "msm8998", "sdm660", "sdm845"])
def test_legacy_platforms_are_refused(tmp_path, platform):
    """Everything before UM 4.14 is out of scope."""
    with pytest.raises(DumpError, match="unsupported platform"):
        AndroidDump(_platform_dump(tmp_path, platform))


def test_a_dump_naming_no_platform_is_still_read(tmp_path):
    """Nothing proves it is another vendor, so this one only warns."""
    root = tmp_path / "dump"
    (root / "system" / "etc").mkdir(parents=True)
    (root / "system" / "build.prop").write_text(
        "ro.product.device=foo\nro.product.cpu.abilist=arm64-v8a\n"
    )
    dump = AndroidDump(root)
    assert dump.platform == "unknown"
    assert not dump.is_supported_platform


def test_the_platform_list_is_qcom_boards_mk_from_um_4_14():
    """The 16 UM 4.14+ entries of qcom_boards.mk on lineage-23.2."""
    from qcomdtgen.dump import QCOM_BOARD_PLATFORMS

    assert QCOM_BOARD_PLATFORMS == {
        "msmnile", "sm6150", "trinket", "atoll",
        "kona", "lito", "bengal",
        "lahaina", "holi",
        "taro", "parrot",
        "kalama", "crow",
        "pineapple", "volcano",
        "sun",
    }  # fmt: skip


def test_system_wins_over_vendor_for_product_props(tmp_path):
    """The merged table lets vendor win; ro.product.* must not follow it."""
    root = tmp_path / "dump"
    (root / "system" / "etc").mkdir(parents=True)
    (root / "vendor").mkdir(parents=True)
    (root / "system" / "build.prop").write_text(
        "ro.product.device=marketingname\nro.product.cpu.abilist=arm64-v8a\n"
    )
    (root / "vendor" / "build.prop").write_text("ro.product.device=internalname\n")
    dump = AndroidDump(root)
    assert dump.device == "marketingname"
    # the merged table still prefers vendor for the vendor specific keys
    assert dump.props["ro.product.device"] == "internalname"
