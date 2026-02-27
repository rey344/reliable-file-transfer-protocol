from __future__ import annotations

import pytest

from rftp.packet import Frame


def test_roundtrip_data():
    f = Frame.data(seq=1, payload=b"hello", fin=True)
    raw = f.to_bytes()
    p = Frame.from_bytes(raw)
    assert p.seq == 1
    assert p.payload == b"hello"
    assert p.fin is True


def test_roundtrip_ack():
    a = Frame.make_ack(7)
    raw = a.to_bytes()
    p = Frame.from_bytes(raw)
    assert p.ack == 7
    assert p.payload == b""


def test_bad_checksum():
    f = Frame.data(seq=2, payload=b"x")
    raw = bytearray(f.to_bytes())
    raw[-1] ^= 0xFF
    with pytest.raises(ValueError):
        Frame.from_bytes(bytes(raw))
