# P7 · A data path is only as safe as its weakest hop

**Question.** Migration plans rank single assets. Data, however, crosses several assets on its way:
load balancer, API gateway, backend, queue, database, backup. "Harvest now, decrypt later" needs only one
readable hop. After a per-asset migration wave, how much of the data is actually safe end to end?

## Method

Code: `qmigrate/engine/paths.py` (used by the platform and by this study).

1. **Data-flow graph.** From the dependency graph, keep only the links along which data moves:
   `routes_to`, `calls`, `publishes_to`, `tunnels_to`, `sends_logs`, and `backs_up` reversed (data flows from the
   database to its backup). Keys, certificates and tokens are not hops. They decide whether a hop is safe.
2. **Paths.** Every simple path from an entry (no incoming flow) to a sink (no outgoing flow).
3. **Hop safety.** A hop is safe when the platform calls the asset quantum-safe. That means its own algorithm is
   post-quantum, hybrid or strong symmetric, and no key, certificate or token it relies on is quantum-vulnerable.
   The study checks this cheap model against the platform's own flag on every asset: 0 mismatches.
4. **Path value.** `max sensitivity / 5 × (1 + min(max retention, 20) / 20)`: the most sensitive data on the path,
   weighted by how long it must stay secret.
5. **Measures.**
   * Paths safe end to end, and the share of path value they hold.
   * **False assurance:** assets that are quantum-safe on their own but sit on a path that is still
     harvestable at another hop.
   * **Bottlenecks:** the unsafe hops, or the keys behind them, that block the most path value.
6. **Path-first planning.** A greedy plan: repeatedly secure the unsafe path with the highest value per
   migration still needed, until the budget is used. It is compared with the platform's own queue (rule score,
   AI score and dependency impact, the order the waves use) and with a random order, at the same number of
   migrations.

## Reproduce

```bash
python -m qmigrate.research.p7_paths.study          # about 4 minutes (trains the models for 17 estates)
python -m qmigrate.research.p7_paths.study --quick  # the two demo companies only
```

Writes `results/summary.md` (the report), `results/summary.json` and `results/curves.csv` (every estate, budget
and strategy).

## Result (see `results/summary.md`)

On both demo companies, Wave 1 of the asset queue (20 migrations) roughly triples asset coverage, from about 8%
to about 28%, but leaves **0** of about 450 data paths safe end to end. False assurance more than triples. With the
same 20 migrations, path-first planning makes about 25 paths safe. The pattern holds in all 15 additional
generated estates.

## In the platform

**Data paths** page (`GET /api/paths`): the end-to-end numbers next to asset coverage, the comparison for Wave 1,
the hops that block the most paths, every path with its weakest hop, and a path-first Wave 1 to compare with the
plan. The PDF report has the same summary.

## Limits

* **Synthetic estates.** The simulator is the only source with data-flow links. Public websites expose only
  their certificate chain, and the AWS, Azure and Google Cloud connectors read keys and certificates, not flows.
  Reading flows (for example ALB listeners to target groups, API Gateway integrations, event-source mappings) is
  the next step for real data.
* A hop is judged by its own algorithm and by the keys, certificates and tokens it relies on directly, as in the
  rest of the platform.
* Path-first is a greedy heuristic, not an optimum. It is designed to maximise path value, so beating the queue
  on that measure is expected. The contribution is measuring the gap the per-asset view hides.
