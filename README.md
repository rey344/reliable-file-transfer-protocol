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

## Status / roadmap
- Repository scaffold created (README, Python .gitignore, MIT license).
- Next steps: add sender/receiver scripts, a simple CLI, logging/metrics output, and test harness for reproducible benchmark runs.
