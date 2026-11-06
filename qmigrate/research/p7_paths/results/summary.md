# P7 · A data path is only as safe as its weakest hop

Run 2026-11-06. 2 demo estates and 15 more generated estates (399 assets each). The hop model agrees with the platform's per-asset 'quantum-safe' flag on every asset (mismatches: 0).

## The two demo companies

**bank (seed 42)**: 445 data paths, 420 carry data of sensitivity 4–5. Today 0 paths are quantum-safe end to end, while 28 assets look safe on their own but carry data that is harvestable at another hop.

After Wave 1 (20 migrations from the platform's queue) asset coverage goes from 8.0% to 27.6%, but only **0** paths are safe end to end and false assurance grows to 92 assets. Path-first planning with the same 20 migrations makes **23** paths safe (6.0% of path value).

| Migrations | Queue: safe paths | Queue: value % | Path-first: safe paths | Path-first: value % | Random: value % | Queue: false assurance | Path-first: false assurance |
|---|---|---|---|---|---|---|---|
| 10 | 0 | 0.0 | 13 | 3.3 | 0.0 | 77 | 48 |
| 20 | 0 | 0.0 | 23 | 6.0 | 0.0 | 92 | 62 |
| 40 | 2 | 0.5 | 57 | 14.3 | 0.0 | 119 | 58 |
| 60 | 4 | 1.0 | 97 | 23.3 | 0.0 | 132 | 47 |
| 100 | 6 | 1.5 | 161 | 38.8 | 0.2 | 173 | 86 |

Hops that block the most valuable paths: AWS-IAM-001 (ECDSA-P256, 191 paths), AWS-CA-001 (RSA-2048, 184 paths), AZURE-CA-002 (RSA-2048, 151 paths), AWS-KMS-004 (RSA-2048, 143 paths), AWS-CA-002 (RSA-4096, 133 paths).

**hospital (seed 7)**: 478 data paths, 462 carry data of sensitivity 4–5. Today 0 paths are quantum-safe end to end, while 26 assets look safe on their own but carry data that is harvestable at another hop.

After Wave 1 (20 migrations from the platform's queue) asset coverage goes from 7.3% to 30.4%, but only **0** paths are safe end to end and false assurance grows to 101 assets. Path-first planning with the same 20 migrations makes **26** paths safe (6.2% of path value).

| Migrations | Queue: safe paths | Queue: value % | Path-first: safe paths | Path-first: value % | Random: value % | Queue: false assurance | Path-first: false assurance |
|---|---|---|---|---|---|---|---|
| 10 | 0 | 0.0 | 12 | 2.8 | 0.0 | 94 | 50 |
| 20 | 0 | 0.0 | 26 | 6.2 | 0.0 | 101 | 75 |
| 40 | 5 | 1.1 | 57 | 13.2 | 0.0 | 125 | 106 |
| 60 | 9 | 2.0 | 87 | 20.1 | 0.1 | 147 | 136 |
| 100 | 13 | 3.0 | 185 | 40.7 | 0.4 | 180 | 105 |

Hops that block the most valuable paths: AZURE-CA-001 (RSA-4096, 222 paths), AZURE-IAM-001 (ECDSA-P256, 154 paths), AZURE-KMS-001 (RSA-2048, 166 paths), AZURE-CA-002 (RSA-4096, 142 paths), AWS-CA-002 (RSA-4096, 135 paths).

## Across 15 more estates (mean)

| Migrations | Queue: value % | Path-first: value % | Random: value % | Queue: asset coverage % | Path-first: asset coverage % | Path-first better in |
|---|---|---|---|---|---|---|
| 10 | 0.0 | 3.0 | 0.0 | 22.6 | 14.3 | 15/15 |
| 20 | 0.2 | 6.1 | 0.0 | 27.4 | 18.7 | 15/15 |
| 40 | 0.8 | 13.7 | 0.1 | 33.1 | 26.5 | 15/15 |
| 60 | 1.8 | 21.5 | 0.1 | 39.5 | 33.3 | 15/15 |
| 100 | 2.7 | 38.1 | 0.6 | 49.6 | 45.9 | 15/15 |

## Reading the result

* Path-first is built to maximise path value, so it is expected to beat the queue on that measure. The finding is the size of the gap that the per-asset view hides: after Wave 1, asset coverage roughly triples while almost no data path is safe end to end.
* The per-asset queue raises asset coverage faster: it picks the riskiest single assets. Path-first raises coverage more slowly but closes whole paths, so recorded traffic stops being readable end to end sooner. Both views are needed, which is why the platform shows them side by side.
* Value weights each path by the most sensitive data on it and how long that data must stay secret.
* False assurance counts assets that are quantum-safe on their own but sit on a path that is still harvestable at another hop.

## Limits

* Synthetic estates: the simulator is the only source with data-flow links. The method runs on any workspace whose connector supplies them (routes_to, calls, publishes_to, tunnels_to, sends_logs, backs_up).
* A hop is judged by its own algorithm and the keys, certificates and tokens it relies on directly, as in the rest of the platform.
* Path-first is a greedy heuristic, not an optimum.
