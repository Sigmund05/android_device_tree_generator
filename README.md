# qcomdtgen

Generate a LineageOS device tree from an extracted Android dump of a Qualcomm device.

## Install

```bash
pip install -e .          # from a checkout
pip install -e ".[dev]"   # with pytest
```

This installs the `qcomdtgen` command (also runnable as `python -m qcomdtgen`).

## Usage

```
qcomdtgen [-h] [-o DIR] [-p | -P] [-f] [-q] [-V] dump
```

| Argument | Meaning |
| --- | --- |
| `dump` | Path to the extracted dump — the directory holding `system/`, `vendor/`, `product/`, … |
| `-o`, `--output ANDROID_TOP` | Root of the Android source tree; the tree is written to `<ANDROID_TOP>/device/<manufacturer>/<device>` (default: the current directory) |
| `-p`, `--proprietary-files` | Generate `proprietary-files.txt` plus `extract-files.py` / `setup-makefiles.py` (default) |
| `-P`, `--no-proprietary-files` | Skip the blob list and the extract scripts |
| `-f`, `--force` | Overwrite a non-empty output directory |
| `-q`, `--quiet` | Only report errors |
| `-V`, `--version` | Print the version |

Example:

```bash
qcomdtgen ~/dumps/venus -o ~/android/lineage
# -> ~/android/lineage/device/xiaomi/venus/
```

Only the platforms LineageOS supports are recognised - the `QCOM_BOARD_PLATFORMS`
list in `hardware/qcom-caf/common/qcom_boards.mk` (23 of them, `msm8937` through
`sun`). Anything else still generates a tree, with a warning. Note these are
platform code names rather than SoC part numbers: an SM8450 device reports `taro`.

The dump is inspected first and the detected device is printed:

```
detected device:
  dump          /home/user/dumps/venus
  partitions    system, vendor
  brand         Xiaomi
  manufacturer  Xiaomi
  model         Mi 11
  device        venus
  platform      lahaina
  arch          arm64
  android       13 (API 33)
  fingerprint   Xiaomi/venus/venus:13/TKQ1/V14:user/release-keys
```

## Supported dump layouts

Every partition (`system`, `system_ext`, `product`, `vendor`, `odm`, `vendor_dlkm`,
`odm_dlkm`, `system_dlkm`) is looked for at `<dump>/<part>/<part>`, `<dump>/<part>`,
`<dump>/system/system/<part>` and `<dump>/system/<part>`, so both `dumpyara` output
and a plain `super.img` unpack work. Properties are read from each partition's
`build.prop` or `etc/build.prop`.

## Generated files

| File | When |
| --- | --- |
| `Android.bp` | always |
| `AndroidProducts.mk` | always |
| `BoardConfig.mk` | always |
| `device.mk` | always |
| `lineage_<device>.mk` | always |
| `lineage.dependencies` | always |
| `proprietary-files.txt` | with `--proprietary-files` |
| `extract-files.py` | with `--proprietary-files`, mode `0755` |
| `setup-makefiles.py` | with `--proprietary-files`, mode `0755` |

Every generated file opens with the same header, kept in `templates/license.tmpl`
and injected as `{{license}}` (translated to `//` comments for `Android.bp`):

```
#
# SPDX-FileCopyrightText: The LineageOS Project
# SPDX-License-Identifier: Apache-2.0
#
```

Only 64-bit ARM devices are supported: a dump whose `ro.product.cpu.abilist` is
x86 or 32-bit ARM only is rejected. Devices that still run 32-bit apps get the
`TARGET_2ND_*` block, 64-bit only devices get `TARGET_SUPPORTS_32_BIT_APPS := false`.

The makefiles are filled in from the dump's properties: the 32-bit app support
above from `ro.product.cpu.abilist`, the board name and platform from `ro.board.platform`, the
shipping API level, screen density, security patch level, and the A/B, virtual A/B
and dynamic-partition blocks from the matching boot properties.

The kernel block - `BOARD_BOOT_HEADER_VERSION`, `BOARD_KERNEL_PAGESIZE`,
`BOARD_KERNEL_CMDLINE`, `BOARD_KERNEL_BASE` and the mkbootimg offsets - comes from
the image headers, parsed the way AOSP's `mkbootimg` writes and reads them
(`bootimg.h` for the structs, `unpack_bootimg.py` for the decoding). No build.prop
property carries any of it. `boot.img` and
`vendor_boot.img` are looked for at the dump root and under `images/`, `IMAGES/`,
`boot/` and `firmware/`; boot header v3 moved the cmdline into `vendor_boot`, so
that copy wins when it has one. Values a dump cannot tell us (partition sizes, and
the header fields when the dump ships no images) are emitted with a `TODO` marker.

`extract-files.py` targets the current python `extract-utils`
(`ExtractUtilsModule` / `ExtractUtils.device`), and `setup-makefiles.py` is the
one-line shebang that re-runs it with `--regenerate_makefiles` - which is why both
are written executable.

## proprietary-files.txt

Blobs are listed in `extract-utils` format: paths relative to the partition root,
prefixed with the partition name for everything but `system`, grouped into sections
(Audio, Camera, Display, GPS, …) and sorted. System-side partitions only contribute
a narrow allow list (Qualcomm libraries, permissions and apps, matched case
insensitively) because the rest is built from source.

## Project layout

```
src/qcomdtgen/
  cli.py               argument parsing and process exit codes
  generator.py         orchestration, output directory handling
  dump.py              partition discovery and build.prop parsing
  bootimg.py           boot.img / vendor_boot.img header parsing
  proprietary.py       blob scanning and proprietary-files.txt rendering
  context.py           dump properties -> template placeholders
  templates_engine.py  template loading and {{placeholder}} rendering
  templates/           the device tree templates themselves
  errors.py            exception types
tests/
```

## Development

```bash
python -m pytest
```

CI runs the suite on python 3.9 - 3.13 and generates a tree from a synthetic
dump on every push.

The version lives only in `src/qcomdtgen/__init__.py`; `pyproject.toml` reads it
from there (`[tool.setuptools.dynamic]`), so a release is a one-line change.
