"""Command line entry point for ``qcomdtgen``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Optional, Sequence

from qcomdtgen import __version__
from qcomdtgen.dump import AndroidDump
from qcomdtgen.errors import QcomDtGenError
from qcomdtgen.generator import (
    DEFAULT_ANDROID_TOP,
    DEVICE_SUBDIR,
    DeviceTreeGenerator,
    GeneratorOptions,
)

PROG = "qcomdtgen"

EXIT_OK = 0
EXIT_ERROR = 1
#: What a shell reports for a command killed by SIGINT / SIGPIPE.
EXIT_INTERRUPTED = 130
EXIT_BROKEN_PIPE = 141

_EXAMPLES = """\
examples:
  qcomdtgen ~/dumps/venus                       write ./device/xiaomi/venus
  qcomdtgen ~/dumps/venus -o ~/android/lineage  write into an Android tree
  qcomdtgen ~/dumps/venus -o . -P --force       regenerate, blob list aside
"""


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Generate a LineageOS device tree from an extracted Android dump.",
        epilog=_EXAMPLES,
        # keep the examples laid out as written instead of being re-wrapped
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "dump",
        type=Path,
        metavar="DUMP",
        help="path to the extracted Android dump (the directory holding "
        "system/, vendor/, product/, ...)",
    )
    parser.add_argument(
        "-o",
        "--output",
        type=Path,
        default=DEFAULT_ANDROID_TOP,
        metavar="ANDROID_TOP",
        help="root of the Android source tree; the device tree is written to "
        f"<ANDROID_TOP>/{DEVICE_SUBDIR}/<manufacturer>/<device> "
        "(default: the current directory)",
    )

    blobs = parser.add_mutually_exclusive_group()
    blobs.add_argument(
        "-p",
        "--proprietary-files",
        dest="proprietary_files",
        action="store_true",
        default=True,
        help="generate proprietary-files.txt and the extract-utils scripts (default)",
    )
    blobs.add_argument(
        "-P",
        "--no-proprietary-files",
        dest="proprietary_files",
        action="store_false",
        help="generate the makefiles only",
    )

    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="replace a previous run in a non-empty output directory",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="only report warnings and errors",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"{PROG} {__version__}",
    )
    return parser


def _print_summary(dump: AndroidDump) -> None:
    """What the dump turned out to be, as a two column table."""
    summary = dump.summary()
    width = max(len(key) for key in summary)
    print("detected device:")
    for key, value in summary.items():
        print(f"  {key.ljust(width)}  {value}")


def _warn_if_not_qualcomm(dump: AndroidDump) -> None:
    """Worth saying even when quiet: the whole tool assumes Qualcomm."""
    if not dump.is_qualcomm:
        print(
            f"{PROG}: warning: {dump.platform!r} does not look like a Qualcomm "
            "platform; results may be wrong",
            file=sys.stderr,
        )


def _options(args: argparse.Namespace) -> GeneratorOptions:
    return GeneratorOptions(
        dump_path=args.dump,
        android_top=args.output,
        proprietary_files=args.proprietary_files,
        force=args.force,
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    verbose = not args.quiet
    log = print if verbose else (lambda *_args, **_kwargs: None)

    try:
        generator = DeviceTreeGenerator(_options(args), log=log)
        _warn_if_not_qualcomm(generator.dump)
        if verbose:
            _print_summary(generator.dump)
        result = generator.run()
        if verbose:
            print(f"device tree: {result.device_dir}")
            print(f"generated {result.file_count} file(s)")
    except QcomDtGenError as exc:
        print(f"{PROG}: error: {exc}", file=sys.stderr)
        return EXIT_ERROR
    except KeyboardInterrupt:
        print(f"{PROG}: interrupted", file=sys.stderr)
        return EXIT_INTERRUPTED
    except BrokenPipeError:
        # A reader such as `| head` went away; close stdout so the interpreter
        # does not report the failed flush on the way out.
        _close_stdout()
        return EXIT_BROKEN_PIPE
    return EXIT_OK


def _close_stdout() -> None:
    try:
        sys.stdout.close()
    except OSError:  # pragma: no cover - already gone
        pass


if __name__ == "__main__":
    sys.exit(main())
