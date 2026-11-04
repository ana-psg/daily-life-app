# Gera o instalador do Daily Life em dist\: limpa, roda os testes, cria o executavel,
# confere que nenhum dado pessoal entrou e monta o instalador.
# Uso: .\build.ps1   (precisa de: pip install -r requirements-dev.txt e do Inno Setup 6)
$ErrorActionPreference = 'Stop'
Set-Location -LiteralPath $PSScriptRoot
$python = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'

function Run-Step($title, [scriptblock]$step) {
    Write-Host "=== $title"
    & $step
    if ($LASTEXITCODE -ne 0) { throw "Falhou: $title" }
}

$iscc = @(
    "$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe",
    "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe",
    "$env:ProgramFiles\Inno Setup 6\ISCC.exe"
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $iscc) { throw 'Inno Setup 6 nao encontrado. Instale com: winget install JRSoftware.InnoSetup' }

Write-Host '=== Limpando'
foreach ($folder in 'dist', 'build') {
    $path = Join-Path $PSScriptRoot $folder
    if (Test-Path -LiteralPath $path) { Remove-Item -LiteralPath $path -Recurse -Force }
}

Run-Step 'Testes' { & $python -m pytest -q --no-header -p no:cacheprovider }
Run-Step 'Executavel' { & $python -m PyInstaller packaging/DailyLife.spec --noconfirm --distpath dist --workpath build --log-level WARN }
Run-Step 'Conferindo o pacote' { & $python tools/verificar_pacote.py dist/DailyLife }
Run-Step 'Instalador' { & $iscc /Q packaging\DailyLife.iss }

Get-ChildItem -LiteralPath dist -Filter '*.exe' | ForEach-Object {
    Write-Host ("Pronto: dist\{0} ({1} MB)" -f $_.Name, [int]($_.Length / 1MB))
}
