"""Orchestration: turn a dump into files on disk."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from qcomdtgen.dump import AndroidDump
from qcomdtgen.errors import OutputError
from qcomdtgen.proprietary import collect_blobs

#: Where generated trees are placed when ``--output`` is not given.
DEFAULT_OUTPUT_ROOT = Path("output")


@dataclass
class GeneratorOptions:
    """Everything the CLI collected from the user."""

    dump_path: Path
    output_root: Path = DEFAULT_OUTPUT_ROOT
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
        """``<output root>/<vendor>/<device>``, the LineageOS tree layout."""
        return (
            Path(self.options.output_root).expanduser()
            / self.dump.vendor
            / self.dump.device
        ).resolve()

    def run(self) -> GeneratorResult:
        device_dir = self._prepare_output()
        result = GeneratorResult(device_dir=device_dir)

        if self.options.proprietary_files:
            result.blob_count = self._write_proprietary_files(device_dir, result)
        else:
            self._log("skipping proprietary-files.txt (disabled)")

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
        target = device_dir / "proprietary-files.txt"
        target.write_text(blobs.render(self.dump), encoding="utf-8")
        result.written.append(target)
        self._log(f"wrote {target} ({blobs.count} blobs)")
        return blobs.count
