"""Run DCF and EDCA through a locally built ns-3 scenario."""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
from math import isfinite
import os
from pathlib import Path
import subprocess
import sys
from tempfile import TemporaryDirectory

ACS = {"VO", "VI", "BE", "BK"}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    engine = parser.add_mutually_exclusive_group(required=True)
    engine.add_argument("--exe", type=Path)
    engine.add_argument("--dll", type=Path)
    parser.add_argument("--lib-dir", action="append", type=Path, default=[])
    parser.add_argument("--out", type=Path, default=Path("results/ext34/ns3_crosscheck.csv"))
    parser.add_argument("--stations", type=int, nargs="+", default=[10])
    parser.add_argument("--modes", choices=("DCF", "EDCA"), nargs="+", default=["DCF", "EDCA"])
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--ns3-version", help="version of the supplied ns-3 build for the metadata")
    args = parser.parse_args()

    program = (args.exe or args.dll).resolve()
    if not program.is_file():
        parser.error(f"scenario executable or library does not exist: {program}")
    library_dirs = [path.resolve() for path in args.lib_dir]
    for path in library_dirs:
        if not path.is_dir():
            parser.error(f"library directory does not exist: {path}")
    if not isfinite(args.duration) or args.duration <= 0:
        parser.error("duration must be finite and positive")
    if not 1 <= args.seed <= 2_147_483_647:
        parser.error("seed must be in the range 1 to 2147483647")
    if any(not 6 <= n <= 253 for n in args.stations) or len(set(args.stations)) != len(args.stations):
        parser.error("stations must be distinct integers from 6 to 253")
    if len(set(args.modes)) != len(args.modes):
        parser.error("modes must be distinct")

    output = args.out.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    env = os.environ.copy()
    path_var = "PATH" if os.name == "nt" else "LD_LIBRARY_PATH"
    if library_dirs:
        env[path_var] = os.pathsep.join([*(str(p) for p in library_dirs),
                                        *([env[path_var]] if env.get(path_var) else [])])
    here = Path(__file__).resolve().parent

    rows = []
    try:
        with TemporaryDirectory(prefix="ns3-crosscheck-", dir=output.parent) as folder:
            work = Path(folder)
            for n in args.stations:
                for mode in args.modes:
                    case = f"{mode}-{n}.csv"
                    options = [f"--out={case}", f"--stations={n}", f"--mode={mode}",
                               f"--duration={args.duration}", f"--seed={args.seed}"]
                    if args.exe:
                        command = [str(program), *options]
                    else:
                        command = [sys.executable, str(here / "run_ns3_one.py"),
                                   "--dll", str(program), *options]
                        command.extend(f"--lib-dir={path}" for path in library_dirs)
                    subprocess.run(command, cwd=work, env=env, check=True)
                    with (work / case).open(encoding="utf-8", newline="") as source:
                        records = list(csv.DictReader(source))
                    if (len(records) != len(ACS) or {r["ac"] for r in records} != ACS
                            or any((r["mode"], int(r["stations"]), int(r["seed"]), float(r["duration_s"]))
                                   != (mode, n, args.seed, args.duration) for r in records)
                            or any("qos_matched_attempts" not in r for r in records)):
                        raise ValueError(f"invalid cross-check CSV for {mode}, N={n}; rebuild the scenario")
                    rows.extend(records)
                    print(f"ns-3: {mode}, N={n}, seed={args.seed}", flush=True)
            combined = work / "combined.csv"
            with combined.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            combined.replace(output)
    except (OSError, subprocess.CalledProcessError, ValueError, KeyError) as exc:
        parser.exit(1, f"ns-3 cross-check failed: {exc}\n")

    metadata = {
        "ns3_version": args.ns3_version,
        "stations": args.stations, "modes": args.modes,
        "duration_s": args.duration, "seed": args.seed,
        "scenario_sha256": hashlib.sha256(
            (here / "wifi-edca-crosscheck.cc").read_bytes().replace(b"\r\n", b"\n")
        ).hexdigest(),
        "binary_sha256": hashlib.sha256(program.read_bytes()).hexdigest(),
        "csv_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
    }
    output.with_name(f"{output.stem}_metadata.json").write_text(
        json.dumps(metadata, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(rows)} validated rows to {output}")


if __name__ == "__main__":
    main()
