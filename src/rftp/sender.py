from __future__ import annotations

import time
from dataclasses import dataclass
from typing import BinaryIO, Tuple

from .constants import DEFAULT_GBN_WINDOW, DEFAULT_SEGMENT_SIZE, DEFAULT_TIMEOUT_MS
from .net import UdpEndpoint
from .packet import Frame
from .receiver import Metrics


@dataclass(slots=True)
class StopAndWaitSender:
    udp: UdpEndpoint
    dest: Tuple[str, int]
    f: BinaryIO
    segment_size: int = DEFAULT_SEGMENT_SIZE
    timeout_ms: int = DEFAULT_TIMEOUT_MS

    def run(self) -> Metrics:
        metrics = Metrics()
        seq = 0

        while True:
            chunk = self.f.read(self.segment_size)
            fin = chunk == b""
            payload = chunk or b""
            frame = Frame.data(seq=seq, payload=payload, fin=fin)

            while True:
                metrics.packets_sent += 1
                metrics.bytes_sent += len(payload)
                self.udp.sendto(frame.to_bytes(), self.dest)

                try:
                    raw, _ = self.udp.recvfrom()
                except TimeoutError:
                    metrics.timeouts += 1
                    metrics.retransmits += 1
                    continue

                try:
                    ack = Frame.from_bytes(raw)
                except ValueError:
                    continue

                if ack.kind != ack.kind.ACK:
                    continue

                if ack.ack == seq + 1:
                    seq += 1
                    break

                metrics.retransmits += 1

            if fin:
                break

        metrics.end_ts = time.monotonic()
        return metrics


@dataclass(slots=True)
class GoBackNSender:
    udp: UdpEndpoint
    dest: Tuple[str, int]
    f: BinaryIO
    window_size: int = DEFAULT_GBN_WINDOW
    segment_size: int = DEFAULT_SEGMENT_SIZE
    timeout_ms: int = DEFAULT_TIMEOUT_MS

    def run(self) -> Metrics:
        metrics = Metrics()
        base = 0
        next_seq = 0
        buffer: dict[int, Frame] = {}
        timer_start: float | None = None
        eof_scheduled = False

        def load_frame(seq: int) -> Frame:
            nonlocal eof_scheduled
            if seq in buffer:
                return buffer[seq]
            chunk = self.f.read(self.segment_size)
            fin = chunk == b""
            payload = chunk or b""
            fr = Frame.data(seq=seq, payload=payload, fin=fin)
            buffer[seq] = fr
            if fin:
                eof_scheduled = True
            return fr

        while True:
            while next_seq < base + self.window_size:
                fr = load_frame(next_seq)
                metrics.packets_sent += 1
                metrics.bytes_sent += len(fr.payload)
                self.udp.sendto(fr.to_bytes(), self.dest)
                if timer_start is None:
                    timer_start = time.monotonic()
                next_seq += 1
                if fr.fin:
                    break

            try:
                raw, _ = self.udp.recvfrom()
            except TimeoutError:
                if timer_start is not None:
                    elapsed_ms = (time.monotonic() - timer_start) * 1000
                    if elapsed_ms >= self.timeout_ms:
                        metrics.timeouts += 1
                        metrics.retransmits += (next_seq - base)
                        for s in range(base, next_seq):
                            self.udp.sendto(buffer[s].to_bytes(), self.dest)
                        timer_start = time.monotonic()
                continue

            try:
                ack = Frame.from_bytes(raw)
            except ValueError:
                continue

            if ack.kind != ack.kind.ACK:
                continue

            if ack.ack > base:
                base = ack.ack
                for k in list(buffer.keys()):
                    if k < base:
                        del buffer[k]
                timer_start = time.monotonic() if base != next_seq else None

            if eof_scheduled and base == next_seq:
                break

        metrics.end_ts = time.monotonic()
        return metrics
