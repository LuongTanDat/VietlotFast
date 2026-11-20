"""Real browser downloads a complete PNG, including rows outside the viewport."""
import io
import json
import math
import struct
import time
import unittest
from pathlib import Path
from PIL import Image

from tests import test_analysis_frequency_web as frequency
from tests.browser_cdp import Browser
from tests.test_prize_web import ROOT, CHROME


@unittest.skipUnless(Path(CHROME).exists(), 'Chrome required')
class AnalysisCaptureWebTests(unittest.TestCase):
    setUpClass = classmethod(frequency.AnalysisFrequencyWebTests.setUpClass.__func__)
    tearDownClass = classmethod(frequency.AnalysisFrequencyWebTests.tearDownClass.__func__)
    start_server = classmethod(frequency.AnalysisFrequencyWebTests.start_server.__func__)
    request = classmethod(frequency.AnalysisFrequencyWebTests.request.__func__)
    login = classmethod(frequency.AnalysisFrequencyWebTests.login.__func__)

    def test_full_png_download_theme_mobile_failure_and_cancel(self):
        browser = Browser(CHROME, self.work / 'analysis-capture-browser')
        self.addCleanup(browser.close)
        output = ROOT / 'runtime/logs/prediction_bao_six_20261118'
        output.mkdir(parents=True, exist_ok=True)
        downloads = self.work / 'downloads'
        downloads.mkdir()
        browser.call('Browser.setDownloadBehavior', dict(behavior='allow', downloadPath=str(downloads)))
        browser.call('Network.enable', page=True)
        browser.call('Network.setCookie', dict(name='LOTTO_AUTH', value=self.admin.split(';')[0].split('=', 1)[1], url=self.url), page=True)
        browser.call('Emulation.setDeviceMetricsOverride', dict(width=1440, height=900, deviceScaleFactor=1, mobile=False), page=True)
        browser.call('Page.navigate', dict(url=self.url + '/'), page=True)

        def wait(expression):
            for _ in range(600):
                if browser.value(expression):
                    return
                time.sleep(.05)
            self.fail('Capture timeout: ' + expression + '; ' + str(browser.value("document.getElementById('analysisCaptureStatus')?.textContent")))

        wait("typeof currentUser==='string' && currentUser==='owner_fixture' && document.getElementById('appShell').style.display==='block'")
        self.assertTrue(browser.value("document.getElementById('analysisCaptureBtn').disabled"))
        browser.value("document.getElementById('predictModeAnalysisTab').click()")
        wait("!analysisState.loading && !!document.querySelector('[data-frequency-group=main]')")
        self.assertFalse(browser.value("document.getElementById('analysisCaptureBtn').disabled"))
        self.assertTrue(browser.value("document.getElementById('analysisCaptureBtn').getBoundingClientRect().right<=document.getElementById('analysisRefreshBtn').getBoundingClientRect().left"))
        for group, numbers in [('main', range(1, 10)), ('special', [1, 2])]:
            for number in numbers:
                browser.value(f"document.querySelector('[data-pick-group={group}][data-frequency-pick=\"{number:02d}\"]').click()")
        browser.value("document.getElementById('analysisPredictSelectedBtn').click();document.getElementById('analysisPredictionCountConfirm').click()")
        saved = browser.value("JSON.stringify({marks:analysisState.marksByType,tickets:analysisState.predictionTickets})")
        browser.value("window.captureCreateUrl=URL.createObjectURL;window.captureBlobs=[];window.captureApi=0;window.captureFetch=fetch;window.fetch=(...args)=>{if(String(args[0]).includes('/api/analysis?'))captureApi++;return captureFetch(...args)};URL.createObjectURL=function(blob){if(blob.type==='image/png'){const doc=document.querySelector('iframe[aria-hidden=true]').contentDocument,root=doc.getElementById('predictRootAnalysis');const rr=root.getBoundingClientRect(),anchors=[root.querySelector('[data-frequency-group=main] tbody tr:last-child th'),[...root.querySelectorAll('.frequency-ticket')].at(-1).querySelector('.frequency-ticket-number:last-child')].map(el=>{const r=el.getBoundingClientRect();return {x:r.x-rr.x,y:r.y-rr.y,width:r.width,height:r.height}});captureBlobs.push({anchors,selectedCount:doc.getElementById('analysisDrawCountSelect').textContent,width:root.getBoundingClientRect().width,height:root.getBoundingClientRect().height,rows:root.querySelectorAll('[data-frequency-group=main] tbody tr').length,specialRows:root.querySelectorAll('[data-frequency-group=special] tbody tr').length,tickets:root.querySelectorAll('.frequency-ticket').length,text:root.textContent,size:blob.size,background:getComputedStyle(root).backgroundColor});}return captureCreateUrl.call(URL,blob)}")
        metadata = []
        for index, (width, theme, quantity, visible, mode) in enumerate([(1440, 'dark', 5, 5, 'normal'), (390, 'light', 5, 5, 'normal'), (1440, 'dark', 42, 6, 'normal'), (390, 'light', 42, 6, 'bao')], 1):
            if mode == 'bao':
                browser.value("document.getElementById('analysisPredictionMode').value='bao';document.getElementById('analysisPredictionMode').dispatchEvent(new Event('change'))")
            if quantity != 5:
                browser.value(f"document.getElementById('analysisPredictSelectedBtn').click();document.getElementById('analysisPredictionCountInput').value='{quantity}';document.getElementById('analysisPredictionCountInput').dispatchEvent(new Event('input'));document.getElementById('analysisPredictionCountConfirm').click()")
                saved = browser.value("JSON.stringify({marks:analysisState.marksByType,tickets:analysisState.predictionTickets})")
            browser.call('Emulation.setDeviceMetricsOverride', dict(width=width, height=850, deviceScaleFactor=1, mobile=width < 500), page=True)
            browser.value(f"document.body.classList.toggle('light-theme',{str(theme=='light').lower()});document.querySelector('.frequency-table-wrap').scrollLeft=200;document.getElementById('analysisCaptureBtn').click();document.getElementById('analysisCaptureBtn').click()")
            wait("!analysisState.captureBusy && document.getElementById('analysisCaptureStatus').textContent.startsWith('Đã tải ảnh:')")
            self.assertEqual(browser.value('captureBlobs.length'), index)
            meta = browser.value('captureBlobs[captureBlobs.length-1]')
            self.assertEqual((meta['rows'], meta['specialRows'], meta['tickets']), (35, 12, visible))
            if quantity == 42:
                self.assertIn('42 bộ', meta['text'])
                self.assertIn('Trang 1 / 7', meta['text'])
            if mode == 'bao':
                self.assertIn('Bao 6 · Bộ 06', meta['text'])
            self.assertEqual(meta['width'], 1440)
            self.assertGreater(meta['height'], 850)
            self.assertIn('Loto_5/35', meta['text'])
            self.assertIn('30 kỳ', meta['text'])
            self.assertIn('Tổng', meta['text'])
            self.assertIn('Đỏ', meta['text'])
            self.assertIn('Xanh', meta['text'])
            self.assertIn('Xám', meta['text'])
            self.assertEqual(meta['selectedCount'], '30 kỳ')
            self.assertNotIn('Đang chụp', meta['text'])
            self.assertNotIn('DVLF BANK', meta['text'])
            self.assertGreater(meta['size'], 100000)
            for _ in range(100):
                files = list(downloads.glob('*.png'))
                if len(files) == index:
                    break
                time.sleep(.05)
            self.assertEqual(len(files), index)
            newest = max(files, key=lambda path: path.stat().st_mtime_ns)
            raw = newest.read_bytes()
            (output / f'analysis-full-{theme}-{quantity}-{mode}.png').write_bytes(raw)
            self.assertEqual(raw[:8], b'\x89PNG\r\n\x1a\n')
            dimensions = struct.unpack('>II', raw[16:24])
            self.assertEqual(dimensions, (2880, math.ceil(meta['height']) * 2))
            # Verify pixels at the last row and the last ticket, not merely DOM counts.
            png = Image.open(io.BytesIO(raw)).convert('RGB')
            ink = (200, 217, 233) if theme == 'dark' else (35, 70, 102)
            for anchor in meta['anchors']:
                box = (int((anchor['x'] + 3) * 2), int((anchor['y'] + 3) * 2),
                       int((anchor['x'] + anchor['width'] - 3) * 2), int((anchor['y'] + anchor['height'] - 3) * 2))
                pixels = png.crop(box).getdata()
                self.assertGreater(sum(max(abs(c - target) for c, target in zip(pixel, ink)) < 30 for pixel in pixels), 20)
            metadata.append(dict(mode=mode,theme=theme,sourceWidth=width,pngDimensions=dimensions,**meta))
            self.assertEqual(browser.value("JSON.stringify({marks:analysisState.marksByType,tickets:analysisState.predictionTickets})"), saved)
            self.assertEqual(browser.value("document.querySelectorAll('iframe[aria-hidden=true]').length"), 0)
            self.assertFalse(browser.value("document.getElementById('analysisCaptureBtn').disabled"))
        self.assertEqual(browser.value('captureApi'), 0)
        browser.value("window.captureToBlob=HTMLCanvasElement.prototype.toBlob;HTMLCanvasElement.prototype.toBlob=function(callback){callback(null)};document.getElementById('analysisCaptureBtn').click()")
        wait("!analysisState.captureBusy && document.getElementById('analysisCaptureStatus').textContent.includes('Chưa lưu được ảnh PNG')")
        self.assertEqual(browser.value('captureBlobs.length'), 4)
        self.assertEqual(browser.value("document.querySelectorAll('iframe[aria-hidden=true]').length"), 0)
        self.assertFalse(browser.value("document.getElementById('analysisCaptureBtn').disabled"))
        browser.value("HTMLCanvasElement.prototype.toBlob=function(callback,type){window.finishCapture=()=>captureToBlob.call(this,callback,type)};document.getElementById('analysisCaptureBtn').click()")
        wait("typeof finishCapture==='function'")
        browser.value("resetAnalysisSession();finishCapture()")
        wait("document.querySelectorAll('iframe[aria-hidden=true]').length===0")
        self.assertEqual(browser.value('captureBlobs.length'), 4)
        self.assertTrue(browser.value("document.getElementById('analysisCaptureBtn').disabled"))
        self.assertTrue(browser.value("document.getElementById('analysisCaptureStatus').hidden"))
        (output / 'capture-metadata.json').write_text(json.dumps(metadata, ensure_ascii=False, indent=2), encoding='utf-8')


if __name__ == '__main__':
    unittest.main()
