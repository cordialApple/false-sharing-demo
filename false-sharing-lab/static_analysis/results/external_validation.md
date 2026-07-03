# External validation: Huron benchmark suite

Date: 2026-07-02 · branch: `external-validation` · analyzers: tier1 `ir_analyzer.py` + tier2 `FalseSharingPass.so` (LLVM 18, WSL Ubuntu)

## Purpose

The in-house corpus scores (tier1/tier2 = 1.00 precision, 0 FP) are circular: the corpus
was written alongside the heuristics. This run measures both tiers against an
**independent dataset with published ground truth**: the test suite of the Huron
false-sharing repair tool (PLDI'19, github.com/efeslab/huron). Each program ships an
original (buggy) and a `_manual` (hand-fixed) version; the diff between them is the
documented false-sharing site.

## Method

- Source: `test_suites/` from a fresh `efeslab/huron` clone (7 C programs; C++/boost
  suites excluded — no boost dev headers in the WSL image).
- Compile: `clang-18 -O0 -g -pthread -S -emit-llvm` (same contract as the in-house
  corpus). `string_match` additionally needed `-include sys/time.h`
  `-Wno-implicit-function-declaration` (K&R-era implicit decl).
- Run: both analyzers via their standard CLI (`<file.ll> --json`), findings compared by
  hand against the original-vs-manual diff.
- Scoring: a **HIT** requires the analyzer to flag the exact data structure the Huron
  authors fixed. Extra findings are scored against the source code individually.

## Results

| Program | Ground-truth site (from `_manual` diff) | Tier 1 | Tier 2 |
|---|---|---|---|
| `false.c` | heap `int *array`, threads write adjacent elements | MISS | MISS |
| `histogram` | heap array of `thread_arg_t` (3096 B); fix = `char padding[40]` + `aligned_alloc(64)` | MISS | MISS |
| `linear_regression` | heap array of `lreg_args`; fix = `aligned_alloc(64)` | **HIT** (H1 on `lreg_args` fields 3–7, exactly the `SX..SXY` accumulators) | **HIT** (same) |
| `locked/toy.c` | heap `int *dynMemory`, tid-strided writes; fix = ×64 index spacing | MISS | MISS (+1 extra, see below) |
| `lockless/toy.c` | same as locked | MISS | MISS |
| `lu_ncb` (SPLASH-2) | heap `double *a` matrix; fix = `aligned_alloc(64)` | MISS (+4 extras) | MISS (+4 extras) |
| `string_match` | two per-thread `malloc(MAX_REC_LEN)` buffers landing adjacent; fix = `aligned_alloc(64)` | MISS | MISS |

**Recall vs ground truth: 1/7 (0.14) for both tiers.** In-house corpus recall was 1.00.
This is the expected gap between a corpus written for the heuristics and independent code.

### Extra findings (not the documented site)

| Finding | Assessment |
|---|---|
| H2 HIGH on `%struct.POINT_T` (2 B), `linear_regression`, both tiers | **FP.** `points[i].x/.y` are only ever *loaded* in the thread function; read-only sharing causes no invalidation traffic. Root cause: H2 fires on any variable-index GEP into a small struct and never checks for stores. |
| H2 HIGH on `%union.pthread_mutex_t` array (40 B), `locked/toy.c`, tier2 only | **Plausible but unconfirmed.** Adjacent mutexes in one cache line is a classic contention pattern, but Huron's fix did not touch the lock array, so scored as FP vs ground truth. Tier1 missed it because it does not parse union layouts. |
| H1 MEDIUM ×1 on `%struct.LocalCopies`, `lu_ncb`, both tiers | **FP.** Each thread `malloc`s its *own* `LocalCopies` instance inside `SlaveStart`; the fields are private to one thread. Root cause: H1 has no instance-privacy notion — it assumes any thread-written struct is a single shared instance. |
| H1 MEDIUM ×2 on `%struct.GlobalMemory` + ×1 on barrier `%struct.anon`, `lu_ncb`, both tiers | **Plausible but unconfirmed.** `Global->id++` really is executed by every thread (under `idlock`), adjacent to other hot fields, and the barrier struct packs mutex/cv/counter into shared lines. Real contention candidates, but not what Huron fixed → FP vs ground truth. |

Strict precision vs ground truth: tier1 2/7 findings correct (0.29), tier2 2/8 (0.25).
Treating the four "plausible" extras generously as true positives: tier1 5/7, tier2 6/8.

## Failure modes (labeled)

1. **Scalar-array gap (dominant, 4/7 misses):** `false.c`, `locked`, `lockless`,
   `lu_ncb` all false-share through plain `int*`/`double*` heap arrays indexed by thread
   id — no struct anywhere. This is the already-roadmapped H6 gap; this dataset shows it
   is the single most common real-world pattern, not an edge case.
2. **Large-struct boundary gap (new, `histogram`):** `thread_arg_t` is 3096 B — far over
   64 B, so H1/H2's small-struct logic never engages. The sharing happens at the
   *boundaries* between adjacent array elements because 3096 % 64 ≠ 0 and `malloc` gives
   no 64 B alignment. New heuristic candidate ("H7"): array-of-structs indexed by tid
   where `sizeof % 64 != 0`, flag the boundary. Extra hazard: the hot writes go through
   hoisted local pointers (`red = thread_arg->red`), so field attribution must follow
   pointer copies.
3. **Allocator-adjacency (statically out of reach):** `string_match` (and `lu_ncb`'s
   `LocalCopies`) false-share only because separate `malloc`s happen to land in one
   line. No static analyzer can see this without an allocator model; this is
   PREDATOR/dynamic-tool territory. Honest label: out of scope for the static tiers.
4. **H2 missing write requirement:** read-only shared arrays (`POINT_T`) get HIGH
   findings. Fix candidate: require at least one store through the variable-index GEP
   chain before firing.
5. **H1 missing instance-privacy:** per-thread private allocations of a struct type
   (`LocalCopies`) are indistinguishable from a shared instance. Fix candidate: track
   whether the struct pointer escapes to other threads (pthread_create arg, global) vs
   stays local to the thread that allocated it.

## Takeaways

- The one hit is a genuine, canonical Phoenix bug (`lreg_args`) found by the exact
  heuristic (H1) designed for that pattern — the pipeline works end to end on foreign IR
  with zero harness errors (7/7 programs parsed and analyzed by both tiers).
- The 1.00 in-house scores do not generalize, as predicted. External recall is 0.14.
- Priority order the data suggests: H6 (scalar arrays) closes 4 of 6 misses; the new
  boundary heuristic closes the 5th; the 6th (`string_match`) is out of static scope.
- Both FP root causes (no-write-check H2, no-privacy H1) are fixable without new
  infrastructure.

## Reproduce

```sh
# in WSL, from repo root
sh false-sharing-lab/static_analysis/external/build_huron_ir.sh
# then, from false-sharing-lab/static_analysis/
python ir_analyzer.py external/huron_ir/<prog>.ll --json
python tier2_analyzer.py external/huron_ir/<prog>.ll --json
```
