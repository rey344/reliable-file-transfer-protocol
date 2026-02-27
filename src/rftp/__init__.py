"""Reliable File Transfer Protocol (RFTP)

This package is intentionally structured to resemble how reliability-first systems are built:
- clear separation of packet framing vs. protocol state machines
- deterministic behavior under timeouts
- clean, testable units

The goal is clarity + maintainability, not "demo only" code.
"""

__all__ = []
