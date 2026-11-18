"""Independently re-solve the Bianchi fixed point (bisection, no scipy) and
compare with data/official_bianchi.csv.

Usage:  python tools/verify_bianchi.py
"""
import csv
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

CW_MIN, CW_MAX, RETRY = 15, 1023, 7


def stages():
    s = [CW_MIN]
    while s[-1] < CW_MAX:
        s.append(min(2 * (s[-1] + 1) - 1, CW_MAX))
    return s


STAGES = stages()


def tau(p, retry_limit=None):
    if retry_limit is None:
        w = [p ** k for k in range(len(STAGES) - 1)]
        w.append(p ** (len(STAGES) - 1) / (1 - p))
        cw = STAGES
    else:
        w = [p ** k for k in range(retry_limit + 1)]
        cw = [STAGES[min(k, len(STAGES) - 1)] for k in range(retry_limit + 1)]
    return sum(w) / sum(x * (c + 2) / 2 for x, c in zip(w, cw))


def p_collision(n, retry_limit=None):
    if n <= 1:
        return 0.0
    lo, hi = 1e-12, 1 - 1e-12
    for _ in range(200):
        mid = (lo + hi) / 2
        if mid - (1 - (1 - tau(mid, retry_limit)) ** (n - 1)) > 0:
            hi = mid
        else:
            lo = mid
    return (lo + hi) / 2


rows = list(csv.DictReader((ROOT / "data" / "official_bianchi.csv").open(encoding="utf-8")))
print("{:>3} {:>13} {:>13} {:>13} {:>10}".format("N", "classic", "finite", "csv_classic", "delta"))
worst = 0.0
for row in rows:
    n = int(row["stations"])
    a, b = p_collision(n), p_collision(n, RETRY)
    ca = float(row["bianchi_classic"])
    worst = max(worst, abs(a - ca), abs(b - float(row["bianchi_finite"])))
    print("{:>3} {:>13.9f} {:>13.9f} {:>13.9f} {:>10.1e}".format(n, a, b, ca, abs(a - ca)))
print("max abs delta:", worst)
print("VERDICT:", "match" if worst < 1e-9 else "MISMATCH")
sys.exit(0 if worst < 1e-9 else 1)
