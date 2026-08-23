"""Loading and rendering the device tree templates.

Templates are plain text files shipped as package data.  Placeholders are
written as ``{{name}}`` so that the templates can contain make's ``$(VAR)``,
soong's braces and python's format characters untouched.

Two rules give the templates their conditionals without a template language:

* a placeholder alone on its line disappears with the line when its value is
  empty, which is how the optional A/B, dynamic partition and vendor blob
  blocks vanish;
* ``{{license}}`` is filled in from ``license.tmpl`` with the comment marker
  the output file needs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import PurePosixPath
from typing import Dict, Iterator, Mapping, Set, Tuple

try:  # python >= 3.9
    from importlib.resources import files as _resource_files
except ImportError:  # pragma: no cover - python 3.8 fallback
    from importlib_resources import files as _resource_files  # type: ignore

from qcomdtgen.errors import TemplateError

#: ``{{name}}``, anywhere in a template.
_PLACEHOLDER = re.compile(r"\{\{\s*(\w+)\s*\}\}")
#: The same, alone on its line, plus the blank line that follows it.
_STANDALONE = re.compile(r"(?m)^[ \t]*\{\{\s*(\w+)\s*\}\}[ \t]*\n\n?")

_TEMPLATE_SUFFIX = ".tmpl"
_TEMPLATE_PACKAGE = "qcomdtgen"
_TEMPLATE_DIR = "templates"

#: The shared license header, rendered into every template's ``{{license}}``.
LICENSE_TEMPLATE = "license"
LICENSE_PLACEHOLDER = "license"

#: Comment marker per output file type.  license.tmpl is written with ``#``
#: and translated for the rest.
_DEFAULT_COMMENT = "#"
_COMMENT_STYLES: Dict[str, str] = {".bp": "//"}


@dataclass(frozen=True)
class Template:
    """One template and what the generator does with its output."""

    #: Template basename, without the .tmpl suffix.
    name: str
    #: Output filename; ``{device}`` is filled in per device.
    filename: str
    #: Only written when blobs are extracted.
    blobs_only: bool = False
    #: Written with the executable bit set.
    executable: bool = False

    def output_name(self, device: str) -> str:
        return self.filename.format(device=device)


#: Every template, in the order the generator writes them.  extract-files.py
#: and setup-makefiles.py need the exec bit: setup-makefiles.py is a shebang
#: pointing at extract-files.py.
TEMPLATES: Tuple[Template, ...] = (
    Template("Android.bp", "Android.bp"),
    Template("AndroidProducts.mk", "AndroidProducts.mk"),
    Template("BoardConfig.mk", "BoardConfig.mk"),
    Template("device.mk", "device.mk"),
    Template("lineage_device.mk", "lineage_{device}.mk"),
    Template("lineage.dependencies", "lineage.dependencies"),
    Template("extract-files.py", "extract-files.py", blobs_only=True, executable=True),
    Template("setup-makefiles.py", "setup-makefiles.py", blobs_only=True, executable=True),
)


def templates_for(with_blobs: bool) -> Iterator[Template]:
    """The templates to write for this run."""
    for template in TEMPLATES:
        if template.blobs_only and not with_blobs:
            continue
        yield template


@lru_cache(maxsize=None)
def load(name: str) -> str:
    """Return the raw text of the template called ``name``.

    Templates are read once per process; they are package data and cannot
    change underneath a run.
    """
    resource = _resource_files(_TEMPLATE_PACKAGE).joinpath(
        _TEMPLATE_DIR, f"{name}{_TEMPLATE_SUFFIX}"
    )
    try:
        return resource.read_text(encoding="utf-8")
    except OSError as exc:  # FileNotFoundError included
        raise TemplateError(f"missing template: {name}{_TEMPLATE_SUFFIX}") from exc


def placeholders(name: str) -> Set[str]:
    """Every ``{{placeholder}}`` a template references."""
    return set(_PLACEHOLDER.findall(load(name)))


def comment_marker(filename: str) -> str:
    """The comment marker the given output file uses."""
    suffix = PurePosixPath(filename).suffix
    return _COMMENT_STYLES.get(suffix, _DEFAULT_COMMENT)


@lru_cache(maxsize=None)
def license_header(marker: str = _DEFAULT_COMMENT) -> str:
    """The license header, re-commented with ``marker``."""
    header = load(LICENSE_TEMPLATE).rstrip("\n")
    if marker == _DEFAULT_COMMENT:
        return header
    return "\n".join(
        marker + line[len(_DEFAULT_COMMENT) :] if line.startswith(_DEFAULT_COMMENT) else line
        for line in header.splitlines()
    )


def render(name: str, context: Mapping[str, str], filename: str = "") -> str:
    """Render a template, substituting every ``{{placeholder}}``.

    ``filename`` is the name the result is written as; it decides the comment
    style of the license header and defaults to the template's own name.
    """
    values: Dict[str, str] = {
        **context,
        LICENSE_PLACEHOLDER: license_header(comment_marker(filename or name)),
    }
    unknown = placeholders(name) - values.keys()
    if unknown:
        raise TemplateError(
            f"template {name}{_TEMPLATE_SUFFIX} uses unknown placeholder(s): "
            + ", ".join(sorted(unknown))
        )

    def drop_if_empty(match: re.Match) -> str:
        """An optional block must not leave a hole behind."""
        key = match.group(1)
        return "" if not str(values[key]).strip() else match.group(0)

    def substitute(match: re.Match) -> str:
        return str(values[match.group(1)])

    rendered = _PLACEHOLDER.sub(substitute, _STANDALONE.sub(drop_if_empty, load(name)))
    # Substituted blocks can leave trailing spaces behind; makefiles are
    # whitespace sensitive enough that they are worth removing.
    return "\n".join(line.rstrip() for line in rendered.splitlines()).rstrip("\n") + "\n"
