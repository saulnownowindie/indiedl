$ErrorActionPreference = 'Stop'
$ProgressPreference = 'Continue'
$Host.UI.RawUI.WindowTitle = 'IndieDL - Instalacion'

function Write-Step([string]$Message) {
    Write-Host "`n==> $Message" -ForegroundColor Yellow
}

function Find-Python312 {
    $launcher = Get-Command py.exe -ErrorAction SilentlyContinue
    if ($launcher) {
        $found = & $launcher.Source -3.12 -c 'import sys; print(sys.executable)' 2>$null
        if ($LASTEXITCODE -eq 0 -and $found) { return ($found | Select-Object -Last 1).Trim() }
    }

    $known = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312\python.exe'
    if (Test-Path -LiteralPath $known) { return $known }
    return $null
}

try {
    if (-not [Environment]::Is64BitOperatingSystem) {
        throw 'IndieDL requiere Windows de 64 bits.'
    }

    $repoRoot = Split-Path -Parent $PSScriptRoot
    $sourceApp = Join-Path $repoRoot 'app'
    if (-not (Test-Path -LiteralPath (Join-Path $sourceApp 'indiedl.py'))) {
        throw 'No encuentro app\indiedl.py. Extrae el ZIP completo y vuelve a ejecutar INSTALAR.bat.'
    }

    $appDir = Join-Path $env:LOCALAPPDATA 'IndieDL'
    $venvDir = Join-Path $appDir 'venv'
    New-Item -ItemType Directory -Force -Path $appDir | Out-Null

    Write-Step 'Buscando Python 3.12 de 64 bits'
    $pythonExe = Find-Python312
    if (-not $pythonExe) {
        $version = '3.12.10'
        $installer = Join-Path $env:TEMP "python-$version-amd64.exe"
        $pythonHome = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312'
        Write-Host "Python 3.12 no esta instalado. Descargando Python $version desde python.org..."
        Invoke-WebRequest -Uri "https://www.python.org/ftp/python/$version/python-$version-amd64.exe" -OutFile $installer
        $signature = Get-AuthenticodeSignature -FilePath $installer
        if ($signature.Status -ne 'Valid' -or $signature.SignerCertificate.Subject -notmatch 'Python Software Foundation') {
            throw 'No pude validar la firma oficial del instalador de Python descargado.'
        }
        Write-Host 'Instalando Python para el usuario actual. El instalador mostrara su propio progreso...'
        $installArgs = @('/passive', 'InstallAllUsers=0', ('TargetDir="{0}"' -f $pythonHome), 'Include_pip=1',
                         'Include_launcher=1', 'Include_tcltk=1', 'PrependPath=0', 'Shortcuts=0', 'Include_test=0')
        $process = Start-Process -FilePath $installer -ArgumentList $installArgs -Wait -PassThru
        if ($process.ExitCode -ne 0) { throw "El instalador de Python termino con codigo $($process.ExitCode)." }
        $pythonExe = Join-Path $pythonHome 'python.exe'
        if (-not (Test-Path -LiteralPath $pythonExe)) { throw 'Python termino de instalarse, pero no encuentro python.exe.' }
    }

    $pythonVersion = & $pythonExe --version
    if ($LASTEXITCODE -ne 0 -or $pythonVersion -notmatch '^Python 3\.12\.') {
        throw "Se necesita Python 3.12; se encontro: $pythonVersion"
    }
    $pythonBits = & $pythonExe -c 'import struct; print(struct.calcsize("P") * 8)'
    if ($LASTEXITCODE -ne 0 -or $pythonBits -ne '64') { throw 'Se necesita Python de 64 bits.' }
    Write-Host "$pythonVersion ($pythonExe)" -ForegroundColor Green

    Write-Step 'Copiando IndieDL a %LOCALAPPDATA%\IndieDL'
    Copy-Item -LiteralPath (Join-Path $sourceApp 'indiedl.py') -Destination (Join-Path $appDir 'indiedl.py') -Force
    Copy-Item -LiteralPath (Join-Path $sourceApp 'analizar_media.py') -Destination (Join-Path $appDir 'analizar_media.py') -Force
    Copy-Item -LiteralPath (Join-Path $repoRoot 'requirements.txt') -Destination (Join-Path $appDir 'requirements.txt') -Force

    Write-Step 'Preparando el entorno privado de IndieDL'
    if (-not (Test-Path -LiteralPath (Join-Path $venvDir 'Scripts\python.exe'))) {
        & $pythonExe -m venv $venvDir
        if ($LASTEXITCODE -ne 0) { throw 'No se pudo crear el entorno de Python.' }
    }
    $venvPython = Join-Path $venvDir 'Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $venvPython)) { throw 'No encuentro el Python del entorno virtual.' }

    Write-Step 'Actualizando pip'
    & $venvPython -m pip install --upgrade pip
    if ($LASTEXITCODE -ne 0) { throw 'No se pudo actualizar pip.' }

    Write-Step 'Instalando interfaz, yt-dlp, gallery-dl y FFmpeg'
    Write-Host 'La salida de pip se muestra aqui; la primera instalacion puede tardar unos minutos.'
    & $venvPython -m pip install --upgrade -r (Join-Path $appDir 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'No se pudieron instalar todas las dependencias. Revisa la salida de pip y vuelve a ejecutar INSTALAR.bat.' }

    Write-Step 'Comprobando las librerias y FFmpeg'
    & $venvPython -c 'import customtkinter, gallery_dl, imageio_ffmpeg, yt_dlp; from PIL import Image; print("Librerias listas"); print("FFmpeg:", imageio_ffmpeg.get_ffmpeg_exe())'
    if ($LASTEXITCODE -ne 0) { throw 'La comprobacion de dependencias fallo.' }

    Write-Step 'Creando acceso directo y registrando enlaces ytdl://'
    $pythonw = Join-Path $venvDir 'Scripts\pythonw.exe'
    $appScript = Join-Path $appDir 'indiedl.py'
    $desktop = [Environment]::GetFolderPath('Desktop')
    $shortcutPath = Join-Path $desktop 'IndieDL.lnk'
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $pythonw
    $shortcut.Arguments = ('"{0}"' -f $appScript)
    $shortcut.WorkingDirectory = $appDir
    $shortcut.Description = 'IndieDL - Descargador de videos, audios e imagenes'
    $shortcut.IconLocation = "$pythonw,0"
    $shortcut.Save()
    & $pythonw $appScript --register-only
    if ($LASTEXITCODE -ne 0) { Write-Host 'Aviso: no se pudo registrar el protocolo ytdl:// en este momento.' -ForegroundColor DarkYellow }

    Write-Host "`nInstalacion completada. Abre IndieDL desde el acceso directo del Escritorio." -ForegroundColor Green
    Write-Host "Aplicacion: $appDir"
    Read-Host 'Pulsa Enter para cerrar esta ventana'
    exit 0
}
catch {
    Write-Host "`nERROR: $($_.Exception.Message)" -ForegroundColor Red
    Write-Host 'La ventana quedara abierta para que puedas leer el error.' -ForegroundColor Yellow
    Read-Host 'Pulsa Enter para cerrar'
    exit 1
}
