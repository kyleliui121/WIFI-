"""Run a reproducible saturated DCF baseline experiment."""

import argparse
import json
from pathlib import Path

from .dcf import DCFConfig, DCFSimulator


def main() -> None:
    parser = argparse.ArgumentParser(description="SimPy saturated Wi-Fi DCF baseline")
    parser.add_argument("--stations", type=int, default=10)
    parser.add_argument("--duration", type=float, default=10.0, help="seconds")
    parser.add_argument("--frame-bytes", type=int, default=1500)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--output", type=Path, help="optional path to a JSON result")
    args = parser.parse_args()

    config = DCFConfig(
        stations=args.stations,
        duration_s=args.duration,
        payload_bytes=args.frame_bytes,
        seed=args.seed,
    )
    result = DCFSimulator(config).run()
    report = result.as_dict()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )


if __name__ == "__main__":
    main()
