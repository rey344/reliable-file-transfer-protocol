from __future__ import annotations

import enum
import hashlib
import struct
from dataclasses import dataclass

from .constants import ACK, DATA, FLAG_FIN, HEADER_FORMAT, SHA1_LEN, VERSION


class PacketKind(enum.IntEnum):
    DATA = DATA
    ACK = ACK


@dataclass(frozen=True, slots=True)
class Frame:
    version: int
    kind: PacketKind
    flags: int
    seq: int
    ack: int
    payload: bytes = b""

    @property
    def fin(self) -> bool:
        return bool(self.flags & FLAG_FIN)

    def to_bytes(self) -> bytes:
        header = struct.pack(
            HEADER_FORMAT,
            self.version,
            int(self.kind),
            self.flags,
            self.seq,
            self.ack,
        )
        checksum = hashlib.sha1(header + self.payload).digest()
        return header + checksum + self.payload

    @staticmethod
    def from_bytes(raw: bytes) -> "Frame":
        header_len = struct.calcsize(HEADER_FORMAT)
        if len(raw) < header_len + SHA1_LEN:
            raise ValueError("datagram too small to be a valid frame")

        header = raw[:header_len]
        checksum = raw[header_len : header_len + SHA1_LEN]
        payload = raw[header_len + SHA1_LEN :]

        if hashlib.sha1(header + payload).digest() != checksum:
            raise ValueError("checksum mismatch")

        version, kind, flags, seq, ack = struct.unpack(HEADER_FORMAT, header)
        if version != VERSION:
            raise ValueError(f"version mismatch: expected {VERSION}, got {version}")

        return Frame(
            version=version,
            kind=PacketKind(kind),
            flags=flags,
            seq=seq,
            ack=ack,
            payload=payload,
        )

    @staticmethod
    def make_ack(ack_num: int) -> "Frame":
        return Frame(version=VERSION, kind=PacketKind.ACK, flags=0, seq=0, ack=ack_num)

    @staticmethod
    def data(seq: int, payload: bytes, ack: int = 0, fin: bool = False) -> "Frame":
        flags = FLAG_FIN if fin else 0
        return Frame(
            version=VERSION,
            kind=PacketKind.DATA,
            flags=flags,
            seq=seq,
            ack=ack,
            payload=payload,
        )
