<#
.SYNOPSIS
  Valida y prueba la infraestructura de Azure (infra/terraform) con Docker: sin instalar Terraform y sin credenciales.

.DESCRIPTION
  Usa las mismas imagenes y comandos que el job "Terraform (Azure)" del CI.
    validar    terraform fmt -check + init/validate de plataforma, entornos/dev y entornos/prod
    probar     terraform test: escenarios con Azure simulado (mock_provider)
    seguridad  tflint (reglas azurerm) + checkov
    todo       los tres (por defecto)

.EXAMPLE
  ./scripts/terraform.ps1
  ./scripts/terraform.ps1 probar
#>
param(
    [ValidateSet('validar', 'probar', 'seguridad', 'todo')]
    [string]$Accion = 'todo'
)

# Solo ASCII en este archivo: Windows PowerShell 5.1 lee los scripts como ANSI.
$ErrorActionPreference = 'Stop'
$infra = (Resolve-Path (Join-Path $PSScriptRoot '..\infra\terraform')).Path
$imgTerraform = 'hashicorp/terraform:1.17.2'
$imgTflint = 'ghcr.io/terraform-linters/tflint:v0.66.0'
$imgCheckov = 'bridgecrew/checkov:3.4.6'
$raices = @('plataforma', 'entornos/dev', 'entornos/prod')
$resultados = New-Object System.Collections.Generic.List[object]

function Invoke-Docker {
    param([string[]]$Parametros, [switch]$Silencioso)
    if ($Silencioso) { & docker @Parametros | Out-Null } else { & docker @Parametros }
    if ($LASTEXITCODE -ne 0) { throw "termino con codigo $LASTEXITCODE (detalle en la salida de arriba)" }
}

function Invoke-Terraform {
    param([string]$Carpeta, [string[]]$Comando, [switch]$Silencioso)
    $base = @('run', '--rm', '-v', "${infra}:/tf", '-v', 'tf-cache:/cache',
        '-e', 'TF_PLUGIN_CACHE_DIR=/cache', '-e', 'TF_IN_AUTOMATION=1', '-w', "/tf/$Carpeta", $imgTerraform)
    Invoke-Docker -Parametros ($base + $Comando) -Silencioso:$Silencioso
}

function Invoke-Paso {
    param([string]$Nombre, [scriptblock]$Bloque)
    Write-Host ""
    Write-Host "==> $Nombre" -ForegroundColor Cyan
    $reloj = [Diagnostics.Stopwatch]::StartNew()
    try {
        & $Bloque
        $resultados.Add([pscustomobject]@{ Paso = $Nombre; Resultado = 'OK'; Segundos = [math]::Round($reloj.Elapsed.TotalSeconds) })
    } catch {
        Write-Host "    FALLA: $($_.Exception.Message)" -ForegroundColor Red
        $resultados.Add([pscustomobject]@{ Paso = $Nombre; Resultado = 'FALLA'; Segundos = [math]::Round($reloj.Elapsed.TotalSeconds) })
    }
}

if ($Accion -in 'validar', 'todo') {
    Invoke-Paso 'Formato (terraform fmt -check)' {
        Invoke-Terraform -Carpeta '' -Comando @('fmt', '-recursive', '-check', '-diff')
        Write-Host '    sin cambios de formato'
    }
    foreach ($r in $raices) {
        Invoke-Paso "Validacion de $r (terraform validate)" {
            Invoke-Terraform -Carpeta $r -Comando @('init', '-backend=false', '-input=false', '-lockfile=readonly', '-no-color') -Silencioso
            Invoke-Terraform -Carpeta $r -Comando @('validate', '-no-color')
        }
    }
}

if ($Accion -in 'probar', 'todo') {
    Invoke-Paso 'Pruebas con Azure simulado (terraform test)' {
        Invoke-Terraform -Carpeta 'plataforma' -Comando @('init', '-backend=false', '-input=false', '-lockfile=readonly', '-no-color') -Silencioso
        Invoke-Terraform -Carpeta 'plataforma' -Comando @('test', '-no-color')
    }
}

if ($Accion -in 'seguridad', 'todo') {
    Invoke-Paso 'tflint (reglas de azurerm)' {
        $tflint = @('run', '--rm', '-v', "${infra}:/data", '-v', 'tflint-plugins:/root/.tflint.d', '-w', '/data')
        if ($env:GITHUB_TOKEN) { $tflint = @('run', '--rm', '-e', 'GITHUB_TOKEN') + $tflint[2..($tflint.Length - 1)] }
        Invoke-Docker -Parametros ($tflint + @($imgTflint, '--init')) -Silencioso
        Invoke-Docker -Parametros ($tflint + @($imgTflint, '--recursive'))
        Write-Host '    sin hallazgos'
    }
    Invoke-Paso 'Seguridad de la IaC (checkov)' {
        Invoke-Docker -Parametros @('run', '--rm', '-v', "${infra}:/tf", '-w', '/tf', $imgCheckov, '--config-file', '/tf/.checkov.yaml')
    }
}

Write-Host ""
Write-Host "Resumen (infra/terraform)" -ForegroundColor Cyan
$resultados | Format-Table -AutoSize | Out-String | Write-Host
$fallas = @($resultados | Where-Object { $_.Resultado -eq 'FALLA' }).Count
if ($fallas -gt 0) {
    Write-Host "$fallas paso(s) con falla" -ForegroundColor Red
    exit 1
}
Write-Host "Todo OK: la infraestructura de Azure es valida y cumple las pruebas y reglas de seguridad." -ForegroundColor Green
exit 0
