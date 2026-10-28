#Requires -Version 5.1
<#
    Indie Now DL - instalador automatico
    ------------------------------------
    Deja la aplicacion lista para usar en un PC con Windows 10/11:

      1. Python 3.12 (lo instala si falta)
      2. Entorno virtual + dependencias en %LOCALAPPDATA%\IndieDL\venv
      3. FFmpeg (winget; si no, usa el binario que trae imageio-ffmpeg)
      4. Copia la app y la extension a %LOCALAPPDATA%\IndieDL
      5. Registra el protocolo ytdl:// (lo usa la extension)
      6. Accesos directos en Escritorio y Menu Inicio

    Uso:
        powershell -ExecutionPolicy Bypass -File installer\instalar.ps1
        powershell -ExecutionPolicy Bypass -File installer\instalar.ps1 -SinAbrir
#>
[CmdletBinding()]
param(
    [switch]$SinAccesoDirecto,
    [switch]$SinAbrir
)

$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'

$RepoDir  = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$AppDir  = Join-Path $env:LOCALAPPDATA 'IndieDL'
$VenvDir = Join-Path $AppDir 'venv'
$VenvPy  = Join-Path $VenvDir 'Scripts\python.exe'
$VenvPyW = Join-Path $VenvDir 'Scripts\pythonw.exe'
$ReqFile = Join-Path $RepoDir 'requirements.txt'

function Titulo {
    Write-Host ''
    Write-Host '  INDIE NOW DL' -ForegroundColor Black -BackgroundColor Yellow
    Write-Host '  Instalador automatico' -ForegroundColor DarkGray
}
function Paso  { param([string]$t) Write-Host ''; Write-Host "  == $t" -ForegroundColor Yellow }
function Detalle { param([string]$t) Write-Host "     $t" -ForegroundColor DarkGray }
function Bien  { param([string]$t) Write-Host "     OK   $t" -ForegroundColor Green }
function Aviso { param([string]$t) Write-Host "     !    $t" -ForegroundColor Yellow }
function Mal   { param([string]$t) Write-Host "     X    $t" -ForegroundColor Red }

# FIX: quita la etiqueta de integridad BAJA de la carpeta de la app.
# Con esa etiqueta, python.exe del venv arranca como proceso de integridad
# baja y no puede escribir en D:\, Escritorio, etc. (Errno 13 al guardar).
# Se aplica a la carpeta y a todo lo que contiene (el venv hereda la etiqueta).
function Fix-Integrity {
    try {
        & icacls $AppDir /setintegritylevel '(OI)(CI)M' /T /C /Q | Out-Null
        if ($LASTEXITCODE -ne 0) { Aviso "icacls devolvio codigo $LASTEXITCODE al normalizar la integridad." }
    } catch {
        Aviso "No se pudo normalizar la integridad: $($_.Exception.Message)"
    }
}

# FIX: prueba real. El python del venv debe poder escribir fuera de IndieDL.
function Probar-Escritura {
    $probe = Join-Path $env:TEMP ("indiedl_probe_{0}.txt" -f [guid]::NewGuid())
    $env:IDL_PROBE = $probe
    try {
        & $VenvPy -c "import os;open(os.environ['IDL_PROBE'],'w').write('x')" 2>$null | Out-Null
    } catch { }
    Remove-Item Env:IDL_PROBE -ErrorAction SilentlyContinue
    if (Test-Path $probe) {
        Remove-Item $probe -Force -ErrorAction SilentlyContinue
        return $true
    }
    return $false
}

# pythonw.exe del Python base (el que creo el venv). Si no existe, usa el del venv.
function Get-HostPyW {
    try {
        $base = (& $VenvPy -c "import sys;print(sys.base_prefix)" 2>$null | Select-Object -First 1)
        if ($base) {
            $cand = Join-Path "$base".Trim() 'pythonw.exe'
            if (Test-Path $cand) { return $cand }
        }
    } catch { }
    if (Test-Path $VenvPyW) { return $VenvPyW }
    return $VenvPy
}

function Refrescar-Ruta {
    $maquina = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $usuario = [Environment]::GetEnvironmentVariable('Path', 'User')
    $partes  = @()
    foreach ($p in @($maquina, $usuario)) {
        if ($p) { $partes += $p }
    }
    $env:Path = ($partes -join ';')
}

function Buscar-Python {
    $candidatos = @(
        @{ Exe = 'py';     Args = @('-3.12') },
        @{ Exe = 'py';     Args = @('-3.13') },
        @{ Exe = 'py';     Args = @('-3')    },
        @{ Exe = 'python'; Args = @()        }
    )
    foreach ($c in $candidatos) {
        $cmd = Get-Command $c.Exe -ErrorAction SilentlyContinue
        if (-not $cmd) { continue }
        $full = @($c.Args) + @('-c', "import sys;print('%d.%d' % sys.version_info[:2])")
        try { $v = (& $cmd.Source @full 2>$null) } catch { continue }
        if ("$v" -match '^3\.(1[0-3])$') {
            return @{ Exe = $cmd.Source; Args = @($c.Args); Version = "$v" }
        }
    }
    # Rutas de instalacion tipicas, por si el PATH todavia no se actualizo.
    $rutas = @(
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'),
        (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python313\python.exe'),
        (Join-Path $env:ProgramFiles 'Python312\python.exe'),
        (Join-Path $env:ProgramFiles 'Python313\python.exe')
    )
    foreach ($r in $rutas) {
        if (Test-Path $r) {
            try { $v = (& $r -c "import sys;print('%d.%d' % sys.version_info[:2])" 2>$null) } catch { continue }
            if ("$v" -match '^3\.(1[0-3])$') {
                return @{ Exe = $r; Args = @(); Version = "$v" }
            }
        }
    }
    return $null
}

function Instalar-Python {
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Detalle 'Probando con winget (Python 3.12)...'
        & $winget.Source install --id Python.Python.3.12 -e --scope user --silent `
            --accept-package-agreements --accept-source-agreements --disable-interactivity | Out-Null
        Refrescar-Ruta
        $py = Buscar-Python
        if ($py) { return $py }
    }
    $url = 'https://www.python.org/ftp/python/3.12.10/python-3.12.10-amd64.exe'
    $destino = Join-Path $env:TEMP 'python-3.12.10-amd64.exe'
    Detalle 'Descargando Python 3.12 desde python.org...'
    Invoke-WebRequest -Uri $url -OutFile $destino -UseBasicParsing
    Detalle 'Instalando Python (silencioso, solo para este usuario)...'
    $p = Start-Process -FilePath $destino -Wait -PassThru -ArgumentList @(
        '/quiet', 'InstallAllUsers=0', 'PrependPath=1', 'Include_pip=1', 'Include_launcher=1'
    )
    Refrescar-Ruta
    return (Buscar-Python)
}

function Instalar-Requisitos {
    & $VenvPy -m pip install --upgrade --disable-pip-version-check --quiet pip setuptools wheel
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo actualizar pip.' }
    Detalle 'Instalando dependencias (puede tardar unos minutos la primera vez)...'
    & $VenvPy -m pip install --disable-pip-version-check --quiet --upgrade -r $ReqFile
    if ($LASTEXITCODE -ne 0) { throw 'Fallo la instalacion de dependencias (revisa la salida de pip).' }
}

function Asegurar-FFmpeg {
    Refrescar-Ruta
    if (Get-Command ffmpeg -ErrorAction SilentlyContinue) { return $true }
    $winget = Get-Command winget -ErrorAction SilentlyContinue
    if ($winget) {
        Detalle 'Instalando FFmpeg con winget...'
        & $winget.Source install --id Gyan.FFmpeg -e --scope user --silent `
            --accept-package-agreements --accept-source-agreements --disable-interactivity | Out-Null
        Refrescar-Ruta
        if (Get-Command ffmpeg -ErrorAction SilentlyContinue) { return $true }
    }
    return $false
}

function Nuevo-Acceso {
    param([string]$Ruta, [string]$Destino, [string]$Argumentos, [string]$Carpeta, [string]$Descripcion)
    try {
        $shell = New-Object -ComObject WScript.Shell
        $lnk = $shell.CreateShortcut($Ruta)
        $lnk.TargetPath = $Destino
        $lnk.Arguments = $Argumentos
        $lnk.WorkingDirectory = $Carpeta
        $lnk.IconLocation = "$Destino,0"
        $lnk.Description = $Descripcion
        $lnk.Save()
        return $true
    } catch {
        Aviso "No se pudo crear el acceso directo: $($_.Exception.Message)"
        return $false
    }
}

# =============================================================
Titulo

Paso '1/6  Python'
$py = Buscar-Python
if ($py) {
    Bien "Python $($py.Version) encontrado"
} else {
    Aviso 'No hay Python 3.10-3.13. Instalando...'
    $py = Instalar-Python
    if (-not $py) {
        Mal 'No se pudo instalar Python automaticamente.'
        Mal 'Instalalo a mano desde https://www.python.org/downloads/ y volve a ejecutar INSTALAR.bat'
        exit 1
    }
    Bien "Python $($py.Version) instalado"
}

Paso '2/6  Carpeta de la aplicacion'
New-Item -ItemType Directory -Force -Path $AppDir | Out-Null
Fix-Integrity   # FIX: antes de crear el venv, para que herede la etiqueta normal
Bien $AppDir

Paso '3/6  Entorno virtual'
if (Test-Path $VenvPy) {
    Bien 'Ya existe, se reutiliza'
} else {
    $pyArgs = @($py.Args) + @('-m', 'venv', $VenvDir)
    Detalle 'Creando entorno virtual...'
    & $py.Exe @pyArgs
    if (-not (Test-Path $VenvPy)) {
        Mal 'No se pudo crear el entorno virtual.'
        exit 1
    }
    Bien 'Entorno virtual creado'
}

Paso '4/6  Dependencias'
Instalar-Requisitos
Bien 'customtkinter, Pillow, yt-dlp, gallery-dl, imageio-ffmpeg'

# FIX: normaliza otra vez (venv ya existente o algo creado con etiqueta baja) y verifica
Fix-Integrity
if (Probar-Escritura) {
    Bien 'El entorno puede guardar en carpetas normales (D:\, Escritorio, etc.)'
} else {
    Mal 'El python del entorno NO puede escribir fuera de la carpeta de IndieDL.'
    Mal "Revisa: icacls `"$AppDir`" | findstr Mandatory"
}

Paso '5/6  Archivos de la aplicacion'
Copy-Item (Join-Path $RepoDir 'app\indiedl.py') $AppDir -Force
Copy-Item (Join-Path $RepoDir 'app\analizar_media.py') $AppDir -Force
Copy-Item (Join-Path $RepoDir 'app\launcher.pyw') $AppDir -Force
$extDst = Join-Path $AppDir 'browser-extension'
New-Item -ItemType Directory -Force -Path $extDst | Out-Null
Copy-Item (Join-Path $RepoDir 'browser-extension\*') $extDst -Force
Bien "App y extension copiadas a $AppDir"

$ff = Asegurar-FFmpeg
if ($ff) {
    Bien 'FFmpeg disponible en el sistema'
} else {
    Aviso 'No se pudo instalar FFmpeg en el sistema; se usara el binario incluido (imageio-ffmpeg). Funciona igual.'
}

Paso '6/6  Integracion con el navegador'
try {
    & $VenvPy (Join-Path $AppDir 'indiedl.py') --register-only | Out-Null
    if ($LASTEXITCODE -eq 0) {
        Bien 'Protocolo ytdl:// registrado'
    } else {
        Aviso 'El registro del protocolo devolvio un error (revisa indiedl.log).'
    }
} catch {
    Aviso "No se pudo registrar ytdl://: $($_.Exception.Message)"
}

if (-not $SinAccesoDirecto) {
    # Los accesos usan el pythonw del Python BASE + launcher.pyw (no el del venv),
    # para no heredar una etiqueta de integridad baja.
    $pythonw = Get-HostPyW
    $appPy = Join-Path $AppDir 'launcher.pyw'
    $escritorio = [Environment]::GetFolderPath('Desktop')
    $inicio = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs'
    Nuevo-Acceso -Ruta (Join-Path $escritorio 'Indie Now DL.lnk') -Destino $pythonw `
        -Argumentos "`"$appPy`"" -Carpeta $AppDir -Descripcion 'Indie Now DL' | Out-Null
    Nuevo-Acceso -Ruta (Join-Path $inicio 'Indie Now DL.lnk') -Destino $pythonw `
        -Argumentos "`"$appPy`"" -Carpeta $AppDir -Descripcion 'Indie Now DL' | Out-Null
    Bien 'Accesos directos creados (Escritorio y Menu Inicio)'
}

Write-Host ''
Write-Host '  =========================================================' -ForegroundColor DarkGray
Write-Host '   LISTO' -ForegroundColor Green
Write-Host ''
Write-Host '   Para la extension del navegador (una sola vez):' -ForegroundColor White
Write-Host "     1. Abri chrome://extensions  (o edge://extensions)" -ForegroundColor Gray
Write-Host '     2. Activa "Modo de desarrollador"' -ForegroundColor Gray
Write-Host '     3. "Cargar descomprimida" y elegi esta carpeta:' -ForegroundColor Gray
Write-Host "        $extDst" -ForegroundColor Cyan
Write-Host ''
Write-Host '   Despues abri cualquier video de YouTube/TikTok/Instagram y usa la barra.' -ForegroundColor Gray
Write-Host '  =========================================================' -ForegroundColor DarkGray

if (-not $SinAbrir) {
    Write-Host ''
    Write-Host '   Abriendo Indie Now DL...' -ForegroundColor DarkGray
    Start-Process -FilePath (Get-HostPyW) -ArgumentList @((Join-Path $AppDir 'launcher.pyw')) -WorkingDirectory $AppDir
}

exit 0
