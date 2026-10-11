"""Authenticated Java/Python bridge and full UI, using a disposable project/DB."""
import json
import csv
import hashlib
import os
import random
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import time
import unittest
import urllib.error
import urllib.parse
import urllib.request
from contextlib import closing, contextmanager
from pathlib import Path
from datetime import date, datetime, timedelta, timezone

from tests.test_prize_web import ROOT, JAVA, JAVAC, CHROME


@unittest.skipUnless(Path(JAVAC).exists() and Path(JAVA).exists(), 'JDK required')
class EffectivenessWebTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix='effectiveness-http-', dir=ROOT / 'runtime')
        cls.work = Path(cls.temp.name)
        (cls.work / 'runtime').mkdir()
        shutil.copytree(ROOT / 'frontend', cls.work / 'frontend')
        shutil.copytree(ROOT / 'ai', cls.work / 'ai',
                        ignore=shutil.ignore_patterns('__pycache__', 'models', 'standalone_predictors', 'predictors'))
        shutil.copytree(ROOT / 'backend', cls.work / 'backend',
                        ignore=shutil.ignore_patterns('__pycache__', 'bin', 'lib', '*.java', 'live_results.py'))
        shutil.copy2(ROOT / 'backend/lib/sqlite-jdbc-3.51.2.0.jar', cls.work / 'sqlite-jdbc.jar')
        (cls.work / 'build').mkdir()
        compilation = subprocess.run([JAVAC, '-encoding', 'UTF-8', '-d',
                                      str((cls.work / 'build').relative_to(ROOT)),
                                      'backend/LottoWebServer.java'], cwd=ROOT, capture_output=True)
        if compilation.returncode:
            cls.temp.cleanup()
            raise AssertionError(compilation.stderr.decode(errors='replace'))
        with socket.socket() as sock:
            sock.bind(('127.0.0.1', 0))
            port = sock.getsockname()[1]
        cls.url = f'http://127.0.0.1:{port}'
        cls.log = (cls.work / 'server.log').open('wb')
        cls.server = subprocess.Popen([JAVA, '-Dfile.encoding=UTF-8', f'-Dlotto.port={port}',
                                      '-Dlotto.effectivenessWorker=false', '-cp',
                                      'build' + os.pathsep + 'sqlite-jdbc.jar', 'LottoWebServer'],
                                     cwd=cls.work, stdout=cls.log, stderr=subprocess.STDOUT,
                                     creationflags=0x08000000 if os.name == 'nt' else 0)
        for _ in range(100):
            try:
                urllib.request.urlopen(cls.url + '/api/time', timeout=1).close()
                break
            except (OSError, urllib.error.URLError):
                time.sleep(.05)
        else:
            cls.tearDownClass()
            raise AssertionError('Disposable server failed to start')
        for user in ('owner_fixture', 'member_fixture'):
            code, _, _ = cls.request('/api/register', {'username': user, 'password': 'fixture_password'})
            if code != 200:
                cls.tearDownClass()
                raise AssertionError('Fixture registration failed')
        _, _, headers = cls.request('/api/login', {'username': 'owner_fixture', 'password': 'fixture_password'})
        cls.admin = headers['Set-Cookie']
        _, _, headers = cls.request('/api/login', {'username': 'member_fixture', 'password': 'fixture_password'})
        cls.member = headers['Set-Cookie']

    @classmethod
    def tearDownClass(cls):
        cls.server.terminate()
        cls.server.wait(timeout=10)
        cls.log.close()
        cls.temp.cleanup()

    @classmethod
    def request(cls, path, form=None, cookie=None, method=None, origin=None):
        data = urllib.parse.urlencode(form).encode() if form is not None else None
        headers = {'Content-Type': 'application/x-www-form-urlencoded'}
        if cookie:
            headers['Cookie'] = cookie
        if origin:
            headers['Origin'] = origin
        request = urllib.request.Request(cls.url + path, data=data, headers=headers, method=method)
        try:
            response = urllib.request.urlopen(request, timeout=30)
        except urllib.error.HTTPError as error:
            response = error
        with response:
            raw = response.read()
            try:
                payload = json.loads(raw)
            except ValueError:
                payload = raw.decode('utf-8')
            return response.status, payload, response.headers

    @classmethod
    def restart_server(cls):
        """Discard all Java memory and sessions while keeping the disposable DB."""
        cls.server.terminate()
        cls.server.wait(timeout=10)
        port = urllib.parse.urlparse(cls.url).port
        cls.server = subprocess.Popen([JAVA, '-Dfile.encoding=UTF-8', f'-Dlotto.port={port}',
                                      '-Dlotto.effectivenessWorker=false', '-cp',
                                      'build' + os.pathsep + 'sqlite-jdbc.jar', 'LottoWebServer'],
                                     cwd=cls.work, stdout=cls.log, stderr=subprocess.STDOUT,
                                     creationflags=0x08000000 if os.name == 'nt' else 0)
        for _ in range(100):
            try:
                urllib.request.urlopen(cls.url + '/api/time', timeout=1).close()
                break
            except OSError:
                time.sleep(.05)
        else:
            raise AssertionError('Restarted disposable server failed to start')
        for user, attribute in (('owner_fixture', 'admin'), ('member_fixture', 'member')):
            code, _, headers = cls.request('/api/login', {'username': user, 'password': 'fixture_password'})
            if code != 200:
                raise AssertionError('Fixture re-login failed')
            setattr(cls, attribute, headers['Set-Cookie'])

    def test_music_asset_ranges_and_cache(self):
        expected = (ROOT / 'frontend/Music_V1.mp3').read_bytes()
        def fetch(headers=None, method='GET', path='/Music_V1.mp3'):
            request = urllib.request.Request(self.url + path, headers=headers or {}, method=method)
            try:
                response = urllib.request.urlopen(request, timeout=10)
            except urllib.error.HTTPError as error:
                response = error
            with response:
                return response.status, response.read(), response.headers
        code, body, headers = fetch()
        self.assertEqual(code, 200)
        self.assertEqual(body, expected)
        self.assertEqual(headers['Content-Type'], 'audio/mpeg')
        self.assertEqual(headers['Accept-Ranges'], 'bytes')
        self.assertIsNone(headers.get('Content-Encoding'))
        for value, part, start in [('bytes=0-1023',expected[:1024],0),
                                   ('bytes=100-',expected[100:],100),
                                   ('bytes=-32',expected[-32:],len(expected)-32),
                                   ('bytes=10-999999999',expected[10:],10)]:
            code, body, ranged = fetch({'Range':value})
            self.assertEqual(code, 206)
            self.assertEqual(body, part)
            self.assertEqual(ranged['Content-Range'], f'bytes {start}-{start+len(part)-1}/{len(expected)}')
        for value in ['bytes=999999999-','bytes=20-10','bytes=-0','bytes=0-1,5-6','bytes=','invalid']:
            self.assertEqual(fetch({'Range':value})[0], 416)
        self.assertEqual(fetch({'If-None-Match':headers['ETag']})[0], 304)
        self.assertEqual(fetch({'Range':'bytes=0-9','If-Range':'wrong'})[:2], (200,expected))
        code, body, head = fetch(method='HEAD')
        self.assertEqual((code,body),(200,b''))
        self.assertEqual(int(head['Content-Length']),len(expected))
        self.assertEqual(fetch(method='POST')[0],405)
        self.assertEqual(fetch(path='/Music_V1.mp3/other')[0],404)
        self.assertEqual(fetch(path='/vietlott-web-music.js')[0],200)

    @unittest.skipUnless(Path(CHROME).exists(), 'Chrome required')
    def test_music_login_continuity_controls_reload_and_autoplay_fallback(self):
        from tests.browser_cdp import Browser
        browser = Browser(CHROME, self.work / 'chrome-music-profile')
        def wait(expression):
            for _ in range(220):
                if browser.value(expression):
                    return
                time.sleep(.05)
            state = browser.value("JSON.stringify({status:document.getElementById('backgroundMusicStatus').textContent,auth:document.getElementById('authMsg').textContent,app:document.getElementById('appShell').style.display,paused:document.getElementById('backgroundMusic').paused,enabled:localStorage.getItem('dvlf.music.enabled'),rejectNext:window.rejectNextMusicPlay,errors:window.musicErrors})")
            self.fail('Music condition not reached: ' + expression + '\n' + state)
        def gesture(expression):
            result = browser.call('Runtime.evaluate', {'expression':expression,'userGesture':True,'returnByValue':True},page=True)
            self.assertNotIn('exceptionDetails', result)
        def open_settings():
            gesture("if(document.getElementById('settingsPanel').hidden)document.getElementById('settingsBtn').click()")
        def toggle_music():
            open_settings()
            self.assertTrue(browser.value("document.getElementById('backgroundMusicToggle').getBoundingClientRect().width>0"))
            gesture("document.getElementById('backgroundMusicToggle').click()")
        try:
            browser.call('Page.enable', page=True)
            browser.call('Page.addScriptToEvaluateOnNewDocument', {'source':"""
                window.musicErrors=[]; window.rejectNextMusicPlay=false;
                window.addEventListener('unhandledrejection',e=>musicErrors.push(String(e.reason)));
                const nativePlay=HTMLMediaElement.prototype.play;
                HTMLMediaElement.prototype.play=function(){
                    if(this.id==='backgroundMusic'&&window.rejectNextMusicPlay){
                        window.rejectNextMusicPlay=false;
                        return Promise.reject(new DOMException('Fixture autoplay blocked','NotAllowedError'));
                    }
                    return nativePlay.call(this);
                };
            """}, page=True)
            browser.call('Page.navigate',{'url':self.url+'/'},page=True)
            wait("!!document.getElementById('backgroundMusicToggle')&&document.getElementById('pageLoader').classList.contains('hide')")
            self.assertTrue(browser.value("document.getElementById('backgroundMusic').paused&&!document.getElementById('backgroundMusic').getAttribute('src')"))
            browser.value("document.getElementById('loginUser').value='owner_fixture';document.getElementById('loginPass').value='wrong_password'")
            gesture("document.getElementById('loginBtn').click()")
            wait("document.getElementById('authMsg').textContent.includes('Sai')")
            self.assertTrue(browser.value("document.getElementById('backgroundMusic').paused&&!document.getElementById('backgroundMusic').getAttribute('src')"))
            browser.value("document.getElementById('loginPass').value='fixture_password'")
            gesture("document.getElementById('loginBtn').click()")
            wait("document.getElementById('appShell').style.display==='block'&&!document.getElementById('backgroundMusic').paused&&document.getElementById('backgroundMusic').currentTime>.1")
            self.assertTrue(browser.value("document.getElementById('backgroundMusic').loop"))
            self.assertEqual(browser.value("document.getElementById('backgroundMusic').volume"), .25)
            browser.value("document.getElementById('backgroundMusic').currentTime=document.getElementById('backgroundMusic').duration-.2")
            wait("document.getElementById('backgroundMusic').currentTime<2&&!document.getElementById('backgroundMusic').paused")
            browser.value("window.originalMusic=document.getElementById('backgroundMusic');originalMusic.currentTime=3;window.musicTime=originalMusic.currentTime")
            # Switching app sections keeps the same media element and clock.
            browser.value("document.querySelector('[data-predict-mode-tab=effectiveness]').click()")
            time.sleep(.15)
            self.assertTrue(browser.value("document.getElementById('backgroundMusic')===originalMusic&&!originalMusic.paused&&originalMusic.currentTime>=musicTime"))
            browser.value("window.dispatchEvent(new CustomEvent('dvlf:auth-changed',{detail:{authenticated:true,user:'owner_fixture'}}))")
            self.assertTrue(browser.value("originalMusic.currentTime>=musicTime&&!originalMusic.paused"))
            toggle_music()
            self.assertTrue(browser.value("originalMusic.paused&&localStorage.getItem('dvlf.music.enabled')==='off'"))
            self.assertTrue(browser.value("(()=>{const b=document.getElementById('backgroundMusicToggle');return b.closest('.background-music-controls')&&b.closest('#settingsPanel')&&b.getAttribute('aria-pressed')==='false'&&getComputedStyle(b.querySelector('.background-music-slash')).display!=='none'})()"))
            browser.value("window.dispatchEvent(new CustomEvent('dvlf:auth-changed',{detail:{authenticated:true}}))")
            self.assertTrue(browser.value("originalMusic.paused"))
            toggle_music()
            wait("!originalMusic.paused")
            self.assertTrue(browser.value("getComputedStyle(document.querySelector('.background-music-slash')).display==='none'"))
            browser.value("const slider=document.getElementById('backgroundMusicVolume');slider.value=15;slider.dispatchEvent(new Event('input',{bubbles:true}));originalMusic.currentTime=5;window.dispatchEvent(new Event('pagehide'))")
            browser.call('Page.reload',{},page=True)
            wait("document.getElementById('appShell').style.display==='block'")
            if browser.value("document.getElementById('backgroundMusic').paused"):
                toggle_music()
            wait("document.getElementById('backgroundMusic').currentTime>=5&&!document.getElementById('backgroundMusic').paused")
            self.assertEqual(browser.value("document.getElementById('backgroundMusic').volume"), .15)
            open_settings()
            self.assertEqual(browser.value("document.querySelector('#settingsPanel .header-popover-head').textContent.trim()"), 'Setting | Cài Đặt')
            self.assertFalse(browser.value("document.getElementById('settingsPanel').textContent.includes('Tùy chỉnh nhanh')"))
            self.assertEqual(browser.value("Array.from(document.querySelectorAll('.background-music-volume-marks > span'),s=>s.textContent)"), ['0','25','50','75','100'])
            browser.value("document.getElementById('backgroundMusicVolume').value=85;document.getElementById('backgroundMusicVolume').dispatchEvent(new Event('input',{bubbles:true}));document.getElementById('backgroundMusicVolume').focus()")
            browser.call('Input.dispatchKeyEvent',{'type':'keyDown','key':'ArrowRight','code':'ArrowRight','windowsVirtualKeyCode':39},page=True)
            browser.call('Input.dispatchKeyEvent',{'type':'keyUp','key':'ArrowRight','code':'ArrowRight','windowsVirtualKeyCode':39},page=True)
            self.assertTrue(browser.value("document.getElementById('backgroundMusicVolume').value==='86'&&document.getElementById('backgroundMusic').volume===.86&&document.getElementById('backgroundMusicStatus').textContent==='Âm Lượng · 86%'"))
            browser.value("document.getElementById('backgroundMusicVolume').value=90;document.getElementById('backgroundMusicVolume').dispatchEvent(new Event('input',{bubbles:true}));document.getElementById('backgroundMusicVolume').focus()")
            self.assertTrue(browser.value("document.getElementById('backgroundMusicStatus').textContent==='Âm Lượng · 90%'&&document.getElementById('backgroundMusicVolume').getAttribute('aria-valuetext')==='90%'&&document.getElementById('backgroundMusicVolume').style.getPropertyValue('--music-volume')==='90%'"))
            for width in (320,390,1440):
                browser.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':900,'deviceScaleFactor':1,'mobile':width<500},page=True)
                self.assertTrue(browser.value('document.documentElement.scrollWidth<=innerWidth+2'))
                self.assertTrue(browser.value("(()=>{const r=document.getElementById('backgroundMusicToggle').getBoundingClientRect();return r.left>=0&&r.right<=innerWidth})()"))
                for theme in ('dark','light'):
                    browser.value(f"document.body.classList.toggle('light-theme',{str(theme=='light').lower()})")
                    self.assertTrue(browser.value("(()=>{const rect=e=>e.getBoundingClientRect(),b=rect(document.getElementById('backgroundMusicToggle')),s=rect(document.getElementById('backgroundMusicVolume')),label=rect(document.querySelector('.background-music-controls strong')),status=rect(document.getElementById('backgroundMusicStatus')),t=rect(document.getElementById('themeToggleBtn')),center=r=>r.top+r.height/2;return s.width>200&&s.top>=b.bottom&&Math.abs(center(label)-center(status))<2&&Math.abs(center(label)-center(b))<2&&Math.abs(b.right-t.right)<2&&status.right<=b.left})()"), f'Music heading alignment: {width}px {theme}')
                    self.assertTrue(browser.value("(()=>{const r=document.getElementById('settingsPanel').getBoundingClientRect();return r.left>=-1&&r.right<=innerWidth+1})()"))
                    self.assertTrue(browser.value("(()=>{const rect=e=>e.getBoundingClientRect(),s=document.getElementById('backgroundMusicVolume'),label=rect(document.querySelector('.background-music-controls strong')),status=rect(document.getElementById('backgroundMusicStatus')),themeStatus=rect(document.querySelector('.header-setting-row > .header-theme-label span')),panel=rect(document.getElementById('settingsPanel'));return rect(s).height===20&&getComputedStyle(s).boxShadow==='none'&&status.left-label.right>=8&&Math.abs(themeStatus.left-status.left)<2&&panel.height<260&&panel.width<=262&&rect(document.getElementById('backgroundMusicToggle')).height===32&&rect(document.getElementById('themeToggleBtn')).height===32})()"), f'Compact music control: {width}px {theme}')
                    self.assertTrue(browser.value("(()=>{const rect=id=>document.getElementById(id).getBoundingClientRect(),t=rect('themeToggleBtn'),m=rect('backgroundMusicToggle'),s=document.querySelector('.background-music-volume-control').getBoundingClientRect(),r=rect('settingsReloadBtn'),l=rect('logoutBtn');return m.top-t.bottom<=4&&s.top-m.bottom===0&&r.top-s.bottom<=2&&l.top-r.bottom<=4&&r.top>=s.bottom&&l.top>=r.bottom})()"), f'Settings gaps: {width}px {theme}')
                    self.assertTrue(browser.value("(()=>{const r=document.querySelector('.background-music-volume-marks').getBoundingClientRect(),spans=Array.from(document.querySelectorAll('.background-music-volume-marks > span')),values=[0,.25,.5,.75,1];return spans.every((s,i)=>{const b=s.getBoundingClientRect();return Math.abs((b.left+b.width/2)-(r.left+r.width*values[i]))<1})})()"), f'Volume marks: {width}px {theme}')
                    artifacts=os.environ.get('LOTTO_MUSIC_ARTIFACT_DIR')
                    if artifacts:
                        import base64
                        output=Path(artifacts).resolve(); self.assertTrue(output.is_relative_to(ROOT.resolve())); output.mkdir(parents=True,exist_ok=True)
                        browser.value("document.getElementById('settingsPanel').setAttribute('data-music-fixture','Tài khoản kiểm thử');if(!document.getElementById('musicFixtureStyle')){const s=document.createElement('style');s.id='musicFixtureStyle';s.textContent='[data-music-fixture]::before{content:attr(data-music-fixture);display:block;padding:8px;font-size:10px;color:#789}';document.head.append(s)}")
                        clip=browser.value("({x:0,y:0,width:innerWidth,height:Math.ceil(document.getElementById('settingsPanel').getBoundingClientRect().bottom+12),scale:1})")
                        shot=browser.call('Page.captureScreenshot',{'format':'png','clip':clip,'captureBeyondViewport':True},page=True)
                        (output/f'fixture_music_controls_{theme}_{width}.png').write_bytes(base64.b64decode(shot['data']))
            browser.value("window.confirm=()=>true")
            gesture("document.getElementById('logoutBtn').click()")
            wait("document.getElementById('appShell').style.display==='none'")
            self.assertTrue(browser.value("document.getElementById('backgroundMusic').paused"))
            browser.value("window.rejectNextMusicPlay=true;document.getElementById('loginUser').value='owner_fixture';document.getElementById('loginPass').value='fixture_password'")
            gesture("document.getElementById('loginBtn').click()")
            wait("document.getElementById('backgroundMusicStatus').textContent.includes('Bấm ♫')")
            self.assertTrue(browser.value("document.getElementById('backgroundMusic').paused"))
            toggle_music()
            wait("!document.getElementById('backgroundMusic').paused")
            self.assertEqual(browser.value('musicErrors'),[])
            self.assertFalse(browser.value("!!document.getElementById('bootErrorBanner')"))
        finally:
            browser.close()
            time.sleep(.3)

    @unittest.skipUnless(Path(CHROME).exists(), 'Chrome required')
    def test_notifications_preview_paging_read_only_deletion_and_history(self):
        from tests.browser_cdp import Browser
        browser = Browser(CHROME, self.work / 'chrome-notifications-profile')
        def wait(expression):
            for _ in range(200):
                if browser.value(expression):
                    return
                time.sleep(.05)
            self.fail('Notification condition not reached: ' + expression)
        def rows():
            return browser.value("Array.from(document.querySelectorAll('#notificationList .header-notification-item'),r=>r.dataset.notificationId)")
        def click(element_id):
            browser.value(f"document.getElementById('{element_id}').click()")
        try:
            browser.call('Page.enable', page=True)
            browser.call('Page.addScriptToEvaluateOnNewDocument', {'source': """
                localStorage.setItem('dvlf.music.enabled','off');
                window.notificationErrors=[];
                window.addEventListener('unhandledrejection',e=>notificationErrors.push(String(e.reason)));
            """}, page=True)
            browser.call('Page.navigate', {'url':self.url+'/'}, page=True)
            wait("document.getElementById('pageLoader').classList.contains('hide')")
            browser.value("document.getElementById('loginUser').value='owner_fixture';document.getElementById('loginPass').value='fixture_password';document.getElementById('loginBtn').click()")
            wait("document.getElementById('appShell').style.display==='block'")
            # Disposable account and browser only: seed a history longer than two pages.
            browser.value("""
                stopLiveAutoSync();liveResultsState={};
                store.predictionLogs=Object.fromEntries(PREDICTION_LOG_TYPES.map(t=>[t,[]]));
                window.notificationBase=Date.now()-100000;
                window.notificationFixture=Array.from({length:25},(_,i)=>({id:'fixture:'+i,kind:i%2?'prediction':'live',title:i===7?'<img src=x onerror=alert(1)>':'Tin kiểm thử '+i,detail:'Thông báo số '+i,timestamp:notificationBase+i*1000}));
                writeHeaderNotificationValue(HEADER_NOTIFICATION_HISTORY_KEY,notificationFixture);
                writeHeaderNotificationValue(HEADER_NOTIFICATION_READ_KEY,['fixture:23']);
                writeHeaderNotificationValue(HEADER_NOTIFICATION_DISMISSED_KEY,[]);
                renderHeaderNotifications();
            """)
            browser.value("writeHeaderNotificationValue(HEADER_NOTIFICATION_HISTORY_KEY,Array.from({length:210},(_,i)=>({id:'unread:'+i,kind:'live',title:'Tin chưa đọc '+i,detail:'Giữ lại',timestamp:notificationBase+i*1000})));renderHeaderNotifications()")
            self.assertEqual(browser.value('collectHeaderNotifications().length'),210)
            browser.value("writeHeaderNotificationValue(HEADER_NOTIFICATION_HISTORY_KEY,notificationFixture);renderHeaderNotifications()")
            click('notificationBtn')
            self.assertEqual(rows(), [f'fixture:{i}' for i in range(24,19,-1)])
            self.assertTrue(browser.value("document.getElementById('notificationPager').hidden"))
            self.assertEqual(browser.value("document.querySelectorAll('#notificationList .header-notification-check').length"),1)
            self.assertEqual(browser.value("document.querySelectorAll('#notificationList .header-notification-remove').length"),1)
            self.assertTrue(browser.value("Array.from(document.querySelectorAll('#notificationList .header-notification-item:not(.is-read)')).every(r=>!r.querySelector('.header-notification-remove'))"))
            # The deletion function enforces the read condition even if called directly.
            browser.value("dismissReadHeaderNotifications('fixture:24')")
            self.assertEqual(browser.value('collectHeaderNotifications().length'),25)
            browser.value("document.querySelector('[data-notification-id=\"fixture:24\"] .header-notification-content').click()")
            self.assertEqual(browser.value("document.querySelector('[data-notification-id=\"fixture:24\"] .header-notification-check').textContent"),'✓')
            browser.value("document.querySelector('[data-notification-id=\"fixture:24\"] .header-notification-remove').click()")
            self.assertEqual(browser.value('collectHeaderNotifications().length'),24)
            click('notificationClearBtn')
            self.assertEqual(browser.value('collectHeaderNotifications().length'),23)
            self.assertTrue(browser.value("document.getElementById('notificationClearBtn').disabled"))
            self.assertTrue(browser.value("getDismissedHeaderNotificationIds().has('fixture:23')&&getDismissedHeaderNotificationIds().has('fixture:24')&&!getDismissedHeaderNotificationIds().has('fixture:22')"))
            click('notificationMoreBtn')
            self.assertEqual(rows(),[f'fixture:{i}' for i in range(22,12,-1)])
            self.assertTrue(browser.value("document.getElementById('notificationPrevBtn').disabled"))
            click('notificationNextBtn')
            self.assertEqual(rows(),[f'fixture:{i}' for i in range(12,2,-1)])
            self.assertFalse(browser.value("!!document.querySelector('#notificationList img')"))
            click('notificationNextBtn')
            self.assertEqual(rows(),['fixture:2','fixture:1','fixture:0'])
            self.assertTrue(browser.value("document.getElementById('notificationNextBtn').disabled"))
            # Mark only this last page, delete read notifications and clamp the page.
            click('notificationMarkReadBtn')
            self.assertEqual(browser.value("document.querySelectorAll('#notificationList .header-notification-check').length"),3)
            click('notificationClearBtn')
            self.assertEqual(browser.value('collectHeaderNotifications().length'),20)
            self.assertEqual(browser.value("document.getElementById('notificationPageLabel').textContent"),'Trang 2 / 2')
            self.assertEqual(len(rows()),10)
            self.assertTrue(browser.value("document.getElementById('notificationClearBtn').disabled"))
            click('notificationPrevBtn')
            self.assertEqual(rows(),[f'fixture:{i}' for i in range(22,12,-1)])
            click('notificationMoreBtn')
            self.assertEqual(len(rows()),5)
            click('notificationMoreBtn')
            click('notificationNextBtn')
            click('notificationBtn');click('notificationBtn')
            self.assertEqual(len(rows()),5)
            self.assertTrue(browser.value("document.getElementById('notificationPager').hidden"))
            # Read/dismiss/history storage belongs to each account, not the open tab.
            browser.value("currentUser='member_fixture';renderHeaderNotifications()")
            self.assertEqual(rows(),[])
            self.assertTrue(browser.value("document.getElementById('notificationFooter').hidden&&document.getElementById('notificationClearBtn').disabled&&document.getElementById('notificationMarkReadBtn').disabled"))
            browser.value("currentUser='owner_fixture';renderHeaderNotifications()")
            self.assertEqual(len(rows()),5)
            # If storage is full, read/delete actions still work in this browser session.
            browser.value("window.savedNotificationHistory=collectHeaderNotifications();window.savedNotificationRead=[...getReadHeaderNotificationIds()];window.savedNotificationDismissed=[...getDismissedHeaderNotificationIds()];window.originalNotificationSet=Storage.prototype.setItem;Storage.prototype.setItem=function(k,v){if(String(k).startsWith('dvlf_header_notification_'))throw new DOMException('Fixture storage full','QuotaExceededError');return originalNotificationSet.call(this,k,v)};markHeaderNotificationRead('fixture:22');renderHeaderNotifications()")
            self.assertTrue(browser.value("getReadHeaderNotificationIds().has('fixture:22')&&!!document.querySelector('[data-notification-id=\"fixture:22\"] .header-notification-check')"))
            browser.value("dismissReadHeaderNotifications('fixture:22')")
            self.assertEqual(browser.value('collectHeaderNotifications().length'),19)
            browser.value("Storage.prototype.setItem=originalNotificationSet;writeHeaderNotificationValue(HEADER_NOTIFICATION_HISTORY_KEY,savedNotificationHistory);writeHeaderNotificationValue(HEADER_NOTIFICATION_READ_KEY,savedNotificationRead);writeHeaderNotificationValue(HEADER_NOTIFICATION_DISMISSED_KEY,savedNotificationDismissed);renderHeaderNotifications()")
            self.assertEqual(browser.value('collectHeaderNotifications().length'),20)
            browser.call('Page.reload',{},page=True)
            wait("document.getElementById('appShell').style.display==='block'")
            browser.value('stopLiveAutoSync()')
            click('notificationBtn')
            self.assertEqual(browser.value('collectHeaderNotifications().length'),20)
            self.assertEqual(len(rows()),5)
            # A new live result is archived; refreshing the same draw does not duplicate it.
            browser.value("liveResultsState={KENO:{key:'KENO',ky:'#999999',date:'11/10/2026',time:'12:00',updatedAt:new Date(notificationBase+1000000).toISOString()}};renderHeaderNotifications()".replace('notificationBase','Date.now()'))
            self.assertEqual(rows()[0],'live:KENO:#999999')
            self.assertEqual(browser.value('collectHeaderNotifications().length'),21)
            browser.value("liveResultsState.KENO.updatedAt=new Date(Date.now()+2000000).toISOString();renderHeaderNotifications()")
            self.assertEqual(browser.value('collectHeaderNotifications().length'),21)
            self.assertEqual(browser.value("collectHeaderNotifications().filter(n=>n.id==='live:KENO:#999999').length"),1)
            for width in (320,390,1440):
                browser.call('Emulation.setDeviceMetricsOverride',{'width':width,'height':900,'deviceScaleFactor':1,'mobile':False},page=True)
                for theme in ('dark','light'):
                    browser.value(f"document.body.classList.toggle('light-theme',{str(theme=='light').lower()})")
                    for expanded in (False,True):
                        if browser.value("document.getElementById('notificationMoreBtn').getAttribute('aria-expanded')==='true'") != expanded:
                            click('notificationMoreBtn')
                        self.assertEqual(len(rows()),10 if expanded else 5)
                        self.assertTrue(browser.value("(()=>{const p=document.getElementById('notificationPanel'),r=p.getBoundingClientRect();return r.left>=-1&&r.right<=innerWidth+1&&r.width<=362&&r.bottom<=innerHeight+1&&p.scrollWidth<=p.clientWidth+1})()"),f'{width}px {theme} expanded={expanded}')
                        artifacts=os.environ.get('LOTTO_NOTIFICATION_ARTIFACT_DIR')
                        if artifacts:
                            import base64
                            output=Path(artifacts).resolve();self.assertTrue(output.is_relative_to(ROOT.resolve()));output.mkdir(parents=True,exist_ok=True)
                            browser.value("document.getElementById('notificationPanel').setAttribute('data-notification-fixture','Tài khoản kiểm thử');if(!document.getElementById('notificationFixtureStyle')){const s=document.createElement('style');s.id='notificationFixtureStyle';s.textContent='[data-notification-fixture]::before{content:attr(data-notification-fixture);display:block;padding:6px;font-size:9px;color:#789}';document.head.append(s)}")
                            clip=browser.value("({x:0,y:0,width:innerWidth,height:Math.ceil(document.getElementById('notificationPanel').getBoundingClientRect().bottom+8),scale:1})")
                            shot=browser.call('Page.captureScreenshot',{'format':'png','clip':clip,'captureBeyondViewport':True},page=True)
                            (output/f'fixture_notifications_{theme}_{width}_{10 if expanded else 5}.png').write_bytes(base64.b64decode(shot['data']))
            self.assertEqual(browser.value('notificationErrors'),[])
            self.assertFalse(browser.value("!!document.getElementById('bootErrorBanner')"))
        finally:
            browser.close();time.sleep(.3)

    def test_routes_require_login_and_admin_for_mutations(self):
        self.assertEqual(401, self.request('/api/ml/effectiveness?type=LOTO_6_45')[0])
        for route in ('effectiveness-settings', 'effectiveness-cycle'):
            form = {'type': 'LOTO_6_45', 'enabled': 'true', 'ticketCount': 3}
            self.assertEqual(401, self.request('/api/ml/' + route, form)[0])
            self.assertEqual(403, self.request('/api/ml/' + route, form, self.member)[0])
        self.assertEqual(403, self.request('/api/ml/effectiveness?type=LOTO_6_45', cookie=self.member,
                                         origin='https://untrusted.example')[0])

    def test_system_actor_cannot_be_registered_renamed_or_logged_in(self):
        form = {'username': '__effectiveness_system__', 'password': 'fixture_password'}
        self.assertEqual(400, self.request('/api/register', form)[0])
        self.assertEqual(403, self.request('/api/login', form)[0])
        rename = {'username': 'member_fixture', 'newUsername': '__effectiveness_system__'}
        self.assertEqual(400, self.request('/api/admin/rename-user', rename, self.admin)[0])

    def test_real_report_is_empty_read_only_and_settings_persist(self):
        code, report, _ = self.request('/api/ml/effectiveness?type=LOTO_6_45', cookie=self.member)
        self.assertEqual(200, code, report)
        self.assertFalse(report['canManage'])
        self.assertEqual(0, report['counts']['total'])
        self.assertEqual([], report['cycles'])
        self.assertEqual({'web', 'random', 'bayesian', 'ewma'}, {m['key'] for m in report['methods']})
        self.assertTrue(all(m['meanHits'] is None for m in report['methods']))
        form = {'type': 'LOTO_6_45', 'enabled': 'true', 'ticketCount': 4}
        code, result, _ = self.request('/api/ml/effectiveness-settings', form, self.admin)
        self.assertEqual(200, code, result)
        self.assertTrue(result['canManage'])
        code, result, _ = self.request('/api/ml/effectiveness-settings?type=LOTO_6_45', cookie=self.member)
        self.assertEqual(200, code, result)
        self.assertTrue(result['settings']['enabled'])
        self.assertEqual(4, result['settings']['ticketCount'])
        with closing(sqlite3.connect(self.work / 'runtime/lotto_web.db')) as connection:
            self.assertEqual(0, connection.execute('SELECT COUNT(*) FROM prediction_runs').fetchone()[0])

    def test_request_validation_and_empty_source_cannot_lock(self):
        for query in ('type=MAX_3D', 'type=LOTO_6_45&limit=301', 'type=LOTO_6_45&limit=nope'):
            self.assertEqual(400, self.request('/api/ml/effectiveness?' + query, cookie=self.admin)[0])
        for enabled, count in (('maybe', '3'), ('true', '10001'), ('true', '0')):
            form = {'type': 'LOTO_6_45', 'enabled': enabled, 'ticketCount': count}
            self.assertEqual(400, self.request('/api/ml/effectiveness-settings', form, self.admin)[0])
        self.assertEqual(405, self.request('/api/ml/effectiveness?type=LOTO_6_45', {}, self.admin)[0])
        self.assertEqual(405, self.request('/api/ml/effectiveness-cycle?type=LOTO_6_45', cookie=self.admin)[0])
        code, result, _ = self.request('/api/ml/effectiveness-cycle', {'type': 'LOTO_6_45'}, self.admin)
        self.assertEqual(400, code, result)
        self.assertFalse(result['ok'])
        with closing(sqlite3.connect(self.work / 'runtime/lotto_web.db')) as connection:
            self.assertEqual(0, connection.execute('SELECT COUNT(*) FROM prediction_runs').fetchone()[0])

    def test_tracking_10000_budget_and_ticket_pages_require_auth(self):
        for game in ('LOTO_6_45', 'KENO'):
            _, previous, _ = self.request('/api/ml/effectiveness-settings?type=' + game, cookie=self.admin)
            try:
                code, result, _ = self.request('/api/ml/effectiveness-settings', {'type': game, 'enabled': 'false', 'ticketCount': 10000}, self.admin)
                self.assertEqual(code, 200, result)
                self.assertEqual(result['settings']['ticketCount'], 10000)
                _, persisted, _ = self.request('/api/ml/effectiveness-settings?type=' + game, cookie=self.member)
                self.assertEqual(persisted['settings']['ticketCount'], 10000)
            finally:
                self.request('/api/ml/effectiveness-settings', {'type': game, 'enabled': str(previous['settings']['enabled']).lower(), 'ticketCount': previous['settings']['ticketCount']}, self.admin)
        route = '/api/ml/effectiveness-tickets?type=KENO&predictionId=00000000-0000-0000-0000-000000000000'
        self.assertEqual(self.request(route)[0], 401)
        self.assertEqual(self.request(route, {}, self.admin)[0], 405)
        self.assertEqual(self.request(route, cookie=self.admin)[0], 400)
        self.assertEqual(self.request(route + '&page=0', cookie=self.admin)[0], 400)

    def test_keno_report_level_pagination_and_admin_settings(self):
        self.assertEqual(401, self.request('/api/ml/effectiveness?type=KENO&level=3')[0])
        code, report, _ = self.request('/api/ml/effectiveness?type=KENO&level=3&page=1', cookie=self.member)
        self.assertEqual(200, code, report)
        self.assertEqual(report['level'], 3)
        self.assertFalse(report['canManage'])
        self.assertEqual(len(report['levels']), 10)
        self.assertEqual(report['pagination']['pageSize'], 10)
        self.assertEqual(report['counts']['total'], 0)
        form = {'type': 'KENO', 'enabled': 'true', 'ticketCount': 3}
        self.assertEqual(403, self.request('/api/ml/effectiveness-settings', form, self.member)[0])
        code, result, _ = self.request('/api/ml/effectiveness-settings', form, self.admin)
        self.assertEqual(200, code, result)
        self.assertTrue(result['settings']['enabled'])
        self.assertEqual(result['settings']['ticketCount'], 3)
        self.request('/api/ml/effectiveness-settings', {**form, 'enabled': 'false'}, self.admin)

    def test_keno_rejects_invalid_level_page_budget_and_lab_requests(self):
        for query in ('level=0', 'level=11', 'level=3.5', 'level=nope', 'page=0', 'page=-1', 'page=1.5', 'page=1000001'):
            self.assertEqual(400, self.request('/api/ml/effectiveness?type=KENO&' + query, cookie=self.admin)[0], query)
        form = {'type': 'KENO', 'enabled': 'true', 'ticketCount': 10001}
        self.assertEqual(400, self.request('/api/ml/effectiveness-settings', form, self.admin)[0])
        self.assertEqual(400, self.request('/api/ml/algorithm-lab?type=KENO', cookie=self.admin)[0])
        self.assertEqual(400, self.request('/api/ml/algorithm-lab', {'type': 'KENO'}, self.admin)[0])

    @contextmanager
    def lab_script(self, body):
        """Exercise the real Java process bridge with a deterministic isolated CLI."""
        path = self.work / 'ai/algorithm_lab.py'
        previous = path.read_bytes() if path.exists() else None
        path.write_text(body, encoding='utf-8')
        try:
            yield
        finally:
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(previous)

    def wait_lab(self, job_id, states=('completed', 'failed')):
        deadline = time.monotonic() + 120
        while time.monotonic() < deadline:
            code, result, _ = self.request('/api/ml/algorithm-lab?type=LOTO_6_45&jobId=' + job_id, cookie=self.admin)
            self.assertEqual(200, code, result)
            if result['job']['state'] in states:
                return result['job']
            time.sleep(.2)
        self.fail('Algorithm lab did not finish')

    def test_algorithm_lab_output_size_limit(self):
        script = "import sys\nsys.stdout.write('x' * (9 * 1024 * 1024))\nsys.stdout.flush()\n"
        with self.lab_script(script):
            code, result, _ = self.request('/api/ml/algorithm-lab', {'type': 'LOTO_6_45'}, self.admin)
            self.assertEqual(202, code, result)
            job = self.wait_lab(result['job']['id'])
            self.assertEqual('failed', job['state'])
            self.assertIn('giới hạn dung lượng', job['error'])
            self.assertIsNone(job['report'])

    def test_algorithm_lab_streamed_progress_is_bounded_monotonic_and_nonblocking(self):
        script = """import json,sys,time
print(json.dumps({'completed':2,'total':10}),file=sys.stderr,flush=True)
time.sleep(1)
print(json.dumps({'completed':1,'total':10}),file=sys.stderr,flush=True)
print(json.dumps({'completed':999,'total':10}),file=sys.stderr,flush=True)
print(json.dumps({'completed':3,'total':99}),file=sys.stderr,flush=True)
sys.stderr.write('z'*5000+'\\n')
print(json.dumps({'completed':4,'total':10}),file=sys.stderr,flush=True)
time.sleep(1)
print(json.dumps({'ok':True,'status':'completed','scope':'historical_diagnostic','type':'LOTO_6_45'}))
"""
        with self.lab_script(script):
            code, result, _ = self.request('/api/ml/algorithm-lab',
                                           {'type': 'LOTO_6_45', 'validationCount': '5', 'testCount': '5'}, self.admin)
            self.assertEqual(202, code, result)
            job_id = result['job']['id']
            seen = []
            for _ in range(30):
                code, value, _ = self.request('/api/ml/algorithm-lab?type=LOTO_6_45&jobId=' + job_id, cookie=self.admin)
                self.assertEqual(200, code, value)
                seen.append(value['job']['progress']['completed'])
                self.assertEqual(10, value['job']['progress']['total'])
                if value['job']['state'] == 'completed':
                    break
                self.assertEqual(200, self.request('/api/time')[0])
                time.sleep(.1)
            self.assertEqual(sorted(seen), seen)
            self.assertIn(2, seen)
            self.assertIn(4, seen)
            self.assertLessEqual(max(seen), 10)
            self.assertEqual('completed', self.wait_lab(job_id)['state'])

    def test_algorithm_lab_auth_validation_and_empty_report(self):
        route = '/api/ml/algorithm-lab'
        self.assertEqual(401, self.request(route + '?type=LOTO_6_45')[0])
        self.assertEqual(401, self.request(route, {'type': 'LOTO_6_45'})[0])
        self.assertEqual(403, self.request(route, {'type': 'LOTO_6_45'}, self.member)[0])
        code, result, _ = self.request(route + '?type=LOTO_6_45', cookie=self.member)
        self.assertEqual(200, code, result)
        self.assertFalse(result['canManage'])
        self.assertIsNone(result['job'])
        self.assertEqual(400, self.request(route + '?type=KENO', cookie=self.admin)[0])
        self.assertEqual(405, self.request(route + '?type=LOTO_6_45', {}, self.admin, method='PUT')[0])
        for key, value in (('ticketCount', '11'), ('ticketCount', '0'), ('validationCount', '4'),
                           ('testCount', '51'), ('testCount', '5.5'), ('action', 'promote')):
            self.assertEqual(400, self.request(route, {'type': 'LOTO_6_45', key: value}, self.admin)[0])
        self.assertEqual(400, self.request(route, {'type': 'LOTO_6_45', 'action': 'cancel'}, self.admin)[0])
        self.assertEqual(403, self.request(route, {'type': 'LOTO_6_45'}, self.admin, origin='https://untrusted.invalid')[0])

    def test_algorithm_lab_async_owner_isolation_and_single_job(self):
        script = """import json,sys,time
args=dict(argument[2:].split('=',1) for argument in sys.argv[1:])
time.sleep(1.2)
print(json.dumps({'ok':True,'status':'completed','type':args['game'],'scope':'historical_diagnostic',
                 'config':{'ticketCount':int(args['ticket-count']),'validationCount':int(args['validation-count']),
                           'testCount':int(args['test-count'])},'methods':[]}))
"""
        route = '/api/ml/algorithm-lab'
        with self.lab_script(script):
            started = time.monotonic()
            code, result, _ = self.request(route, {'type': 'LOTO_6_45', 'ticketCount': '4',
                                                  'validationCount': '5', 'testCount': '7'}, self.admin)
            self.assertEqual(202, code, result)
            self.assertLess(time.monotonic() - started, 1.0)
            job_id = result['job']['id']
            self.assertEqual(200, self.request('/api/time')[0])
            self.assertEqual(409, self.request(route, {'type': 'LOTO_6_45'}, self.admin)[0])
            query = route + '?type=LOTO_6_45&jobId=' + job_id
            self.assertEqual(404, self.request(query, cookie=self.member)[0])
            self.assertEqual(404, self.request(route + '?type=LOTO_5_35&jobId=' + job_id, cookie=self.admin)[0])
            self.assertEqual(403, self.request(route, {'type': 'LOTO_6_45', 'action': 'cancel', 'jobId': job_id}, self.member)[0])
            completed = self.wait_lab(job_id)
            self.assertEqual('completed', completed['state'], completed)
            self.assertEqual({'ticketCount': 4, 'validationCount': 5, 'testCount': 7}, completed['report']['config'])
            self.assertTrue(completed['finishedAt'])
            code, result, _ = self.request(route + '?type=LOTO_6_45', cookie=self.admin)
            self.assertEqual(job_id, result['job']['id'])
        with closing(sqlite3.connect(self.work / 'runtime/lotto_web.db')) as connection:
            if connection.execute("SELECT 1 FROM sqlite_master WHERE name='prediction_runs'").fetchone():
                self.assertEqual(0, connection.execute('SELECT COUNT(*) FROM prediction_runs').fetchone()[0])

    def test_algorithm_lab_domain_error_and_cancel(self):
        route = '/api/ml/algorithm-lab'
        with self.lab_script("import json,sys\nprint(json.dumps({'ok':False,'message':'Unsafe model cutoff'}))\nsys.exit(1)\n"):
            code, result, _ = self.request(route, {'type': 'LOTO_6_45'}, self.admin)
            self.assertEqual(202, code, result)
            failed = self.wait_lab(result['job']['id'])
            self.assertEqual('failed', failed['state'])
            self.assertEqual('Unsafe model cutoff', failed['error'])
            self.assertIsNone(failed['report'])
        with self.lab_script("import time\ntime.sleep(30)\n"):
            code, result, _ = self.request(route, {'type': 'LOTO_6_45'}, self.admin)
            self.assertEqual(202, code, result)
            job_id = result['job']['id']
            code, result, _ = self.request(route, {'type': 'LOTO_6_45', 'action': 'cancel', 'jobId': job_id}, self.admin)
            self.assertEqual(200, code, result)
            self.assertEqual('cancelled', result['job']['state'])
            self.assertIsNone(result['job']['report'])
            # Wait for the killed worker to release its global slot before changing the stub.
            for _ in range(100):
                code, next_job, _ = self.request(route, {'type': 'LOTO_6_45'}, self.admin)
                if code == 202:
                    self.request(route, {'type': 'LOTO_6_45', 'action': 'cancel', 'jobId': next_job['job']['id']}, self.admin)
                    break
                self.assertEqual(409, code, next_job)
                time.sleep(.05)
            else:
                self.fail('Cancelled worker did not release the lab slot')

    def test_algorithm_lab_real_pipeline_on_disposable_history(self):
        """Real Java -> lab -> classic/Adaptive Coverage -> prize report, no ledger writes."""
        predictor_dir = self.work / 'ai/predictors'
        canonical_dir = self.work / 'data/canonical'
        live_source = self.work / 'backend/live_results.py'
        for target in (predictor_dir, canonical_dir, live_source):
            self.assertTrue(target.resolve().is_relative_to(self.work.resolve()))
            self.assertFalse(target.exists())
        shutil.copytree(ROOT / 'ai/predictors', predictor_dir, ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copy2(ROOT / 'backend/live_results.py', live_source)
        canonical_dir.mkdir(parents=True)
        canonical = canonical_dir / 'mega_6_45_all_day.csv'
        rng = random.Random(65045)
        now_saigon = datetime.now(timezone(timedelta(hours=7)))
        current_day = now_saigon.date()
        draw_days = []
        while len(draw_days) < 70:
            if current_day.weekday() in (2, 4, 6) and datetime.combine(current_day, datetime.min.time(), now_saigon.tzinfo).replace(hour=18) < now_saigon:
                draw_days.append(current_day)
            current_day -= timedelta(days=1)
        draw_days.reverse()
        with canonical.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(['Kỳ', 'Ngày', 'Giờ', 'Bộ Số'])
            for index, current_day in enumerate(draw_days):
                writer.writerow([index + 1, current_day.strftime('%d/%m/%Y'), '18:00',
                                 ','.join(str(number) for number in sorted(rng.sample(range(1, 46), 6)))])
        original_hash = hashlib.sha256(canonical.read_bytes()).hexdigest()
        try:
            code, result, _ = self.request('/api/ml/algorithm-lab',
                                          {'type': 'LOTO_6_45', 'ticketCount': '2',
                                           'validationCount': '5', 'testCount': '5'}, self.admin)
            self.assertEqual(202, code, result)
            job = self.wait_lab(result['job']['id'])
            self.assertEqual('completed', job['state'], job)
            report = job['report']
            self.assertEqual('historical_diagnostic', report['scope'])
            self.assertTrue({'web', 'random', 'bayesian', 'ewma'} <= {method['key'] for method in report['methods']})
            self.assertEqual(10, len(report['methods']))
            self.assertEqual(6, len(report['profiles']))
            self.assertTrue(report['conclusion']['canTrack'])
            self.assertEqual(60, report['split']['training']['count'])
            self.assertEqual('65', report['split']['validation']['lastDrawId'])
            self.assertEqual('66', report['split']['test']['firstDrawId'])
            self.assertTrue(report['selection']['validationOnly'])
            self.assertEqual(10, len(report['folds']))
            for fold in report['folds']:
                self.assertLess(int(fold['cutoffDrawId']), int(fold['targetDrawId']))
                self.assertEqual(2, len(fold['methods']['web']['tickets']))
                self.assertTrue(all('prizeCode' in ticket['result'] for ticket in fold['methods']['web']['tickets']))
            route = '/api/ml/algorithm-lab'
            run_id = job['id']
            code, overview, _ = self.request(route + '?type=LOTO_6_45&jobId=' + run_id, cookie=self.admin)
            self.assertEqual(200, code, overview)
            self.assertIn(run_id, {item['id'] for item in overview['history']})
            code, member_report, _ = self.request(route + '?type=LOTO_6_45', cookie=self.member)
            self.assertEqual(200, code, member_report)
            self.assertEqual([], member_report['history'])
            self.assertIsNone(member_report['tracking']['candidate'])
            self.assertEqual(403, self.request(route, {'type': 'LOTO_6_45', 'action': 'start_tracking', 'jobId': run_id}, self.member)[0])
            code, tracking, _ = self.request(route, {'type': 'LOTO_6_45', 'action': 'start_tracking', 'jobId': run_id}, self.admin)
            self.assertEqual(200, code, tracking)
            candidate = tracking['tracking']['candidate']
            self.assertEqual('active', candidate['status'])
            self.assertEqual(run_id, candidate['runId'])
            self.assertEqual(1, tracking['tracking']['counts']['locked'])
            self.assertEqual(0, tracking['tracking']['counts']['scored'])
            self.assertEqual({'candidate', 'random', 'web'}, {item['key'] for item in tracking['tracking']['methods']})
            self.assertEqual(1, len(tracking['tracking']['cycles']))
            for prediction in tracking['tracking']['cycles'][0]['methods'].values():
                self.assertEqual(2, len(prediction['tickets']))
            # Starting again preserves the same candidate and already locked tickets.
            code, again, _ = self.request(route, {'type': 'LOTO_6_45', 'action': 'start_tracking', 'jobId': run_id}, self.admin)
            self.assertEqual(200, code, again)
            self.assertEqual(candidate['id'], again['tracking']['candidate']['id'])
            self.assertEqual(tracking['tracking']['cycles'], again['tracking']['cycles'])
            old_cookie = self.admin
            self.restart_server()
            self.assertEqual(401, self.request(route + '?type=LOTO_6_45', cookie=old_cookie)[0])
            code, restarted, _ = self.request(route + '?type=LOTO_6_45&jobId=' + run_id, cookie=self.admin)
            self.assertEqual(200, code, restarted)
            self.assertEqual(report, restarted['job']['report'])
            self.assertEqual(candidate['id'], restarted['tracking']['candidate']['id'])
            code, stopped, _ = self.request(route, {'type': 'LOTO_6_45', 'action': 'stop_tracking', 'candidateId': candidate['id']}, self.admin)
            self.assertEqual(200, code, stopped)
            self.assertEqual('stopped', stopped['tracking']['candidate']['status'])
            self.assertEqual(tracking['tracking']['cycles'], stopped['tracking']['cycles'])
            self.assertEqual(original_hash, hashlib.sha256(canonical.read_bytes()).hexdigest())
            with closing(sqlite3.connect(self.work / 'runtime/lotto_web.db')) as connection:
                if connection.execute("SELECT 1 FROM sqlite_master WHERE name='prediction_runs'").fetchone():
                    self.assertEqual(0, connection.execute('SELECT COUNT(*) FROM prediction_runs').fetchone()[0])
        finally:
            for target in (predictor_dir, canonical_dir):
                self.assertTrue(target.resolve().is_relative_to(self.work.resolve()))
                shutil.rmtree(target)
            live_source.unlink()

    @unittest.skipUnless(Path(CHROME).exists(), 'Chrome required')
    def test_frontend_navigation_and_canonical_data_without_csv_history_panel(self):
        """Removing the old panel must preserve live results and shared CSV consumers."""
        import backend.live_results as lr
        from tests.browser_cdp import Browser
        canonical = self.work / 'data/canonical'
        live_source = self.work / 'backend/live_results.py'
        self.assertFalse(canonical.exists())
        self.assertFalse(live_source.exists())
        canonical.mkdir(parents=True)
        browser = None
        keys = ('LOTO_5_35', 'LOTO_6_45', 'LOTO_6_55', 'KENO', 'MAX_3D', 'MAX_3D_PRO')
        try:
            # Java validates the source script before its direct canonical CSV reader.
            # A disposable source keeps incidental live polling offline in this UI test.
            live_source.write_text("import json\nprint(json.dumps({'ok':True,'results':[],'errors':[],'fetchedAt':''}))\n", encoding='utf-8')
            for key in keys:
                rows = {}
                for ky in (1, 2):
                    row = {field: '' for field in lr.CSV_FIELDS}
                    size = 20 if key == 'KENO' else 5 if key == 'LOTO_5_35' else 6
                    row.update(Ky=str(ky), Ngay='01/10/2026', Gio='13:00',
                               Main=','.join(map(str, range(1, size + 1))), Label=lr.LIVE_TYPES[key].label)
                    if key.startswith('MAX'):
                        row.update(Main='', DisplayLines='Đặc biệt: 000 000 || Giải nhất: 001 002 003 004 || Giải nhì: 005 006 007 008 009 010 || Giải ba: 011 012 013 014 015 016 017 018')
                    if key in ('LOTO_5_35', 'LOTO_6_55'):
                        row['Special'] = '10'
                    row['PrizeHit'] = {'LOTO_5_35': 'ĐB', 'LOTO_6_45': 'Jackpot', 'LOTO_6_55': 'Jackpot 1, 2'}.get(key, '') if ky == 2 else ''
                    if key == 'LOTO_5_35':
                        row.update(Time='13:00' if ky == 1 else '21:00',
                                   SpecialPrize='12000000000' if ky == 1 else '6000000000')
                        if ky == 1:
                            row['PrizeHit'] = 'Chia Giải'
                    rows[str(ky)] = row
                lr.write_csv_rows(canonical / f'{lr.CANONICAL_OUTPUT_STEMS[key]}_all_day.csv', rows, type_key=key)
            browser = Browser(CHROME, self.work / 'chrome-history-removal')
            browser.call('Page.enable', page=True)
            browser.call('Page.addScriptToEvaluateOnNewDocument', {'source': """
                window.smokeErrors=[]; window.smokeRequests=[]; window.smokePending=0;
                addEventListener('error',event=>window.smokeErrors.push(event.message));
                addEventListener('unhandledrejection',event=>window.smokeErrors.push(String(event.reason)));
                const originalFetch=window.fetch;
                window.fetch=(...args)=>{window.smokeRequests.push(String(args[0]));window.smokePending++;return originalFetch(...args).finally(()=>window.smokePending--);};
            """}, page=True)
            browser.call('Page.navigate', {'url': self.url + '/'}, page=True)
            def wait_for(expression):
                for _ in range(150):
                    if browser.value(expression):
                        return
                    time.sleep(.05)
                state = browser.value("JSON.stringify({path:location.pathname,table:document.getElementById('dataTableStatus')?.textContent,body:document.getElementById('dataTableBody')?.textContent,stats:document.getElementById('statsInsightsOut')?.textContent.slice(0,300),errors:smokeErrors,requests:smokeRequests.slice(-12)})")
                self.fail(f'Browser state did not become ready: {expression}\n{state}')
            def evaluate(expression):
                result = browser.call('Runtime.evaluate', {'expression': expression, 'awaitPromise': True,
                                                           'returnByValue': True}, page=True)
                self.assertNotIn('exceptionDetails', result, result)
                return result['result'].get('value')
            wait_for("typeof applyLiveResultsProgressSnapshot === 'function' && !!document.getElementById('loginBtn')")
            browser.value("document.getElementById('loginUser').value='owner_fixture';document.getElementById('loginPass').value='fixture_password';document.getElementById('loginBtn').click()")
            wait_for("document.getElementById('whoami').textContent.includes('owner_fixture')")
            self.assertFalse(browser.value("!!document.querySelector('.live-history-card, #liveHistoryOut, #liveHistoryType, #liveHistoryBtn, #liveHistoryRefreshBtn')"))
            self.assertEqual(6, browser.value("document.querySelectorAll('#liveResultGrid .live-card').length"))
            self.assertTrue(browser.value("!!document.getElementById('liveSyncBtn')"))
            self.assertEqual([], evaluate("(async()=>{const before=smokeRequests.length;await applyLiveResultsProgressSnapshot({typeStates:{KENO:{updatedAt:'history-removal-smoke',status:'completed'}}});return smokeRequests.slice(before).filter(url=>url.includes('/api/live-history'));})()"))
            browser.value("document.getElementById('dataTableMenuBtn').click()")
            wait_for("!document.getElementById('dataTableSection').hidden && document.getElementById('dataTableBody').textContent.includes('01/10/2026')")
            for key in keys:
                self.assertEqual(2, len(self.request('/api/live-history?type=' + key + '&count=all', cookie=self.admin)[1]['history']))
                evaluate(f"(async()=>{{const input=document.getElementById('dataTableType');input.value='{key}';input.dispatchEvent(new Event('change',{{bubbles:true}}));return true;}})()")
                wait_for(f"!dataTableLoading && dataTableSelectedType === '{key}' && document.querySelectorAll('#dataTableBody tr').length === 2")
                headers = browser.value("document.getElementById('dataTableHead').textContent")
                self.assertEqual(key in lr.PRIZE_FIELDS_BY_TYPE, 'Nổ' in headers)
                self.assertEqual(key != 'LOTO_5_35', browser.value("document.getElementById('dataTableShareFilterBtn').disabled"))
                if key == 'LOTO_5_35':
                    self.assertTrue(browser.value("document.getElementById('dataTableHitFilterBtn').nextElementSibling.id === 'dataTableShareFilterBtn'"))
                    artifact_dir = os.environ.get('LOTTO_DATA_TOOLBAR_ARTIFACT_DIR')
                    for theme in ('dark', 'light'):
                        browser.value(f"document.body.classList.toggle('light-theme', {str(theme == 'light').lower()})")
                        for width in (320, 390, 768, 1024, 1180, 1200, 1280, 1440, 1680):
                            browser.call('Emulation.setDeviceMetricsOverride', {'width': width, 'height': 900,
                                                                               'deviceScaleFactor': 1, 'mobile': False}, page=True)
                            wait_for(f'window.innerWidth === {width}')
                            layout = browser.value("""(() => {
                                const fields=['dataTableType','dataTableLimit','dataTableWeekday','dataTableDay','dataTableMonth','dataTableYear'];
                                const buttons=['dataTableRefreshBtn','dataTableDownloadBtn','dataTableHitFilterBtn','dataTableShareFilterBtn','dataTableClearFilterBtn'];
                                const rect=id=>{const el=document.getElementById(id);return (el.parentElement.querySelector('.select-trigger')||el).getBoundingClientRect();};
                                const inputs=fields.map(rect), actions=buttons.map(rect), all=[...inputs,...actions];
                                const a=rect('dataTableHitFilterBtn'),b=rect('dataTableShareFilterBtn'),c=rect('dataTableClearFilterBtn');
                                const heading=document.querySelector('.data-table-head h2').getBoundingClientRect();
                                const toolbar=document.querySelector('.data-table-toolbar').getBoundingClientRect();
                                return {sameRow:Math.abs(a.y-b.y)<1,adjacent:b.x>=a.right,inside:all.every(r=>r.x>=0&&r.right<=innerWidth+1),
                                    uniformHeight:all.every(r=>Math.abs(r.height-34)<1),fieldsSameRow:inputs.every(r=>Math.abs(r.y-inputs[0].y)<1),
                                    allSameRow:all.every(r=>Math.abs(r.y-inputs[0].y)<1),clearRow:Math.abs(a.y-c.y)<1,
                                    besideHeading:toolbar.x>=heading.right && toolbar.y<=heading.bottom && toolbar.bottom>=heading.y,
                                    inputY:inputs.map(r=>r.y),buttonY:actions.map(r=>r.y)};
                            })()""")
                            self.assertTrue(all(layout[name] for name in ('sameRow', 'adjacent', 'inside', 'uniformHeight')), (theme,width,layout))
                            if width > 1180:
                                self.assertTrue(layout['fieldsSameRow'] and layout['clearRow'], (theme,width,layout))
                                self.assertTrue(layout['allSameRow'] and layout['besideHeading'], (theme,width,layout))
                            if artifact_dir:
                                import base64
                                output = Path(artifact_dir)
                                output.mkdir(parents=True, exist_ok=True)
                                browser.value("document.querySelector('.data-table-eyebrow').textContent='CANONICAL ALL_DAY.CSV · DỮ LIỆU KIỂM THỬ'")
                                capture = browser.call('Page.captureScreenshot', {'format':'png'}, page=True)
                                (output / f'fixture_toolbar_{theme}_{width}.png').write_bytes(base64.b64decode(capture['data']))
                    browser.value("document.body.classList.remove('light-theme');document.querySelector('.data-table-eyebrow').textContent='CANONICAL ALL_DAY.CSV'")
                    browser.value("document.getElementById('dataTableHitFilterBtn').click()")
                    wait_for("!dataTableLoading && document.querySelectorAll('#dataTableBody tr').length === 1 && document.querySelector('#dataTableBody tr').lastElementChild.textContent === 'ĐB'")
                    browser.value("document.getElementById('dataTableShareFilterBtn').click()")
                    wait_for("!dataTableLoading && document.querySelectorAll('#dataTableBody tr').length === 2")
                    self.assertTrue(browser.value("['dataTableHitFilterBtn','dataTableShareFilterBtn'].every(id => document.getElementById(id).getAttribute('aria-pressed') === 'true')"))
                    self.assertIn('Nổ hoặc Chia giải', browser.value("document.getElementById('dataTableStatus').textContent"))
                    browser.value("document.getElementById('dataTableHitFilterBtn').click()")
                    wait_for("!dataTableLoading && document.querySelectorAll('#dataTableBody tr').length === 1 && document.querySelector('#dataTableBody tr').lastElementChild.textContent === 'Chia Giải'")
                    browser.value("document.getElementById('dataTableClearFilterBtn').click()")
                    wait_for("!dataTableLoading && document.querySelectorAll('#dataTableBody tr').length === 2")
                    self.assertTrue(browser.value("['dataTableHitFilterBtn','dataTableShareFilterBtn'].every(id => document.getElementById(id).getAttribute('aria-pressed') === 'false')"))
            for button, section in (('homeMenuBtn', 'liveBoardSection'), ('paypalDepositMenuBtn', 'paypalDepositSection'),
                                    ('luckyWheelMenuBtn', 'luckyWheelSection'), ('homeMenuBtn', 'liveBoardSection')):
                browser.value(f"document.getElementById('{button}').click()")
                wait_for(f"!document.getElementById('{section}').hidden")
            for mode, section in (('normal', 'predictRootNormal'), ('manual', 'predictRootManual'), ('vip', 'predictRootVip'),
                                  ('stats-v2', 'predictRootStatsV2'), ('charts', 'predictRootCharts'),
                                  ('dashboard', 'predictRootDashboard'), ('analysis', 'predictRootAnalysis'),
                                  ('effectiveness', 'predictRootEffectiveness')):
                browser.value(f"document.querySelector('[data-predict-mode-tab=\"{mode}\"]').click()")
                wait_for(f"!document.getElementById('{section}').hidden")
            browser.value("document.querySelector('[data-predict-mode-tab=\"stats\"]').click()")
            wait_for("!statsPanelLoading && statsSelectedType === 'KENO' && document.getElementById('statsInsightsOut').textContent.includes('Keno')")
            self.assertNotIn('Không tải được', browser.value("document.getElementById('statsInsightsOut').textContent"))
            browser.value("document.querySelector('[data-predict-mode-tab=\"normal\"]').click()")
            wait_for('window.smokePending === 0')
            self.assertFalse(browser.value("!!document.getElementById('bootErrorBanner')"))
            self.assertEqual([], browser.value('window.smokeErrors'))
        finally:
            if browser is not None:
                browser.close()
            self.assertTrue(canonical.resolve().is_relative_to(self.work.resolve()))
            shutil.rmtree(canonical)
            live_source.unlink()

    @unittest.skipUnless(Path(CHROME).exists(), 'Chrome required')
    def test_full_frontend_tab_empty_state_and_admin_controls(self):
        from tests.browser_cdp import Browser
        browser = Browser(CHROME, self.work / 'chrome-profile')
        try:
            browser.call('Page.navigate', {'url': self.url + '/'}, page=True)
            for _ in range(100):
                if browser.value("typeof window.VietlottEffectiveness === 'object' && !!document.getElementById('loginBtn')"):
                    break
                time.sleep(.05)
            expression = """(async () => {
                const response=await fetch('/api/login',{method:'POST',headers:{'Content-Type':'application/x-www-form-urlencoded'},body:'username=owner_fixture&password=fixture_password'});
                if(!response.ok)throw new Error('fixture login');
                document.getElementById('loginUser').value='owner_fixture';
                document.getElementById('loginPass').value='fixture_password';
                document.getElementById('loginBtn').click();
                return true;
            })()"""
            result = browser.call('Runtime.evaluate', {'expression': expression, 'awaitPromise': True,
                                                     'returnByValue': True}, page=True)
            self.assertNotIn('exceptionDetails', result)
            for _ in range(150):
                if browser.value("!!document.querySelector('[data-predict-mode-tab=effectiveness]')"):
                    browser.value("document.querySelector('[data-predict-mode-tab=effectiveness]').click()")
                    break
                time.sleep(.05)
            for _ in range(150):
                text = browser.value("document.getElementById('predictRootEffectiveness')?.innerText || ''")
                if 'Ngẫu nhiên' in text and 'Bayesian' in text and 'EWMA' in text:
                    break
                time.sleep(.05)
            self.assertIn('Ngẫu nhiên', text)
            self.assertIn('Bayesian', text)
            self.assertIn('EWMA', text)
            self.assertTrue(browser.value("!document.getElementById('predictRootEffectiveness').hidden"))
            self.assertFalse(browser.value("!!document.getElementById('bootErrorBanner')"))
            self.assertNotIn('NaN', text)
        finally:
            browser.close()

    def test_zz_keno_real_pipeline_locks_all_levels_through_http(self):
        """Java -> production Keno pipeline -> 40 immutable ledger predictions."""
        predictor_dir = self.work / 'ai/predictors'
        canonical_dir = self.work / 'data/canonical'
        live_source = self.work / 'backend/live_results.py'
        for target in (predictor_dir, canonical_dir, live_source):
            self.assertTrue(target.resolve().is_relative_to(self.work.resolve()))
            self.assertFalse(target.exists())
        shutil.copytree(ROOT / 'ai/predictors', predictor_dir, ignore=shutil.ignore_patterns('__pycache__'))
        shutil.copy2(ROOT / 'backend/live_results.py', live_source)
        canonical_dir.mkdir(parents=True)
        canonical = canonical_dir / 'keno_all_day.csv'
        local = timezone(timedelta(hours=7))
        now = datetime.now(local)
        minute = now.hour * 60 + now.minute
        if minute < 368:
            latest = (now - timedelta(days=1)).replace(hour=21, minute=52, second=0, microsecond=0)
        else:
            slot = min(1312, 368 + ((minute - 368) // 8) * 8)
            latest = now.replace(hour=slot // 60, minute=slot % 60, second=0, microsecond=0)
        dates = [latest]
        for _ in range(239):
            at = dates[-1]
            dates.append((at - timedelta(days=1)).replace(hour=21, minute=52) if (at.hour, at.minute) == (6, 8) else at - timedelta(minutes=8))
        rng = random.Random(801020)
        with canonical.open('w', encoding='utf-8', newline='') as stream:
            writer = csv.writer(stream)
            writer.writerow(['Kỳ', 'Ngày', 'Giờ', 'Bộ Số'])
            for index, at in enumerate(reversed(dates)):
                writer.writerow([index + 1, at.strftime('%d/%m/%Y'), at.strftime('%H:%M'), ','.join(map(str, sorted(rng.sample(range(1, 81), 20))))])
        original = hashlib.sha256(canonical.read_bytes()).hexdigest()
        try:
            code, configured, _ = self.request('/api/ml/effectiveness-settings', {'type': 'KENO', 'enabled': 'false', 'ticketCount': 10000}, self.admin)
            self.assertEqual(code, 200, configured)
            code, first, _ = self.request('/api/ml/effectiveness-cycle', {'type': 'KENO'}, self.admin)
            self.assertEqual(200, code, first)
            self.assertEqual(first['totalTickets'], 332960)
            self.assertEqual(first['targetDrawId'], '241')
            self.request('/api/ml/effectiveness-settings', {'type': 'KENO', 'enabled': 'false', 'ticketCount': 1}, self.admin)
            code, duplicate, _ = self.request('/api/ml/effectiveness-cycle', {'type': 'KENO'}, self.admin)
            self.assertEqual(200, code, duplicate)
            self.assertEqual(duplicate['status'], 'already_locked')
            self.assertEqual(duplicate['cycleId'], first['cycleId'])
            for level in (1, 5, 10):
                code, report, _ = self.request(f'/api/ml/effectiveness?type=KENO&level={level}', cookie=self.member)
                self.assertEqual(200, code, report)
                self.assertEqual(report['counts'], {'scored': 0, 'locked': 1, 'total': 1})
                self.assertEqual(sum(len(m['tickets']) for m in report['cycles'][0]['methods'].values()), 80)
                self.assertTrue(all(len(t['main']) == level for m in report['cycles'][0]['methods'].values() for t in m['tickets']))
                expected_total = 80 if level == 1 else 10000
                self.assertTrue(all(m['ticketPagination']['total'] == expected_total for m in report['cycles'][0]['methods'].values()))
            entry = report['cycles'][0]['methods']['web']
            code, ticket_page, _ = self.request('/api/ml/effectiveness-tickets?type=KENO&predictionId=' + entry['predictionId'] + '&page=500', cookie=self.member)
            self.assertEqual(code, 200, ticket_page)
            self.assertEqual(ticket_page['ticketResults'][-1]['ticketIndex'], 10000)
            self.assertEqual(len(ticket_page['tickets']), 20)
            with closing(sqlite3.connect(self.work / 'runtime/lotto_web.db')) as connection:
                self.assertEqual(40, connection.execute("SELECT COUNT(*) FROM prediction_runs WHERE game_type='KENO'").fetchone()[0])
                self.assertEqual(10, connection.execute('SELECT COUNT(DISTINCT level) FROM keno_effectiveness_predictions').fetchone()[0])
                self.assertEqual(0, connection.execute('SELECT COUNT(*) FROM prediction_scores').fetchone()[0])
                self.assertEqual(332960, connection.execute("SELECT SUM(json_array_length(tickets_json)) FROM prediction_runs WHERE game_type='KENO'").fetchone()[0])
            self.assertEqual(original, hashlib.sha256(canonical.read_bytes()).hexdigest())
            self.assertFalse((self.work / 'ai/models/KENO').exists())
        finally:
            self.request('/api/ml/effectiveness-settings', {'type': 'KENO', 'enabled': 'false', 'ticketCount': 3}, self.admin)
            for target in (predictor_dir, canonical_dir):
                self.assertTrue(target.resolve().is_relative_to(self.work.resolve()))
                shutil.rmtree(target)
            live_source.unlink()
