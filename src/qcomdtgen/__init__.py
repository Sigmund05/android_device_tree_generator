"""qcomdtgen - LineageOS device tree generator for Qualcomm devices."""

#: Single source of truth for the version; pyproject.toml reads it from here.
__version__ = "0.1.0"

from qcomdtgen.dump import AndroidDump
from qcomdtgen.errors import DumpError, OutputError, QcomDtGenError, TemplateError
from qcomdtgen.generator import DeviceTreeGenerator, GeneratorOptions

__all__ = [
    "__version__",
    "AndroidDump",
    "DeviceTreeGenerator",
    "GeneratorOptions",
    "QcomDtGenError",
    "DumpError",
    "OutputError",
    "TemplateError",
]
