"""Reading an extracted Android dump from disk.

A "dump" is a directory holding the extracted contents of a device's
partitions, as produced by tools such as ``dumpyara`` or by simply unpacking
``super.img``.  Layouts differ between tools, so every partition is looked up
in a handful of well known places instead of a single fixed path.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional

from qcomdtgen.errors import DumpError

#: Partitions a device tree may pull blobs and properties from, in the order
#: they should be searched.
PARTITIONS: List[str] = [
    "system",
    "system_ext",
    "product",
    "vendor",
    "odm",
    "vendor_dlkm",
    "odm_dlkm",
    "system_dlkm",
]

#: Files that mark a directory as the root of a partition.
_PARTITION_MARKERS: List[str] = [
    "build.prop",
    "etc/build.prop",
    "bin",
    "lib",
    "lib64",
    "etc",
    "framework",
    "app",
    "priv-app",
    "overlay",
]

#: Where a partition's ``build.prop`` may live, relative to the partition root.
_BUILD_PROP_NAMES: List[str] = ["build.prop", "etc/build.prop"]


def _read_prop_file(path: Path) -> Dict[str, str]:
    """Parse a ``key=value`` property file, ignoring comments and junk."""
    props: Dict[str, str] = {}
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return props
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if key:
            props[key] = value.strip()
    return props


@dataclass
class Partition:
    """A single partition found inside a dump."""

    name: str
    path: Path
    props: Dict[str, str] = field(default_factory=dict)

    def walk_files(self) -> Iterator[Path]:
        """Yield every regular file in the partition, as a relative path."""
        for dirpath, dirnames, filenames in os.walk(self.path):
            dirnames.sort()
            base = Path(dirpath)
            for name in sorted(filenames):
                full = base / name
                if full.is_symlink() or not full.is_file():
                    continue
                yield full.relative_to(self.path)


class AndroidDump:
    """An extracted Android dump on the local filesystem."""

    def __init__(self, path: os.PathLike | str) -> None:
        self.path = Path(path).expanduser().resolve()
        if not self.path.exists():
            raise DumpError(f"dump path does not exist: {self.path}")
        if not self.path.is_dir():
            raise DumpError(f"dump path is not a directory: {self.path}")

        self.partitions: Dict[str, Partition] = self._find_partitions()
        if not self.partitions:
            raise DumpError(
                f"no Android partitions (system, vendor, product, ...) found in {self.path}"
            )

        self.props: Dict[str, str] = self._collect_props()
        if not self.props:
            raise DumpError(f"no build.prop found in any partition of {self.path}")
        self._reject_unsupported_arch()

    # -- discovery ---------------------------------------------------------

    def _candidate_roots(self, name: str) -> Iterable[Path]:
        root = self.path
        yield root / name / name
        yield root / name
        yield root / "system" / "system" / name
        yield root / "system" / name
        if name == "system":
            yield root

    @staticmethod
    def _looks_like_partition(path: Path) -> bool:
        if not path.is_dir():
            return False
        return any((path / marker).exists() for marker in _PARTITION_MARKERS)

    def _find_partitions(self) -> Dict[str, Partition]:
        found: Dict[str, Partition] = {}
        seen: set[Path] = set()
        for name in PARTITIONS:
            for candidate in self._candidate_roots(name):
                if candidate in seen or not self._looks_like_partition(candidate):
                    continue
                seen.add(candidate)
                found[name] = Partition(name=name, path=candidate)
                break
        return found

    def _collect_props(self) -> Dict[str, str]:
        """Merge every partition's build.prop into one lookup table.

        Later partitions win, so vendor/odm values override the system ones -
        that matches what the device itself resolves at runtime for the
        vendor specific keys we care about.
        """
        merged: Dict[str, str] = {}
        for name in PARTITIONS:
            partition = self.partitions.get(name)
            if partition is None:
                continue
            for prop_name in _BUILD_PROP_NAMES:
                prop_path = partition.path / prop_name
                if prop_path.is_file():
                    partition.props.update(_read_prop_file(prop_path))
            merged.update(partition.props)
        return merged

    def _reject_unsupported_arch(self) -> None:
        """Only ARM devices are supported; Qualcomm SoCs are all ARM."""
        abilist = self.get_prop("ro.product.cpu.abilist", "ro.product.cpu.abi")
        if "x86" in abilist:
            raise DumpError(
                f"unsupported architecture {abilist!r}: qcomdtgen only handles ARM devices"
            )

    # -- property access ---------------------------------------------------

    def get_prop(self, *keys: str, default: str = "") -> str:
        """Return the first non-empty value among ``keys``."""
        for key in keys:
            value = self.props.get(key)
            if value:
                return value
        return default

    def get_product_prop(self, suffix: str, default: str = "") -> str:
        """Look up ``ro.product.<suffix>`` across all its partition variants."""
        keys = [f"ro.product.{suffix}"]
        keys += [f"ro.product.{part}.{suffix}" for part in PARTITIONS]
        keys += [f"ro.{part}.product.{suffix}" for part in PARTITIONS]
        return self.get_prop(*keys, default=default)

    # -- derived device information ---------------------------------------

    @property
    def device(self) -> str:
        return self.get_product_prop("device") or self.get_prop(
            "ro.build.product", default="unknown"
        )

    @property
    def manufacturer(self) -> str:
        return self.get_product_prop("manufacturer", default="unknown")

    @property
    def brand(self) -> str:
        return self.get_product_prop("brand", default=self.manufacturer)

    @property
    def model(self) -> str:
        return self.get_product_prop("model", default="unknown")

    @property
    def vendor(self) -> str:
        """Vendor directory name used by the device tree (lowercase brand)."""
        return (self.manufacturer or self.brand).lower().replace(" ", "_")

    @property
    def platform(self) -> str:
        return self.get_prop(
            "ro.board.platform",
            "ro.vendor.qti.soc_name",
            "ro.soc.model",
            default="unknown",
        )

    @property
    def is_qualcomm(self) -> bool:
        soc = " ".join(
            [
                self.platform,
                self.get_prop("ro.soc.manufacturer"),
                self.get_prop("ro.vendor.qti.soc_name"),
                self.get_prop("ro.hardware"),
            ]
        ).lower()
        return any(tag in soc for tag in ("qcom", "qualcomm", "msm", "sdm", "sm", "kona", "lito"))

    @property
    def arch(self) -> str:
        abilist = self.get_prop("ro.product.cpu.abilist", "ro.product.cpu.abi")
        if "armeabi" in abilist and "arm64" not in abilist:
            return "arm"
        return "arm64"

    @property
    def api_level(self) -> Optional[int]:
        value = self.get_prop("ro.build.version.sdk")
        return int(value) if value.isdigit() else None

    @property
    def android_version(self) -> str:
        return self.get_prop("ro.build.version.release", default="unknown")

    @property
    def fingerprint(self) -> str:
        return self.get_prop(
            "ro.build.fingerprint",
            "ro.vendor.build.fingerprint",
            "ro.system.build.fingerprint",
            default="unknown",
        )

    def summary(self) -> Dict[str, str]:
        """Human readable overview of what was detected in the dump."""
        return {
            "dump": str(self.path),
            "partitions": ", ".join(sorted(self.partitions)),
            "brand": self.brand,
            "manufacturer": self.manufacturer,
            "model": self.model,
            "device": self.device,
            "platform": self.platform,
            "arch": self.arch,
            "android": f"{self.android_version} (API {self.api_level or '?'})",
            "fingerprint": self.fingerprint,
        }
