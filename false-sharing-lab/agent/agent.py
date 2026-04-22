import os
import subprocess
from dotenv import load_dotenv

# Ensure dotenv is loaded before ChatAnthropic initialization
load_dotenv()

from langchain_core.tools import tool
from langchain_anthropic import ChatAnthropic
from langgraph.prebuilt import create_react_agent
from langchain_core.messages import HumanMessage

RESULTS_FILE = "../results/benchmark_results.csv"
REPORT_FILE = "../reports/analysis.md"

@tool
def run_benchmark(threads: int) -> str:
    """
    Runs the C benchmark for the specified number of threads.
    It compiles the code first, then runs the benchmark.
    """
    print(f"Tool execution: Running benchmark with {threads} threads...")
    try:
        if os.name == 'nt':
            # We are on Windows, compile and run using WSL
            subprocess.run(["wsl", "make"], cwd="../c_benchmark", capture_output=True, check=True)
            subprocess.run(["wsl", "./benchmark", str(threads)], cwd="../c_benchmark", capture_output=True, check=True)
        else:
            # We are natively in Linux/WSL
            subprocess.run(["make"], cwd="../c_benchmark", capture_output=True, check=True)
            subprocess.run(["./benchmark", str(threads)], cwd="../c_benchmark", capture_output=True, check=True)
            
        return f"Successfully ran benchmark with {threads} threads. Data appended to CSV."
    except subprocess.CalledProcessError as e:
        return f"Error running benchmark for {threads} threads: {e.stderr}"

@tool
def read_benchmark_results() -> str:
    """
    Reads the benchmark results CSV and returns the contents.
    Use this after running the benchmark to see the data.
    """
    print("Tool execution: Reading benchmark CSV...")
    if not os.path.exists(RESULTS_FILE):
        return "File not found. Please run_benchmark first."
    with open(RESULTS_FILE, "r") as f:
        return f.read()

@tool
def write_report(content: str) -> str:
    """
    Writes the provided markdown content to the analysis.md report file.
    Use this to finalize and save the report.
    """
    print("Tool execution: Writing markdown report...")
    os.makedirs(os.path.dirname(REPORT_FILE), exist_ok=True)
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(content)
    return "Report written successfully."

def get_core_count() -> int:
    """Detects the number of available processing cores using nproc within WSL/Linux."""
    try:
        if os.name == 'nt':
            result = subprocess.run(["wsl", "nproc"], capture_output=True, text=True, check=True)
        else:
            result = subprocess.run(["nproc"], capture_output=True, text=True, check=True)
        return int(result.stdout.strip())
    except Exception as e:
        print(f"Error detecting core count: {e}. Defaulting to 4.")
        return 4

def main():
    cores = get_core_count()
    print(f"Detected {cores} processing cores in WSL.")

    os.makedirs(os.path.dirname(RESULTS_FILE), exist_ok=True)
    with open(RESULTS_FILE, "w") as f:
        f.write("version,threads,runtime_seconds\n")
        
    thread_counts = []
    tc = 1
    while tc <= cores:
        thread_counts.append(tc)
        tc *= 2
    if not thread_counts or thread_counts[-1] != cores:
        thread_counts.append(cores)

    # Initialize agent
    model = ChatAnthropic(model="claude-sonnet-4-20250514")
    tools = [run_benchmark, read_benchmark_results, write_report]
    agent_executor = create_react_agent(model, tools)

    prompt = f"""
I want you to analyze the behavior of false sharing in a C program.
First, use the `run_benchmark` tool to collect performance data for the following thread counts: {', '.join(map(str, thread_counts))}.
Second, use the `read_benchmark_results` tool to view the collected CSV data.
Third, analyze the performance differences between the unpadded (false sharing) and padded versions.
Finally, use the `write_report` tool to write a detailed markdown report explaining true sharing vs false sharing, why the performance differs based on CPU cache line behavior, and include a markdown table formatting the data you observed. 
"""
    print("Starting agent execution...")
    try:
        response = agent_executor.invoke({"messages": [HumanMessage(content=prompt)]})
        print("Agent execution complete. Check reports/analysis.md")
    except Exception as e:
        print(f"Agent failed: {e}")

if __name__ == "__main__":
    main()
