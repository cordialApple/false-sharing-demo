# False Sharing Lab

This project demonstrates the phenomenon of false sharing in C by benchmarking a concurrent counter increment with and without padding to cache lines. It includes a Python agent using LangChain that autonomously tests thread counts and writes an analysis.

## Prerequisites
- Windows Subsystem for Linux (WSL) with `gcc`, `make`, `nproc`.
- Python 3.9+ 
- Anthropic API Key

## Setup
1. Create a `.env` file in the `agent/` directory:
   ```env
   ANTHROPIC_API_KEY=your_key_here
   ```
2. Install Python dependencies:
   ```bash
   cd agent
   pip install -r requirements.txt
   ```

## Running the Lab
You can execute the entire flow by simply running the python script:
```bash
cd agent
python agent.py
```
This script will:
1. Detect your available WSL cores.
2. Direct the AI agent to build and run the C benchmark across multiple thread counts (unpadded & padded).
3. Record data in `results/benchmark_results.csv`.
4. Command the AI to review the CSV and write a final report to `reports/analysis.md`.

## Static Analysis (compile-time prediction)

The `static_analysis/` module predicts false sharing from LLVM IR before running
anything — the counterpart to the runtime benchmark above. It emits IR with WSL
clang (`clang -S -emit-llvm`), then applies layout + thread-reachability
heuristics (see `static_analysis/STRATEGY.md` and `SOA.md`).

Requires `clang`/`llvm` in WSL (`sudo apt install clang llvm`). Then:
```bash
cd static_analysis
wsl make ir                              # emit LLVM IR from c_benchmark sources
python ir_analyzer.py ir/false_sharing.ll  # run the analyzer (add --json for machine output)
python analysis_agent.py                 # or let the LangGraph agent drive the full flow
```
The agent flow mirrors `agent/agent.py`: emit IR → analyze → write a report to
`reports/static_analysis.md` comparing the static prediction against the
dynamic benchmark results.

### Tier 2: real LLVM pass + heuristic evaluation

`static_analysis/tier2_pass/` is an out-of-tree LLVM 18 pass (needs
`llvm-18-dev cmake g++` in WSL; build with `wsl ./build.sh` inside tier2_pass).
It uses exact `DataLayout` offsets, a real call-graph walk, and detects atomics
(H3) and adjacent globals (H5) that the Tier-1 regex analyzer cannot — and it
works on optimized (-O1) IR. Same CLI: `python tier2_analyzer.py <file.ll> [--json]`.

`evaluate.py` scores any registered analyzer against the labeled corpus in
`corpus/` (precision/recall per heuristic, results in
`results/heuristic_scores_<analyzer>.md`). Current: tier1 P=1.00/R=0.50,
tier2 P=1.00/R=1.00, with one shared documented gap (runtime function-pointer
thread entries are statically unresolvable).
