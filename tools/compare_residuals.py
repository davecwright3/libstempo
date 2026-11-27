"""Compare libstempo results between two installs (for example a wheel and a source build).

    python tools/compare_residuals.py dump OUT.json     # run in each environment
    python tools/compare_residuals.py compare A.json B.json [--tol-ns 1]

dump fits each pulsar in libstempo/data and records pre-fit and post-fit residuals and
fitted parameters. compare prints the largest differences and exits 1 if any residual
differs by more than the tolerance.
"""

import argparse
import json
import sys
from pathlib import Path


def dump(out):
    import libstempo as T

    data = Path(T.__path__[0]) / "data"
    result = {"tempo2": str(T.tempo2version()), "pulsars": {}}
    for par in sorted(data.glob("*.par")):
        psr = T.tempopulsar(parfile=str(par), timfile=str(par.with_suffix(".tim")))
        prefit = [float(r) for r in psr.residuals()]
        psr.fit()
        result["pulsars"][par.stem] = {
            "prefit": prefit,
            "postfit": [float(r) for r in psr.residuals()],
            "params": {p: [float(psr[p].val), float(psr[p].err)] for p in psr.pars()},
        }
    Path(out).write_text(json.dumps(result))


def compare(a_path, b_path, tol_ns):
    a, b = json.loads(Path(a_path).read_text()), json.loads(Path(b_path).read_text())
    print("tempo2 {} vs {}".format(a["tempo2"], b["tempo2"]))
    worst = 0.0
    for name in a["pulsars"]:
        pa, pb = a["pulsars"][name], b["pulsars"][name]
        for kind in ("prefit", "postfit"):
            diff = max(abs(x - y) for x, y in zip(pa[kind], pb[kind])) * 1e9
            worst = max(worst, diff)
            print("{} {}: max |difference| {:.3g} ns over {} TOAs".format(name, kind, diff, len(pa[kind])))
        params = [p for p in pa["params"] if pa["params"][p][1] > 0]
        shifts = [abs(pa["params"][p][0] - pb["params"][p][0]) / pa["params"][p][1] for p in params]
        print("{} parameters: max shift {:.3g} sigma".format(name, max(shifts)))
    ok = worst <= tol_ns
    print("largest residual difference {:.3g} ns; tolerance {} ns: {}".format(worst, tol_ns, "ok" if ok else "FAILED"))
    return 0 if ok else 1


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("dump").add_argument("out")
    c = sub.add_parser("compare")
    c.add_argument("a")
    c.add_argument("b")
    c.add_argument("--tol-ns", type=float, default=1.0)
    args = parser.parse_args()
    if args.cmd == "dump":
        dump(args.out)
        return 0
    return compare(args.a, args.b, args.tol_ns)


if __name__ == "__main__":
    sys.exit(main())
