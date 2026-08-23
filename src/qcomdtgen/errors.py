"""Exception types raised by qcomdtgen."""


class QcomDtGenError(Exception):
    """Base class for every error raised by qcomdtgen."""


class DumpError(QcomDtGenError):
    """The given path is not a usable Android dump."""


class OutputError(QcomDtGenError):
    """The output location cannot be used."""
