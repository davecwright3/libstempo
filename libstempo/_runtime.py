"""Download the tempo2 runtime data (clock, Earth, observatory and ephemeris files) once.

Wheels of libstempo contain the tempo2 library but no runtime data. On first import,
libstempo downloads the files it needs from the tempo2 release tag recorded in
``tempo2_runtime.json`` into a per-user cache, and checks each file against its SHA-256 hash.
Later imports find the marker file ``.complete`` and use no network. Planetary ephemerides
are large, so each is downloaded only when a pulsar first needs it.

Environment variables:

- ``TEMPO2``: an existing runtime directory. If set, libstempo never downloads anything,
  unless it points to a cache this module created.
- ``LIBSTEMPO_CACHE_DIR``: where the cache lives (default: platformdirs' user cache dir).
- ``LIBSTEMPO_RUNTIME_URL``: base URL to download from (default: the tempo2 repository on Bitbucket).

This module must not import the compiled extension: it runs before the extension is loaded.
"""

import contextlib
import hashlib
import json
import os
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.request import urlopen

MANIFEST_PATH = Path(__file__).parent / "tempo2_runtime.json"
DEFAULT_BASE_URL = "https://bitbucket.org/psrsoft/tempo2/raw/{tag}/T2runtime/"

# file written in each cache directory: a copy of the manifest plus the base URL used
CACHE_METADATA = ".libstempo-runtime.json"
COMPLETE_MARKER = ".complete"
LOCK_FILE = ".lock"

# runtime subdirectories that tempo2 does not need to run
SKIPPED_DIRS = ("example_data",)
# files in ephemeris/ that every run needs (time ephemerides); other ephemeris files are lazy
EAGER_EPHEMERIS = ("TDB.1950.2050", "TIMEEPH_short.te405")

DOWNLOAD_THREADS = 8
TIMEOUT_S = 60
CHUNK = 1 << 20


class RuntimeDownloadError(RuntimeError):
    """A runtime file could not be downloaded or failed its hash check."""


def _sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(CHUNK), b""):
            h.update(block)
    return h.hexdigest()


def make_manifest(runtime_dir, tag):
    """Return the manifest for a tempo2 runtime directory (T2runtime) at release ``tag``."""
    runtime_dir = Path(runtime_dir)
    files = {}
    for path in sorted(p for p in runtime_dir.rglob("*") if p.is_file()):
        rel = path.relative_to(runtime_dir).as_posix()
        if rel.split("/")[0] in SKIPPED_DIRS:
            continue
        lazy = rel.startswith("ephemeris/") and path.name not in EAGER_EPHEMERIS
        files[rel] = {"size": path.stat().st_size, "sha256": _sha256(path), "lazy": lazy}
    return {"tempo2_tag": tag, "files": files}


def load_manifest(path=MANIFEST_PATH):
    with open(path) as f:
        return json.load(f)


def bundled_tempo2():
    """True if this libstempo carries its own tempo2 library (a wheel repaired by auditwheel or delocate)."""
    here = Path(__file__).resolve().parent
    return (here.parent / "libstempo.libs").is_dir() or (here / ".dylibs").is_dir()


def cache_dir(manifest=None):
    """The cache directory for the manifest's tempo2 tag."""
    if manifest is None:
        manifest = load_manifest()
    root = os.environ.get("LIBSTEMPO_CACHE_DIR")
    if not root:
        import platformdirs

        root = platformdirs.user_cache_dir("libstempo")
    return Path(root) / "tempo2-{}".format(manifest["tempo2_tag"])


def base_url(manifest):
    """LIBSTEMPO_RUNTIME_URL if set, else the URL recorded in a cache's metadata, else Bitbucket."""
    url = (
        os.environ.get("LIBSTEMPO_RUNTIME_URL")
        or manifest.get("base_url")
        or DEFAULT_BASE_URL.format(tag=manifest["tempo2_tag"])
    )
    return url if url.endswith("/") else url + "/"


@contextlib.contextmanager
def _locked(directory):
    """Hold an exclusive lock on ``directory`` across processes (no-op where fcntl is missing)."""
    try:
        import fcntl
    except ImportError:  # pragma: no cover (Windows; no wheels are built there)
        yield
        return
    with open(Path(directory) / LOCK_FILE, "a") as f:
        fcntl.flock(f, fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(f, fcntl.LOCK_UN)


def _atomic_write_text(path, text):
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".part")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        raise


def _download(rel, entry, root, url_base):
    """Download one file to root/rel through a temporary file; check size and hash, then rename."""
    dest = Path(root) / rel
    url = url_base + rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=dest.name + ".", suffix=".part")
    try:
        h, size = hashlib.sha256(), 0
        with os.fdopen(fd, "wb") as out, urlopen(url, timeout=TIMEOUT_S) as resp:
            for block in iter(lambda: resp.read(CHUNK), b""):
                out.write(block)
                h.update(block)
                size += len(block)
        if size != entry["size"]:
            raise RuntimeDownloadError("{}: got {} bytes, expected {}".format(rel, size, entry["size"]))
        if h.hexdigest() != entry["sha256"]:
            raise RuntimeDownloadError("{}: SHA-256 does not match the manifest".format(rel))
        os.replace(tmp, dest)
    except BaseException as e:
        with contextlib.suppress(FileNotFoundError):
            os.unlink(tmp)
        if isinstance(e, RuntimeDownloadError):
            raise RuntimeDownloadError(_advice(str(e), url, root)) from None
        if isinstance(e, Exception):
            raise RuntimeDownloadError(_advice("{}: {}".format(rel, e), url, root)) from e
        raise


def _advice(problem, url, root):
    return (
        "Could not download tempo2 runtime file ({}) from {} into {}. "
        "Run 'python -m libstempo.fetch_runtime --all' on a machine with network access "
        "(set LIBSTEMPO_CACHE_DIR to share the cache), or set TEMPO2 to an existing tempo2 runtime directory."
    ).format(problem, url, root)


def _fetch(rels, manifest, root):
    """Download the files in ``rels`` that are not in ``root`` yet. The caller holds the lock."""
    missing = [rel for rel in rels if not (Path(root) / rel).is_file()]
    if not missing:
        return
    url_base = base_url(manifest)
    with ThreadPoolExecutor(DOWNLOAD_THREADS) as pool:
        futures = [pool.submit(_download, rel, manifest["files"][rel], root, url_base) for rel in missing]
        errors = [e for e in (f.exception() for f in futures) if e is not None]
    if errors:
        raise errors[0]


def ensure_base(manifest=None, root=None):
    """Make sure the files every run needs are in the cache; return the cache directory.

    After the first successful call, this checks one marker file and uses no network.
    """
    if manifest is None:
        manifest = load_manifest()
    root = Path(root) if root is not None else cache_dir(manifest)
    if (root / COMPLETE_MARKER).is_file():
        return str(root)
    root.mkdir(parents=True, exist_ok=True)
    with _locked(root):
        if not (root / COMPLETE_MARKER).is_file():
            _atomic_write_text(root / CACHE_METADATA, json.dumps(dict(manifest, base_url=base_url(manifest))))
            _fetch([rel for rel, e in manifest["files"].items() if not e["lazy"]], manifest, root)
            _atomic_write_text(root / COMPLETE_MARKER, manifest["tempo2_tag"] + "\n")
    return str(root)


def ensure_all(manifest=None, root=None):
    """Download every runtime file, including all ephemerides; return the cache directory."""
    if manifest is None:
        manifest = load_manifest()
    root = Path(ensure_base(manifest, root))
    with _locked(root):
        _fetch(list(manifest["files"]), manifest, root)
    return str(root)


def ensure_file(path):
    """Download ``path`` if it is a missing file of the libstempo-managed runtime in $TEMPO2.

    Does nothing for paths outside $TEMPO2, for files that exist, and when $TEMPO2 is not a
    cache made by this module (for example, a tempo2 installed by the user).
    """
    root = os.environ.get("TEMPO2")
    if not root or os.path.isfile(path):
        return
    metadata = Path(root) / CACHE_METADATA
    if not metadata.is_file():
        return
    try:
        rel = Path(os.path.abspath(path)).relative_to(os.path.abspath(root)).as_posix()
    except ValueError:
        return
    manifest = load_manifest(metadata)
    if rel not in manifest["files"]:
        return
    with _locked(root):
        _fetch([rel], manifest, root)


def ensure_file_in(root, rel, manifest=None):
    """Download runtime file ``rel`` into cache ``root`` if it is missing."""
    if manifest is None:
        manifest = load_manifest()
    with _locked(root):
        _fetch([rel], manifest, root)


def ephemeris_file(name):
    """The runtime path tempo2 uses for EPHEM ``name`` (see tempo2's readParfile.C)."""
    if name == "DE414":
        return "ephemeris/DE414.1960.2020"
    if name == "INPOP06":
        return "ephemeris/INPOP06"
    return "ephemeris/{}.1950.2050".format(name)
