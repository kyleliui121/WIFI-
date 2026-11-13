"""Saturated IEEE 802.11 DCF simulator for the course-design baseline.

The simulation clock is in microseconds. SimPy advances to the next channel
transmission rather than visiting every empty 9-us slot, but the backoff
counters still count down in integer idle slots and freeze while the medium is
busy. All stations can hear one another (no hidden terminals).
"""

from __future__ import annotations

import random
from dataclasses import asdict, dataclass, field
from statistics import fmean

import simpy


@dataclass(frozen=True)
class DCFConfig:
    stations: int = 10
    duration_s: float = 10.0
    payload_bytes: int = 1500
    seed: int = 42
    slot_us: float = 9.0
    sifs_us: float = 16.0
    preamble_us: float = 20.0
    phy_rate_mbps: float = 54.0
    ack_bytes: int = 14
    cw_min: int = 15
    cw_max: int = 1023
    retry_limit: int = 7

    def __post_init__(self) -> None:
        if self.stations < 1 or self.duration_s <= 0 or self.payload_bytes < 1:
            raise ValueError("stations, duration_s and payload_bytes must be positive")
        if self.slot_us <= 0 or self.sifs_us <= 0 or self.preamble_us < 0:
            raise ValueError("invalid MAC/PHY timing")
        if self.phy_rate_mbps <= 0 or self.ack_bytes < 0:
            raise ValueError("invalid PHY rate or ACK size")
        if not (0 <= self.cw_min <= self.cw_max) or self.retry_limit < 0:
            raise ValueError("invalid contention windows or retry limit")

    @property
    def difs_us(self) -> float:
        return self.sifs_us + 2 * self.slot_us

    def frame_time_us(self, frame_bytes: int) -> float:
        # With rate in Mbit/s and time in us, bits / Mbps yields us.
        return self.preamble_us + frame_bytes * 8 / self.phy_rate_mbps


@dataclass
class Station:
    station_id: int
    backoff: int
    retries: int = 0
    packet_ready_us: float = 0.0


@dataclass
class DCFResult:
    config: DCFConfig
    elapsed_s: float
    attempts: int = 0
    collided_attempts: int = 0
    collision_events: int = 0
    successful_frames: int = 0
    dropped_frames: int = 0
    delivered_payload_bits: int = 0
    access_delays_us: list[float] = field(default_factory=list, repr=False)

    @property
    def collision_probability(self) -> float:
        # A collision involving 2 stations accounts for 2 failed attempts.
        return self.collided_attempts / self.attempts if self.attempts else 0.0

    @property
    def throughput_mbps(self) -> float:
        return self.delivered_payload_bits / self.elapsed_s / 1_000_000

    @property
    def mean_delay_ms(self) -> float | None:
        return fmean(self.access_delays_us) / 1000 if self.access_delays_us else None

    def as_dict(self) -> dict:
        return {
            "mode": "saturated_dcf",
            "config": asdict(self.config),
            "elapsed_s": self.elapsed_s,
            "attempts": self.attempts,
            "collided_attempts": self.collided_attempts,
            "collision_events": self.collision_events,
            "collision_probability": self.collision_probability,
            "successful_frames": self.successful_frames,
            "dropped_frames": self.dropped_frames,
            "throughput_mbps": self.throughput_mbps,
            "mean_access_delay_ms": self.mean_delay_ms,
            "p99_access_delay_ms": percentile(self.access_delays_us, 0.99),
            "p999_access_delay_ms": percentile(self.access_delays_us, 0.999),
        }


def percentile(delays_us: list[float], quantile: float) -> float | None:
    """Linearly interpolated percentile in milliseconds, or None when empty."""
    if not delays_us:
        return None
    values = sorted(delays_us)
    position = (len(values) - 1) * quantile
    lo = int(position)
    hi = min(lo + 1, len(values) - 1)
    value_us = values[lo] + (values[hi] - values[lo]) * (position - lo)
    return value_us / 1000


class DCFSimulator:
    """One shared medium and a saturated packet source per station.

    CW at retry r is min((CWmin + 1) * 2**r - 1, CWmax).
    A packet is dropped after an initial transmission plus retry_limit
    retransmissions (8 total attempts with the default retry_limit=7).
    """

    def __init__(self, config: DCFConfig):
        self.config = config
        self.env = simpy.Environment()
        self.rng = random.Random(config.seed)
        self.stations = [
            Station(i, self.rng.randint(0, config.cw_min))
            for i in range(config.stations)
        ]
        self.result = DCFResult(config=config, elapsed_s=config.duration_s)
        self._has_run = False

    def contention_window(self, retries: int) -> int:
        cfg = self.config
        return min((cfg.cw_min + 1) * (2 ** retries) - 1, cfg.cw_max)

    def _draw_backoff(self, retries: int) -> int:
        return self.rng.randint(0, self.contention_window(retries))

    def _restart_station(self, station: Station) -> None:
        station.retries = 0
        station.packet_ready_us = self.env.now
        station.backoff = self._draw_backoff(0)

    def _channel_loop(self):
        cfg = self.config
        deadline_us = cfg.duration_s * 1_000_000
        # For each attempt, success is DATA + SIFS + ACK. After a collision,
        # use the same SIFS + ACK airtime as an explicit ACK-timeout proxy.
        # It is not a detailed 802.11 PHY ACK timeout implementation.
        attempt_us = (
            cfg.frame_time_us(cfg.payload_bytes)
            + cfg.sifs_us
            + cfg.frame_time_us(cfg.ack_bytes)
        )

        while True:
            slots_to_next_attempt = min(st.backoff for st in self.stations)
            idle_us = cfg.difs_us + slots_to_next_attempt * cfg.slot_us
            # Do not count a frame whose ACK / failure timeout cannot fit
            # in the requested observation interval.
            if self.env.now + idle_us + attempt_us > deadline_us:
                return

            yield self.env.timeout(idle_us)
            for station in self.stations:
                station.backoff -= slots_to_next_attempt

            contenders = [st for st in self.stations if st.backoff == 0]
            self.result.attempts += len(contenders)

            # The medium is busy until the ACK is received, or until the
            # collision's simplified ACK timeout has elapsed. Backoff of all
            # nontransmitting stations remains frozen throughout this time.
            yield self.env.timeout(attempt_us)

            if len(contenders) == 1:
                station = contenders[0]
                self.result.successful_frames += 1
                self.result.delivered_payload_bits += cfg.payload_bytes * 8
                self.result.access_delays_us.append(
                    self.env.now - station.packet_ready_us
                )
                self._restart_station(station)
            else:
                self.result.collision_events += 1
                self.result.collided_attempts += len(contenders)
                for station in contenders:
                    station.retries += 1
                    if station.retries > cfg.retry_limit:
                        self.result.dropped_frames += 1
                        self._restart_station(station)
                    else:
                        station.backoff = self._draw_backoff(station.retries)

    def run(self) -> DCFResult:
        if self._has_run:
            raise RuntimeError("DCFSimulator.run() can only be called once")
        self._has_run = True
        self.env.process(self._channel_loop())
        self.env.run(until=self.config.duration_s * 1_000_000)
        return self.result
