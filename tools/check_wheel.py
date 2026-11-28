"""Check that built wheels bundle tempo2 but no tempo2 runtime data.

Usage: python tools/check_wheel.py wheelhouse/*.whl
"""

import sys
import zipfile

RUNTIME_DIRS = ("atmosphere", "clock", "earth", "ephemeris", "observatory", "solarWindModel", "plugin_data")


def problems(path):
    names = zipfile.ZipFile(path).namelist()
    found = []
    runtime = [n for n in names if "T2runtime" in n or any("/{}/".format(d) in "/" + n for d in RUNTIME_DIRS)]
    if runtime:
        found.append("runtime data files: {}".format(runtime[:5]))
    if not any("libtempo2" in n and n.startswith(("libstempo.libs/", "libstempo/.dylibs/")) for n in names):
        found.append("no bundled libtempo2")
    for required in ("libstempo/TEMPO2_COPYING", "libstempo/tempo2_runtime.json"):
        if required not in names:
            found.append("missing " + required)
    build_only = [n for n in names if n.endswith((".pyx", ".cpp", ".h"))]
    if build_only:
        found.append("build-only files: {}".format(build_only))
    return found


def main(paths):
    failed = False
    for path in paths:
        found = problems(path)
        size = sum(i.compress_size for i in zipfile.ZipFile(path).infolist())
        print("{}: {:.2f} MB compressed, {}".format(path, size / 1e6, "; ".join(found) or "ok"))
        failed |= bool(found)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
