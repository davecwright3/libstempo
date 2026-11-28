"""Tests of the download-once tempo2 runtime cache (libstempo/_runtime.py).

A local HTTP server serves a small fake runtime, so these tests need no network.
"""

import hashlib
import json
import os
import socket
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from libstempo import _runtime

RUNTIME_PY = Path(_runtime.__file__)

FAKE_FILES = {
    "observatory/aliases": b"gbt GB\n",
    "observatory/observatories.dat": b"1 2 3 GBT gbt\n",
    "clock/gbt2gps.clk": b"# clock\n" * 1000,
    "earth/eopc04_IAU2000.62-now": os.urandom(50_000),
    "ephemeris/TDB.1950.2050": os.urandom(20_000),
    "ephemeris/DE440.1950.2050": os.urandom(300_000),
    "ephemeris/DE421.1950.2050": os.urandom(300_000),
    "example_data/example.par": b"PSR J0000+0000\n",
}
LAZY = {"ephemeris/DE440.1950.2050", "ephemeris/DE421.1950.2050"}
BASE = set(FAKE_FILES) - LAZY - {"example_data/example.par"}


class Server:
    """Serves a directory; counts requests per path; can corrupt or truncate chosen files."""

    def __init__(self, root):
        self.root, self.requests, self.corrupt, self.truncate = Path(root), {}, set(), set()
        lock, server = threading.Lock(), self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_GET(self):
                rel = self.path.lstrip("/")
                with lock:
                    server.requests[rel] = server.requests.get(rel, 0) + 1
                path = server.root / rel
                if not path.is_file():
                    self.send_error(404)
                    return
                data = path.read_bytes()
                if rel in server.corrupt:
                    data = bytes([data[0] ^ 0xFF]) + data[1:]
                self.send_response(200)
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                if rel in server.truncate:
                    self.wfile.write(data[: len(data) // 2])
                    self.wfile.flush()
                    self.connection.shutdown(socket.SHUT_RDWR)
                    return
                self.wfile.write(data)

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:{}/".format(self.httpd.server_address[1])
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def total(self):
        return sum(self.requests.values())


@pytest.fixture
def runtime(tmp_path, monkeypatch):
    """A fake T2runtime served over HTTP, its manifest, and an empty cache directory."""
    src = tmp_path / "T2runtime"
    for rel, data in FAKE_FILES.items():
        (src / rel).parent.mkdir(parents=True, exist_ok=True)
        (src / rel).write_bytes(data)
    manifest = _runtime.make_manifest(src, "test-tag")
    server = Server(src)
    monkeypatch.setenv("LIBSTEMPO_RUNTIME_URL", server.url)
    monkeypatch.setenv("LIBSTEMPO_CACHE_DIR", str(tmp_path / "cache"))
    yield manifest, server, tmp_path / "cache" / "tempo2-test-tag"
    server.httpd.shutdown()


@pytest.fixture
def no_network(monkeypatch):
    def refuse(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", refuse)


def leftovers(root):
    return sorted(p.name for p in Path(root).rglob("*.part"))


def test_manifest_marks_only_planetary_ephemerides_lazy(runtime):
    manifest, _, _ = runtime
    assert "example_data/example.par" not in manifest["files"]
    assert {rel for rel, e in manifest["files"].items() if e["lazy"]} == LAZY


def test_shipped_manifest_matches_install_script():
    """The runtime manifest and the tempo2 build refer to the same tempo2 tag."""
    import re

    script = (Path(__file__).parents[1] / "install_tempo2.sh").read_text()
    tag = re.search(r"^TEMPO2_TAG=(\S+)$", script, re.MULTILINE).group(1)
    manifest = _runtime.load_manifest()
    assert manifest["tempo2_tag"] == tag
    assert "observatory/aliases" in manifest["files"]
    assert manifest["files"]["ephemeris/DE440.1950.2050"]["lazy"]


def test_first_call_downloads_base_set_and_checks_hashes(runtime):
    """Criterion 2."""
    manifest, server, root = runtime
    assert _runtime.ensure_base(manifest) == str(root)
    assert (root / _runtime.COMPLETE_MARKER).is_file()
    assert set(server.requests) == BASE
    for rel in BASE:
        assert hashlib.sha256((root / rel).read_bytes()).hexdigest() == manifest["files"][rel]["sha256"]
    for rel in LAZY:
        assert not (root / rel).exists()


def test_second_call_uses_no_network(runtime, monkeypatch):
    """Criterion 3."""
    manifest, server, root = runtime
    _runtime.ensure_base(manifest)
    n = server.total()

    def refuse(*args, **kwargs):
        raise AssertionError("network access attempted")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    assert _runtime.ensure_base(manifest) == str(root)
    assert server.total() == n


def test_user_tempo2_is_left_alone(tmp_path, monkeypatch, no_network):
    """Criterion 4: with TEMPO2 pointing to a user's runtime, nothing is downloaded or changed."""
    user = tmp_path / "user_tempo2"
    (user / "ephemeris").mkdir(parents=True)
    monkeypatch.setenv("TEMPO2", str(user))
    _runtime.ensure_file(str(user / "ephemeris" / "DE440.1950.2050"))
    assert os.environ["TEMPO2"] == str(user)
    assert list((user / "ephemeris").iterdir()) == []


def test_import_keeps_user_tempo2(tmp_path):
    """Criterion 4, at import: a set TEMPO2 is used as given."""
    code = "import os, libstempo; print(os.environ['TEMPO2'])"
    env = dict(os.environ, TEMPO2=os.environ["TEMPO2"])
    out = subprocess.run(
        [sys.executable, "-c", code], env=env, cwd=tmp_path, capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == os.environ["TEMPO2"]


def test_ephemeris_is_downloaded_once_on_first_use(runtime, monkeypatch):
    """Criterion 5."""
    manifest, server, root = runtime
    _runtime.ensure_base(manifest)
    monkeypatch.setenv("TEMPO2", str(root))
    target = str(root / "ephemeris" / "DE440.1950.2050")
    _runtime.ensure_file(target)
    _runtime.ensure_file(target)
    assert server.requests["ephemeris/DE440.1950.2050"] == 1
    assert "ephemeris/DE421.1950.2050" not in server.requests
    assert Path(target).read_bytes() == FAKE_FILES["ephemeris/DE440.1950.2050"]


def test_hash_mismatch_raises_and_leaves_no_file(runtime):
    """Criterion 6."""
    manifest, server, root = runtime
    server.corrupt.add("clock/gbt2gps.clk")
    with pytest.raises(_runtime.RuntimeDownloadError, match="clock/gbt2gps.clk"):
        _runtime.ensure_base(manifest)
    assert not (root / "clock" / "gbt2gps.clk").exists()
    assert not (root / _runtime.COMPLETE_MARKER).exists()
    assert leftovers(root) == []


def test_interrupted_download_leaves_no_file_and_next_call_completes(runtime):
    """Criterion 7."""
    manifest, server, root = runtime
    server.truncate.add("earth/eopc04_IAU2000.62-now")
    with pytest.raises(_runtime.RuntimeDownloadError, match="eopc04"):
        _runtime.ensure_base(manifest)
    assert not (root / "earth" / "eopc04_IAU2000.62-now").exists()
    assert leftovers(root) == []

    server.truncate.clear()
    _runtime.ensure_base(manifest)
    assert (root / "earth" / "eopc04_IAU2000.62-now").read_bytes() == FAKE_FILES["earth/eopc04_IAU2000.62-now"]
    assert (root / _runtime.COMPLETE_MARKER).is_file()


def test_concurrent_first_use(runtime, tmp_path):
    """Criterion 8: 8 processes filling an empty cache at once all succeed; each file is fetched once."""
    manifest, server, root = runtime
    manifest_file = tmp_path / "manifest.json"
    manifest_file.write_text(json.dumps(manifest))
    code = (
        "import importlib.util, sys\n"
        "spec = importlib.util.spec_from_file_location('_runtime', sys.argv[1])\n"
        "r = importlib.util.module_from_spec(spec); spec.loader.exec_module(r)\n"
        "print(r.ensure_base(r.load_manifest(sys.argv[2])))\n"
    )
    procs = [
        subprocess.Popen(
            [sys.executable, "-c", code, str(RUNTIME_PY), str(manifest_file)],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        for _ in range(8)
    ]
    results = [p.communicate(timeout=120) + (p.returncode,) for p in procs]
    assert all(rc == 0 for _, _, rc in results), [err for _, err, _ in results]
    assert all(out.strip() == str(root) for out, _, _ in results)
    assert server.requests == {rel: 1 for rel in BASE}
    for rel in BASE:
        assert (root / rel).read_bytes() == FAKE_FILES[rel]


def test_ensure_all_downloads_everything(runtime):
    manifest, server, root = runtime
    _runtime.ensure_all(manifest)
    assert set(server.requests) == BASE | LAZY


@pytest.mark.parametrize(
    "name, rel",
    [
        ("DE440", "ephemeris/DE440.1950.2050"),
        ("DE414", "ephemeris/DE414.1960.2020"),
        ("INPOP06", "ephemeris/INPOP06"),
    ],
)
def test_ephemeris_file_follows_tempo2_naming(name, rel):
    assert _runtime.ephemeris_file(name) == rel
    assert rel in _runtime.load_manifest()["files"]


def test_tempopulsar_downloads_missing_ephemeris(tmp_path, monkeypatch):
    """A tempopulsar on a libstempo-managed runtime fetches its EPHEM file once, and gives the same residuals."""
    import numpy as np

    import libstempo as T

    real = Path(os.environ["TEMPO2"])
    data = Path(T.__path__[0]) / "data"
    par, tim = str(data / "J1909-3744_NANOGrav_dfg+12.par"), str(data / "J1909-3744_NANOGrav_dfg+12.tim")
    reference = T.tempopulsar(parfile=par, timfile=tim).residuals()

    # a managed cache that links to the real runtime, except for DE405 (the par file's EPHEM)
    root = tmp_path / "managed"
    for d in real.iterdir():
        if d.name != "ephemeris":
            (root / d.name).parent.mkdir(parents=True, exist_ok=True)
            (root / d.name).symlink_to(d)
    (root / "ephemeris").mkdir(parents=True)
    for f in (real / "ephemeris").iterdir():
        if f.name != "DE405.1950.2050":
            (root / "ephemeris" / f.name).symlink_to(f)
    manifest = {"tempo2_tag": "test-tag", "files": {}}
    for rel in ["ephemeris/DE405.1950.2050"]:
        manifest["files"][rel] = {
            "size": (real / rel).stat().st_size,
            "sha256": hashlib.sha256((real / rel).read_bytes()).hexdigest(),
            "lazy": True,
        }
    server = Server(real)
    try:
        manifest["base_url"] = server.url
        (root / _runtime.CACHE_METADATA).write_text(json.dumps(manifest))
        monkeypatch.setenv("TEMPO2", str(root))
        monkeypatch.delenv("LIBSTEMPO_RUNTIME_URL", raising=False)

        residuals = T.tempopulsar(parfile=par, timfile=tim).residuals()
        T.tempopulsar(parfile=par, timfile=tim)
    finally:
        server.httpd.shutdown()

    assert server.requests == {"ephemeris/DE405.1950.2050": 1}
    assert (root / "ephemeris" / "DE405.1950.2050").is_file()
    np.testing.assert_array_equal(residuals, reference)
