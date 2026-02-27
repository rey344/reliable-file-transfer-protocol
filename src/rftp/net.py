from __future__ import annotations

import random
import socket
import time
from dataclasses import dataclass
from typing import Tuple


@dataclass(frozen=True, slots=True)
class Impairment:
    loss_rate: float = 0.0
    delay_ms: int = 0

    def should_drop(self) -> bool:
        return random.random() < self.loss_rate

    def sleep_if_needed(self) -> None:
        if self.delay_ms > 0:
            time.sleep(self.delay_ms / 1000.0)


class UdpEndpoint:
    def __init__(self, sock: socket.socket, impairment: Impairment | None = None):
        self.sock = sock
        self.impairment = impairment or Impairment()

    @classmethod
    def listening(
        cls,
        host: str,
        port: int,
        timeout_ms: int = 0,
        impairment: Impairment | None = None,
    ) -> "UdpEndpoint":
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        sock.bind((host, port))
        if timeout_ms > 0:
            sock.settimeout(timeout_ms / 1000.0)
        return cls(sock, impairment)

    @classmethod
    def sending(
        cls,
        timeout_ms: int = 0,
        impairment: Impairment | None = None,
    ) -> "UdpEndpoint":
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        if timeout_ms > 0:
            sock.settimeout(timeout_ms / 1000.0)
        return cls(sock, impairment)

    def sendto(self, data: bytes, addr: Tuple[str, int]) -> None:
        if self.impairment.should_drop():
            return
        self.impairment.sleep_if_needed()
        self.sock.sendto(data, addr)

    def recvfrom(self, bufsize: int = 65535) -> Tuple[bytes, Tuple[str, int]]:
        while True:
            data, addr = self.sock.recvfrom(bufsize)
            if self.impairment.should_drop():
                continue
            self.impairment.sleep_if_needed()
            return data, addr

    def close(self) -> None:
        self.sock.close()
