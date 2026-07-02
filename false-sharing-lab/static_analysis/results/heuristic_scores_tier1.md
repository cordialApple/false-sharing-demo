# Heuristic Score Report — Analyzer: tier1

## Score Table

| Heuristic | TP | FP | FN | GAP | KNOWN-FP | Precision | Recall |
|-----------|----|----|----|----|----------|-----------|--------|
| H1 | 2 | 0 | 0 | 2 | 0 | 1.00 | 1.00 |
| H2 | 3 | 0 | 0 | 1 | 0 | 1.00 | 1.00 |
| H3 | 0 | 0 | 0 | 1 | 0 | N/A | N/A |
| H5 | 0 | 0 | 0 | 1 | 0 | N/A | N/A |
| H6 | 0 | 0 | 0 | 1 | 0 | N/A | N/A |
| **TOTAL** | **5** | **0** | **0** | **6** | **0** | **1.00** | **1.00** |

## Per-Case Detail

| Case | Expected | Got | Verdict |
|------|----------|-----|---------|
| adv_tn_alignas_atomics | (none) | (none) | PASS |
| adv_tn_malloc_per_thread | (none) | (none) | PASS |
| adv_tp_deceptive_padding | H2 (deceptive_t) | H2 %struct.deceptive_t | PASS |
| adv_tp_global_scalar_array | H6 | (none) | GAP |
| adv_tp_mutex_data_same_line | H1 (mutex_counter_t) | (none) | GAP |
| adv_tp_nested_inner_fields | H1 (outer) | (none) | GAP |
| adv_tp_ring_head_tail | H1 (spsc_ring_t) | H1 %struct.spsc_ring_t | PASS |
| adv_tp_stats_array | H2 (stat_t) | H2 %struct.stat_t | PASS |
| edge_fnptr_entry | H2 (tiny) | (none) | GAP |
| tn_h1_separate_lines | (none) | (none) | PASS |
| tn_h2_aligned_attr | (none) | (none) | PASS |
| tn_h2_padded_array | (none) | (none) | PASS |
| tn_readonly_sharing | (none) | (none) | PASS |
| tn_single_thread | (none) | (none) | PASS |
| tp_h1_hot_fields | H1 (hot_fields) | H1 %struct.hot_fields | PASS |
| tp_h2_tid_array | H2 (tid_counter) | H2 %struct.tid_counter_t | PASS |
| tp_h3_adjacent_atomics | H3 (atomic_pair) | (none) | GAP |
| tp_h5_adjacent_globals | H5 | (none) | GAP |

## Summary

- **Unexpected FP** (false alarms on TN cases): 0
- **Unexpected FN / MISS** (TP cases not caught): 0
- **Known Gaps** (known_limitation=true, not penalized): 6
- **Known FP** (known_fp=[...], not penalized): 0
