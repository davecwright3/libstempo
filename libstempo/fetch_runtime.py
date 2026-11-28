"""Download the tempo2 runtime data into libstempo's cache ahead of time.

Use this on a login node before running on compute nodes without network access:

    python -m libstempo.fetch_runtime            # files every run needs
    python -m libstempo.fetch_runtime --ephem DE440 DE421
    python -m libstempo.fetch_runtime --all      # also every planetary ephemeris

Set LIBSTEMPO_CACHE_DIR to put the cache on a shared filesystem. Files already in the
cache are not downloaded again.
"""

import argparse

from libstempo import _runtime


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m libstempo.fetch_runtime", description=__doc__.splitlines()[0])
    parser.add_argument("--all", action="store_true", help="download every runtime file, including all ephemerides")
    parser.add_argument("--ephem", nargs="+", default=[], metavar="NAME", help="ephemerides to download, e.g. DE440")
    args = parser.parse_args(argv)

    manifest = _runtime.load_manifest()
    if args.all:
        root = _runtime.ensure_all(manifest)
    else:
        root = _runtime.ensure_base(manifest)
        for name in args.ephem:
            rel = _runtime.ephemeris_file(name)
            if rel not in manifest["files"]:
                parser.error("tempo2 {} has no ephemeris {}".format(manifest["tempo2_tag"], name))
            _runtime.ensure_file_in(root, rel, manifest)
    print("tempo2 {} runtime in {}".format(manifest["tempo2_tag"], root))


if __name__ == "__main__":
    main()
