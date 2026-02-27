# Reliable File Transfer Protocol (UDP)

A UDP-based reliable file transfer system implementing Stop-and-Wait (SW) and Go-Back-N (GBN) with custom packet framing, timers, retransmissions, and SHA-1 checksums for integrity verification.

## Why this is relevant to a Data Center Technician role
- **Reliability under failure:** simulates packet loss/latency and includes retransmission logic and timeouts.
- **Integrity & safety:** SHA-1 checksums prevent accepting corrupt payloads—mirrors checksum-based validation you’d rely on when moving/replicating data.
- **Structured procedures:** clear protocol state, window management, and configurable timers (documented assumptions and default safe values).
- **Metrics & incident review:** intended logging hooks for timeouts, retransmits, and throughput benchmarking so you can explain what happened and why.

## What I’m benchmarking
- Throughput comparisons of SW vs. GBN under varying network conditions (loss rate, RTT, window size).
- Observed retransmission rates and the tradeoffs between reliability and efficiency.

## Status

### Implemented
- **Packet framing:** `Frame` class with serialization, SHA-1 checksums, version/kind/flags/seq/ack fields.
- **Network layer:** `UdpEndpoint` for sending/receiving with built-in impairment simulation (loss, delay).
- **Sender protocols:** `StopAndWaitSender` and `GoBackNSender` with retransmission logic and metrics.
- **Receiver:** `Receiver` that acknowledges in-order packets and writes to output.
- **Benchmarks:** `run_benchmark()` to measure throughput, retransmits, timeouts under various conditions.
- **CLI:** sender/receiver/benchmark commands with JSON output and configurable parameters.
- **Tests:** pytest suite validating packet roundtrip and checksum integrity.
- **CI:** GitHub Actions workflow (ruff, pytest, mypy).

## Usage

### Receiver (listening on port 9999, write to output.bin):
```bash
python -m rftp.cli recv --listen-port 9999 --out output.bin
```

### Sender (Stop-and-Wait, send file.txt to 127.0.0.1:9999):
```bash
python -m rftp.cli send --protocol sw --dest-host 127.0.0.1 --dest-port 9999 --file file.txt
```

### Sender (Go-Back-N, window=16, with 5% loss):
```bash
python -m rftp.cli send --protocol gbn --window-size 16 --dest-host 127.0.0.1 --dest-port 9999 --file file.txt --loss-rate 0.05
```

### Benchmark (5 MB, 10% loss, 50ms latency):
```bash
python -m rftp.cli bench --protocol gbn --size-bytes 5000000 --loss-rate 0.1 --delay-ms 50 --json
```

### Notes
- The legacy monolithic implementation is in `legacy/rftp.py` for reference.
- All metrics are reported in JSON format with `--json` flag.
