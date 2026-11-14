param(
  [Parameter(Mandatory = $true)]
  [string]$DatabaseUrl
)
$ErrorActionPreference = 'Stop'
$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot '..\..\..')).Path
$migrations = Get-ChildItem (Join-Path $repoRoot 'backend\migrations') -Filter '*.sql' | Sort-Object Name
if ($migrations.Count -eq 0) { throw 'Миграции не найдены' }
foreach ($migration in $migrations) {
  Write-Output "Применяю $($migration.Name)"
  & psql $DatabaseUrl --set ON_ERROR_STOP=1 --file $migration.FullName
  if ($LASTEXITCODE -ne 0) { throw "Ошибка миграции $($migration.Name)" }
}
Write-Output "Миграции применены: $($migrations.Count)"
