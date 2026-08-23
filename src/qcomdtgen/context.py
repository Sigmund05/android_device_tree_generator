"""Turning a dump's properties into the values the templates need."""

from __future__ import annotations

from typing import Dict, List, Optional

from qcomdtgen.bootimg import KERNEL_OFFSET
from qcomdtgen.dump import AndroidDump

#: Primary architecture of every supported device; qcomdtgen is 64-bit ARM only.
_ARM64: Dict[str, str] = {
    "arch": "arm64",
    "arch_variant": "armv8-a",
    "cpu_abi": "arm64-v8a",
    "cpu_variant": "generic",
}

#: Secondary architecture of devices that still run 32-bit apps.
_ARM32: Dict[str, str] = {
    "arch": "arm",
    "arch_variant": "armv8-a",
    "cpu_abi": "armeabi-v7a",
    "cpu_abi2": "armeabi",
    "cpu_variant": "generic",
    "cpu_variant_runtime": "cortex-a75",
}

def _int_prop(dump: AndroidDump, *keys: str) -> Optional[int]:
    value = dump.get_prop(*keys)
    return int(value) if value.isdigit() else None


def _bool_prop(dump: AndroidDump, *keys: str) -> bool:
    return dump.get_prop(*keys).lower() in ("true", "1", "yes")


def _arch_block(dump: AndroidDump) -> str:
    """The 32-bit app support half of the architecture block.

    A 64-bit device that still runs 32-bit apps gets a full TARGET_2ND_* set;
    a 64-bit only device says so instead.
    """
    if not dump.supports_32_bit_apps:
        return "\n".join(
            [
                "TARGET_SUPPORTS_32_BIT_APPS := false",
                "TARGET_SUPPORTS_64_BIT_APPS := true",
            ]
        )
    return "\n".join(
        [
            f"TARGET_2ND_ARCH := {_ARM32['arch']}",
            f"TARGET_2ND_ARCH_VARIANT := {_ARM32['arch_variant']}",
            f"TARGET_2ND_CPU_ABI := {_ARM32['cpu_abi']}",
            f"TARGET_2ND_CPU_ABI2 := {_ARM32['cpu_abi2']}",
            f"TARGET_2ND_CPU_VARIANT := {_ARM32['cpu_variant']}",
            f"TARGET_2ND_CPU_VARIANT_RUNTIME := {_ARM32['cpu_variant_runtime']}",
            "TARGET_SUPPORTS_32_BIT_APPS := true",
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
        boot = dump.boot_image
        has_dtbo = boot is None or boot.recovery_dtbo_size > 0
        lines += [
            "# Recovery",
            f"BOARD_INCLUDE_RECOVERY_DTBO := {str(has_dtbo).lower()}",
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
        f"BOARD_{dump.manufacturer_dir.upper()}_DYNAMIC_PARTITIONS_PARTITION_LIST := " + " ".join(groups),
        f"BOARD_{dump.manufacturer_dir.upper()}_DYNAMIC_PARTITIONS_SIZE := 0 # TODO",
        f"BOARD_SUPER_PARTITION_GROUPS := {dump.manufacturer_dir}_dynamic_partitions",
    ]
    return "\n".join(lines)


def _vendor_blob_blocks(with_blobs: bool, manufacturer: str, device: str) -> Dict[str, str]:
    """Lines that only make sense once blobs have been extracted."""
    if not with_blobs:
        return {"boardconfig_vendor_block": "", "device_vendor_block": ""}
    return {
        "boardconfig_vendor_block": "\n".join(
            [
                "# Inherit the proprietary files",
                f"include vendor/{manufacturer}/{device}/BoardConfigVendor.mk",
            ]
        ),
        "device_vendor_block": "\n".join(
            [
                "# Inherit from the proprietary files makefile.",
                f"$(call inherit-product, vendor/{manufacturer}/{device}/{device}-vendor.mk)",
            ]
        ),
    }


def _make_safe(value: str) -> str:
    """Escape what make would otherwise eat: expansion and comments."""
    return value.replace("$", "$$").replace("#", "\\#")


def _cmdline_block(cmdline: str) -> str:
    """BOARD_KERNEL_CMDLINE, one argument per continuation line."""
    if not cmdline:
        return "BOARD_KERNEL_CMDLINE := # TODO: no cmdline in the dump's boot images"
    arguments = [_make_safe(argument) for argument in cmdline.split()]
    if len(arguments) == 1:
        return f"BOARD_KERNEL_CMDLINE := {arguments[0]}"
    body = " \\\n".join(f"    {argument}" for argument in arguments)
    return "BOARD_KERNEL_CMDLINE := \\\n" + body


def _kernel_address_block(dump: AndroidDump) -> str:
    """BOARD_KERNEL_BASE and the offsets mkbootimg needs alongside it.

    Load addresses are stored absolute; mkbootimg builds them as base plus
    offset, with the kernel always at +0x8000, so the base falls out of the
    kernel address. boot v3 dropped the addresses, and vendor_boot carries
    them from then on.
    """
    for image in (dump.boot_image, dump.vendor_boot_image):
        if image is not None and image.has_load_addresses:
            break
    else:
        return "BOARD_KERNEL_BASE := # TODO: no load addresses in the dump's images"

    lines = [
        f"BOARD_KERNEL_BASE := {image.base_address:#010x}",
        f"BOARD_KERNEL_OFFSET := {KERNEL_OFFSET:#010x}",
    ]
    args = ["--base $(BOARD_KERNEL_BASE)", "--kernel_offset $(BOARD_KERNEL_OFFSET)"]
    for variable, address, argument in (
        ("BOARD_RAMDISK_OFFSET", image.ramdisk_address, "--ramdisk_offset"),
        ("BOARD_KERNEL_TAGS_OFFSET", image.tags_address, "--tags_offset"),
        ("BOARD_SECOND_OFFSET", image.second_address, "--second_offset"),
        ("BOARD_DTB_OFFSET", image.dtb_address, "--dtb_offset"),
    ):
        offset = image.offset_of(address)
        if offset is None:
            continue
        lines.append(f"{variable} := {offset:#010x}")
        args.append(f"{argument} $({variable})")
    lines += [f"BOARD_MKBOOTIMG_ARGS += {argument}" for argument in args]
    return "\n".join(lines)


def _boot_image_values(dump: AndroidDump) -> Dict[str, str]:
    """Header fields only the boot image can answer.

    No build.prop property carries the boot header version, so a dump without
    a boot.img leaves a TODO behind instead of a guess.
    """
    boot = dump.boot_image
    # vendor_boot declares its own page size, and some dumps ship only that.
    page_sized = boot or dump.vendor_boot_image
    page_size = page_sized.page_size if page_sized else 4096
    return {
        "kernel_cmdline_block": _cmdline_block(dump.kernel_cmdline),
        "kernel_address_block": _kernel_address_block(dump),
        "boot_header_version": (
            str(boot.header_version)
            if boot
            else "4 # TODO: no boot.img in the dump, check the stock image"
        ),
        "kernel_pagesize": str(page_size),
        "flash_block_size": str(page_size * 64),
    }


def build_context(dump: AndroidDump, with_blobs: bool = True) -> Dict[str, str]:
    """Every placeholder the templates may reference."""
    device = dump.device
    manufacturer = dump.manufacturer_dir
    api_level = dump.api_level
    shipping_api = _int_prop(dump, "ro.product.first_api_level") or api_level
    # The vendor image's own API level, which can lag the system one.
    board_api = _int_prop(
        dump,
        "ro.board.first_api_level",
        "ro.board.api_level",
        "ro.vendor.build.version.sdk",
    )

    context: Dict[str, str] = {
        "device": device,
        "manufacturer": manufacturer,
        "product_manufacturer": dump.manufacturer,
        "brand": dump.brand,
        "model": dump.model,
        "platform": dump.platform,
        "board_name": dump.get_prop(
            "ro.product.board", "ro.board.platform", default=dump.platform
        ),
        # architecture
        "target_arch": _ARM64["arch"],
        "target_arch_variant": _ARM64["arch_variant"],
        "target_cpu_abi": _ARM64["cpu_abi"],
        "target_cpu_variant": _ARM64["cpu_variant"],
        "target_cpu_variant_runtime": dump.get_prop(
            "ro.bionic.cpu_variant", default="generic"
        ),
        "arch_block": _arch_block(dump),
        # build / product
        "shipping_api_level": str(shipping_api or ""),
        "board_api_level": str(board_api or shipping_api or ""),
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
        "kernel_source": f"kernel/{manufacturer}/{dump.platform}",
    }
    context.update(_boot_image_values(dump))
    context.update(_vendor_blob_blocks(with_blobs, manufacturer, device))
    return context
