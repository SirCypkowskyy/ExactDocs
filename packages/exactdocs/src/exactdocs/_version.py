from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("exactdocs")
except PackageNotFoundError:  # running from a source tree without installed metadata
    __version__ = "0.0.0"
