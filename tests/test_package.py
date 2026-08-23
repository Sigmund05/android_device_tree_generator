"""The packaging metadata and the module must agree on one version."""

from importlib.metadata import PackageNotFoundError, version as installed_version

import pytest

import qcomdtgen


def test_version_is_a_release_string():
    assert qcomdtgen.__version__.count(".") >= 1
    assert all(part.isdigit() for part in qcomdtgen.__version__.split(".")[:2])


def test_installed_metadata_matches_the_module():
    try:
        metadata_version = installed_version("qcomdtgen")
    except PackageNotFoundError:  # not installed, e.g. a bare source checkout
        pytest.skip("qcomdtgen is not installed")
    assert metadata_version == qcomdtgen.__version__


def test_the_package_is_marked_as_typed():
    """PEP 561: without py.typed, callers get no type information."""
    from importlib.resources import files

    assert files("qcomdtgen").joinpath("py.typed").is_file()
