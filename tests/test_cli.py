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
    generated = out / "xiaomi" / "venus" / "proprietary-files.txt"
    assert generated.is_file()
    assert "vendor/lib64/hw/camera.qcom.so" in generated.read_text()
    assert "venus" in capsys.readouterr().out


def test_run_without_proprietary_files(dump_dir, tmp_path):
    out = tmp_path / "out"
    assert main([str(dump_dir), "-o", str(out), "-P"]) == 0
    assert not (out / "xiaomi" / "venus" / "proprietary-files.txt").exists()


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
