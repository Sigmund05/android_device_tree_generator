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
| `-o`, `--output DIR` | Output root; the tree is written to `<DIR>/<vendor>/<device>` (default: `output/`) |
| `-p`, `--proprietary-files` | Generate `proprietary-files.txt` (default) |
| `-P`, `--no-proprietary-files` | Skip the blob list |
| `-f`, `--force` | Overwrite a non-empty output directory |
| `-q`, `--quiet` | Only report errors |
| `-V`, `--version` | Print the version |

Example:

```bash
qcomdtgen ~/dumps/venus -o ~/android/lineage/device
# -> ~/android/lineage/device/xiaomi/venus/proprietary-files.txt
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

## proprietary-files.txt

Blobs are listed in `extract-utils` format: paths relative to the partition root,
prefixed with the partition name for everything but `system`, grouped into sections
(Audio, Camera, Display, GPS, …) and sorted. System-side partitions only contribute
a narrow allow list (Qualcomm libraries, permissions, apps) because the rest is
built from source.

## Project layout

```
src/qcomdtgen/
  cli.py           argument parsing and process exit codes
  generator.py     orchestration, output directory handling
  dump.py          partition discovery and build.prop parsing
  proprietary.py   blob scanning and proprietary-files.txt rendering
  errors.py        exception types
tests/
```

## Development

```bash
python -m pytest
```
