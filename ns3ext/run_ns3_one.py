"""Run one cross-check variant from a locally built scenario library."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
import ctypes
import os
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dll", required=True, type=Path)
    parser.add_argument("--lib-dir", action="append", type=Path, default=[])
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--stations", type=int, default=10)
    parser.add_argument("--mode", choices=("DCF", "EDCA"), required=True)
    parser.add_argument("--duration", type=float, default=10.0)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    library = args.dll.resolve()
    if not library.is_file():
        parser.error(f"scenario library does not exist: {library}")
    directories = list(dict.fromkeys([library.parent, *(p.resolve() for p in args.lib_dir)]))
    for path in directories:
        if not path.is_dir():
            parser.error(f"library directory does not exist: {path}")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    try:
        with ExitStack() as scope:
            if hasattr(os, "add_dll_directory"):
                for directory in directories:
                    scope.enter_context(os.add_dll_directory(str(directory)))
            function = ctypes.CDLL(str(library)).run_scenario
            function.argtypes = [ctypes.c_char_p, ctypes.c_int, ctypes.c_int,
                                 ctypes.c_double, ctypes.c_int]
            function.restype = ctypes.c_int
            code = function(str(args.out.resolve()).encode("utf-8"), args.stations,
                            int(args.mode == "EDCA"), args.duration, args.seed)
    except (OSError, AttributeError) as exc:
        parser.exit(1, f"Could not load run_scenario from {library}: {exc}\n")
    raise SystemExit(code)


if __name__ == "__main__":
    main()
