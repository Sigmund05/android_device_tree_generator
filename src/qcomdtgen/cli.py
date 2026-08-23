"""Command line entry point for ``qcomdtgen``."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional, Sequence

from qcomdtgen import __version__
from qcomdtgen.errors import QcomDtGenError
from qcomdtgen.generator import (
    DEFAULT_ANDROID_TOP,
    DEVICE_SUBDIR,
    DeviceTreeGenerator,
    GeneratorOptions,
)

PROG = "qcomdtgen"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog=PROG,
        description="Generate a LineageOS device tree from an extracted Android dump.",
        epilog=(
            "example: qcomdtgen ~/dumps/lahaina -o ~/android/lineage "
            "--proprietary-files"
        ),
    )
    parser.add_argument(
        "dump",
        type=Path,
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
        help="generate proprietary-files.txt (default)",
    )
    blobs.add_argument(
        "-P",
        "--no-proprietary-files",
        dest="proprietary_files",
        action="store_false",
        help="do not generate proprietary-files.txt",
    )

    parser.add_argument(
        "-f",
        "--force",
        action="store_true",
        help="overwrite an existing, non-empty output directory",
    )
    parser.add_argument(
        "-q",
        "--quiet",
        action="store_true",
        help="only report errors",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"{PROG} {__version__}",
    )
    return parser


def _print_summary(generator: DeviceTreeGenerator) -> None:
    summary = generator.dump.summary()
    width = max(len(key) for key in summary)
    print("detected device:")
    for key, value in summary.items():
        print(f"  {key.ljust(width)}  {value}")
    if not generator.dump.is_qualcomm:
        print(
            f"warning: {generator.dump.platform!r} does not look like a Qualcomm "
            "platform; results may be wrong",
            file=sys.stderr,
        )


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    verbose = not args.quiet

    def log(message: str) -> None:
        if verbose:
            print(message)

    options = GeneratorOptions(
        dump_path=args.dump,
        android_top=args.output,
        proprietary_files=args.proprietary_files,
        force=args.force,
    )

    try:
        generator = DeviceTreeGenerator(options, log=log)
        if verbose:
            _print_summary(generator)
        result = generator.run()
    except QcomDtGenError as exc:
        print(f"{PROG}: error: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(f"{PROG}: interrupted", file=sys.stderr)
        return 130

    if verbose:
        written: List[str] = [str(path) for path in result.written]
        print(f"device tree: {result.device_dir}")
        if written:
            print(f"generated {len(written)} file(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
