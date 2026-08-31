$ErrorActionPreference = "Continue"
Set-Location -LiteralPath "G:\刷刷宝\GameScript-Local"
$log = "G:\刷刷宝\GameScript-Local\logs\codex_sol_review_20260901.log"
New-Item -ItemType Directory -Force -Path (Split-Path $log) | Out-Null
$prompt = Get-Content -LiteralPath "G:\刷刷宝\GameScript-Local\docs\CODEX_SOL_HANDOFF_20260901.md" -Raw -Encoding UTF8
"=== codex Sol-high review started: $(Get-Date -Format o) ===" | Out-File -FilePath $log -Encoding utf8 -Append
codex exec --model gpt-5.6-sol -c model_reasoning_effort="high" -c sandbox_workspace_write.network_access=true --sandbox workspace-write --skip-git-repo-check $prompt *>> $log
"=== codex finished with exit code ${LASTEXITCODE}: $(Get-Date -Format o) ===" | Out-File -FilePath $log -Encoding utf8 -Append
exit ${LASTEXITCODE}
