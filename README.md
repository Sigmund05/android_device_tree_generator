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
# Copyright (C) The LineageOS Project
# SPDX-License-Identifier: Apache-2.0
#
```

The makefiles are filled in from the dump's properties: architecture and ABIs from
`ro.product.cpu.abilist`, the board name and platform from `ro.board.platform`, the
shipping API level, screen density, security patch level, and the A/B, virtual A/B
and dynamic-partition blocks from the matching boot properties. Values a dump cannot
tell us (kernel cmdline, partition sizes) are emitted with a `TODO` marker.

`extract-files.py` targets the current python `extract-utils`
(`ExtractUtilsModule` / `ExtractUtils.device`), and `setup-makefiles.py` is the
one-line shebang that re-runs it with `--regenerate_makefiles` - which is why both
are written executable.

## proprietary-files.txt

Blobs are listed in `extract-utils` format: paths relative to the partition root,
prefixed with the partition name for everything but `system`, grouped into sections
(Audio, Camera, Display, GPS, …) and sorted. System-side partitions only contribute
a narrow allow list (Qualcomm libraries, permissions, apps) because the rest is
built from source.

## Project layout

```
src/qcomdtgen/
  cli.py               argument parsing and process exit codes
  generator.py         orchestration, output directory handling
  dump.py              partition discovery and build.prop parsing
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
