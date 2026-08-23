"""Orchestration: turn a dump into a device tree on disk."""

from __future__ import annotations

import stat
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path
from typing import Callable, Iterator, List, Optional, Tuple

from qcomdtgen.context import build_context
from qcomdtgen.dump import AndroidDump
from qcomdtgen.errors import OutputError
from qcomdtgen.proprietary import collect_blobs
from qcomdtgen.templates_engine import TEMPLATES, render, templates_for

#: ANDROID_TOP used when ``--output`` is not given.
DEFAULT_ANDROID_TOP = Path(".")

#: Device trees live under ANDROID_TOP/device/<manufacturer>/<device>.
DEVICE_SUBDIR = "device"

#: The blob list, the one output that is not rendered from a template.
PROPRIETARY_FILES = "proprietary-files.txt"

_EXEC_BITS = stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH


@dataclass
class GeneratorOptions:
    """Everything the CLI collected from the user."""

    dump_path: Path
    android_top: Path = DEFAULT_ANDROID_TOP
    proprietary_files: bool = True
    force: bool = False


@dataclass
class GeneratorResult:
    """What a run produced."""

    device_dir: Path
    written: List[Path] = field(default_factory=list)
    blob_count: int = 0

    @property
    def file_count(self) -> int:
        return len(self.written)


class DeviceTreeGenerator:
    """Generates a LineageOS device tree from an Android dump."""

    def __init__(
        self,
        options: GeneratorOptions,
        log: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.options = options
        self._log = log or (lambda message: None)
        self.dump = AndroidDump(options.dump_path)

    @cached_property
    def device_dir(self) -> Path:
        """``ANDROID_TOP/device/<manufacturer>/<device>``.

        Only ANDROID_TOP is resolved: resolving the whole path would follow a
        symlinked device directory, and _prepare_output refuses those.
        """
        android_top = Path(self.options.android_top).expanduser().resolve()
        return android_top / DEVICE_SUBDIR / self.dump.manufacturer_dir / self.dump.device

    def run(self) -> GeneratorResult:
        self._prepare_output()
        result = GeneratorResult(device_dir=self.device_dir)
        self._log(f"generating device tree in {self.device_dir}")

        if self.options.proprietary_files:
            blob_list, result.blob_count = self._write_proprietary_files()
            result.written.append(blob_list)
        else:
            self._log(f"skipping {PROPRIETARY_FILES} (disabled)")

        result.written.extend(self._write_templates())
        return result

    # -- output directory --------------------------------------------------

    def generated_names(self) -> Iterator[str]:
        """Every filename this tool owns, whatever the options are.

        Used to clear a previous run out of the way; anything else in the
        directory belongs to whoever put it there and is left alone.
        """
        yield PROPRIETARY_FILES
        for template in TEMPLATES:
            yield template.output_name(self.dump.device)

    def _prepare_output(self) -> None:
        device_dir = self.device_dir
        if device_dir.is_symlink():
            # is_dir() would follow it and the run would write somewhere the
            # caller did not name.
            raise OutputError(f"output path is a symlink: {device_dir}")
        if device_dir.exists():
            if not device_dir.is_dir():
                raise OutputError(f"output path is not a directory: {device_dir}")
            if any(device_dir.iterdir()):
                if not self.options.force:
                    raise OutputError(
                        f"output directory is not empty: {device_dir} "
                        "(use --force to overwrite)"
                    )
                self._clear_previous_run()
        try:
            device_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise OutputError(f"cannot create output directory {device_dir}: {exc}") from exc

    def _clear_previous_run(self) -> None:
        """Drop the files a previous run left, so none of them go stale.

        Without this, generating with --no-proprietary-files over a tree that
        had blobs would leave an extract-files.py claiming blobs are set up.
        """
        removed = 0
        for name in self.generated_names():
            stale = self.device_dir / name
            if stale.is_file():
                stale.unlink()
                removed += 1
        if removed:
            self._log(f"removed {removed} file(s) from the previous run")

    # -- output files ------------------------------------------------------

    def _write_proprietary_files(self) -> Tuple[Path, int]:
        self._log("scanning partitions for proprietary blobs...")
        blobs = collect_blobs(self.dump)
        target = self._write(self.device_dir / PROPRIETARY_FILES, blobs.render(self.dump))
        self._log(f"wrote {target.name} ({blobs.count} blobs)")
        return target, blobs.count

    def _write_templates(self) -> List[Path]:
        context = build_context(self.dump, with_blobs=self.options.proprietary_files)
        written: List[Path] = []
        for template in templates_for(self.options.proprietary_files):
            target = self.device_dir / template.output_name(self.dump.device)
            self._write(
                target,
                render(template.name, context, target.name),
                executable=template.executable,
            )
            written.append(target)
            self._log(f"wrote {target.name}")
        return written

    @staticmethod
    def _write(target: Path, content: str, executable: bool = False) -> Path:
        try:
            target.write_text(content, encoding="utf-8")
            if executable:
                target.chmod(target.stat().st_mode | _EXEC_BITS)
        except OSError as exc:
            raise OutputError(f"cannot write {target}: {exc}") from exc
        return target
