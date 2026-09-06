# Script to run the SQL agent
cd "c:\Users\pal amit kumar\Downloads\gates_ai_lld_code\gates_ai_lld"
. .\venv\Scripts\Activate.ps1

# Run the agent and capture output
python -m agents.sql_agent "What is the total budget by region?" 2>&1 | Tee-Object -FilePath agent_output.log

# Display the output
Write-Host ""
Write-Host "--- Agent Output ---"
Get-Content agent_output.log
