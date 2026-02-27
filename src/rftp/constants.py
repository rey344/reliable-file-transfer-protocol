from __future__ import annotations

SHA1_LEN = 20
HEADER_FORMAT = "!BBHII"  # version, kind, flags, seq, ack
VERSION = 1

DATA = 0
ACK = 1

FLAG_FIN = 0x1

DEFAULT_SEGMENT_SIZE = 1400
DEFAULT_TIMEOUT_MS = 250
DEFAULT_GBN_WINDOW = 8
