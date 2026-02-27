from __future__ import annotations

import os
import tempfile
import threading
from dataclasses import dataclass
from typing import BinaryIO, Literal, Union, cast

from .constants import DEFAULT_SEGMENT_SIZE
from .net import Impairment, UdpEndpoint
from .receiver import Receiver
from .sender import GoBackNSender, StopAndWaitSender


@dataclass(frozen=True, slots=True)
class BenchmarkResult:
    bytes_transferred: int
    duration_s: float
    throughput_mbps: float
    retransmits: int
    timeouts: int


def run_benchmark(
    *,
    protocol: Literal["sw", "gbn"],
    size_bytes: int,
    loss_rate: float = 0.0,
    delay_ms: int = 0,
    segment_size: int = DEFAULT_SEGMENT_SIZE,
    window_size: int = 8,
    timeout_ms: int = 250,
) -> BenchmarkResult:
    payload = b"A" * size_bytes
    impair = Impairment(loss_rate=loss_rate, delay_ms=delay_ms)

    recv_ep = UdpEndpoint.listening("127.0.0.1", 0, timeout_ms=timeout_ms, impairment=impair)
    recv_host, recv_port = recv_ep.sock.getsockname()

    out_file = tempfile.NamedTemporaryFile(delete=False)
    recv = Receiver(recv_ep, cast(BinaryIO, out_file))

    recv_metrics_holder = {}

    def recv_runner():
        try:
            recv_metrics_holder["m"] = recv.run()
        finally:
            recv_ep.close()

    t = threading.Thread(target=recv_runner, daemon=True)
    t.start()

    send_ep = UdpEndpoint.sending(timeout_ms=timeout_ms, impairment=impair)
    try:
        send_f = tempfile.TemporaryFile()
        send_f.write(payload)
        send_f.seek(0)

        if protocol == "sw":
            sender: Union[StopAndWaitSender, GoBackNSender] = StopAndWaitSender(
                send_ep,
                (recv_host, recv_port),
                send_f,
                segment_size=segment_size,
                timeout_ms=timeout_ms,
            )
        else:
            sender = GoBackNSender(
                send_ep,
                (recv_host, recv_port),
                send_f,
                window_size=window_size,
                segment_size=segment_size,
                timeout_ms=timeout_ms,
            )

        send_metrics = sender.run()
    finally:
        send_ep.close()

    t.join(timeout=10.0)

    out_file.close()
    try:
        actual_size = os.path.getsize(out_file.name)
        assert actual_size == size_bytes
    finally:
        os.unlink(out_file.name)

    duration_s = max(0.001, send_metrics.duration_s)
    throughput_mbps = (size_bytes * 8 / 1_000_000) / duration_s

    return BenchmarkResult(
        bytes_transferred=size_bytes,
        duration_s=duration_s,
        throughput_mbps=throughput_mbps,
        retransmits=send_metrics.retransmits,
        timeouts=send_metrics.timeouts,
    )
