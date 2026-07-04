# Ground truth: documented false sharing in PARSEC / SPLASH-2x / Phoenix

Scout research 2026-07-03. Sources: Sheriff (OOPSLA'11), PREDATOR (PPoPP'14), LASER (HPCA'16), Huron (PLDI'19), TMI, Feather, Cheetah (secondary only).

## PARSEC proper

| # | Program (suite ver) | Object / location | Mechanism | Reported by | Fix published | Statically visible? |
|---|---|---|---|---|---|---|
| 1 | **streamcluster** (PARSEC 2.1/3.0, kernel) | `work_mem` (double*), malloc'd in `pgain()`, `streamcluster.cpp:985`; padding macro `CACHE_LINE` at `streamcluster.cpp:52` | tid-strided heap array: `work_mem[pid*stride]`; author padded with `CACHE_LINE=32` but real line is 64B → adjacent tids share lines | Sheriff, PREDATOR (+7.5%), LASER (3x fewer HITMs), Feather/Cheetah confirm | Yes: set `CACHE_LINE` to 64. **Never fixed upstream — PARSEC 3.0 mirror still ships `#define CACHE_LINE 32` (verified 2026-07-03)** | **Yes** — compile-time stride macro; per-tid indexed writes. Ideal insufficient-padding target |
| 2 | **streamcluster** | `switch_membership` (global `bool*`, `streamcluster.cpp:70`), written `switch_membership[i]=1` in `pgain` (~line 1907) | shared global byte array; threads write disjoint contiguous ranges; 1-byte elems → up to 64 tids per line + block-boundary sharing | **PREDATOR — first report** (+4.77%) | Yes: widen `bool`→`long` (paper's fix) | **Yes** — range-partitioned global array, boundary sharing (H7 shape). `is_center` (line 71) same shape, not in papers |
| 3 | canneal | — | Sheriff detected FS but <10 interleavings/line → below threshold; PREDATOR couldn't run; LASER: no perf bug | Sheriff (negligible) | n/a | Ground truth = **no significant FS** (true-negative case) |
| 4 | fluidanimate | — | Sheriff: FS detected, <10 interleavings → insignificant | Sheriff (negligible) | n/a | true-negative-ish; heavy locking |
| 5 | dedup | pipeline `queue` + lock (queue.c) | **TRUE sharing** (lock contention), not FS | LASER (16% via lockfree queue) | manual, paper only | negative control: must NOT call FS |
| 6 | bodytrack | `TicketDispenser::getTicket()` counter | **TRUE sharing** (inherent) | LASER | none | negative control |
| 7 | ferret, blackscholes, swaptions, x264, vips, freqmine, facesim, raytrace | — | no documented FS in any of six papers | — | — | true negatives |

## SPLASH-2x

| # | Program | Object | Mechanism | Reported by | Fix | Static? |
|---|---|---|---|---|---|---|
| 8 | **lu_ncb** | `a` matrix | block-partitioned writes to unaligned/unpadded global matrix; blocks straddle lines | LASER (manual fix +36%), Huron, Feather | align `a` to line boundary | Partially — malloc alignment + block-stride visible; severity layout-dependent |
| 9 | volrend | lock guarding `Global->Queue` counter | **TRUE sharing** | LASER | batched atomics (no speedup) | negative control |
| 10 | radix, ocean, fft | in Huron Table 1 detection set | per-row values not extractable from PDF | Huron | — | detection-benchmark rows only |

## Phoenix

| # | Program | Object / location | Mechanism | Reported by | Fix | Static? |
|---|---|---|---|---|---|---|
| 11 | **linear_regression** | `lreg_args` array (tid-indexed), alloc `stddefines.h:53`, writes `linear_regression-pthread.c:133` | ~52B struct < 64B → two threads share line; severity offset-dependent (0-15x swing) | Sheriff, PREDATOR (12.07x latent), LASER (16%), Huron, Feather (16x), Cheetah | pad to 64B / align | **Yes** — canonical case (our existing H1 hit) |
| 12 | **histogram** | `thread_arg_t` heap object; `red/green/blue` arrays; `histogram-pthread.c:213` | threads modify different fields/ranges of one heap object; input-dependent | **PREDATOR first report (+46%)**, LASER (19%), Huron case study | pad `thread_arg_t` | Yes struct fields; array-range case input-dependent |
| 13 | reverse_index | `use_len` int array, `(use_len[curr_thread])++`, `reverseindex-pthread.c:511` | tid-indexed int array | Sheriff, PREDATOR (+0.09% negligible), LASER, Huron | thread-local accumulate | **Yes** but perf-insignificant |
| 14 | word_count | shared heap counters, `word_count-pthread.c:136` | threads update same heap object | Sheriff, PREDATOR (+0.14%), LASER | — | yes-ish, insignificant |
| 15 | string_match | adjacent per-thread mallocs | **allocator adjacency** — Sheriff-Protect +40%, Sheriff-Detect saw nothing | Sheriff | allocator isolation | **No** — out of static scope (documented boundary) |
| 16 | kmeans | falsely-shared heap object (details thin) | LASER Table 2; Sheriff: insignificant | LASER, Sheriff | — | weak ground truth |

Extras (non-PARSEC): MySQL-5.5.32 (6x), boost-1.49.0 spinlock pool (40%) — PREDATOR/Huron.

Feather/Cheetah primary PDFs paywalled; secondary sources say their PARSEC findings duplicate rows 1, 8, 11.

## Source acquisition

- parsec.cs.princeton.edu **dead since ~Sept 2023**.
- Best mirror: **github.com/cirosantilli/parsec-benchmark** — full 3.0-beta-20150206 tree; input archives re-uploaded as GitHub release tag `3.0`. Verified live 2026-07-03.
- Alternates: bamos/parsec-benchmark, Mic92/parsec-benchmark, connorimes/parsec-3.0, gtcasl/hpc-benchmarks.
- Phoenix: github mirrors of kozyraki/phoenix.
- streamcluster `CACHE_LINE 32` bug ships to this day — analyzer can find a real unfixed bug in pristine source.

## Standalone compile difficulty (verified file lists)

| Program | Files | `clang++ -O0 -g -pthread -S -emit-llvm` standalone? | Notes |
|---|---|---|---|
| streamcluster | `streamcluster.cpp` + `parsec_barrier.{cpp,hpp}` | **Yes, trivial** | `-DENABLE_THREADS`; barrier in-tree; TBB only if `-DTBB_VERSION` |
| fluidanimate | `pthreads.cpp` + `cellpool.cpp` + `parsec_barrier.cpp` | **Yes, easy** | ignore serial.cpp/tbb.cpp/fluidview.cpp (GL) |
| canneal | `main.cpp netlist.cpp netlist_elem.cpp rng.cpp annealer_thread.cpp` + in-tree `atomic/` + MersenneTwister.h | **Yes, easy** | in-tree x86 atomic asm; C++ only |
| dedup | ~15 .c files | Moderate | needs -lcrypto (SHA1) + -lz |
| ferret | multi-dir | Hard | needs gsl + libjpeg + own image/cass libs — keep in PARSEC harness |

## Validation design takeaway

Statically-visible positives: streamcluster×2, lu_ncb, linear_regression, histogram(struct), reverse_index, word_count.
Allocator-luck (out of static scope, documented boundary): string_match, lreg_args offset-dependence.
Strong negative controls: dedup/bodytrack/volrend (TRUE sharing, must not flag as FS), canneal/fluidanimate (detected-but-insignificant).

Sources: people.cs.umass.edu/~emery/pubs/res005-liu.pdf (Sheriff) · people.cs.umass.edu/~emery/pubs/Predator-ppopp14.pdf · web.eecs.umich.edu/~mozafari/php/data/uploads/pldi_2019.pdf (Huron) · users.ece.cmu.edu/~asrirama/publication/hpca16/laser.pdf · dl.acm.org/doi/10.1145/3123939.3123947 (TMI) · dl.acm.org/doi/10.1145/3178487.3178499 (Feather) · dl.acm.org/doi/10.1145/2854038.2854039 (Cheetah) · github.com/cirosantilli/parsec-benchmark · github.com/efeslab/huron · github.com/plasma-umass/sheriff
