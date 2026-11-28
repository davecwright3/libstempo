import os
from . import _runtime
from ._find_tempo2 import find_tempo2_runtime

# Import sandbox functionality
from .sandbox import tempopulsar as sandbox_tempopulsar, Policy, configure_logging  # noqa: F401
from .tim_file_analyzer import TimFileAnalyzer  # noqa: F401

# check to see if TEMPO2 environment variable is set
TEMPO2_RUNTIME = os.getenv("TEMPO2")


# if not, a wheel downloads the runtime once into the user cache; a source install
# looks for an installed tempo2 and raises an error otherwise
if not TEMPO2_RUNTIME:
    if _runtime.bundled_tempo2():
        os.environ["TEMPO2"] = _runtime.ensure_base()
    else:
        os.environ["TEMPO2"] = find_tempo2_runtime()


from libstempo.libstempo import *  # noqa F401,F402,F403

try:
    from ._version import version as __version__
except ModuleNotFoundError:
    __version__ = ""
