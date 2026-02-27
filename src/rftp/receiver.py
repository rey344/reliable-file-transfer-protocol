from __future__ import annotations

import time
from dataclasses import dataclass
from typing import BinaryIO

from .net import UdpEndpoint
from .packet import Frame


@dataclass(slots=True)
class Metrics:
    packets_sent: int = 0
    bytes_sent: int = 0
    timeouts: int = 0
    retransmits: int = 0
    start_ts: float = time.monotonic()
    end_ts: float | None = None

    @property
    def duration_s(self) -> float:
        if self.end_ts is None:
            return 0.0
        return max(0.0, self.end_ts - self.start_ts)

    @property
    def throughput_mbps(self) -> float:
        if self.duration_s <= 0:
            return 0.0
        return (self.bytes_sent * 8 / 1_000_000) / self.duration_s


@dataclass(slots=True)
class Receiver:
    udp: UdpEndpoint
    out: BinaryIO

    def run(self) -> Metrics:
        metrics = Metrics()
        expected = 0

        while True:
            raw, addr = self.udp.recvfrom()
            try:
                frame = Frame.from_bytes(raw)
            except ValueError:
                continue

            if frame.kind != frame.kind.DATA:
                continue

            if frame.seq == expected:
                self.out.write(frame.payload)
                expected += 1
                metrics.bytes_sent += len(frame.payload)

            self.udp.sendto(Frame.make_ack(expected).to_bytes(), addr)
            metrics.packets_sent += 1

            if frame.fin and frame.seq < expected:
                break

        self.out.flush()
        metrics.end_ts = time.monotonic()
        return metrics
