import pytest

BUILD_PROP = """\
# begin build properties
ro.product.system.brand=Xiaomi
ro.product.system.manufacturer=Xiaomi
ro.product.system.model=Mi 11
ro.product.system.device=venus
ro.product.cpu.abilist=arm64-v8a,armeabi-v7a,armeabi
ro.build.version.release=13
ro.build.version.sdk=33
ro.build.fingerprint=Xiaomi/venus/venus:13/TKQ1.220829.002/V14.0.4.0:user/release-keys
"""

VENDOR_PROP = """\
ro.board.platform=lahaina
ro.soc.manufacturer=QTI
ro.product.vendor.device=venus
ro.hardware=qcom
"""


def _write(path, content=""):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


@pytest.fixture
def dump_dir(tmp_path):
    """A minimal but realistic dumpyara-style Android dump."""
    root = tmp_path / "dump"

    _write(root / "system" / "system" / "build.prop", BUILD_PROP)
    _write(root / "system" / "system" / "bin" / "qti_hook")
    _write(root / "system" / "system" / "lib64" / "libqti-perfd-client.so")
    _write(root / "system" / "system" / "lib64" / "libandroid_runtime.so")
    _write(root / "system" / "system" / "etc" / "selinux" / "plat_sepolicy.cil")

    _write(root / "vendor" / "build.prop", VENDOR_PROP)
    _write(root / "vendor" / "bin" / "hw" / "android.hardware.gnss@2.1-service-qti")
    _write(root / "vendor" / "lib64" / "hw" / "camera.qcom.so")
    _write(root / "vendor" / "lib64" / "libaudioroute.so")
    _write(root / "vendor" / "firmware" / "adsp.mbn")
    _write(root / "vendor" / "etc" / "init" / "init.qcom.rc")
    _write(root / "vendor" / "etc" / "media_codecs.xml")

    _write(root / "product" / "etc" / "build.prop", "ro.product.product.name=venus\n")
    _write(root / "product" / "priv-app" / "QtiApp" / "QtiApp.apk")

    return root
