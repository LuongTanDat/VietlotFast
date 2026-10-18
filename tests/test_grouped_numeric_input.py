"""Real Chrome IME events must not duplicate grouped numeric text."""
import json
import tempfile
import time
import unittest
from pathlib import Path

from tests.browser_cdp import Browser
from tests.test_prize_web import ROOT, CHROME


class GroupedNumericInputTests(unittest.TestCase):
    def test_typing_ime_commit_replacement_paste_and_limits(self):
        ids = ['tickets', 'paypal', 'diamond', 'vip', 'spins', 'quantity', 'repeat', 'account']
        fields = '<input id="tickets" value="1">' + ''.join(f'<input id="{name}" data-grouped-integer {"data-empty-zero" if name in ("paypal", "diamond", "vip", "spins") else ""} value="0">' for name in ids[1:])
        script = '''
let maximum=1000000;
const options={maximum:()=>maximum,minimum:1,rejectMalformed:false};
VietlottNumericInput.bind(document.getElementById('tickets'),options);
VietlottNumericInput.bind(document.getElementById('fields'));
// A parent delegate must not process an input event twice.
VietlottNumericInput.bind(document.body);
window.errors=[];window.addEventListener('error',e=>errors.push(e.message));window.addEventListener('unhandledrejection',e=>errors.push(String(e.reason)));
'''
        with tempfile.TemporaryDirectory(prefix='grouped_numeric_', dir=ROOT / 'runtime') as folder:
            work = Path(folder)
            page = work / 'fixture.html'
            page.write_text('<!doctype html><meta charset="utf-8"><div id="fields">' + fields + '</div><script src="' + (ROOT / 'frontend/vietlott-web-numeric.js').as_uri() + '"></script><script>' + script + '</script>', encoding='utf-8')
            b = Browser(CHROME, work / 'profile')
            try:
                b.call('Page.enable', page=True)
                b.call('Page.navigate', {'url': page.as_uri()}, page=True)
                end = time.monotonic() + 10
                while not b.value('typeof maximum!=="undefined"'):
                    self.assertLess(time.monotonic(), end)
                    time.sleep(.03)
                results = []
                for name in ids:
                    node = f'document.getElementById({json.dumps(name)})'
                    for raw in ('200000', '220000', '1000000', '0200000', '200.000'):
                        b.value(node + '.focus();' + node + '.select()')
                        for length in range(1, len(raw) + 1):
                            composing = raw[:length]
                            b.call('Input.imeSetComposition', {'text': composing, 'selectionStart': length, 'selectionEnd': length}, page=True)
                            expected = f'{int(composing.replace(".", "")):,}'.replace(',', '.')
                            self.assertEqual(b.value(node + '.value'), expected, (name, composing))
                        b.call('Input.insertText', {'text': raw}, page=True)
                        expected = f'{int(raw.replace(".", "")):,}'.replace(',', '.')
                        self.assertEqual(b.value(node + '.value'), expected, (name, 'commit', raw))
                        self.assertEqual(b.value(node + '.selectionStart'), len(expected))
                        results.append({'field': name, 'typed': raw, 'shown': expected})
                    b.value(node + '.select()')
                    b.call('Input.insertText', {'text': '200.000'}, page=True)
                    self.assertEqual(b.value(node + '.value'), '200.000')
                    b.value(node + '.setSelectionRange(0,1)')
                    b.call('Input.imeSetComposition', {'text': '3', 'selectionStart': 1, 'selectionEnd': 1}, page=True)
                    b.call('Input.insertText', {'text': '3'}, page=True)
                    self.assertEqual(b.value(node + '.value'), '300.000', (name, 'middle replacement'))
                    b.value(node + '.select()')
                    b.call('Input.insertText', {'text': '2'}, page=True)
                    for event in ('keyDown', 'keyUp'):
                        b.call('Input.dispatchKeyEvent', {'type': event, 'key': '2', 'code': 'Digit2', 'text': '2' if event == 'keyDown' else '', 'windowsVirtualKeyCode': 50}, page=True)
                    self.assertEqual(b.value(node + '.value'), '22', (name, 'intentional repeated digit'))
                for maximum in (80, 3160, 82160, 1000000):
                    b.value(f'maximum={maximum};document.getElementById("tickets").focus();document.getElementById("tickets").select()')
                    for raw in ('9', '99', '999', '9999', '99999', '9999999'):
                        b.call('Input.imeSetComposition', {'text': raw, 'selectionStart': len(raw), 'selectionEnd': len(raw)}, page=True)
                        self.assertEqual(b.value('document.getElementById("tickets").value'), f'{min(int(raw), maximum):,}'.replace(',', '.'))
                    b.call('Input.insertText', {'text': '9999999'}, page=True)
                    self.assertEqual(b.value('document.getElementById("tickets").value'), f'{maximum:,}'.replace(',', '.'))
                self.assertEqual(b.value('window.errors'), [])
                proof = {'ok': True, 'imeSequences': results, 'boundaries': [80, 3160, 82160, 1000000], 'intentionalRepeatedDigitsPreserved': True}
                (ROOT / 'Bin/session_1_latest/numeric_ime_unified_verification.json').write_text(json.dumps(proof, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            finally:
                b.close()
