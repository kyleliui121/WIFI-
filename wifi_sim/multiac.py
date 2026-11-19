"""Four-AC EDCA model (AC_VO / AC_VI / AC_BE / AC_BK).

Course extension 3 ("增加 AC_VI、AC_BK 两类业务"): the mandatory simulator
(:mod:`wifi_sim.priority`) knows only one high-priority queue (AC_VO-like) and
one low-priority queue (AC_BE-like).  This module generalises the same
event-driven MAC approximation to the four 802.11e access categories, each
with its own AIFSN, CWmin/CWmax, frame length and traffic pattern:

==========  ======  ===========  ==================  ==========================
AC          AIFSN   CWmin/CWmax  traffic             deadline
==========  ======  ===========  ==================  ==========================
AC_VO       2       3 / 7        100 B every 10 ms    10 ms
AC_VI       2       7 / 15       1000 B every 10 ms   100 ms
AC_BE       3       15 / 1023    saturated 1500 B     -
AC_BK       7       15 / 1023    saturated 500 B      -
==========  ======  ===========  ==================  ==========================

All stations carry the two saturated background ACs (BE and BK); the two
real-time ACs are attached to a subset of stations (``vo_stations`` and
``vi_stations``), mirroring the mandatory scenario where a few stations carry
the delay-sensitive flow.

Modelled behaviour
------------------
* One BSS, all stations mutually audible, one shared channel, AP hidden from
  the model (frames are assumed to be acknowledged whenever no collision
  happens).
* Per-AC contention: every AC has its own AIFS and integer backoff counter.
  All ACs of an idle station count down simultaneously while the medium is
  idle (the real 802.11e EDCA behaviour).
* Internal collision: when two ACs of the same station are ready in the same
  slot, the higher-priority AC transmits and the lower one doubles its
  contention window and draws a new backoff (IEEE 802.11e internal
  collision rule, simplified: no retry is charged to the frame).
* External neighbour-network busy periods (optional) stop all four ACs
  exactly as in the mandatory simulator.
* No RTS/CTS, no frame errors, no hidden terminals and no NPCA secondary
  channel: this module is used for the AC_VI/AC_BK extension and for the
  ns-3 cross-check, not for the NPCA study.

``mode="DCF"`` collapses the four queues into one FIFO per station with
DIFS (AIFSN=2) and CWmin/CWmax = 15/1023; the class tag is kept only for
statistics, which is exactly the "DCF does not differentiate traffic" baseline.

Times are microseconds throughout, matching ``wifi_sim.priority``.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from math import floor
import random
from statistics import fmean

from .dcf import percentile

EPS = 1e-7
AC_ORDER = ("VO", "VI", "BE", "BK")
MODES = ("DCF", "EDCA")


@dataclass(frozen=True)
class ACParams:
    """One access category: EDCA parameters plus its traffic contract."""

    ac: str
    aifsn: int
    cw_min: int
    cw_max: int
    frame_bytes: int
    traffic: str = "saturated"   # "saturated" or "periodic"
    period_us: float = 0.0
    deadline_us: float | None = None

    def __post_init__(self) -> None:
        if self.ac not in AC_ORDER:
            raise ValueError(f"unknown access category {self.ac}")
        if not 0 <= self.aifsn <= 15:
            raise ValueError("AIFSN must lie in [0, 15]")
        if not 0 <= self.cw_min <= self.cw_max:
            raise ValueError("invalid contention window")
        if self.frame_bytes < 1:
            raise ValueError("frame length must be positive")
        if self.traffic not in ("saturated", "periodic"):
            raise ValueError("traffic must be 'saturated' or 'periodic'")
        if self.traffic == "periodic" and self.period_us <= 0:
            raise ValueError("periodic traffic needs a positive period")
        if self.deadline_us is not None and self.deadline_us <= 0:
            raise ValueError("deadline must be positive")

    @property
    def is_periodic(self) -> bool:
        return self.traffic == "periodic"


# 802.11e default EDCA parameter set (the same numbers the mandatory
# simulator already used for its two classes: VO = 2/(3,7), BE = 3/(15,1023)).
DEFAULT_ACS: dict[str, ACParams] = {
    "VO": ACParams("VO", 2, 3, 7, 100, "periodic", 10_000.0, 10_000.0),
    "VI": ACParams("VI", 2, 7, 15, 1000, "periodic", 10_000.0, 100_000.0),
    "BE": ACParams("BE", 3, 15, 1023, 1500, "saturated"),
    "BK": ACParams("BK", 7, 15, 1023, 500, "saturated"),
}
DCF_PARAMS = ACParams("BE", 2, 15, 1023, 1500, "saturated")


@dataclass(frozen=True)
class MultiACConfig:
    stations: int = 10
    mode: str = "EDCA"
    duration_s: float = 10.0
    seed: int = 42
    vo_stations: int = 2
    vi_stations: int = 2
    slot_us: float = 9.0
    sifs_us: float = 16.0
    preamble_us: float = 20.0
    phy_rate_mbps: float = 54.0
    ack_bytes: int = 14
    retry_limit: int = 7
    primary_busy_fraction: float = 0.30
    mean_external_busy_us: float = 2000.0
    acs: dict[str, ACParams] = field(default_factory=lambda: dict(DEFAULT_ACS))
    assignments: dict[str, tuple[int, ...]] | None = None

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"invalid mode {self.mode}: expected {MODES}")
        if self.stations < 6:
            raise ValueError("four-AC scenarios need at least 6 stations")
        if self.vo_stations < 1 or self.vi_stations < 1:
            raise ValueError("need at least one VO and one VI station")
        if self.vo_stations + self.vi_stations + 2 > self.stations:
            raise ValueError("too many real-time stations for this N")
        if min(self.duration_s, self.slot_us, self.sifs_us,
               self.phy_rate_mbps, self.mean_external_busy_us) <= 0:
            raise ValueError("timing, duration and PHY rate must be positive")
        if self.ack_bytes < 0 or self.retry_limit < 0:
            raise ValueError("ACK size and retry limit must be nonnegative")
        if not 0.0 <= self.primary_busy_fraction < 1.0:
            raise ValueError("external busy fraction must lie in [0, 1)")
        if set(self.acs) != set(AC_ORDER):
            raise ValueError("acs must define exactly VO, VI, BE and BK")
        if self.assignments is not None:
            if set(self.assignments) != set(AC_ORDER):
                raise ValueError("assignments must define all four ACs")
            for ac, indexes in self.assignments.items():
                for index in indexes:
                    if not 0 <= index < self.stations:
                        raise ValueError(f"station {index} out of range for {ac}")

    @property
    def duration_us(self) -> float:
        return self.duration_s * 1_000_000

    def frame_us(self, size: int) -> float:
        return self.preamble_us + size * 8 / self.phy_rate_mbps

    def tx_us(self, sizes: list[int]) -> float:
        return (max(self.frame_us(size) for size in sizes)
                + self.sifs_us + self.frame_us(self.ack_bytes))

    def ac_stations(self, ac: str) -> list[int]:
        """Station indexes that carry this access category.

        By default the two real-time ACs live on the first stations and the
        two saturated background ACs are split evenly over the remaining
        stations, mirroring the mandatory scenario (2 real-time stations and
        N-2 saturated low-priority stations).  ``assignments`` overrides this
        and may put several ACs on one station (internal contention).
        """
        if self.assignments is not None:
            return list(self.assignments[ac])
        if ac == "VO":
            return list(range(self.vo_stations))
        if ac == "VI":
            return list(range(self.vo_stations,
                              self.vo_stations + self.vi_stations))
        rest = list(range(self.vo_stations + self.vi_stations, self.stations))
        half = (len(rest) + 1) // 2
        return rest[:half] if ac == "BE" else rest[half:]


@dataclass
class Packet:
    created_us: float
    ac: str
    frame_bytes: int
    retries: int = 0


@dataclass
class ACQueue:
    """Per-AC EDCA function: queue + its own backoff state."""

    ac: str
    packets: deque[Packet] = field(default_factory=deque)
    backoff: int = 0
    ifs_remaining: float = 0.0
    slot_progress: float = 0.0
    internal_collisions: int = 0

    @property
    def head(self) -> Packet | None:
        return self.packets[0] if self.packets else None


@dataclass
class Node:
    station_id: int
    queues: dict[str, ACQueue]
    transmitting: bool = False

    def pending(self) -> bool:
        return any(queue.packets for queue in self.queues.values())


@dataclass
class Transmission:
    end_us: float
    contenders: list[tuple[Node, str]]


@dataclass
class ACResult:
    generated: int = 0
    success: int = 0
    dropped: int = 0
    unfinished: int = 0
    bits: int = 0
    success_late: int = 0
    deadline_observed: int = 0
    deadline_observed_failure: int = 0
    attempts: int = 0
    collisions: int = 0
    internal_collisions: int = 0
    delays_us: list[float] = field(default_factory=list)

    def row(self, ac: str, config: MultiACConfig) -> dict:
        resolved = self.success + self.dropped
        has_deadline = config.acs[ac].deadline_us is not None
        return {
            "mode": config.mode,
            "stations": config.stations,
            "seed": config.seed,
            "duration_s": config.duration_s,
            "external_busy_fraction": config.primary_busy_fraction,
            "ac": ac,
            "generated": self.generated,
            "success": self.success,
            "dropped": self.dropped,
            "unfinished": self.unfinished,
            "success_late": self.success_late,
            "deadline_observed": self.deadline_observed,
            "deadline_observed_failure": self.deadline_observed_failure,
            "throughput_mbps": self.bits / config.duration_s / 1_000_000,
            "mean_ms": (fmean(self.delays_us) / 1000
                        if self.delays_us else None),
            "p99_ms": percentile(self.delays_us, 0.99),
            "p999_ms": percentile(self.delays_us, 0.999),
            "deadline_observed_failure_pct": (
                100 * self.deadline_observed_failure / self.deadline_observed
                if self.deadline_observed else None),
            "deadline_failure_pct": (100 * (self.success_late + self.dropped) / resolved
                                     if has_deadline and resolved else None),
            "success_late_pct": (100 * self.success_late / self.success
                                 if has_deadline and self.success else None),
            "drop_pct": 100 * self.dropped / resolved if resolved else None,
            "unfinished_pct": 100 * self.unfinished / self.generated if self.generated else None,
            "attempts": self.attempts,
            "internal_collisions": self.internal_collisions,
            "collision_pct": (100 * self.collisions / self.attempts
                              if self.attempts else None),
        }


class MultiACSimulator:
    """One SimPy process driving the four-AC EDCA/DCF event model."""

    def __init__(self, config: MultiACConfig):
        import simpy

        self.config = config
        self.env = simpy.Environment()
        self._has_run = False
        self.rng = [random.Random(config.seed + i * 9973)
                    for i in range(config.stations)]
        self.results = {ac: ACResult() for ac in AC_ORDER}
        self.busy: list[Transmission] = []
        self.external_events = self._external_events()
        self.external_index = 0
        self.external_busy = False
        self.external_busy_us = 0.0
        self.collisions = 0
        self.collision_events = 0
        self.attempts = 0
        self.next_arrival: dict[str, float] = {}
        self.nodes = self._make_nodes()
        self._seed_traffic()

    # ------------------------------------------------------------------ setup
    def _make_nodes(self) -> list[Node]:
        nodes: list[Node] = []
        for station in range(self.config.stations):
            if self.config.mode == "DCF":
                queues = {"DCF": ACQueue("DCF")}
            else:
                queues = {ac: ACQueue(ac) for ac in AC_ORDER
                          if station in self.config.ac_stations(ac)}
            nodes.append(Node(station, queues))
        return nodes

    def _queue_for(self, node: Node, ac: str) -> ACQueue:
        return node.queues["DCF"] if self.config.mode == "DCF" else node.queues[ac]

    def _seed_traffic(self) -> None:
        for ac in AC_ORDER:
            spec = self.config.acs[ac]
            if spec.is_periodic:
                self.next_arrival[ac] = 0.0
                continue
            for station in self.config.ac_stations(ac):
                node = self.nodes[station]
                queue = self._queue_for(node, ac)
                queue.packets.append(Packet(0.0, ac, spec.frame_bytes))
                self.results[ac].generated += 1
                self._reset_backoff(node, queue)

    def _external_events(self) -> list[tuple[float, bool]]:
        c = self.config
        if c.primary_busy_fraction <= 0:
            return []
        rng = random.Random(c.seed + 1_000_000)
        idle_mean = (c.mean_external_busy_us * (1 - c.primary_busy_fraction)
                     / c.primary_busy_fraction)
        events: list[tuple[float, bool]] = []
        t = rng.expovariate(1 / idle_mean)
        while t < c.duration_us:
            events.append((t, True))
            t += rng.expovariate(1 / c.mean_external_busy_us)
            events.append((min(t, c.duration_us), False))
            t += rng.expovariate(1 / idle_mean)
        return events

    # --------------------------------------------------------------- EDCA
    def _spec(self, ac: str) -> ACParams:
        return DCF_PARAMS if self.config.mode == "DCF" else self.config.acs[ac]

    def _aifs(self, ac: str) -> float:
        return self.config.sifs_us + self._spec(ac).aifsn * self.config.slot_us

    def _reset_backoff(self, node: Node, queue: ACQueue) -> None:
        packet = queue.head
        if packet is None:
            queue.backoff = 0
            queue.slot_progress = 0.0
            queue.ifs_remaining = self._aifs(queue.ac)
            return
        spec = self._spec(packet.ac)
        exponent = min(packet.retries + queue.internal_collisions, 20)
        cw = min((spec.cw_min + 1) * (2 ** exponent) - 1, spec.cw_max)
        queue.backoff = self.rng[node.station_id].randint(0, cw)
        queue.ifs_remaining = self._aifs(queue.ac)
        queue.slot_progress = 0.0

    def _time_until_ready(self, queue: ACQueue) -> float:
        return (max(0.0, queue.ifs_remaining)
                + max(0.0, queue.backoff * self.config.slot_us
                      - queue.slot_progress))

    def _channel_idle(self) -> bool:
        return not self.busy and not self.external_busy

    def _next_external(self) -> float:
        return (self.external_events[self.external_index][0]
                if self.external_index < len(self.external_events)
                else float("inf"))

    def _external_update(self, now: float) -> None:
        while self._next_external() <= now + EPS:
            _, busy = self.external_events[self.external_index]
            self.external_busy = busy
            self.external_index += 1
            self._channel_resets()

    def _channel_resets(self) -> None:
        """A busy medium restarts the AIFS of every backlogged AC."""
        for node in self.nodes:
            if node.transmitting:
                continue
            for queue in node.queues.values():
                if queue.packets:
                    queue.ifs_remaining = self._aifs(queue.ac)
                    queue.slot_progress = 0.0

    # ------------------------------------------------------------ arrivals
    def _handle_arrivals(self, now: float) -> None:
        for ac in AC_ORDER:
            if not self.config.acs[ac].is_periodic:
                continue
            while (self.next_arrival[ac] <= now + EPS
                   and self.next_arrival[ac] < self.config.duration_us):
                spec = self.config.acs[ac]
                for station in self.config.ac_stations(ac):
                    node = self.nodes[station]
                    queue = self._queue_for(node, ac)
                    was_empty = not queue.packets
                    queue.packets.append(Packet(now, ac, spec.frame_bytes))
                    self.results[ac].generated += 1
                    if was_empty and not node.transmitting:
                        self._reset_backoff(node, queue)
                self.next_arrival[ac] += spec.period_us

    # ------------------------------------------------------------ transmit
    def _start_ready_transmissions(self, now: float) -> None:
        if not self._channel_idle():
            return
        boundary = min(self.config.duration_us, self._next_external()) + EPS
        ready: list[tuple[Node, str]] = []
        for node in self.nodes:
            if node.transmitting or not node.pending():
                continue
            # Select eligible frames before resolving internal collisions.
            eligible = [
                (key, queue) for key, queue in node.queues.items()
                if (packet := queue.head) is not None
                and queue.ifs_remaining <= EPS and queue.backoff == 0
                and now + self.config.tx_us([packet.frame_bytes]) <= boundary
            ]
            if not eligible:
                continue
            primary = eligible[0][0]
            for _, queue in eligible[1:]:
                # 802.11e internal collision: lower AC doubles its window.
                queue.internal_collisions += 1
                self.results[queue.head.ac].internal_collisions += 1  # type: ignore[union-attr]
                self._reset_backoff(node, queue)
            ready.append((node, primary))
        if not ready:
            return
        sizes = [node.queues[ac].head.frame_bytes  # type: ignore[union-attr]
                 for node, ac in ready]
        duration = self.config.tx_us(sizes)
        self.attempts += len(ready)
        for node, ac in ready:
            node.transmitting = True
            packet = node.queues[ac].head
            assert packet is not None
            self.results[packet.ac].attempts += 1
        self.busy.append(Transmission(now + duration, ready))
        self._channel_resets()

    def _end_transmissions(self, now: float) -> None:
        finished = [tx for tx in self.busy if tx.end_us <= now + EPS]
        if not finished:
            return
        for tx in finished:
            self.busy.remove(tx)
            collided = len(tx.contenders) > 1
            if collided:
                self.collision_events += 1
            for node, ac in tx.contenders:
                node.transmitting = False
                queue = node.queues[ac]
                packet = queue.head
                assert packet is not None
                if collided:
                    self.collisions += 1
                    self.results[packet.ac].collisions += 1
                    self._failed(node, queue, now)
                else:
                    self._delivered(node, queue, now)
        self._channel_resets()

    def _delivered(self, node: Node, queue: ACQueue, now: float) -> None:
        packet = queue.packets.popleft()
        result = self.results[packet.ac]
        delay = now - packet.created_us
        result.success += 1
        result.bits += packet.frame_bytes * 8
        result.delays_us.append(delay)
        self._record_deadline(packet, completed_us=now)
        queue.internal_collisions = 0
        if self.config.acs[packet.ac].is_periodic:
            if queue.packets:
                self._reset_backoff(node, queue)
            return
        # Saturated source: the next frame is already waiting.
        queue.packets.append(
            Packet(now, packet.ac, self.config.acs[packet.ac].frame_bytes))
        result.generated += 1
        self._reset_backoff(node, queue)

    def _failed(self, node: Node, queue: ACQueue, now: float) -> None:
        packet = queue.head
        assert packet is not None
        packet.retries += 1
        result = self.results[packet.ac]
        if packet.retries > self.config.retry_limit:
            queue.packets.popleft()
            result.dropped += 1
            self._record_deadline(packet)
            queue.internal_collisions = 0
            if not self.config.acs[packet.ac].is_periodic:
                queue.packets.append(
                    Packet(now, packet.ac,
                           self.config.acs[packet.ac].frame_bytes))
                result.generated += 1
        if queue.packets:
            self._reset_backoff(node, queue)

    def _record_deadline(self, packet: Packet, completed_us: float | None = None) -> None:
        relative_deadline = self.config.acs[packet.ac].deadline_us
        if relative_deadline is None:
            return
        result = self.results[packet.ac]
        deadline = packet.created_us + relative_deadline
        on_time = completed_us is not None and completed_us <= deadline
        if completed_us is not None and not on_time:
            result.success_late += 1
        if deadline <= self.config.duration_us:
            result.deadline_observed += 1
            result.deadline_observed_failure += not on_time

    # --------------------------------------------------------------- clock
    def _next_event(self, now: float) -> float:
        future = [self.config.duration_us, self._next_external()]
        future.extend(tx.end_us for tx in self.busy)
        future.extend(t for t in self.next_arrival.values())
        if self._channel_idle():
            for node in self.nodes:
                if node.transmitting:
                    continue
                for queue in node.queues.values():
                    if queue.packets:
                        future.append(now + self._time_until_ready(queue))
        return min(value for value in future if value > now + EPS)

    def _advance(self, delta: float) -> None:
        if not self._channel_idle():
            return
        for node in self.nodes:
            if node.transmitting or not node.pending():
                continue
            for queue in node.queues.values():
                if not queue.packets:
                    continue
                remain = delta
                if queue.ifs_remaining > EPS:
                    consumed = min(queue.ifs_remaining, remain)
                    queue.ifs_remaining -= consumed
                    remain -= consumed
                if queue.ifs_remaining <= EPS:
                    queue.ifs_remaining = 0.0
                    if queue.backoff > 0 and remain > 0:
                        queue.slot_progress += remain
                        ticks = min(queue.backoff, int(floor(
                            (queue.slot_progress + EPS) / self.config.slot_us)))
                        queue.backoff -= ticks
                        queue.slot_progress -= ticks * self.config.slot_us
                        if queue.backoff == 0:
                            queue.slot_progress = 0.0

    def _run_loop(self):
        import simpy

        while self.env.now + EPS < self.config.duration_us:
            now = self.env.now
            self._end_transmissions(now)
            self._external_update(now)
            self._handle_arrivals(now)
            self._start_ready_transmissions(now)
            future = self._next_event(now)
            dt = future - now
            if dt <= EPS:
                raise RuntimeError("event scheduler stalled")
            if self.external_busy:
                self.external_busy_us += dt
            self._advance(dt)
            yield self.env.timeout(dt)

    def run(self) -> dict[str, ACResult]:
        if getattr(self, "_has_run", False):
            raise RuntimeError("MultiACSimulator.run() can only be called once")
        self._has_run = True
        self.env.process(self._run_loop())
        self.env.run(until=self.config.duration_us)
        self._end_transmissions(self.env.now)
        for node in self.nodes:
            for queue in node.queues.values():
                for packet in queue.packets:
                    self.results[packet.ac].unfinished += 1
                    self._record_deadline(packet)
        self._validate()
        return self.results

    def _validate(self) -> None:
        total = 0
        for ac, result in self.results.items():
            assert result.generated == result.success + result.dropped + result.unfinished, ac
            assert 0 <= result.deadline_observed_failure <= result.deadline_observed <= result.generated
            total += result.success
        assert self.attempts == total + self.collisions

    def rows(self) -> list[dict]:
        return [self.results[ac].row(ac, self.config) for ac in AC_ORDER]
