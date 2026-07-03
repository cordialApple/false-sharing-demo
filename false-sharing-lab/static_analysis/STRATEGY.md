# Detection Strategy — Tier-1 Static False-Sharing Analyzer

*Phase-3 synthesis by the orchestrator, from SOA.md + environment assessment.*

## Decision

**Route A** from SOA.md §3: Python analysis of textual LLVM IR emitted by
`clang -S -emit-llvm`, wrapped in a LangGraph agent that mirrors the existing
benchmark workflow (`agent/agent.py`). Chosen because:

1. **Environment fit** — WSL Ubuntu now has clang/LLVM 18 (apt `clang llvm`),
   but not `llvm-dev`/CMake; Route B's plugin ABI lock-in isn't worth it for a POC.
2. **Project coherence** — the lab is Python-orchestrated (LangGraph agent driving
   a C artifact through WSL). Route A reuses that exact shape.
3. **Ground truth exists** — `c_benchmark/false_sharing.c` gives a perfect
   labeled test: `unpadded_counter_t` (8 B, tid-indexed, thread-written) must be
   flagged; `padded_counter_t` (64 B) must pass.

## Heuristics implemented (POC scope)

From SOA.md §4, in order of signal strength for this codebase:

- **H2** (primary): variable-index GEP into an array of structs with
  `sizeof(struct) < 64`, inside a thread-reachable function → HIGH severity.
- **H1**: two fields of one struct in the same 64-byte bucket, both stored to
  from thread-reachable code → MEDIUM.
- **H4**: struct used as array element, `sizeof % 64 != 0` → LOW (advisory).

H3/H5/H6 are documented as future work (Tier 2 LLVM pass territory).

## Pipeline (mirrors run_benchmark → read_results → write_report)

```
emit_ir      clang -S -emit-llvm -O0 -g <src>.c -o ir/<src>.ll   (via WSL)
analyze_ir   ir_analyzer.py: parse struct layouts, pthread_create entries,
             GEP/store sites; apply H2/H1/H4; emit findings JSON
write_report agent renders findings -> reports/static_analysis.md
```

`-O0 -g` deliberately: every source-level access survives as an explicit
load/GEP/store (at -O1+ the non-atomic counter increment can be hoisted into a
register, erasing the store pattern), and debug metadata keeps source lines.

## Layout-offset math

The analyzer replicates natural-alignment layout: each field aligned to
`min(sizeof(scalar), 8)`, struct size rounded up to max member alignment. This
matches clang's x86-64 SysV layout for the C types used here; exotic types
(bitfields, over-aligned members) are out of POC scope and reported as UNKNOWN.

## Verification criteria (Phase 5)

- `unpadded_counter_t` flagged by H2 with `worker_unpadded` named as the
  thread-reachable writer.
- `padded_counter_t` NOT flagged by H2 (element size == 64).
- Report written to `reports/static_analysis.md` with cache-line diagrams.

## Model assignment recap

Research = Sonnet, synthesis/steering = orchestrator (Fable/opus-tier),
implementation = Sonnet under this tight spec, verification = orchestrator.
