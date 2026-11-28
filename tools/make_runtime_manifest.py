"""Write libstempo/tempo2_runtime.json from a tempo2 source tree.

Usage: python tools/make_runtime_manifest.py <tempo2 source dir>

The tag is read from install_tempo2.sh (TEMPO2_TAG), so the manifest and the tempo2
build always refer to the same release. Run 'make runtime-manifest' after changing the tag.
"""

import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

spec = importlib.util.spec_from_file_location("_runtime", ROOT / "libstempo" / "_runtime.py")
_runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(_runtime)


def main(tempo2_src):
    script = (ROOT / "install_tempo2.sh").read_text()
    tag = re.search(r"^TEMPO2_TAG=(\S+)$", script, re.MULTILINE).group(1)
    runtime_dir = Path(tempo2_src) / "T2runtime"
    if not runtime_dir.is_dir():
        sys.exit("{} not found; nothing written".format(runtime_dir))
    manifest = _runtime.make_manifest(runtime_dir, tag)
    if not manifest["files"]:
        sys.exit("{} has no files; nothing written".format(runtime_dir))
    out = ROOT / "libstempo" / "tempo2_runtime.json"
    out.write_text(json.dumps(manifest, indent=1, sort_keys=True) + "\n")
    n_lazy = sum(e["lazy"] for e in manifest["files"].values())
    print("{}: tag {}, {} files ({} downloaded on first use)".format(out, tag, len(manifest["files"]), n_lazy))


if __name__ == "__main__":
    main(sys.argv[1])
