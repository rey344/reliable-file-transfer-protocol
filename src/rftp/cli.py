from __future__ import annotations

import argparse
import json
from typing import Union

from .bench import run_benchmark
from .constants import DEFAULT_SEGMENT_SIZE, DEFAULT_TIMEOUT_MS
from .net import Impairment, UdpEndpoint
from .receiver import Receiver
from .sender import GoBackNSender, StopAndWaitSender


def cmd_recv(args: argparse.Namespace) -> int:
    impair = Impairment(args.loss_rate, args.delay_ms)
    udp = UdpEndpoint.listening(
        args.listen_host,
        args.listen_port,
        timeout_ms=args.timeout_ms,
        impairment=impair,
    )
    with open(args.out, "wb") as out:
        metrics = Receiver(udp, out).run()
    udp.close()

    payload = {
        "role": "receiver",
        "bytes": metrics.bytes_sent,
        "seconds": metrics.duration_s,
        "mbps": metrics.throughput_mbps,
    }
    print(json.dumps(payload, indent=2) if args.json else payload)
    return 0


def cmd_send(args: argparse.Namespace) -> int:
    impair = Impairment(args.loss_rate, args.delay_ms)
    udp = UdpEndpoint.sending(timeout_ms=args.timeout_ms, impairment=impair)

    with open(args.file, "rb") as f:
        if args.protocol == "sw":
            sender: Union[StopAndWaitSender, GoBackNSender] = StopAndWaitSender(
                udp,
                (args.dest_host, args.dest_port),
                f,
                segment_size=args.segment_size,
                timeout_ms=args.timeout_ms,
            )
        else:
            sender = GoBackNSender(
                udp,
                (args.dest_host, args.dest_port),
                f,
                window_size=args.window_size,
                segment_size=args.segment_size,
                timeout_ms=args.timeout_ms,
            )
        metrics = sender.run()

    udp.close()

    payload = {
        "role": "sender",
        "bytes": metrics.bytes_sent,
        "seconds": metrics.duration_s,
        "mbps": metrics.throughput_mbps,
        "timeouts": metrics.timeouts,
        "retransmits": metrics.retransmits,
    }
    print(json.dumps(payload, indent=2) if args.json else payload)
    return 0


def cmd_bench(args: argparse.Namespace) -> int:
    r = run_benchmark(
        protocol=args.protocol,
        size_bytes=args.size_bytes,
        loss_rate=args.loss_rate,
        delay_ms=args.delay_ms,
        segment_size=args.segment_size,
        window_size=args.window_size,
        timeout_ms=args.timeout_ms,
    )
    payload = {"role": "bench", **r.__dict__}
    print(json.dumps(payload, indent=2) if args.json else payload)
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="rftp", description="Reliable UDP file transfer (SW + GBN).")
    sub = p.add_subparsers(dest="cmd", required=True)

    def add_common(x: argparse.ArgumentParser) -> None:
        x.add_argument("--timeout-ms", type=int, default=DEFAULT_TIMEOUT_MS)
        x.add_argument("--loss-rate", type=float, default=0.0)
        x.add_argument("--delay-ms", type=int, default=0)
        x.add_argument("--segment-size", type=int, default=DEFAULT_SEGMENT_SIZE)
        x.add_argument("--json", action="store_true")

    recv = sub.add_parser("recv")
    add_common(recv)
    recv.add_argument("--listen-host", default="0.0.0.0")
    recv.add_argument("--listen-port", type=int, required=True)
    recv.add_argument("--out", required=True)
    recv.set_defaults(func=cmd_recv)

    send = sub.add_parser("send")
    add_common(send)
    send.add_argument("--protocol", choices=["sw", "gbn"], default="gbn")
    send.add_argument("--window-size", type=int, default=8)
    send.add_argument("--dest-host", required=True)
    send.add_argument("--dest-port", type=int, required=True)
    send.add_argument("--file", required=True)
    send.set_defaults(func=cmd_send)

    bench = sub.add_parser("bench")
    add_common(bench)
    bench.add_argument("--protocol", choices=["sw", "gbn"], default="gbn")
    bench.add_argument("--window-size", type=int, default=8)
    bench.add_argument("--size-bytes", type=int, default=5_000_000)
    bench.set_defaults(func=cmd_bench)

    args = p.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
