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
