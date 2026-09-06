#!/usr/bin/env python3
import subprocess
import sys
import os

# Change to the project directory
os.chdir(r"c:\Users\pal amit kumar\Downloads\gates_ai_lld_code\gates_ai_lld")

# Run the agent
result = subprocess.run(
    [r"c:\Users\pal amit kumar\Downloads\gates_ai_lld_code\gates_ai_lld\venv\Scripts\python.exe", 
     "-m", "agents.sql_agent", "What is the total budget by region?"],
    capture_output=True,
    text=True,
    timeout=30
)

print("STDOUT:")
print(result.stdout)
print("\nSTDERR:")
print(result.stderr)
print(f"\nReturn Code: {result.returncode}")
