 6 Workers Result:
  - Duration: 18,225 ms (~18 sec)
  - Throughput: 548.7 items/sec

  Final Results
  ┌─────────┬───────────────┬───────────┬─────────┐
  │ Workers │ Duration (ms) │ Items/sec │ Speedup │
  ├─────────┼───────────────┼───────────┼─────────┤
  │ 1       │ 41,831        │ 239.1     │ 1.0x    │
  ├─────────┼───────────────┼───────────┼─────────┤
  │ 2       │ 22,285        │ 448.7     │ 1.9x    │
  ├─────────┼───────────────┼───────────┼─────────┤
  │ 3       │ 16,458        │ 607.6     │ 2.5x    │
  ├─────────┼───────────────┼───────────┼─────────┤
  │ 4       │ 18,368        │ 544.4     │ 2.3x    │
  ├─────────┼───────────────┼───────────┼─────────┤
  │ 5       │ 20,456        │ 488.8     │ 2.0x    │
  ├─────────┼───────────────┼───────────┼─────────┤
  │ 6       │ 18,225        │ 548.7     │ 2.3x    │
  └─────────┴───────────────┴───────────┴─────────┘
  Conclusion: 3 workers is the sweet spot for this setup. Beyond that, contention on PGMQ's SELECT ... FOR UPDATE SKIP LOCKED causes degradation. The workers compete for the same queue rows, causing lock contention.

20 threads per worker (concurrency: 20)

  So actual thread counts were:
  ┌─────────┬─────────┬───────────┐
  │ Workers │ Threads │ Items/sec │
  ├─────────┼─────────┼───────────┤
  │ 1       │ 20      │ 239.1     │
  ├─────────┼─────────┼───────────┤
  │ 2       │ 40      │ 448.7     │
  ├─────────┼─────────┼───────────┤
  │ 3       │ 60      │ 607.6     │
  ├─────────┼─────────┼───────────┤
  │ 4       │ 80      │ 544.4     │
  ├─────────┼─────────┼───────────┤
  │ 5       │ 100     │ 488.8     │
  ├─────────┼─────────┼───────────┤
  │ 6       │ 120     │ 548.7     │
  └─────────┴─────────┴───────────┘
  Peak throughput at 60 threads total. Beyond that, lock contention on the queue outweighs parallelism benefits.

Benchmark Results (40 threads/worker, batch_size 100)
  ┌─────────┬─────────┬──────────┬────────────┐
  │ Workers │ Threads │ Duration │ Throughput │
  ├─────────┼─────────┼──────────┼────────────┤
  │ 1       │ 40      │ 23s      │ 436 /s     │
  ├─────────┼─────────┼──────────┼────────────┤
  │ 2       │ 80      │ 14s      │ 733 /s     │
  ├─────────┼─────────┼──────────┼────────────┤
  │ 3       │ 120     │ 11s      │ 887 /s ⭐  │
  ├─────────┼─────────┼──────────┼────────────┤
  │ 4       │ 160     │ 12s      │ 840 /s     │
  ├─────────┼─────────┼──────────┼────────────┤
  │ 5       │ 200     │ 13s      │ 753 /s     │
  ├─────────┼─────────┼──────────┼────────────┤
  │ 6       │ 240     │ 12s      │ 858 /s     │
  └─────────┴─────────┴──────────┴────────────┘
  Comparison
  ┌───────────────────────────────────┬─────────────────┬─────────────────┐
  │              Config               │ Peak Throughput │ Workers at Peak │
  ├───────────────────────────────────┼─────────────────┼─────────────────┤
  │ 20 threads, batch 10 (before fix) │ 608 /s          │ 3 workers       │
  ├───────────────────────────────────┼─────────────────┼─────────────────┤
  │ 20 threads, batch 10 (after fix)  │ 833 /s          │ 6 workers       │
  ├───────────────────────────────────┼─────────────────┼─────────────────┤
  │ 40 threads, batch 100             │ 887 /s          │ 3 workers       │
  └───────────────────────────────────┴─────────────────┴─────────────────┘
  Key findings:
  - Peak throughput ~887/s at 3 workers (120 threads)
  - Performance plateaus after 3 workers - likely hitting other bottlenecks (CPU, DB connections, etc.)
  - Doubling threads + larger batch achieves similar peak with fewer workers


Results: 200ms Latency Tasks (40 threads/worker, batch 100)
  ┌─────────┬─────────┬──────────┬────────────┐
  │ Workers │ Threads │ Duration │ Throughput │
  ├─────────┼─────────┼──────────┼────────────┤
  │ 1       │ 40      │ 53s      │ 187 /s     │
  ├─────────┼─────────┼──────────┼────────────┤
  │ 2       │ 80      │ 30s      │ 338 /s     │
  ├─────────┼─────────┼──────────┼────────────┤
  │ 3       │ 120     │ 21s      │ 485 /s     │
  ├─────────┼─────────┼──────────┼────────────┤
  │ 4       │ 160     │ 18s      │ 550 /s     │
  ├─────────┼─────────┼──────────┼────────────┤
  │ 5       │ 200     │ 16s      │ 637 /s ⭐  │
  ├─────────┼─────────┼──────────┼────────────┤
  │ 6       │ 240     │ 17s      │ 598 /s     │
  └─────────┴─────────┴──────────┴────────────┘
  Analysis

  Theoretical max with 200ms latency: 1 thread = 5 items/sec → 200 threads = 1000 items/sec
  ┌─────────┬─────────┬────────┬─────────────┬────────────┐
  │ Workers │ Threads │ Actual │ Theoretical │ Efficiency │
  ├─────────┼─────────┼────────┼─────────────┼────────────┤
  │ 1       │ 40      │ 187 /s │ 200 /s      │ 94%        │
  ├─────────┼─────────┼────────┼─────────────┼────────────┤
  │ 5       │ 200     │ 637 /s │ 1000 /s     │ 64%        │
  └─────────┴─────────┴────────┴─────────────┴────────────┘
  Key findings:
  - Near-linear scaling from 1→5 workers with I/O-bound tasks
  - Peak at 5 workers (200 threads) - 637/s
  - 6 workers shows slight degradation (thread/connection overhead)
  - 64% efficiency at peak vs theoretical max
