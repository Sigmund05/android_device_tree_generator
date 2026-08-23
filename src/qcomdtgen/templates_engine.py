"""Loading and rendering the device tree templates.

Templates are plain text files shipped as package data.  Placeholders are
written as ``{{name}}`` so that the templates can contain make's ``$(VAR)``,
soong's braces and python's format characters untouched.
"""

from __future__ import annotations

import re
from typing import Dict

try:  # python >= 3.9
    from importlib.resources import files as _resource_files
except ImportError:  # pragma: no cover - python 3.8 fallback
    from importlib_resources import files as _resource_files  # type: ignore

from qcomdtgen.errors import QcomDtGenError

_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")
#: A placeholder sitting alone on its line, plus the blank line after it.
_STANDALONE = re.compile(r"(?m)^[ \t]*\{\{\s*(\w+)\s*\}\}[ \t]*\n\n?")

#: Templates written for every device tree.
BASE_TEMPLATES: Dict[str, str] = {
    "Android.bp": "Android.bp",
    "AndroidProducts.mk": "AndroidProducts.mk",
    "BoardConfig.mk": "BoardConfig.mk",
    "device.mk": "device.mk",
    "lineage_device.mk": "lineage_{device}.mk",
    "lineage.dependencies": "lineage.dependencies",
}

#: Templates only written when blobs are extracted.  Both need the exec bit:
#: setup-makefiles.py is a shebang pointing at extract-files.py.
BLOB_TEMPLATES: Dict[str, str] = {
    "extract-files.py": "extract-files.py",
    "setup-makefiles.py": "setup-makefiles.py",
}

#: Files that must be executable once written.
EXECUTABLE_FILES = frozenset(BLOB_TEMPLATES.values())


def load(name: str) -> str:
    """Return the raw text of the template called ``name``."""
    resource = _resource_files("qcomdtgen").joinpath("templates", f"{name}.tmpl")
    try:
        return resource.read_text(encoding="utf-8")
    except (FileNotFoundError, OSError) as exc:
        raise QcomDtGenError(f"missing template: {name}.tmpl") from exc


def render(name: str, context: Dict[str, str]) -> str:
    """Render a template, substituting every ``{{placeholder}}``."""
    template = load(name)
    missing: set = set()

    def drop_if_empty(match: "re.Match[str]") -> str:
        """Optional blocks must not leave a hole behind."""
        key = match.group(1)
        if key in context and not str(context[key]).strip():
            return ""
        return match.group(0)

    def substitute(match: "re.Match[str]") -> str:
        key = match.group(1)
        if key not in context:
            missing.add(key)
            return match.group(0)
        return str(context[key])

    rendered = _PLACEHOLDER.sub(substitute, _STANDALONE.sub(drop_if_empty, template))
    if missing:
        raise QcomDtGenError(
            f"template {name}.tmpl uses unknown placeholder(s): "
            + ", ".join(sorted(missing))
        )
    rendered = "\n".join(line.rstrip() for line in rendered.splitlines())
    return rendered.rstrip("\n") + "\n"
