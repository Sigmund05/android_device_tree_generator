"""Reading an extracted Android dump from disk.

A "dump" is a directory holding the extracted contents of a device's
partitions, as produced by tools such as ``dumpyara`` or by simply unpacking
``super.img``.  Layouts differ between tools, so every partition is looked up
in a handful of well known places instead of a single fixed path.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional

from qcomdtgen.bootimg import BootImage, load_boot_image, load_vendor_boot_image
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

#: Anything outside this set is folded away: these names become directories in
#: the Android tree and parts of make variable names, and "TCL Communication
#: Ltd." must not turn into a path ending in a dot or BOARD_...LTD._SIZE.
_UNSAFE_NAME_CHARS = re.compile(r"[^a-z0-9_]+")

#: Every TARGET_BOARD_PLATFORM LineageOS supports, from the QCOM_BOARD_PLATFORMS
#: list in hardware/qcom-caf/common/qcom_boards.mk (lineage-23.2), grouped by
#: the UM kernel family it belongs to there.  Note these are the platform code
#: names, not the SoC part numbers: an SM8450 device says "taro".
QCOM_BOARD_PLATFORMS = frozenset(
    {
        # UM 3.18
        "msm8937", "msm8953", "msm8996",
        # UM 4.4
        "msm8998", "sdm660",
        # UM 4.9
        "sdm710", "sdm845",
        # UM 4.14
        "msmnile", "sm6150", "trinket", "atoll",
        # UM 4.19
        "kona", "lito", "bengal",
        # UM 5.4
        "lahaina", "holi",
        # UM 5.10
        "taro", "parrot",
        # UM 5.15
        "kalama", "crow",
        # UM 6.1
        "pineapple", "volcano",
        # UM 6.6
        "sun",
    }
)  # fmt: skip


def sanitize_name(name: str, default: str = "unknown") -> str:
    """Fold a property value into something usable as a directory name."""
    cleaned = _UNSAFE_NAME_CHARS.sub("_", name.lower()).strip("_")
    return cleaned or default


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
        #: Parsed image headers, when the dump ships them.
        self.boot_image: Optional[BootImage] = load_boot_image(self.path)
        self.vendor_boot_image: Optional[BootImage] = load_vendor_boot_image(self.path)

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
        """Only 64-bit ARM devices are supported."""
        abilist = self.abilist
        if not abilist:
            return
        if "x86" in abilist:
            raise DumpError(
                f"unsupported architecture {abilist!r}: qcomdtgen only handles ARM devices"
            )
        if "arm64" not in abilist:
            raise DumpError(
                f"unsupported architecture {abilist!r}: qcomdtgen only handles "
                "64-bit devices"
            )

    # -- property access ---------------------------------------------------

    def get_prop(self, *keys: str, default: str = "") -> str:
        """Return the first non-empty value among ``keys``."""
        for key in keys:
            value = self.props.get(key)
            if value:
                return value
        return default

    def get_partition_prop(self, key: str, default: str = "") -> str:
        """Read ``key`` from each partition in turn, system side first.

        The merged table lets vendor and odm win, which is what the runtime
        does for the vendor specific keys - but not what a device tree wants
        from ``ro.product.*``, where the system value is the canonical one.
        """
        for name in PARTITIONS:
            partition = self.partitions.get(name)
            if partition is None:
                continue
            value = partition.props.get(key)
            if value:
                return value
        return default

    def get_product_prop(self, suffix: str, default: str = "") -> str:
        """Look up ``ro.product.<suffix>`` across all its partition variants."""
        unprefixed = self.get_partition_prop(f"ro.product.{suffix}")
        if unprefixed:
            return unprefixed
        keys = [f"ro.product.{part}.{suffix}" for part in PARTITIONS]
        keys += [f"ro.{part}.product.{suffix}" for part in PARTITIONS]
        return self.get_prop(*keys, default=default)

    # -- derived device information ---------------------------------------

    @property
    def device(self) -> str:
        """The codename, as the tree directory and PRODUCT_DEVICE spell it."""
        codename = self.get_product_prop("device") or self.get_prop("ro.build.product")
        return sanitize_name(codename)

    @property
    def manufacturer(self) -> str:
        """``ro.product.manufacturer``, falling back to the brand."""
        return (
            self.get_product_prop("manufacturer")
            or self.get_product_prop("brand")
            or "unknown"
        )

    @property
    def brand(self) -> str:
        return self.get_product_prop("brand") or self.manufacturer

    @property
    def model(self) -> str:
        return self.get_product_prop("model", default="unknown")

    @property
    def manufacturer_dir(self) -> str:
        """Manufacturer as the device tree spells it: lowercase, no spaces."""
        return sanitize_name(self.manufacturer)

    @property
    def platform(self) -> str:
        return self.get_prop(
            "ro.board.platform",
            "ro.vendor.qti.soc_name",
            "ro.soc.model",
            default="unknown",
        )

    @property
    def is_supported_platform(self) -> bool:
        """Whether TARGET_BOARD_PLATFORM is one qcom-caf/common knows."""
        return self.platform.lower() in QCOM_BOARD_PLATFORMS

    @property
    def abilist(self) -> str:
        return self.get_prop("ro.product.cpu.abilist", "ro.product.cpu.abi")

    @property
    def arch(self) -> str:
        """Always arm64 - 32-bit only devices are rejected at load time."""
        return "arm64"

    @property
    def supports_32_bit_apps(self) -> bool:
        """Whether the device still runs 32-bit apps next to the 64-bit ones."""
        return "armeabi" in self.abilist

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

    @property
    def kernel_cmdline(self) -> str:
        """The kernel cmdline, from vendor_boot when the device has one.

        Boot header v3 moved the cmdline into vendor_boot, so that copy wins
        whenever it carries anything.
        """
        for image in (self.vendor_boot_image, self.boot_image):
            if image is not None and image.cmdline:
                return image.cmdline
        return ""

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
            "boot image": (
                self.boot_image.describe() if self.boot_image else "not found in dump"
            ),
            "vendor_boot": (
                self.vendor_boot_image.describe()
                if self.vendor_boot_image
                else "not found in dump"
            ),
        }
