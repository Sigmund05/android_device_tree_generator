from qcomdtgen.dump import AndroidDump
from qcomdtgen.proprietary import collect_blobs


def test_collect_blobs(dump_dir):
    dump = AndroidDump(dump_dir)
    blobs = collect_blobs(dump)
    entries = [entry for paths in blobs.sections.values() for entry in paths]

    # vendor blobs keep their partition prefix, system blobs do not
    assert "vendor/lib64/hw/camera.qcom.so" in entries
    assert "vendor/firmware/adsp.mbn" in entries
    assert "lib64/libqti-perfd-client.so" in entries
    assert "product/priv-app/QtiApp/QtiApp.apk" in entries

    # noise is filtered out
    assert "lib64/libandroid_runtime.so" not in entries
    assert "etc/selinux/plat_sepolicy.cil" not in entries
    assert "vendor/etc/init/init.qcom.rc" not in entries

    rendered = blobs.render(dump)
    assert "# Camera" in rendered
    assert rendered.endswith("\n")


def test_sections_are_sorted(dump_dir):
    blobs = collect_blobs(AndroidDump(dump_dir))
    for paths in blobs.sections.values():
        assert paths == sorted(paths)
