$ErrorActionPreference = "Continue"
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
Set-Location -LiteralPath "G:\刷刷宝\GameScript-Local"
$log = "G:\刷刷宝\GameScript-Local\logs\codex_sol_review_20260901.log"
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
# Prompt goes via stdin: avoids PowerShell 5.1 GBK re-encoding of a UTF-8 heredoc arg.
"=== codex Sol-high review started: $(Get-Date -Format o) ===" | Out-File -FilePath $log -Encoding utf8 -Append
Get-Content -LiteralPath "G:\刷刷宝\GameScript-Local\docs\CODEX_SOL_HANDOFF_20260901.md" -Raw -Encoding UTF8 |
  & node "C:\Users\10639\AppData\Roaming\npm\node_modules\@openai\codex\bin\codex.js" exec --model gpt-5.6-sol -c model_reasoning_effort="high" -c sandbox_workspace_write.network_access=true --sandbox workspace-write --skip-git-repo-check - >> $log 2>&1
"=== codex finished with exit code ${LASTEXITCODE}: $(Get-Date -Format o) ===" | Out-File -FilePath $log -Encoding utf8 -Append
exit ${LASTEXITCODE}
