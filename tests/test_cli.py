import os

import pytest

from qcomdtgen.cli import build_parser, main


def test_defaults(dump_dir):
    args = build_parser().parse_args([str(dump_dir)])
    assert args.dump == dump_dir
    assert args.proprietary_files is True
    assert args.force is False


def test_no_proprietary_files_flag(dump_dir):
    args = build_parser().parse_args([str(dump_dir), "--no-proprietary-files"])
    assert args.proprietary_files is False


def test_run_writes_proprietary_files(dump_dir, tmp_path, capsys):
    out = tmp_path / "out"
    assert main([str(dump_dir), "-o", str(out)]) == 0
    generated = out / "device" / "xiaomi" / "venus" / "proprietary-files.txt"
    assert generated.is_file()
    assert "vendor/lib64/hw/camera.qcom.so" in generated.read_text()
    assert "venus" in capsys.readouterr().out


def test_run_without_proprietary_files(dump_dir, tmp_path):
    out = tmp_path / "out"
    assert main([str(dump_dir), "-o", str(out), "-P"]) == 0
    assert not (out / "device" / "xiaomi" / "venus" / "proprietary-files.txt").exists()


def test_non_empty_output_needs_force(dump_dir, tmp_path, capsys):
    out = tmp_path / "out"
    assert main([str(dump_dir), "-o", str(out)]) == 0
    assert main([str(dump_dir), "-o", str(out)]) == 1
    assert "--force" in capsys.readouterr().err
    assert main([str(dump_dir), "-o", str(out), "--force"]) == 0


def test_bad_dump_returns_error(tmp_path, capsys):
    assert main([str(tmp_path / "missing")]) == 1
    assert "error" in capsys.readouterr().err


def test_quiet(dump_dir, tmp_path, capsys):
    assert main([str(dump_dir), "-o", str(tmp_path / "out"), "-q"]) == 0
    assert capsys.readouterr().out == ""


def test_device_tree_layout(dump_dir, tmp_path):
    out = tmp_path / "android"
    assert main([str(dump_dir), "-o", str(out)]) == 0
    tree = out / "device" / "xiaomi" / "venus"
    assert sorted(p.name for p in tree.iterdir()) == [
        "Android.bp",
        "AndroidProducts.mk",
        "BoardConfig.mk",
        "device.mk",
        "extract-files.py",
        "lineage.dependencies",
        "lineage_venus.mk",
        "proprietary-files.txt",
        "setup-makefiles.py",
    ]


def test_blob_scripts_are_executable(dump_dir, tmp_path):
    out = tmp_path / "android"
    main([str(dump_dir), "-o", str(out)])
    tree = out / "device" / "xiaomi" / "venus"
    for name in ("extract-files.py", "setup-makefiles.py"):
        assert os.access(tree / name, os.X_OK), name


def test_blob_scripts_skipped_without_proprietary_files(dump_dir, tmp_path):
    out = tmp_path / "android"
    main([str(dump_dir), "-o", str(out), "-P"])
    tree = out / "device" / "xiaomi" / "venus"
    assert not (tree / "extract-files.py").exists()
    assert not (tree / "setup-makefiles.py").exists()
    # the base templates are still generated
    assert (tree / "BoardConfig.mk").is_file()
    assert "BoardConfigVendor.mk" not in (tree / "BoardConfig.mk").read_text()


def test_force_clears_the_previous_run(dump_dir, tmp_path):
    """A rerun without blobs must not leave the extract scripts behind."""
    out = tmp_path / "android"
    assert main([str(dump_dir), "-o", str(out)]) == 0
    tree = out / "device" / "xiaomi" / "venus"
    assert (tree / "extract-files.py").is_file()

    assert main([str(dump_dir), "-o", str(out), "-P", "--force"]) == 0
    assert not (tree / "extract-files.py").exists()
    assert not (tree / "setup-makefiles.py").exists()
    assert not (tree / "proprietary-files.txt").exists()
    assert (tree / "BoardConfig.mk").is_file()


def test_force_keeps_files_the_tool_does_not_own(dump_dir, tmp_path):
    out = tmp_path / "android"
    main([str(dump_dir), "-o", str(out)])
    tree = out / "device" / "xiaomi" / "venus"
    (tree / "sepolicy").mkdir()
    (tree / "sepolicy" / "vendor.te").write_text("# hand written\n")
    (tree / "manifest.xml").write_text("<manifest/>\n")

    assert main([str(dump_dir), "-o", str(out), "--force"]) == 0
    assert (tree / "sepolicy" / "vendor.te").read_text() == "# hand written\n"
    assert (tree / "manifest.xml").is_file()


def test_result_lists_every_written_file(dump_dir, tmp_path):
    from qcomdtgen.generator import DeviceTreeGenerator, GeneratorOptions

    generator = DeviceTreeGenerator(
        GeneratorOptions(dump_path=dump_dir, android_top=tmp_path / "android")
    )
    result = generator.run()
    assert result.file_count == 9
    assert result.blob_count > 0
    assert all(path.is_file() for path in result.written)
    assert result.device_dir.name == "venus"


def test_unsupported_platform_warning_survives_quiet(dump_dir, tmp_path, capsys):
    (dump_dir / "vendor" / "build.prop").write_text("ro.board.platform=exynos2200\n")
    assert main([str(dump_dir), "-o", str(tmp_path / "android"), "-q"]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "hardware/qcom-caf/common supports" in captured.err


def test_no_warning_for_a_supported_platform(dump_dir, tmp_path, capsys):
    assert main([str(dump_dir), "-o", str(tmp_path / "android")]) == 0
    assert "warning" not in capsys.readouterr().err


def test_broken_pipe_exits_like_a_shell_does(dump_dir, tmp_path, monkeypatch):
    """`qcomdtgen ... | head` must not end in a traceback."""
    import builtins

    from qcomdtgen import cli

    monkeypatch.setattr(cli, "_close_stdout", lambda: None)

    def explode(*args, **kwargs):
        raise BrokenPipeError

    monkeypatch.setattr(builtins, "print", explode)
    assert main([str(dump_dir), "-o", str(tmp_path / "android")]) == cli.EXIT_BROKEN_PIPE


def test_help_keeps_the_examples_readable(capsys):
    with pytest.raises(SystemExit) as exit_info:
        build_parser().parse_args(["--help"])
    assert exit_info.value.code == 0
    help_text = capsys.readouterr().out
    assert "qcomdtgen ~/dumps/venus -o ~/android/lineage  write into an Android tree" in help_text


def test_a_symlinked_output_directory_is_refused(dump_dir, tmp_path, capsys):
    real = tmp_path / "elsewhere"
    real.mkdir()
    link_parent = tmp_path / "android" / "device" / "xiaomi"
    link_parent.mkdir(parents=True)
    (link_parent / "venus").symlink_to(real, target_is_directory=True)

    assert main([str(dump_dir), "-o", str(tmp_path / "android")]) == 1
    assert "symlink" in capsys.readouterr().err
    assert not any(real.iterdir())
