"""Orchestration: turn a dump into a device tree on disk."""

from __future__ import annotations

import os
import stat
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, List, Optional

from qcomdtgen.context import build_context
from qcomdtgen.dump import AndroidDump
from qcomdtgen.errors import OutputError
from qcomdtgen.proprietary import collect_blobs
from qcomdtgen.templates_engine import (
    BASE_TEMPLATES,
    BLOB_TEMPLATES,
    EXECUTABLE_FILES,
    render,
)

#: ANDROID_TOP used when ``--output`` is not given.
DEFAULT_ANDROID_TOP = Path(".")

#: Device trees live under ANDROID_TOP/device/<manufacturer>/<device>.
DEVICE_SUBDIR = "device"


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

    @property
    def device_dir(self) -> Path:
        """``ANDROID_TOP/device/<manufacturer>/<device>``."""
        return (
            Path(self.options.android_top).expanduser()
            / DEVICE_SUBDIR
            / self.dump.manufacturer_dir
            / self.dump.device
        ).resolve()

    def run(self) -> GeneratorResult:
        device_dir = self._prepare_output()
        result = GeneratorResult(device_dir=device_dir)
        self._log(f"generating device tree in {device_dir}")

        if self.options.proprietary_files:
            result.blob_count = self._write_proprietary_files(device_dir, result)
        else:
            self._log("skipping proprietary-files.txt (disabled)")

        self._write_templates(device_dir, result)
        return result

    # -- steps -------------------------------------------------------------

    def _prepare_output(self) -> Path:
        device_dir = self.device_dir
        if device_dir.exists():
            if not device_dir.is_dir():
                raise OutputError(f"output path is not a directory: {device_dir}")
            if os.listdir(device_dir) and not self.options.force:
                raise OutputError(
                    f"output directory is not empty: {device_dir} (use --force to overwrite)"
                )
        try:
            device_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise OutputError(f"cannot create output directory {device_dir}: {exc}") from exc
        return device_dir

    def _write_proprietary_files(self, device_dir: Path, result: GeneratorResult) -> int:
        self._log("scanning partitions for proprietary blobs...")
        blobs = collect_blobs(self.dump)
        target = self._write(device_dir / "proprietary-files.txt", blobs.render(self.dump))
        result.written.append(target)
        self._log(f"wrote {target.name} ({blobs.count} blobs)")
        return blobs.count

    def _write_templates(self, device_dir: Path, result: GeneratorResult) -> None:
        context = build_context(self.dump, with_blobs=self.options.proprietary_files)
        for template, filename in self._template_map().items():
            target = device_dir / filename.format(device=self.dump.device)
            self._write(target, render(template, context, target.name))
            result.written.append(target)
            self._log(f"wrote {target.name}")

    def _template_map(self) -> Dict[str, str]:
        templates = dict(BASE_TEMPLATES)
        if self.options.proprietary_files:
            templates.update(BLOB_TEMPLATES)
        return templates

    @staticmethod
    def _write(target: Path, content: str) -> Path:
        target.write_text(content, encoding="utf-8")
        if target.name in EXECUTABLE_FILES:
            mode = target.stat().st_mode
            target.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        return target
