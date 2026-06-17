try:
    from tunneldup._version import __version__, __version_tuple__
except ImportError:  # source checkout without setuptools-scm having run
    __version__ = "0.0.0+unknown"
    __version_tuple__ = (0, 0, 0, "unknown")
