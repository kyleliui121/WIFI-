"""Reproducible SimPy MAC model for A-class vehicular Wi-Fi experiments.

Event-driven backoff counts down only during idle channel time. This is a
*teaching approximation*, not a bit-accurate implementation of IEEE 802.11bn.
Times are in microseconds throughout.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from math import floor
import random
from statistics import fmean

import simpy

from .dcf import percentile

EPS = 1e-7
MODES = ("DCF", "EDCA", "P-EDCA", "NPCA")


@dataclass(frozen=True)
class MACConfig:
    stations: int = 10
    mode: str = "EDCA"
    duration_s: float = 10.0
    seed: int = 42
    high_stations: int = 2
    high_period_us: float = 10_000.0
    high_frame_bytes: int = 100
    deadline_us: float = 10_000.0
    low_frame_bytes: int = 1500
    slot_us: float = 9.0
    sifs_us: float = 16.0
    preamble_us: float = 20.0
    phy_rate_mbps: float = 54.0
    ack_bytes: int = 14
    retry_limit: int = 7
    primary_busy_fraction: float = 0.30
    mean_external_busy_us: float = 2000.0
    switch_us: float = 100.0
    urgent_queue_us: float = 5000.0
    urgent_retry_count: int = 2
    urgent_aifsn: int = 1
    urgent_cw_min: int = 1
    urgent_cw_max: int = 3

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"invalid mode {self.mode}: expected {MODES}")
        if self.stations < 3 or not 1 <= self.high_stations < self.stations:
            raise ValueError("require at least one high and one low station")
        if min(self.duration_s, self.high_period_us, self.deadline_us,
               self.slot_us, self.sifs_us, self.phy_rate_mbps,
               self.mean_external_busy_us) <= 0:
            raise ValueError("timing, duration, and PHY rate must be positive")
        if self.low_frame_bytes < 1 or self.high_frame_bytes < 1 or self.ack_bytes < 0:
            raise ValueError("invalid frame lengths")
        if not 0 < self.primary_busy_fraction < 1:
            raise ValueError("external busy fraction must lie in (0, 1)")
        if not 50 <= self.switch_us <= 200:
            raise ValueError("NPCA switching delay must be 50-200 us")
        if self.retry_limit < 0 or self.urgent_retry_count < 0:
            raise ValueError("retry counters must be nonnegative")
        if not 0 <= self.urgent_cw_min <= self.urgent_cw_max:
            raise ValueError("invalid urgent contention window")
        if self.urgent_queue_us <= 0:
            raise ValueError("urgent threshold must be positive")

    @property
    def duration_us(self) -> float:
        return self.duration_s * 1_000_000

    def frame_us(self, size: int) -> float:
        return self.preamble_us + size * 8 / self.phy_rate_mbps

    def tx_us(self, sizes: list[int]) -> float:
        # Approximate collision ACK-timeout = SIFS + ACK airtime.
        return max(self.frame_us(size) for size in sizes) + self.sifs_us + self.frame_us(self.ack_bytes)


@dataclass
class Packet:
    created_us: float
    retries: int = 0
    urgent: bool = False


@dataclass
class Node:
    station_id: int
    high: bool
    queue: deque[Packet] = field(default_factory=deque)
    channel: int = 0
    backoff: int = 0
    ifs_remaining: float = 0.0
    slot_progress: float = 0.0
    switching_until: float | None = None
    switch_target: int | None = None
    pending_target: int | None = None
    transmitting: bool = False

    @property
    def head(self) -> Packet | None:
        return self.queue[0] if self.queue else None


@dataclass
class Transmission:
    end_us: float
    contenders: list[Node]
    channel: int


@dataclass
class MACResult:
    config: MACConfig
    high_delays_us: list[float] = field(default_factory=list)
    high_generated: int = 0
    high_success: int = 0
    high_dropped: int = 0
    high_success_late: int = 0
    low_success: int = 0
    low_dropped: int = 0
    collisions: int = 0
    collision_events: int = 0
    attempts: int = 0
    low_bits: int = 0
    external_busy_us: float = 0.0
    secondary_success: int = 0
    switch_events: int = 0
    unfinished_high: int = 0

    def as_dict(self) -> dict:
        c = self.config
        resolved = self.high_success + self.high_dropped
        deadline_failures = self.high_success_late + self.high_dropped
        p999 = percentile(self.high_delays_us, 0.999)
        return {
            "mode": c.mode, "stations": c.stations, "seed": c.seed,
            "duration_s": c.duration_s, "high_generated": self.high_generated,
            "high_success": self.high_success, "high_dropped": self.high_dropped,
            "high_unfinished": self.unfinished_high,
            "high_resolved": resolved,
            "deadline_us": c.deadline_us,
            "high_success_late": self.high_success_late,
            "high_deadline_failure": deadline_failures,
            "high_mean_ms": (fmean(self.high_delays_us) / 1000
                             if self.high_delays_us else None),
            "high_p99_ms": percentile(self.high_delays_us, 0.99),
            "high_p999_ms": p999,
            # Late ACKs are conditional on success; drops are a separate outcome.
            "high_success_late_pct": (100 * self.high_success_late / self.high_success
                                      if self.high_success else None),
            "deadline_failure_pct": (100 * deadline_failures / resolved
                                     if resolved else None),
            "high_drop_pct": (100 * self.high_dropped / resolved if resolved else None),
            "high_unfinished_pct": (100 * self.unfinished_high / self.high_generated
                                    if self.high_generated else None),
            "low_throughput_mbps": self.low_bits / c.duration_s / 1_000_000,
            "collision_pct": (100 * self.collisions / self.attempts
                              if self.attempts else None),
            "attempts": self.attempts, "collided_attempts": self.collisions,
            "collision_events": self.collision_events,
            "equivalent_distance_cm": (p999 * (10 / 3.6) / 10
                                       if p999 is not None else None),
            "observed_primary_external_busy_pct": 100 * self.external_busy_us / c.duration_us,
            "secondary_success": self.secondary_success,
            "switch_events": self.switch_events,
        }


class MACSimulator:
    """One SimPy process orchestrating arrivals, backoff, channel occupancy.

    For fair comparisons, all four modes share the same external-primary-busy
    calendar (seed + 1_000_000) and per-node random streams (seed + id*9973).
    Primary external periods alternate exponential busy (mean 2 ms) and
    exponential idle (mean 4.667 ms at 30% target occupancy).
    Secondary channel is available only in NPCA while primary is externally busy.
    """
    def __init__(self, config: MACConfig):
        self.config = config
        self.env = simpy.Environment()
        self.nodes = [Node(i, i < config.high_stations) for i in range(config.stations)]
        self.rng = [random.Random(config.seed + i * 9973) for i in range(config.stations)]
        self.report = MACResult(config)
        self.busy: dict[int, Transmission | None] = {0: None, 1: None}
        self.external_busy = False
        self.external_events = self._external_events()
        self.external_index = 0
        self.next_arrival = 0.0
        self._has_run = False
        for node in self.nodes:
            if not node.high:
                node.queue.append(Packet(0.0))
                self._reset_backoff(node)

    def _external_events(self) -> list[tuple[float, bool]]:
        c = self.config
        rng = random.Random(c.seed + 1_000_000)
        idle_mean = c.mean_external_busy_us * (1 - c.primary_busy_fraction) / c.primary_busy_fraction
        t = rng.expovariate(1 / idle_mean)
        events = []
        while t < c.duration_us:
            events.append((t, True))
            t += rng.expovariate(1 / c.mean_external_busy_us)
            events.append((min(t, c.duration_us), False))
            t += rng.expovariate(1 / idle_mean)
        return events

    def _next_external(self) -> float:
        return (self.external_events[self.external_index][0]
                if self.external_index < len(self.external_events) else float("inf"))

    def _params(self, node: Node) -> tuple[int, int, int]:
        if self.config.mode == "DCF":
            return 2, 15, 1023
        if not node.high:
            return 3, 15, 1023
        if node.head and node.head.urgent and self.config.mode in ("P-EDCA", "NPCA"):
            c = self.config
            return c.urgent_aifsn, c.urgent_cw_min, c.urgent_cw_max
        return 2, 3, 7

    def _aifs(self, node: Node) -> float:
        return self.config.sifs_us + self._params(node)[0] * self.config.slot_us

    def _reset_ifs(self, node: Node) -> None:
        node.ifs_remaining = self._aifs(node)
        node.slot_progress = 0.0

    def _reset_backoff(self, node: Node) -> None:
        _, cw_min, cw_max = self._params(node)
        assert node.head is not None
        r = node.head.retries
        cw = min((cw_min + 1) * (2 ** min(r, 20)) - 1, cw_max)
        node.backoff = self.rng[node.station_id].randint(0, cw)
        self._reset_ifs(node)

    def _start_switch(self, node: Node, target: int, now: float) -> None:
        if node.transmitting:
            node.pending_target = target
            return
        if node.channel == target and node.switching_until is None:
            return
        node.switch_target = target
        node.switching_until = now + self.config.switch_us
        node.slot_progress = 0.0
        self.report.switch_events += 1

    def _switch_update(self, now: float) -> None:
        if self.config.mode != "NPCA":
            return
        desired = 1 if self.external_busy else 0
        for node in self.nodes[:self.config.high_stations]:
            if node.transmitting:
                node.pending_target = desired
            elif node.switching_until is not None:
                if node.switch_target != desired:
                    self._start_switch(node, desired, now)
            else:
                self._start_switch(node, desired, now)

    def _end_transmissions(self, now: float) -> None:
        for channel, tx in tuple(self.busy.items()):
            if tx is None or tx.end_us > now + EPS:
                continue
            self.busy[channel] = None
            if len(tx.contenders) > 1:
                self.report.collision_events += 1
            for node in tx.contenders:
                node.transmitting = False
                packet = node.head
                assert packet is not None
                if len(tx.contenders) == 1:
                    node.queue.popleft()
                    if node.high:
                        delay = now - packet.created_us
                        self.report.high_delays_us.append(delay)
                        self.report.high_success += 1
                        if delay > self.config.deadline_us:
                            self.report.high_success_late += 1
                    else:
                        self.report.low_success += 1
                        self.report.low_bits += self.config.low_frame_bytes * 8
                    if channel == 1:
                        self.report.secondary_success += 1
                    if not node.high:
                        node.queue.append(Packet(now))
                    if node.head:
                        self._reset_backoff(node)
                else:
                    self.report.collisions += 1
                    packet.retries += 1
                    if packet.retries > self.config.retry_limit:
                        node.queue.popleft()
                        if node.high:
                            self.report.high_dropped += 1
                        else:
                            self.report.low_dropped += 1
                            node.queue.append(Packet(now))
                    if node.head:
                        self._refresh_urgent_one(node, now)
                        self._reset_backoff(node)
                if node.pending_target is not None:
                    target = node.pending_target
                    node.pending_target = None
                    self._start_switch(node, target, now)
            self._channel_resets(channel)

    def _channel_resets(self, channel: int) -> None:
        for node in self.nodes:
            if node.channel == channel and node.head and not node.transmitting:
                self._reset_ifs(node)

    def _refresh_urgent_one(self, node: Node, now: float) -> None:
        packet = node.head
        if (self.config.mode not in ("P-EDCA", "NPCA") or not node.high
                or packet is None or packet.urgent):
            return
        if (now - packet.created_us + EPS >= self.config.urgent_queue_us
                or packet.retries >= self.config.urgent_retry_count):
            packet.urgent = True
            node.backoff = min(node.backoff, self.config.urgent_cw_max)
            node.ifs_remaining = min(node.ifs_remaining, self._aifs(node))
            node.slot_progress = 0.0

    def _refresh_urgency(self, now: float) -> None:
        for node in self.nodes[:self.config.high_stations]:
            self._refresh_urgent_one(node, now)

    def _handle_arrivals(self, now: float) -> None:
        if self.next_arrival > now + EPS or self.next_arrival >= self.config.duration_us:
            return
        for node in self.nodes[:self.config.high_stations]:
            if not node.head:
                node.queue.append(Packet(now))
                self._reset_backoff(node)
            else:
                node.queue.append(Packet(now))
            self.report.high_generated += 1
        self.next_arrival += self.config.high_period_us

    def _external_update(self, now: float) -> None:
        while self._next_external() <= now + EPS:
            _, busy = self.external_events[self.external_index]
            self.external_busy = busy
            self.external_index += 1
            self._channel_resets(0)
            self._switch_update(now)

    def _finish_switches(self, now: float) -> None:
        for node in self.nodes[:self.config.high_stations]:
            if node.switching_until is not None and node.switching_until <= now + EPS:
                node.channel = node.switch_target  # type: ignore[assignment]
                node.switch_target = None
                node.switching_until = None
                self._reset_ifs(node)

    def _is_idle(self, channel: int) -> bool:
        if self.busy[channel] is not None:
            return False
        if channel == 0 and self.external_busy:
            return False
        return True

    def _eligible(self, node: Node) -> bool:
        return bool(node.head and not node.transmitting
                    and node.switching_until is None
                    and self._is_idle(node.channel))

    def _time_until_ready(self, node: Node) -> float:
        return max(0.0, node.ifs_remaining) + max(0.0,
            node.backoff * self.config.slot_us - node.slot_progress)

    def _start_ready_transmissions(self, now: float) -> None:
        for channel in (0, 1):
            if channel == 1 and self.config.mode != "NPCA":
                continue
            if not self._is_idle(channel):
                continue
            ready = [n for n in self.nodes if n.channel == channel
                     and self._eligible(n) and self._time_until_ready(n) <= EPS]
            # Admission is per frame: a deferred long frame must not block
            # shorter contenders in the remaining primary idle interval.
            if channel == 0:
                ready = [n for n in ready if now + self.config.tx_us([
                    self.config.high_frame_bytes if n.high
                    else self.config.low_frame_bytes]) <= self._next_external() + EPS]
            if not ready:
                continue
            sizes = [self.config.high_frame_bytes if node.high
                     else self.config.low_frame_bytes for node in ready]
            duration = self.config.tx_us(sizes)
            if now + duration > self.config.duration_us + EPS:
                continue
            self.report.attempts += len(ready)
            for node in ready:
                node.transmitting = True
            self.busy[channel] = Transmission(now + duration, ready, channel)
            self._channel_resets(channel)

    def _next_event(self, now: float) -> float:
        future = [self.config.duration_us, self._next_external(),
                  self.next_arrival]
        future.extend(tx.end_us for tx in self.busy.values() if tx is not None)
        future.extend(n.switching_until for n in self.nodes
                      if n.switching_until is not None)
        if self.config.mode in ("P-EDCA", "NPCA"):
            future.extend(n.head.created_us + self.config.urgent_queue_us
                          for n in self.nodes[:self.config.high_stations]
                          if n.head is not None and not n.head.urgent)
        for node in self.nodes:
            if not self._eligible(node):
                continue
            delta = self._time_until_ready(node)
            # Ready but non-fitting frames wait for a future event. Only
            # positive countdowns may schedule another contention wakeup.
            if delta > EPS:
                future.append(now + delta)
        return min(v for v in future if v > now + EPS)

    def _advance(self, delta: float) -> None:
        for node in self.nodes:
            if not self._eligible(node):
                continue
            remain = delta
            if node.ifs_remaining > EPS:
                consumed = min(node.ifs_remaining, remain)
                node.ifs_remaining -= consumed
                remain -= consumed
            if node.ifs_remaining <= EPS:
                node.ifs_remaining = 0.0
                if node.backoff > 0:
                    node.slot_progress += remain
                    ticks = min(node.backoff,
                                int(floor((node.slot_progress + EPS) / self.config.slot_us)))
                    node.backoff -= ticks
                    node.slot_progress -= ticks * self.config.slot_us
                    if node.backoff == 0:
                        node.slot_progress = 0.0

    def _run_loop(self):
        c = self.config
        while self.env.now + EPS < c.duration_us:
            now = self.env.now
            self._end_transmissions(now)
            self._external_update(now)
            self._finish_switches(now)
            self._handle_arrivals(now)
            self._refresh_urgency(now)
            self._start_ready_transmissions(now)
            future = self._next_event(now)
            dt = future - now
            if dt <= EPS:
                raise RuntimeError("event scheduler stalled")
            if self.external_busy:
                self.report.external_busy_us += dt
            self._advance(dt)
            yield self.env.timeout(dt)

    def run(self) -> MACResult:
        if self._has_run:
            raise RuntimeError("MACSimulator.run() can only be called once")
        self._has_run = True
        self.env.process(self._run_loop())
        self.env.run(until=self.config.duration_us)
        # The process is resumed after every jump, except exactly at the final
        # boundary; include completed transmissions at that boundary.
        self._end_transmissions(self.env.now)
        self.report.unfinished_high = sum(len(node.queue) for node in self.nodes if node.high)
        assert self.report.high_generated == (self.report.high_success +
            self.report.high_dropped + self.report.unfinished_high)
        assert self.report.attempts == (self.report.high_success +
            self.report.low_success + self.report.collisions)
        return self.report
