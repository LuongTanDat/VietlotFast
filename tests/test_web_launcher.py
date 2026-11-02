"""Exercise the Windows launcher with fake processes, ports and compiler.

The helper is dot-sourced with LibraryOnly. No test queries or stops the live
8080 listener, starts Java, or opens a browser.
"""
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
POWERSHELL = shutil.which('powershell.exe') or shutil.which('pwsh.exe')


@unittest.skipUnless(POWERSHELL, 'Windows PowerShell is unavailable')
class WebLauncherTests(unittest.TestCase):
    def scenario(self, setup, expected_message='', automatic=False):
        with tempfile.TemporaryDirectory(prefix='launcher-test-', dir=ROOT / 'runtime') as temp:
            work = Path(temp)
            fake_root = work / 'project with spaces'
            fake_root.mkdir()
            executable = fake_root / 'java.exe'
            executable.touch()
            compiler = fake_root / 'javac.exe'
            compiler.touch()
            harness = work / 'check.ps1'
            harness.write_text(r'''
param($Helper, $Root, $Java, $Compiler)
$ErrorActionPreference = 'Stop'
. $Helper -LibraryOnly
$script:RealCompile = ${function:Invoke-LottoCompile}
$script:RealStart = ${function:Start-LottoJava}
$script:Calls = New-Object 'System.Collections.Generic.List[string]'
$script:Owner = [pscustomobject]@{ ProcessId=987654321; Name='java.exe'; CommandLine='java -cp old-build LottoWebServer'; Created=([datetime]'2026-10-23T01:00:00Z').Ticks.ToString() }
$script:Workers = @()
function Get-LottoPortOwner { $script:Owner }
function Get-LottoChildWorkers($ProcessId) { $script:Workers }
function Invoke-LottoCompile($Root, $Compiler, $Build) { $script:Calls.Add('compile') }
function Get-Process {
    param($Id, $ErrorAction)
    $p = [pscustomobject]@{ Id=$Id; StartTime=[datetime]::new([long]$script:Owner.Created, [DateTimeKind]::Utc) }
    $p | Add-Member -MemberType ScriptMethod -Name WaitForExit -Value { param($Timeout) $true }
    $p
}
function Stop-Process {
    param($InputObject, [switch]$Force, $ErrorAction)
    $script:Calls.Add('stop'); $script:Owner = $null
}
function Start-LottoJava($Root, $Executable, $Build, $LogStem) {
    $script:Calls.Add('start')
    [pscustomobject]@{ Id=987654322; HasExited=$false }
}
function Wait-LottoReady($Started) { $script:Calls.Add('ready') }
function Open-LottoBrowser { $script:Calls.Add('browser') }
''' + setup + r'''
$message = ''
try { Invoke-LottoWebLauncher $Root $Java $Compiler AUTOMATIC_VALUE }
catch { $message = $_.Exception.Message }
[pscustomobject]@{ calls=@($script:Calls); message=$message } | ConvertTo-Json -Compress
'''.replace('AUTOMATIC_VALUE', '$true' if automatic else '$false'), encoding='utf-8')
            result = subprocess.run(
                [POWERSHELL, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(harness),
                 '-Helper', str(ROOT / 'scripts/start_lotto_web.ps1'), '-Root', str(fake_root),
                 '-Java', str(executable), '-Compiler', str(compiler)],
                capture_output=True, text=True, encoding='utf-8', errors='replace', timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            output = json.loads(result.stdout.strip().splitlines()[-1])
            if expected_message:
                self.assertIn(expected_message, output['message'])
            else:
                self.assertEqual(output['message'], '')
            return output['calls']

    def test_compile_failure_preserves_running_server(self):
        calls = self.scenario(r'''
function Invoke-LottoCompile($Root, $Compiler, $Build) {
    $script:Calls.Add('compile'); throw 'compiler-fixture-failed'
}
''', 'compiler-fixture-failed')
        self.assertEqual(calls, ['compile'])

    def test_real_compile_exit_code_is_checked_before_restart(self):
        calls = self.scenario(r'''
$Compiler = Join-Path $Root 'fake compiler.ps1'
Set-Content -LiteralPath $Compiler -Value '$global:LASTEXITCODE = 1'
function Invoke-LottoCompile($Root, $Compiler, $Build) {
    $script:Calls.Add('compile')
    & $script:RealCompile $Root $Compiler $Build
}
''', 'Bien dich that bai')
        self.assertEqual(calls, ['compile'])

    def test_compiler_that_cannot_start_does_not_reuse_previous_success(self):
        calls = self.scenario(r'''
$global:LASTEXITCODE = 0
function Invoke-LottoCompile($Root, $Compiler, $Build) {
    $script:Calls.Add('compile')
    & $script:RealCompile $Root $Compiler $Build
}
''', 'Bien dich that bai')
        self.assertEqual(calls, ['compile'])

    def test_worker_blocks_restart_without_stopping_parent_or_child(self):
        calls = self.scenario(r'''
$script:Workers = @([pscustomobject]@{ Name='python.exe'; ProcessId=987654323 })
''', 'worker xu ly du lieu')
        self.assertEqual(calls, ['compile'])

    def test_changed_process_snapshot_blocks_restart(self):
        calls = self.scenario(r'''
function Invoke-LottoCompile($Root, $Compiler, $Build) {
    $script:Calls.Add('compile'); $script:Owner.Created = 'different-process-same-pid'
    $script:Owner = [pscustomobject]@{ ProcessId=987654321; Name='java.exe'; CommandLine='java -cp changed-build LottoWebServer'; Created='new-time' }
}
''', 'PID/lenh server')
        self.assertEqual(calls, ['compile'])

    def test_successful_restart_compiles_before_stop_then_starts_hidden_helper(self):
        calls = self.scenario('')
        self.assertEqual(calls, ['compile', 'stop', 'start', 'ready', 'browser'])

    def test_pid_reuse_after_cim_snapshot_is_never_stopped(self):
        calls = self.scenario(r'''
function Get-Process {
    param($Id, $ErrorAction)
    [pscustomobject]@{ Id=$Id; StartTime=([datetime]'2026-10-23T02:00:00Z') }
}
''', 'PID/start time')
        self.assertEqual(calls, ['compile'])

    def test_cim_microsecond_precision_does_not_block_same_process(self):
        calls = self.scenario(r'''
function Get-Process {
    param($Id, $ErrorAction)
    $p = [pscustomobject]@{ Id=$Id; StartTime=[datetime]::new(([long]$script:Owner.Created + 9), [DateTimeKind]::Utc) }
    $p | Add-Member -MemberType ScriptMethod -Name WaitForExit -Value { param($Timeout) $true }
    $p
}
''')
        self.assertEqual(calls, ['compile', 'stop', 'start', 'ready', 'browser'])

    def test_new_worker_before_stop_is_not_interrupted(self):
        calls = self.scenario(r'''
$script:ChildChecks = 0
function Get-LottoChildWorkers($ProcessId) {
    $script:ChildChecks++
    if ($script:ChildChecks -ge 2) { [pscustomobject]@{ Name='python.exe'; ProcessId=987654323 } }
}
''', 'vua tao worker')
        self.assertEqual(calls, ['compile'])

    def test_mismatched_java_and_compiler_are_rejected(self):
        calls = self.scenario(r'''
$Compiler = Join-Path $Root 'other JDK/javac.exe'
[void][System.IO.Directory]::CreateDirectory((Split-Path -Parent $Compiler))
Set-Content -LiteralPath $Compiler -Value ''
''', 'cung mot JDK')
        self.assertEqual(calls, [])

    def test_auto_reuses_server_without_compile_or_stop(self):
        self.assertEqual(self.scenario('', automatic=True), ['browser'])

    def test_auto_can_reuse_hidden_java_command_only_with_page_fingerprint(self):
        calls = self.scenario(r'''
$script:Owner.CommandLine = ''
function Test-LottoPage { $true }
''', automatic=True)
        self.assertEqual(calls, ['browser'])

    def test_auto_rejects_hidden_java_command_without_page_fingerprint(self):
        calls = self.scenario(r'''
$script:Owner.CommandLine = ''
function Test-LottoPage { $false }
''', 'process khac su dung', automatic=True)
        self.assertEqual(calls, [])

    def test_page_fingerprint_never_authorizes_manual_stop(self):
        calls = self.scenario(r'''
$script:Owner.CommandLine = ''
function Test-LottoPage { $true }
''', 'process khac su dung')
        self.assertEqual(calls, [])

    def test_port_taken_during_compile_does_not_stop_new_owner(self):
        calls = self.scenario(r'''
$script:Owner = $null
function Invoke-LottoCompile($Root, $Compiler, $Build) {
    $script:Calls.Add('compile')
    $script:Owner = [pscustomobject]@{ ProcessId=987654324; Name='other.exe'; CommandLine='other'; Created='new' }
}
''', 'trong luc bien dich')
        self.assertEqual(calls, ['compile'])

    def test_unknown_listener_is_never_stopped(self):
        calls = self.scenario("$script:Owner.CommandLine = 'java OtherServer'", 'process khac su dung')
        self.assertEqual(calls, [])

    def test_real_start_uses_hidden_window_and_root_relative_classpath(self):
        calls = self.scenario(r'''
function Start-Process {
    param($FilePath, $ArgumentList, $WorkingDirectory, $WindowStyle, [switch]$PassThru,
          $RedirectStandardOutput, $RedirectStandardError)
    if ($WindowStyle -ne 'Hidden' -or $WorkingDirectory -ne $Root -or
        $ArgumentList[2] -notlike 'runtime/build_launcher_*;backend/lib/sqlite-jdbc-3.51.2.0.jar' -or
        -not $RedirectStandardOutput.EndsWith('_stdout.log') -or
        -not $RedirectStandardError.EndsWith('_stderr.log')) { throw 'invalid-start-arguments' }
    $script:Calls.Add('start-hidden')
    [pscustomobject]@{ Id=987654322; HasExited=$false }
}
function Start-LottoJava($Root, $Executable, $Build, $LogStem) {
    & $script:RealStart $Root $Executable $Build $LogStem
}
''')
        self.assertEqual(calls, ['compile', 'stop', 'start-hidden', 'ready', 'browser'])


if __name__ == '__main__':
    unittest.main()
