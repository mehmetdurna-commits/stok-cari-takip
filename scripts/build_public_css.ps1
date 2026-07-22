param(
    [string]$TailwindVersion = '3.4.17'
)

$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path -Parent $PSScriptRoot
$cliPath = Join-Path $env:TEMP "tailwindcss-$TailwindVersion.exe"

if (-not (Test-Path -LiteralPath $cliPath)) {
    $downloadUrl = "https://github.com/tailwindlabs/tailwindcss/releases/download/v$TailwindVersion/tailwindcss-windows-x64.exe"
    Invoke-WebRequest -Uri $downloadUrl -OutFile $cliPath
}

Push-Location $projectRoot
try {
    & $cliPath `
        -c tailwind.public.config.js `
        -i static/css/public-tailwind.css `
        -o static/css/public-tailwind.min.css `
        --minify
}
finally {
    Pop-Location
}
