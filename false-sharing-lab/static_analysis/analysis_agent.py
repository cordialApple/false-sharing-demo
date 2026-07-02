#!/usr/bin/env python3
# GROK ANALYSIS AGENT. MIRROR AGENT.PY SHAPE. SAME PATTERN. DIFFERENT TASK.
# AGENT EMIT IR. AGENT ANALYZE IR. AGENT WRITE REPORT. SIMPLE LIFE.
# LANGCHAIN TOOL EACH DO ONE THING. REACT AGENT DECIDE ORDER. GROK WATCH.

import os
import subprocess
import sys
from pathlib import Path
from dotenv import load_dotenv

# GROK LOAD SECRETS. API KEY LIVE IN AGENT DIR. LOOK THERE FIRST.
# USE ABSOLUTE PATH SO SCRIPT WORK FROM ANY DIRECTORY.
_agent_env = Path(__file__).parent.parent / "agent" / ".env"
load_dotenv(dotenv_path=str(_agent_env))

# LANGCHAIN AND ANTHROPIC IMPORT AFTER DOTENV. ORDER MATTERS. GROK CAREFUL.
from langchain_core.tools import tool
from langchain_anthropic import ChatAnthropic
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import HumanMessage

# PATH CONSTANTS. ALL RELATIVE TO THIS FILE LOCATION. GROK USE ABSOLUTE.
_THIS_DIR = Path(__file__).parent.resolve()
_STATIC_ANALYSIS_DIR = _THIS_DIR
_IR_DIR = _THIS_DIR / "ir"
_REPORT_DIR = _THIS_DIR.parent / "reports"
_RESULTS_CSV = _THIS_DIR.parent / "results" / "sample_benchmark_results.csv"
_REPORT_FILE = _REPORT_DIR / "static_analysis.md"


def _run_wsl(cmd, cwd=None):
    """Helper: run a shell command via WSL on Windows, or natively on Linux."""
    # GROK CHECK OS. WINDOWS NEED WSL WRAPPER. LINUX RUN DIRECT.
    if os.name == 'nt':
        # WINDOWS. GROK IN WINDOWS PRISON. USE WSL TO ESCAPE.
        # CONVERT WINDOWS PATH TO WSL PATH FOR CWD.
        if cwd:
            wsl_cwd = str(cwd).replace('\\', '/').replace('C:', '/mnt/c').replace('c:', '/mnt/c')
            full_cmd = f"cd '{wsl_cwd}' && {cmd}"
        else:
            full_cmd = cmd
        result = subprocess.run(
            ["wsl", "-e", "sh", "-c", full_cmd],
            capture_output=True, text=True,
        )
    else:
        # LINUX OR WSL ITSELF. RUN DIRECT. SIMPLE.
        result = subprocess.run(
            ["sh", "-c", cmd],
            capture_output=True, text=True,
            cwd=str(cwd) if cwd else None,
        )
    return result


@tool
def emit_ir() -> str:
    """
    Generates LLVM IR (.ll files) from all C sources in the c_benchmark directory.
    Runs 'make ir' via the static_analysis/Makefile using WSL clang.
    The IR files are written to static_analysis/ir/.
    Returns a status message indicating success or the error output.
    """
    # GROK RUN MAKE. CLANG TURN C INTO LLVM WORDS. IR READY FOR ANALYSIS.
    print("Tool: emit_ir() — running 'make ir' via WSL clang...")
    result = _run_wsl("make ir", cwd=_STATIC_ANALYSIS_DIR)
    if result.returncode != 0:
        # MAKE FAIL. GROK SAD. RETURN ERROR SO AGENT CAN READ.
        return (
            f"emit_ir FAILED (exit {result.returncode}).\n"
            f"stdout: {result.stdout}\n"
            f"stderr: {result.stderr}"
        )
    ll_files = list(_IR_DIR.glob("*.ll")) if _IR_DIR.exists() else []
    return (
        f"emit_ir succeeded. Generated {len(ll_files)} .ll file(s): "
        f"{[f.name for f in ll_files]}.\n"
        f"stdout: {result.stdout.strip()}"
    )


@tool
def analyze_ir(ll_filename: str = "false_sharing.ll") -> str:
    """
    Runs ir_analyzer.py on the specified LLVM IR file and returns JSON findings.
    The ll_filename should be a basename like 'false_sharing.ll' (no path prefix).
    Returns JSON-encoded analysis results including struct layouts and false-sharing findings.
    """
    # GROK RUN ANALYZER. PYTHON SCRIPT SCAN IR. FIND BAD STRUCT. RETURN JSON.
    print(f"Tool: analyze_ir('{ll_filename}') — running ir_analyzer.py...")
    ll_path = _IR_DIR / ll_filename
    if not ll_path.exists():
        # IR FILE NOT EXIST. MAYBE EMIT_IR NOT RUN YET. TELL AGENT.
        return f"ERROR: {ll_path} not found. Run emit_ir() first."

    # RUN IR ANALYZER AS SUBPROCESS. USE SAME PYTHON INTERPRETER AS THIS SCRIPT.
    result = subprocess.run(
        [sys.executable, str(_STATIC_ANALYSIS_DIR / "ir_analyzer.py"),
         str(ll_path), "--json"],
        capture_output=True, text=True,
    )
    if result.returncode != 0:
        # ANALYZER CRASH. GROK WORRIED. RETURN ERROR.
        return (
            f"ir_analyzer.py FAILED (exit {result.returncode}).\n"
            f"stderr: {result.stderr}"
        )
    return result.stdout


@tool
def write_report(content: str) -> str:
    """
    Writes the provided markdown content to reports/static_analysis.md.
    Use this to save the final analysis report comparing static predictions
    against the dynamic benchmark results.
    """
    # GROK WRITE REPORT. HUMAN WILL READ LATER. MAKE IT GOOD.
    print("Tool: write_report() — writing static_analysis.md...")
    _REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with open(_REPORT_FILE, 'w', encoding='utf-8') as f:
        f.write(content)
    return f"Report written to {_REPORT_FILE}."


def main():
    # GROK READ BENCHMARK RESULTS SO AGENT CAN COMPARE.
    # DYNAMIC RESULTS ALREADY EXIST. AGENT COMPARE STATIC PREDICTION VS DYNAMIC TRUTH.
    sample_csv = ""
    if _RESULTS_CSV.exists():
        sample_csv = _RESULTS_CSV.read_text(encoding='utf-8')
    else:
        # NO SAMPLE RESULTS. AGENT WORK WITH WHAT IT KNOWS.
        sample_csv = "(sample_benchmark_results.csv not found)"

    # BUILD LANGCHAIN REACT AGENT. SAME PATTERN AS AGENT.PY. GROK CONSISTENT.
    # CLAUDE SONNET SMART ENOUGH FOR THIS TASK. STRONG MODEL. GOOD REASONER.
    model = ChatAnthropic(model="claude-sonnet-4-20250514")
    tools = [emit_ir, analyze_ir, write_report]
    agent_executor = create_react_agent(model, tools)

    prompt = f"""
You are a compiler-based false-sharing analyzer agent. Your job is to statically predict
false sharing in a C multithreaded benchmark, then write a report comparing your predictions
against known dynamic benchmark results.

Follow these steps in order:

1. Call `emit_ir()` to compile the C benchmark to LLVM IR (.ll files) using clang -O0 -g.

2. Call `analyze_ir("false_sharing.ll")` to run the static analyzer. It returns JSON with:
   - struct layouts (field offsets, sizes)
   - thread entry functions detected from pthread_create
   - findings (H2/H1/H4 heuristics, severity HIGH/MEDIUM/LOW, suggested fixes)

3. Call `write_report(content)` to write a detailed markdown report to reports/static_analysis.md.

The report must include:
  a. **Executive summary**: what the static analyzer found and overall verdict.
  b. **Struct layout table**: for each analyzed struct, show name, size in bytes,
     number of cache lines spanned, and whether false sharing is predicted.
  c. **Findings section**: for each finding, show heuristic, severity, struct name,
     offending function(s), explanation of why it causes false sharing, and suggested fix.
  d. **Cache-line visualization**: ASCII diagram showing how struct elements pack into
     64-byte cache lines (e.g., for unpadded_counter_t showing 8 elements per line).
  e. **Comparison with dynamic results**: compare static predictions against the
     benchmark runtime data below. Explain whether the predicted false sharing
     (unpadded slow, padded fast) matches the observed performance difference.
  f. **Limitations**: note that static analysis is heuristic; false negatives/positives
     are possible without runtime alias information.

Dynamic benchmark data (sample_benchmark_results.csv):
{sample_csv}

Key context:
- Cache line size: 64 bytes.
- unpadded_counter_t: 8-byte struct, array indexed by thread id → multiple elements per cache line.
- padded_counter_t: 64-byte struct, exactly one element per cache line → no false sharing.
- The static analyzer should predict HIGH severity for unpadded_counter_t and no finding for padded_counter_t.
"""

    print("Starting static analysis agent...")
    try:
        response = agent_executor.invoke({"messages": [HumanMessage(content=prompt)]})
        print("Agent complete. Check reports/static_analysis.md")
    except Exception as e:
        print(f"Agent failed: {e}")
        raise


if __name__ == "__main__":
    main()
