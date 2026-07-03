# Heuristic Score Report — Analyzer: tier1

## Score Table

| Heuristic | TP | FP | FN | GAP | KNOWN-FP | Precision | Recall |
|-----------|----|----|----|----|----------|-----------|--------|
| H1 | 3 | 0 | 0 | 1 | 0 | 1.00 | 1.00 |
| H2 | 3 | 0 | 0 | 1 | 0 | 1.00 | 1.00 |
| H3 | 0 | 0 | 0 | 1 | 0 | N/A | N/A |
| H5 | 0 | 0 | 0 | 1 | 0 | N/A | N/A |
| H6 | 2 | 0 | 0 | 0 | 0 | 1.00 | 1.00 |
| H7 | 1 | 0 | 0 | 0 | 0 | 1.00 | 1.00 |
| **TOTAL** | **9** | **0** | **0** | **4** | **0** | **1.00** | **1.00** |

## Per-Case Detail

| Case | Expected | Got | Verdict |
|------|----------|-----|---------|
| advanced/adv_tn_alignas_atomics | (none) | (none) | PASS |
| advanced/adv_tn_malloc_per_thread | (none) | (none) | PASS |
| advanced/adv_tn_private_two_fields | (none) | (none) | PASS |
| advanced/adv_tn_private_via_helper | (none) | (none) | PASS |
| advanced/adv_tn_readonly_tid_array | (none) | (none) | PASS |
| advanced/adv_tp_boundary_args | H7 (barg_t) | H7 %struct.barg_t | PASS |
| advanced/adv_tp_deceptive_padding | H2 (deceptive_t) | H2 %struct.deceptive_t | PASS |
| advanced/adv_tp_global_scalar_array | H6 | H6 @counters i64 array | PASS |
| advanced/adv_tp_heap_scalar_array | H6 | H6 (pointer) i32 array | PASS |
| advanced/adv_tp_mutex_data_same_line | H1 (mutex_counter_t) | H1 %struct.mutex_counter_t | PASS |
| advanced/adv_tp_nested_inner_fields | H1 (outer) | (none) | GAP |
| advanced/adv_tp_ring_head_tail | H1 (spsc_ring_t) | H1 %struct.spsc_ring_t | PASS |
| advanced/adv_tp_stats_array | H2 (stat_t) | H2 %struct.stat_t | PASS |
| basic/edge_fnptr_entry | H2 (tiny) | (none) | GAP |
| basic/tn_h1_separate_lines | (none) | (none) | PASS |
| basic/tn_h2_aligned_attr | (none) | (none) | PASS |
| basic/tn_h2_padded_array | (none) | (none) | PASS |
| basic/tn_readonly_sharing | (none) | (none) | PASS |
| basic/tn_single_thread | (none) | (none) | PASS |
| basic/tp_h1_hot_fields | H1 (hot_fields) | H1 %struct.hot_fields | PASS |
| basic/tp_h2_tid_array | H2 (tid_counter) | H2 %struct.tid_counter_t | PASS |
| basic/tp_h3_adjacent_atomics | H3 (atomic_pair) | (none) | GAP |
| basic/tp_h5_adjacent_globals | H5 | (none) | GAP |

## Summary

- **Unexpected FP** (false alarms on TN cases): 0
- **Unexpected FN / MISS** (TP cases not caught): 0
- **Known Gaps** (known_limitation=true, not penalized): 4
- **Known FP** (known_fp=[...], not penalized): 0
- **Analyzer errors** (case not analyzed at all): 0
