import json
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.test_web_launcher import ROOT, POWERSHELL


@unittest.skipUnless(POWERSHELL, 'PowerShell required')
class RecoveredPortTests(unittest.TestCase):
    def check(self, endpoints, failure=False):
        with tempfile.TemporaryDirectory(prefix='lotto-port-test-') as directory:
            script = Path(directory) / 'port.ps1'
            body = '''param($Helper)
. $Helper -LibraryOnly
function Get-CimInstance {
    param($Namespace, $ClassName, $Filter, $ErrorAction)
    if ($ClassName -eq 'MSFT_NetTCPConnection') {
        ENDPOINTS
    } else {
        [pscustomobject]@{ ProcessId=42; Name='java.exe'; CommandLine='java LottoWebServer'; CreationDate=[datetime]'2026-11-01T00:00:00Z' }
    }
}
try { $p = Get-LottoPortOwner; [pscustomobject]@{id=$p.ProcessId;error=''} | ConvertTo-Json -Compress }
catch { [pscustomobject]@{id=$null;error=$_.Exception.Message} | ConvertTo-Json -Compress }
'''.replace('ENDPOINTS', "throw 'query failed'" if failure else endpoints)
            script.write_text(body, encoding='utf-8')
            result = subprocess.run([POWERSHELL, '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', str(script),
                                     '-Helper', str(ROOT / 'scripts/start_lotto_web.ps1')], capture_output=True,
                                    text=True, encoding='utf-8', timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            return json.loads(result.stdout.strip().splitlines()[-1])

    def test_state_zero_bound_socket_is_found(self):
        self.assertEqual(self.check("[pscustomobject]@{LocalPort=8080;RemotePort=0;RemoteAddress='0.0.0.0';OwningProcess=42;State=0}")['id'], 42)

    def test_null_state_bound_socket_is_found(self):
        self.assertEqual(self.check("[pscustomobject]@{RemotePort=0;RemoteAddress='::';OwningProcess=42;State=$null}")['id'], 42)

    def test_same_owner_ipv4_ipv6_is_deduplicated(self):
        self.assertEqual(self.check("[pscustomobject]@{RemotePort=0;RemoteAddress='0.0.0.0';OwningProcess=42};[pscustomobject]@{RemotePort=0;RemoteAddress='::';OwningProcess=42}")['id'], 42)

    def test_multiple_owners_fail_closed(self):
        self.assertTrue(self.check("[pscustomobject]@{RemotePort=0;RemoteAddress='0.0.0.0';OwningProcess=42};[pscustomobject]@{RemotePort=0;RemoteAddress='::';OwningProcess=43}")['error'])

    def test_connection_with_remote_port_is_ignored(self):
        self.assertIsNone(self.check("[pscustomobject]@{RemotePort=1234;RemoteAddress='127.0.0.1';OwningProcess=42}")['id'])

    def test_query_failure_is_not_treated_as_free_port(self):
        self.assertTrue(self.check('', True)['error'])

    def test_empty_query_means_free_port(self):
        self.assertIsNone(self.check('$null')['id'])
