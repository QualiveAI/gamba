param(
  [string]$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
)
$ErrorActionPreference = 'Stop'
$out = Join-Path $RepoRoot 'deploy\hosting\cloudflare\dist'
Remove-Item $out -Recurse -Force -ErrorAction SilentlyContinue
New-Item (Join-Path $out 'app') -ItemType Directory -Force | Out-Null
Copy-Item (Join-Path $RepoRoot 'landing\*') $out -Recurse -Force
Copy-Item (Join-Path $RepoRoot 'frontend\*') (Join-Path $out 'app') -Recurse -Force
Copy-Item (Join-Path $PSScriptRoot '_redirects') $out -Force
Copy-Item (Join-Path $PSScriptRoot '_headers') $out -Force
Remove-Item (Join-Path $out 'app\node_modules'),(Join-Path $out 'app\.cache'),(Join-Path $out 'app\test-results') -Recurse -Force -ErrorAction SilentlyContinue
Write-Output "Cloudflare Pages dist готов: $out"
