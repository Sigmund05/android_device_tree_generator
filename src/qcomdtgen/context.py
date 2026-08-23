"""Turning a dump's properties into the values the templates need."""

from __future__ import annotations

import datetime
from typing import Dict, List, Optional, Tuple

from qcomdtgen import __version__
from qcomdtgen.dump import AndroidDump

#: aapt density buckets, used to pick PRODUCT_AAPT_PREF_CONFIG.
_DENSITY_BUCKETS: Tuple[Tuple[int, str], ...] = (
    (120, "ldpi"),
    (160, "mdpi"),
    (213, "tvdpi"),
    (240, "hdpi"),
    (320, "xhdpi"),
    (480, "xxhdpi"),
    (640, "xxxhdpi"),
)

#: Per-arch defaults for the TARGET_* block of BoardConfig.mk.
_ARCH_DEFAULTS: Dict[str, Dict[str, str]] = {
    "arm64": {
        "arch": "arm64",
        "arch_variant": "armv8-a",
        "cpu_abi": "arm64-v8a",
        "cpu_abi2": "",
        "cpu_variant": "generic",
    },
    "arm": {
        "arch": "arm",
        "arch_variant": "armv7-a-neon",
        "cpu_abi": "armeabi-v7a",
        "cpu_abi2": "armeabi",
        "cpu_variant": "cortex-a53",
    },
    "x86_64": {
        "arch": "x86_64",
        "arch_variant": "x86_64",
        "cpu_abi": "x86_64",
        "cpu_abi2": "",
        "cpu_variant": "generic",
    },
    "x86": {
        "arch": "x86",
        "arch_variant": "x86",
        "cpu_abi": "x86",
        "cpu_abi2": "",
        "cpu_variant": "generic",
    },
}

#: Release configuration used by the lunch combos, per shipped API level.
#: LineageOS 22 (Android 15) onwards spells the release out in the combo.
_RELEASE_CONFIGS: Tuple[Tuple[int, str], ...] = (
    (36, "bp2a"),
    (35, "bp1a"),
)

_BUILD_TYPES = ("user", "userdebug", "eng")


def _density_bucket(density: Optional[int]) -> str:
    if not density:
        return "xxhdpi"
    return min(_DENSITY_BUCKETS, key=lambda bucket: abs(bucket[0] - density))[1]


def _int_prop(dump: AndroidDump, *keys: str) -> Optional[int]:
    value = dump.get_prop(*keys)
    return int(value) if value.isdigit() else None


def _bool_prop(dump: AndroidDump, *keys: str) -> bool:
    return dump.get_prop(*keys).lower() in ("true", "1", "yes")


def _release_config(api_level: Optional[int]) -> str:
    for level, name in _RELEASE_CONFIGS:
        if api_level and api_level >= level:
            return name
    return ""


def _lunch_choices(device: str, api_level: Optional[int]) -> str:
    release = _release_config(api_level)
    infix = f"-{release}" if release else ""
    return " \\\n".join(
        f"    lineage_{device}{infix}-{build_type}" for build_type in _BUILD_TYPES
    )


def _second_arch_block(dump: AndroidDump) -> str:
    """The TARGET_2ND_* block, for 64-bit devices that also run 32-bit code."""
    abilist = dump.get_prop("ro.product.cpu.abilist")
    if dump.arch != "arm64" or "armeabi" not in abilist:
        return ""
    second = _ARCH_DEFAULTS["arm"]
    return "\n".join(
        [
            "TARGET_2ND_ARCH := arm",
            "TARGET_2ND_ARCH_VARIANT := armv8-a",
            f"TARGET_2ND_CPU_ABI := {second['cpu_abi']}",
            f"TARGET_2ND_CPU_ABI2 := {second['cpu_abi2']}",
            "TARGET_2ND_CPU_VARIANT := generic",
            "TARGET_2ND_CPU_VARIANT_RUNTIME := cortex-a75",
            "TARGET_SUPPORTS_64_BIT_APPS := true",
        ]
    )


def _ota_block(dump: AndroidDump) -> str:
    lines: List[str] = []
    if _bool_prop(dump, "ro.build.ab_update"):
        lines += [
            "# A/B",
            "AB_OTA_UPDATER := true",
            "AB_OTA_PARTITIONS += \\",
            "    boot \\",
            "    dtbo \\",
            "    odm \\",
            "    product \\",
            "    system \\",
            "    system_ext \\",
            "    vbmeta \\",
            "    vbmeta_system \\",
            "    vendor",
            "",
            "BOARD_USES_RECOVERY_AS_BOOT := false",
        ]
    else:
        lines += [
            "# Recovery",
            "BOARD_INCLUDE_RECOVERY_DTBO := true",
            "TARGET_RECOVERY_PIXEL_FORMAT := RGBX_8888",
        ]
    if _bool_prop(dump, "ro.virtual_ab.enabled"):
        lines += [
            "",
            "# Virtual A/B",
            "BOARD_DONT_USE_VABC_OTA := false",
        ]
    return "\n".join(lines)


def _partition_block(dump: AndroidDump) -> str:
    """Dynamic partition scaffolding; sizes cannot be read from a dump."""
    if not _bool_prop(dump, "ro.boot.dynamic_partitions", "ro.build.dynamic_partitions"):
        return ""
    groups = [name for name in ("system", "system_ext", "product", "vendor", "odm") if name in dump.partitions]
    lines = [
        "# Dynamic partitions",
        "BOARD_SUPER_PARTITION_SIZE := 0 # TODO: read from the stock super.img",
        f"BOARD_{dump.vendor.upper()}_DYNAMIC_PARTITIONS_PARTITION_LIST := " + " ".join(groups),
        f"BOARD_{dump.vendor.upper()}_DYNAMIC_PARTITIONS_SIZE := 0 # TODO",
        f"BOARD_SUPER_PARTITION_GROUPS := {dump.vendor}_dynamic_partitions",
    ]
    return "\n".join(lines)


def _vendor_blob_blocks(with_blobs: bool, vendor: str, device: str) -> Dict[str, str]:
    """Lines that only make sense once blobs have been extracted."""
    if not with_blobs:
        return {"boardconfig_vendor_block": "", "device_vendor_block": ""}
    return {
        "boardconfig_vendor_block": "\n".join(
            [
                "# Inherit from the proprietary version",
                f"include vendor/{vendor}/{device}/BoardConfigVendor.mk",
            ]
        ),
        "device_vendor_block": "\n".join(
            [
                "# Inherit proprietary blobs",
                f"$(call inherit-product, vendor/{vendor}/{device}/{device}-vendor.mk)",
            ]
        ),
    }


def build_context(dump: AndroidDump, with_blobs: bool = True) -> Dict[str, str]:
    """Every placeholder the templates may reference."""
    arch = _ARCH_DEFAULTS.get(dump.arch, _ARCH_DEFAULTS["arm64"])
    device = dump.device
    vendor = dump.vendor
    api_level = dump.api_level
    shipping_api = _int_prop(
        dump,
        "ro.product.first_api_level",
        "ro.board.first_api_level",
        "ro.board.api_level",
    ) or api_level

    context: Dict[str, str] = {
        "year": str(datetime.date.today().year),
        "generator": f"qcomdtgen {__version__}",
        "device": device,
        "vendor": vendor,
        "manufacturer": dump.manufacturer,
        "brand": dump.brand,
        "model": dump.model,
        "platform": dump.platform,
        "hardware": dump.get_prop("ro.hardware", default="qcom"),
        "board_name": dump.get_prop(
            "ro.product.board", "ro.board.platform", default=dump.platform
        ),
        "soc_model": dump.get_prop("ro.soc.model", default=dump.platform),
        # architecture
        "target_arch": arch["arch"],
        "target_arch_variant": arch["arch_variant"],
        "target_cpu_abi": arch["cpu_abi"],
        "target_cpu_abi2": arch["cpu_abi2"],
        "target_cpu_variant": arch["cpu_variant"],
        "target_cpu_variant_runtime": dump.get_prop(
            "ro.bionic.cpu_variant", default="generic"
        ),
        "second_arch_block": _second_arch_block(dump),
        # build / product
        "android_version": dump.android_version,
        "api_level": str(api_level or ""),
        "shipping_api_level": str(shipping_api or ""),
        "lunch_choices": _lunch_choices(device, api_level),
        "density": _density_bucket(_int_prop(dump, "ro.sf.lcd_density")),
        "build_description": dump.get_prop(
            "ro.build.description", default=dump.fingerprint
        ),
        "build_fingerprint": dump.fingerprint,
        "system_name": dump.get_product_prop("name", default=device),
        "device_product": dump.get_product_prop("device", default=device),
        "vendor_security_patch": dump.get_prop(
            "ro.vendor.build.security_patch",
            "ro.build.version.security_patch",
            default="",
        ),
        # optional blocks
        "ota_block": _ota_block(dump),
        "partition_block": _partition_block(dump),
        "kernel_source": f"kernel/{vendor}/{dump.platform}",
        "boot_header_version": str(_int_prop(dump, "ro.boot.hardware.header_version") or 4),
    }
    context.update(_vendor_blob_blocks(with_blobs, vendor, device))
    return context
