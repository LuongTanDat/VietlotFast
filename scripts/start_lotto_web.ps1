param(
    [string]$ProjectRoot = (Split-Path -Parent $PSScriptRoot),
    [string]$JavaExe,
    [string]$JavacExe,
    [switch]$Auto,
    [switch]$LibraryOnly
)

# Loaded without side effects by the isolated launcher regression tests.
function Get-LottoPortOwner {
    $endpoints = @(Get-CimInstance -Namespace root/StandardCimv2 -ClassName MSFT_NetTCPConnection -Filter 'LocalPort = 8080' -ErrorAction Stop)
    $owners = @($endpoints | Where-Object {
        $_.RemotePort -eq 0 -and $_.RemoteAddress -in @('0.0.0.0', '::') -and $_.OwningProcess -gt 0
    } | ForEach-Object { [int]$_.OwningProcess } | Sort-Object -Unique)
    if ($owners.Count -eq 0) { return $null }
    if ($owners.Count -ne 1) { throw 'Cong 8080 co nhieu process. Khong tu dong dung.' }
    $process = Get-CimInstance Win32_Process -Filter ('ProcessId = ' + $owners[0]) -ErrorAction Stop
    if (-not $process) { throw 'PID tren cong 8080 da thay doi. Hay thu lai.' }
    [pscustomobject]@{
        ProcessId = [int]$process.ProcessId
        Name = [string]$process.Name
        CommandLine = [string]$process.CommandLine
        Created = [string]$process.CreationDate.ToUniversalTime().Ticks
    }
}

function Test-LottoServerIdentity($Process) {
    $Process -and $Process.Name -match '^java(w)?\.exe$' -and
        $Process.CommandLine -match '(?:^|\s)LottoWebServer(?:\s|$)'
}

function Test-LottoPage {
    try {
        $page = Invoke-WebRequest 'http://127.0.0.1:8080/' -UseBasicParsing -TimeoutSec 3 -ErrorAction Stop
        return $page.StatusCode -eq 200 -and $page.Content.Contains('predictRootEffectiveness') -and
            $page.Content.Contains('/vietlott-web-effectiveness.js')
    } catch { return $false }
}

function Get-LottoChildWorkers($ProcessId) {
    @(Get-CimInstance Win32_Process -Filter ('ParentProcessId = ' + $ProcessId) -ErrorAction Stop |
        Where-Object { $_.Name -ine 'conhost.exe' })
}

function Assert-LottoSameProcess($Expected, $Current) {
    if (-not $Current -or -not (Test-LottoServerIdentity $Current) -or
        $Current.ProcessId -ne $Expected.ProcessId -or $Current.Created -ne $Expected.Created -or
        $Current.CommandLine -cne $Expected.CommandLine) {
        throw 'PID/lenh server tren cong 8080 da thay doi. Khong dung process; hay thu lai.'
    }
}

function Invoke-LottoCompile($Root, $Compiler, $Build) {
    Push-Location -LiteralPath $Root
    $previousErrorPreference = $ErrorActionPreference
    try {
        # Windows PowerShell 5 treats native stderr (including javac warnings)
        # as ErrorRecord; use the compiler's exit code to decide success.
        $ErrorActionPreference = 'Continue'
        # A native executable that cannot start leaves LASTEXITCODE unchanged.
        # Clear its global value so a previous successful command cannot pass.
        $global:LASTEXITCODE = $null
        try {
            & $Compiler -encoding UTF-8 -d $Build 'backend/LottoWebServer.java' 2>&1 | ForEach-Object { Write-Host $_ }
        } catch {
            throw 'Bien dich that bai: khong khoi dong duoc Javac; server dang chay van duoc giu nguyen.'
        }
        $compileExit = $global:LASTEXITCODE
        $ErrorActionPreference = $previousErrorPreference
        if ($null -eq $compileExit -or $compileExit -ne 0) { throw 'Bien dich that bai; server dang chay van duoc giu nguyen.' }
    } finally {
        $ErrorActionPreference = $previousErrorPreference
        Pop-Location
    }
}

function Stop-LottoVerifiedServer($Expected) {
    Assert-LottoSameProcess $Expected (Get-LottoPortOwner)
    $workers = @(Get-LottoChildWorkers $Expected.ProcessId)
    if ($workers.Count -ne 0) {
        throw 'Server dang co worker xu ly du lieu. Hay doi worker hoan tat roi chay lai; khong dung server/worker.'
    }
    # Re-read the listener immediately before stopping. PID reuse and a changed
    # command line/creation time must never stop an unrelated process.
    Assert-LottoSameProcess $Expected (Get-LottoPortOwner)
    $running = Get-Process -Id $Expected.ProcessId -ErrorAction Stop
    # CIM serializes creation timestamps to microseconds; Process.StartTime
    # retains 100-nanosecond ticks. Ignore only that lost final digit.
    if ([Math]::Abs($running.StartTime.ToUniversalTime().Ticks - [long]$Expected.Created) -gt 9) {
        throw 'PID/start time da thay doi truoc khi dung. Khong dung process; hay thu lai.'
    }
    if (@(Get-LottoChildWorkers $Expected.ProcessId).Count -ne 0) {
        throw 'Server vua tao worker xu ly du lieu. Hay doi worker hoan tat; khong dung server/worker.'
    }
    Stop-Process -InputObject $running -Force -ErrorAction Stop
    if (-not $running.WaitForExit(5000)) { throw 'Server cu chua dung xong. Hay kiem tra truoc khi thu lai.' }
    if (Get-LottoPortOwner) { throw 'Cong 8080 da duoc process khac su dung. Khong khoi dong de len.' }
}

function Start-LottoJava($Root, $Executable, $Build, $LogStem) {
    $javaArgs = @('-Dfile.encoding=UTF-8', '-cp', ($Build + ';backend/lib/sqlite-jdbc-3.51.2.0.jar'), 'LottoWebServer')
    $startedProcess = Start-Process -FilePath $Executable -ArgumentList $javaArgs -WorkingDirectory $Root -WindowStyle Hidden -PassThru `
        -RedirectStandardOutput (Join-Path $Root ('runtime/' + $LogStem + '_stdout.log')) `
        -RedirectStandardError (Join-Path $Root ('runtime/' + $LogStem + '_stderr.log'))
    $startedProcess | Add-Member -NotePropertyName LottoErrorLog -NotePropertyValue (Join-Path $Root ('runtime/' + $LogStem + '_stderr.log'))
    return $startedProcess
}

function Wait-LottoReady($Started) {
    for ($attempt = 0; $attempt -lt 15; $attempt++) {
        if ($Started.HasExited) { throw ('Server moi da thoat. Kiem tra log: ' + $Started.LottoErrorLog) }
        $listener = Get-LottoPortOwner
        if ($listener) {
            if ($listener.ProcessId -ne $Started.Id) { throw 'Cong 8080 da doi chu. Khong tu dong dung process moi.' }
            if (Test-LottoPage) { return }
        }
        Start-Sleep -Seconds 1
    }
    throw 'Chua xac nhan server san sang. Xem log launcher trong runtime; khong chay them server.'
}

function Open-LottoBrowser { Start-Process 'http://localhost:8080/' }

function Invoke-LottoWebLauncher($Root, $Executable, $Compiler, [bool]$Automatic) {
    $Root = (Resolve-Path -LiteralPath $Root -ErrorAction Stop).Path
    if (-not (Test-Path -LiteralPath $Executable -PathType Leaf) -or
        -not (Test-Path -LiteralPath $Compiler -PathType Leaf)) { throw 'Khong tim thay Java/Javac. Hay kiem tra JAVA_HOME.' }
    if ((Split-Path -Parent (Resolve-Path -LiteralPath $Executable).Path) -ine
        (Split-Path -Parent (Resolve-Path -LiteralPath $Compiler).Path)) {
        throw 'Java va Javac phai thuoc cung mot JDK. Hay kiem tra JAVA_HOME.'
    }
    $runtime = Join-Path $Root 'runtime'
    [void][System.IO.Directory]::CreateDirectory($runtime)
    $launcherLock = $null
    try {
        try {
            $launcherLock = [System.IO.File]::Open((Join-Path $runtime 'web_launcher.write.lock'),
                [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None)
        } catch { throw 'Mot launcher khac dang chay. Hay doi hoan tat roi thu lai.' }
        $existing = Get-LottoPortOwner
        if ($existing) {
            $known = Test-LottoServerIdentity $existing
            # Auto mode can reuse a Java listener when Windows hides its command
            # line, but that weaker page fingerprint NEVER authorizes a stop.
            if ($Automatic -and -not $known -and $existing.Name -match '^java(w)?\.exe$') { $known = Test-LottoPage }
            if (-not $known) { throw 'Cong 8080 dang duoc process khac su dung. Khong tu dong dung.' }
            if ($Automatic) {
                Write-Host 'Lotto Web Server dang chay. Su dung server hien tai.'
                Open-LottoBrowser
                return
            }
        }
        $stamp = Get-Date -Format 'yyyyMMdd_HHmmss'
        $build = 'runtime/build_launcher_' + $stamp + '_' + [guid]::NewGuid().ToString('N')
        [void][System.IO.Directory]::CreateDirectory((Join-Path $Root $build))
        Write-Host 'Dang bien dich backend/LottoWebServer.java...'
        # A fresh build keeps lazily loaded classes of the running server intact.
        Invoke-LottoCompile $Root $Compiler $build
        if ($existing) {
            Stop-LottoVerifiedServer $existing
        } elseif (Get-LottoPortOwner) {
            throw 'Cong 8080 da duoc process khac su dung trong luc bien dich. Hay thu lai.'
        }
        $logStem = if ($Automatic) { 'web_auto' } else { 'web_launcher_' + $stamp + '_' + [guid]::NewGuid().ToString('N') }
        $started = Start-LottoJava $Root $Executable $build $logStem
        Wait-LottoReady $started
        Write-Host 'Server da san sang tai http://localhost:8080/'
        Write-Host ('Log: runtime/' + $logStem + '_stdout.log va _stderr.log')
        Open-LottoBrowser
    } finally {
        if ($launcherLock) { $launcherLock.Dispose() }
    }
}

if (-not $LibraryOnly) {
    $ErrorActionPreference = 'Stop'
    try {
        Invoke-LottoWebLauncher $ProjectRoot $JavaExe $JavacExe ([bool]$Auto)
        exit 0
    } catch {
        [Console]::Error.WriteLine($_.Exception.Message)
        exit 1
    }
}
