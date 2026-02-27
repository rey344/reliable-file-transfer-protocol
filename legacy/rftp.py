#!/usr/bin/env python3
"""Reliable File Transfer Protocol (UDP)

Implements Stop-and-Wait and Go-Back-N with SHA-1 packet checksums.
This is intentionally "structured ops" style: explicit states + logging.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import os
import random
import socket
import struct
import threading
import time
from dataclasses import dataclass
from typing import Optional, Tuple

VER = 1
FLAG_ACK = 0x01
FLAG_FIN = 0x02

HEADER_STRUCT = struct.Struct("!BBIIH20s")  # ver, flags, seq, ack, payload_len, checksum
MAX_PAYLOAD = 1400  # conservative to avoid IP fragmentation


class ChecksumError(Exception):
    pass


@dataclass(slots=True)
class Packet:
    version: int
    flags: int
    seq: int
    ack: int
    payload: bytes

    @property
    def is_ack(self) -> bool:
        return bool(self.flags & FLAG_ACK)

    @property
    def is_fin(self) -> bool:
        return bool(self.flags & FLAG_FIN)


def compute_checksum(version: int, flags: int, seq: int, ack: int, payload: bytes) -> bytes:
    payload_len = len(payload)
    hdr_no_cksum = HEADER_STRUCT.pack(version, flags, seq, ack, payload_len, b"\x00" * 20)
    return hashlib.sha1(hdr_no_cksum + payload).digest()


def build_packet(version: int, flags: int, seq: int, ack: int, payload: bytes) -> bytes:
    payload_len = len(payload)
    if payload_len > MAX_PAYLOAD:
        raise ValueError(f"payload too large: {payload_len}")
    checksum = compute_checksum(version, flags, seq, ack, payload)
    return HEADER_STRUCT.pack(version, flags, seq, ack, payload_len, checksum) + payload


def parse_packet(data: bytes) -> Packet:
    if len(data) < HEADER_STRUCT.size:
        raise ValueError("packet too short")
    version, flags, seq, ack, payload_len, checksum = HEADER_STRUCT.unpack_from(data)
    payload_start = HEADER_STRUCT.size
    payload_end = payload_start + payload_len
    payload = data[payload_start:payload_end]
    if len(payload) != payload_len:
        raise ValueError("truncated payload")
    expected = compute_checksum(version, flags, seq, ack, payload)
    if expected != checksum:
        raise ChecksumError("checksum mismatch")
    return Packet(version, flags, seq, ack, payload)


def sha1_file(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


class ImpairedSocket:
    """Simple simulation of network loss/delay for benchmarking."""

    def __init__(self, sock: socket.socket, loss_rate: float = 0.0, delay_ms: float = 0.0, name: str = ""):
        self._sock = sock
        self.loss_rate = loss_rate
        self.delay_ms = delay_ms
        self.name = name

    def sendto(self, data: bytes, addr: Tuple[str, int]) -> int:
        if self.loss_rate > 0 and random.random() < self.loss_rate:
            logging.debug("[%s] DROPPED outbound %d bytes", self.name, len(data))
            return len(data)
        if self.delay_ms > 0:
            time.sleep(self.delay_ms / 1000.0)
        return self._sock.sendto(data, addr)

    def __getattr__(self, item):
        return getattr(self._sock, item)


class ReliableReceiver:
    def __init__(self, sock: socket.socket, out_path: str):
        self.sock = sock
        self.out_path = out_path
        self.expected_seq = 0
        self.meta: Optional[dict] = None

    def _send_ack(self, addr: Tuple[str, int]) -> None:
        ack_pkt = build_packet(VER, FLAG_ACK, seq=0, ack=self.expected_seq, payload=b"")
        self.sock.sendto(ack_pkt, addr)

    def run(self) -> None:
        logging.info("receiver listening; writing to %s", self.out_path)
        with open(self.out_path, "wb") as out:
            while True:
                try:
                    data, addr = self.sock.recvfrom(65535)
                except socket.timeout:
                    continue
                try:
                    pkt = parse_packet(data)
                except ChecksumError:
                    logging.debug("checksum error; re-ack expected_seq=%d", self.expected_seq)
                    if addr:
                        self._send_ack(addr)
                    continue

                # ignore pure ack packets (shouldn't happen inbound)
                if pkt.is_ack:
                    continue

                if pkt.seq == self.expected_seq:
                    self.expected_seq += 1
                    if pkt.is_fin:
                        self.meta = json.loads(pkt.payload.decode("utf-8"))
                        logging.info("FIN received; meta=%s", self.meta)
                        self._send_ack(addr)
                        break
                    else:
                        out.write(pkt.payload)
                        self._send_ack(addr)
                else:
                    # out-of-order or duplicate; just re-ack cumulative expected_seq
                    self._send_ack(addr)

        # integrity check
        expected_sha1 = (self.meta or {}).get("sha1")
        if expected_sha1:
            actual = sha1_file(self.out_path)
            if actual != expected_sha1:
                raise SystemExit(f"SHA-1 mismatch! expected {expected_sha1} got {actual}")
        logging.info("receiver done; expected_seq=%d", self.expected_seq)


class StopAndWaitSender:
    def __init__(self, sock: socket.socket, addr: Tuple[str, int], timeout: float, max_retries: int):
        self.sock = sock
        self.addr = addr
        self.timeout = timeout
        self.max_retries = max_retries

    def _wait_for_ack(self, expected_ack: int) -> bool:
        while True:
            self.sock.settimeout(self.timeout)
            try:
                data, _ = self.sock.recvfrom(4096)
            except socket.timeout:
                return False
            pkt = parse_packet(data)
            if pkt.is_ack and pkt.ack == expected_ack:
                return True

    def send_file(self, path: str) -> None:
        seq = 0
        total_bytes = os.path.getsize(path)
        logging.info("SW send start; size=%d bytes", total_bytes)
        start = time.perf_counter()

        with open(path, "rb") as f:
            while True:
                chunk = f.read(MAX_PAYLOAD)
                is_fin = chunk == b""
                payload = chunk
                flags = 0
                if is_fin:
                    meta = {"sha1": sha1_file(path), "name": os.path.basename(path)}
                    payload = json.dumps(meta).encode("utf-8")
                    flags |= FLAG_FIN

                pkt_bytes = build_packet(VER, flags, seq=seq, ack=0, payload=payload)

                retries = 0
                while retries <= self.max_retries:
                    self.sock.sendto(pkt_bytes, self.addr)
                    expected_ack = seq + 1
                    got_ack = self._wait_for_ack(expected_ack)
                    if got_ack:
                        break
                    retries += 1
                    logging.debug("timeout; seq=%d retry=%d", seq, retries)
                if retries > self.max_retries:
                    raise SystemExit(f"too many retries at seq={seq}")

                seq += 1
                if is_fin:
                    break

        elapsed = time.perf_counter() - start
        if elapsed > 0:
            logging.info("done; throughput=%.2f MiB/s", total_bytes / elapsed / (1024 * 1024))


class GoBackNSender:
    def __init__(self, sock: socket.socket, addr: Tuple[str, int], timeout: float, max_retries: int, window: int):
        self.sock = sock
        self.addr = addr
        self.timeout = timeout
        self.max_retries = max_retries
        self.window = max(1, window)

    def send_file(self, path: str) -> None:
        data = open(path, "rb").read()
        segments = [data[i:i + MAX_PAYLOAD] for i in range(0, len(data), MAX_PAYLOAD)]
        meta = {"sha1": sha1_file(path), "name": os.path.basename(path)}
        fin_payload = json.dumps(meta).encode("utf-8")
        segments.append(fin_payload)  # last is FIN payload

        total_bytes = len(data)
        logging.info("GBN send start; segments=%d window=%d size=%d bytes", len(segments), self.window, total_bytes)
        start = time.perf_counter()

        base = 0
        next_seq = 0
        retries = 0
        timer_start: Optional[float] = None

        while base < len(segments):
            # send window
            while next_seq < base + self.window and next_seq < len(segments):
                is_fin = next_seq == len(segments) - 1
                flags = FLAG_FIN if is_fin else 0
                pkt_bytes = build_packet(VER, flags, seq=next_seq, ack=0, payload=segments[next_seq])
                self.sock.sendto(pkt_bytes, self.addr)
                if timer_start is None:
                    timer_start = time.monotonic()
                next_seq += 1

            # wait for ack
            if timer_start is None:
                timer_start = time.monotonic()
            remaining = max(0.0, self.timeout - (time.monotonic() - timer_start))
            self.sock.settimeout(remaining)
            got_ack = False
            try:
                data, _ = self.sock.recvfrom(4096)
                pkt = parse_packet(data)
                if pkt.is_ack:
                    got_ack = True
            except socket.timeout:
                pass

            if got_ack:
                if pkt.ack > base:
                    base = pkt.ack
                    retries = 0
                    if base == next_seq:
                        timer_start = None
                    else:
                        timer_start = time.monotonic()
            else:
                retries += 1
                if retries > self.max_retries:
                    raise SystemExit(f"too many timeouts; base={base}")
                logging.debug("timeout; retransmit window base=%d next_seq=%d retry=%d", base, next_seq, retries)
                timer_start = time.monotonic()
                for seq in range(base, next_seq):
                    is_fin = seq == len(segments) - 1
                    flags = FLAG_FIN if is_fin else 0
                    pkt_bytes = build_packet(VER, flags, seq=seq, ack=0, payload=segments[seq])
                    self.sock.sendto(pkt_bytes, self.addr)

        elapsed = time.perf_counter() - start
        if elapsed > 0:
            logging.info("done; throughput=%.2f MiB/s", total_bytes / elapsed / (1024 * 1024))


def run_sender(args: argparse.Namespace) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    if args.bind_port:
        sock.bind(("0.0.0.0", args.bind_port))
    if args.loss_rate or args.delay_ms:
        sock = ImpairedSocket(sock, loss_rate=args.loss_rate, delay_ms=args.delay_ms, name="sender")  # type: ignore[assignment]
    addr = (args.dest_host, args.dest_port)

    if args.protocol == "sw":
        sender = StopAndWaitSender(sock, addr, timeout=args.timeout, max_retries=args.max_retries)
    else:
        sender = GoBackNSender(sock, addr, timeout=args.timeout, max_retries=args.max_retries, window=args.window)

    sender.send_file(args.file)


def run_receiver(args: argparse.Namespace) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind((args.listen_host, args.listen_port))
    sock.settimeout(0.5)
    if args.loss_rate or args.delay_ms:
        sock = ImpairedSocket(sock, loss_rate=args.loss_rate, delay_ms=args.delay_ms, name="receiver")  # type: ignore[assignment]
    receiver = ReliableReceiver(sock, out_path=args.out)
    receiver.run()


def run_bench(args: argparse.Namespace) -> None:
    # localhost benchmark: receiver thread + sender
    port = args.port
    tmp_in = args.tmp_in
    tmp_out = args.tmp_out

    recv_thread = threading.Thread(
        target=run_receiver,
        args=(argparse.Namespace(
            listen_host="127.0.0.1",
            listen_port=port,
            out=tmp_out,
            loss_rate=args.loss_rate,
            delay_ms=args.delay_ms,
        ),),
        daemon=True,
    )
    recv_thread.start()
    time.sleep(0.1)
    run_sender(argparse.Namespace(
        protocol=args.protocol,
        dest_host="127.0.0.1",
        dest_port=port,
        file=tmp_in,
        timeout=args.timeout,
        max_retries=args.max_retries,
        window=args.window,
        bind_port=None,
        loss_rate=args.loss_rate,
        delay_ms=args.delay_ms,
    ))
    recv_thread.join()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reliable file transfer over UDP (SW/GBN).")
    parser.add_argument("--log-level", default="INFO", choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"])
    sub = parser.add_subparsers(dest="cmd", required=True)

    send = sub.add_parser("send", help="send a file to a receiver")
    send.add_argument("--protocol", default="gbn", choices=["sw", "gbn"])
    send.add_argument("--dest-host", required=True)
    send.add_argument("--dest-port", required=True, type=int)
    send.add_argument("--file", required=True)
    send.add_argument("--window", default=8, type=int, help="GBN window size (gbn only)")
    send.add_argument("--timeout", default=0.25, type=float)
    send.add_argument("--max-retries", default=20, type=int)
    send.add_argument("--bind-port", type=int, default=None)
    send.add_argument("--loss-rate", default=0.0, type=float, help="simulate outbound packet loss")
    send.add_argument("--delay-ms", default=0.0, type=float, help="simulate outbound send delay")
    send.set_defaults(func=run_sender)

    recv = sub.add_parser("recv", help="receive a file and write it to disk")
    recv.add_argument("--listen-host", default="0.0.0.0")
    recv.add_argument("--listen-port", required=True, type=int)
    recv.add_argument("--out", required=True)
    recv.add_argument("--loss-rate", default=0.0, type=float, help="simulate inbound packet loss")
    recv.add_argument("--delay-ms", default=0.0, type=float, help="simulate inbound delay before sendto")
    recv.set_defaults(func=run_receiver)

    bench = sub.add_parser("bench", help="local benchmark on loopback (used for structured testing)")
    bench.add_argument("--protocol", default="gbn", choices=["sw", "gbn"])
    bench.add_argument("--port", default=54321, type=int)
    bench.add_argument("--tmp-in", required=True)
    bench.add_argument("--tmp-out", required=True)
    bench.add_argument("--window", default=8, type=int)
    bench.add_argument("--timeout", default=0.25, type=float)
    bench.add_argument("--max-retries", default=20, type=int)
    bench.add_argument("--loss-rate", default=0.0, type=float)
    bench.add_argument("--delay-ms", default=0.0, type=float)
    bench.set_defaults(func=run_bench)

    return parser


def main(argv: Optional[list[str]] = None) -> None:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(level=getattr(logging, args.log_level), format="%(asctime)s [%(levelname)s] %(message)s")
    args.func(args)


if __name__ == "__main__":
    main()
