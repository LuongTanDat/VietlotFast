"""OAuth adapters through test-only HTTPS transport plus real unauthenticated Chrome."""
import base64
import json
import os
import sqlite3
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import closing
from tests.test_account_balances import AccountBalanceTests
from tests.browser_cdp import Browser
from tests.test_prize_web import ROOT, JAVA, JAVAC, CHROME


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl): return None


def callback(url, provider, values, cookie=''):
    request=urllib.request.Request(url+'/api/auth/social/callback/'+provider+'?'+urllib.parse.urlencode(values),headers={'Cookie':cookie})
    try: response=urllib.request.build_opener(NoRedirect).open(request,timeout=10)
    except urllib.error.HTTPError as error: response=error
    with response: return response.status,response.headers,response.read()


class SocialLoginTests(AccountBalanceTests):
    @classmethod
    def start_server(cls):
        config=cls.work/'runtime/social-login.properties'
        config.write_text(f'publicBaseUrl={cls.url}\ngoogle.clientId=google_client\ngoogle.clientSecret=fixture_google_secret\nfacebook.clientId=facebook_client\nfacebook.clientSecret=fixture_facebook_secret\nfacebook.graphVersion=v99.0\nzalo.clientId=zalo_client\nzalo.clientSecret=fixture_zalo_secret\n',encoding='utf-8')
        if not (cls.work/'build/SocialOAuthFixture.class').exists():
            build=str((cls.work/'build').relative_to(ROOT))
            result=subprocess.run([JAVAC,'-encoding','UTF-8','-cp',build,'-d',build,'tests/SocialOAuthFixture.java'],cwd=ROOT,capture_output=True)
            if result.returncode:
                cls.log.close();cls.temp.cleanup()
                raise AssertionError(result.stderr.decode(errors='replace'))
        cls.server=subprocess.Popen([JAVA,'-Dfile.encoding=UTF-8',f'-Dlotto.port={cls.port}','-Dlotto.effectivenessWorker=false','-cp','build'+os.pathsep+'sqlite-jdbc.jar','SocialOAuthFixture'],cwd=cls.work,stdout=cls.log,stderr=subprocess.STDOUT,creationflags=0x08000000 if os.name=='nt' else 0)
        for _ in range(100):
            try: urllib.request.urlopen(cls.url+'/api/time',timeout=1).close();return
            except OSError: time.sleep(.05)
        raise AssertionError('OAuth fixture server failed to start')

    def begin(self, provider):
        status,data,headers=self.request('/api/auth/social/start',dict(provider=provider))
        self.assertEqual(status,200,data)
        values=dict(urllib.parse.parse_qsl(urllib.parse.urlparse(data['url']).query))
        self.assertNotIn('fixture_',data['url'])
        return values,headers['Set-Cookie'].split(';')[0]

    def finish(self, provider, code, params, cookie):
        status,headers,body=callback(self.url,provider,dict(state=params['state'],code=code),cookie)
        self.assertEqual(status,303,body)
        self.assertEqual(headers['Location'],'/')
        auth=next(c.split(';')[0] for c in headers.get_all('Set-Cookie') if c.startswith('LOTTO_AUTH='))
        status,data,_=self.request('/api/me',cookie=auth)
        self.assertEqual(status,200,data);self.assertEqual(data['role'],'user')
        return data['username'],auth

    def test_three_adapters_identity_isolation_pkce_replay_lock_and_rename(self):
        status,data,_=self.request('/api/auth/social/providers')
        self.assertEqual(status,200,data)
        self.assertTrue(all(p['enabled'] for p in data['providers'].values()))
        self.assertNotIn('client',json.dumps(data))
        identities=[]
        for provider in ['google','facebook','zalo']:
            values,cookie=self.begin(provider)
            self.assertEqual(values['redirect_uri'],self.url+'/api/auth/social/callback/'+provider)
            if provider!='facebook': self.assertRegex(values['code_challenge'],r'^[A-Za-z0-9_-]{43}$')
            status,headers,_=callback(self.url,provider,dict(state=values['state'],code='same_identity'),'LOTTO_OAUTH=wrong_cookie')
            self.assertEqual(headers['Location'],'/?auth_error=state')
            user,auth=self.finish(provider,'same_identity',values,cookie)
            self.assertNotEqual(user,'owner_fixture');identities.append(user)
            self.assertEqual(callback(self.url,provider,dict(state=values['state'],code='same_identity'),cookie)[1]['Location'],'/?auth_error=state')
            values,cookie=self.begin(provider);self.assertEqual(self.finish(provider,'same_identity',values,cookie)[0],user)
        self.assertEqual(len(set(identities)),3)
        numeric='123456789012345678'
        values,cookie=self.begin('zalo');numeric_user,_=self.finish('zalo',numeric,values,cookie)
        with closing(sqlite3.connect(self.work/'runtime/lotto_web.db')) as db:
            self.assertEqual(db.execute('SELECT subject FROM social_identities WHERE username=?',(numeric_user,)).fetchone()[0],numeric)
        requests=(self.work/'runtime/oauth_fixture_requests.txt').read_text(encoding='utf-8')
        self.assertIn('code_verifier=',requests)
        with closing(sqlite3.connect(self.work/'runtime/lotto_web.db')) as db:
            self.assertEqual(db.execute('SELECT COUNT(*) FROM social_identities').fetchone()[0],4)
        new='renamed_google_fixture'
        self.assertEqual(self.request('/api/admin/rename-user',dict(username=identities[0],newUsername=new),self.admin)[0],200)
        values,cookie=self.begin('google');self.assertEqual(self.finish('google','same_identity',values,cookie)[0],new)
        self.assertEqual(self.request('/api/admin/update-user',dict(username=new,role='user',enabled='0'),self.admin)[0],200)
        values,cookie=self.begin('google')
        self.assertEqual(callback(self.url,'google',dict(state=values['state'],code='same_identity'),cookie)[1]['Location'],'/?auth_error=disabled')
        self.assertEqual(self.request('/api/me',cookie=auth)[0],200)  # Last Facebook/Zalo session stays independent.
        self.assertEqual(self.request('/api/admin/delete-user',dict(username=new),self.admin)[0],200)
        self.assertEqual(self.request('/api/register',dict(username=new,password='another_fixture_password'))[0],200)
        values,cookie=self.begin('google')
        replacement,_=self.finish('google','same_identity',values,cookie)
        self.assertNotEqual(replacement,new)  # Deleted mapping cannot authenticate a reused local username.
        self.server.terminate();self.server.wait(timeout=10);self.start_server();self.login()
        values,cookie=self.begin('facebook')
        self.assertEqual(self.finish('facebook','same_identity',values,cookie)[0],identities[1])
        config=self.work/'runtime/social-login.properties'
        config.write_text(config.read_text(encoding='utf-8').replace('facebook.clientId=facebook_client','facebook.clientId=facebook_second_client'),encoding='utf-8')
        values,cookie=self.begin('facebook')
        self.assertNotEqual(self.finish('facebook','same_identity',values,cookie)[0],identities[1])

    def test_cancellation_profile_rejection_app_binding_and_origin(self):
        self.assertEqual(self.request('/api/auth/social/start',dict(provider='unknown'))[0],400)
        request=urllib.request.Request(self.url+'/api/auth/social/start',data=b'provider=google',headers={'Origin':'https://foreign.example','Content-Type':'application/x-www-form-urlencoded'})
        with self.assertRaises(urllib.error.HTTPError) as error:urllib.request.urlopen(request,timeout=5)
        self.assertEqual(error.exception.code,403)
        for provider,code,expected in [('google','rejected','failed'),('google','invalid_profile','failed'),('facebook','wrong_app','failed')]:
            values,cookie=self.begin(provider)
            self.assertEqual(callback(self.url,provider,dict(state=values['state'],code=code),cookie)[1]['Location'],'/?auth_error='+expected)
        values,cookie=self.begin('zalo')
        self.assertEqual(callback(self.url,'zalo',dict(state=values['state'],error='access_denied'),cookie)[1]['Location'],'/?auth_error=cancelled')
        self.assertEqual(callback(self.url,'zalo',dict(state=values['state'],code='same_identity'),cookie)[1]['Location'],'/?auth_error=state')


class LoginDesignTests(AccountBalanceTests):
    def test_disabled_providers_new_auth_ui_layout_password_and_local_login(self):
        status,data,_=self.request('/api/auth/social/providers')
        self.assertEqual(status,200,data);self.assertFalse(any(p['enabled'] for p in data['providers'].values()))
        for provider in ['google','facebook','zalo']:
            self.assertEqual(self.request('/api/auth/social/start',dict(provider=provider))[0],503)
        self.assertEqual(callback(self.url,'google',dict(code='untrusted',state='bad'))[1]['Location'],'/?auth_error=state')
        b=Browser(CHROME,self.work/'login-design-profile')
        def wait(expression):
            for _ in range(300):
                if b.value(expression):return
                time.sleep(.05)
            raise AssertionError(expression)
        try:
            b.call('Page.navigate',dict(url=self.url),page=True)
            wait("document.getElementById('loginForm').style.display==='block' && getComputedStyle(document.getElementById('pageLoader')).opacity==='0'")
            checks=[]
            for theme in ['dark','light']:
                b.value("document.body.classList.toggle('light-theme',"+str(theme=='light').lower()+")")
                for width,height in [(1440,900),(1242,702),(820,800),(760,844),(390,844),(320,667)]:
                    b.call('Emulation.setDeviceMetricsOverride',dict(width=width,height=height,deviceScaleFactor=1,mobile=width<500),page=True)
                    for registering in [False,True]:
                        b.value("document.getElementById("+json.dumps('showRegisterBtn' if registering else 'showLoginBtn')+").click()")
                        data=b.value("(()=>{const card=document.querySelector('.auth-card').getBoundingClientRect(),o=document.getElementById('authOverlay'),els=[...document.querySelectorAll('.auth-social button')];return {width:card.width,height:card.height,within:card.left>=0&&card.right<=innerWidth,overflow:document.documentElement.scrollWidth>innerWidth+1,scrollable:getComputedStyle(o).overflowY==='auto',socialHeights:els.map(e=>e.getBoundingClientRect().height),logo:document.querySelector('.auth-social img').naturalWidth>0}})()")
                        self.assertTrue(data['within'] and data['scrollable'] and data['logo']);self.assertFalse(data['overflow'])
                        self.assertTrue(all(h==40 for h in data['socialHeights']))
                        checks.append(dict(theme=theme,viewportWidth=width,registering=registering,**data))
                        if theme=='dark' and width==1242 and not registering:
                            shot=b.call('Page.captureScreenshot',dict(format='png'),page=True)
                            (ROOT/'Bin/session_1_latest/auth_redesign_dark_1242.png').write_bytes(base64.b64decode(shot['data']))
                        if theme=='light' and width==390 and not registering:
                            shot=b.call('Page.captureScreenshot',dict(format='png'),page=True)
                            (ROOT/'Bin/session_1_latest/auth_redesign_light_390.png').write_bytes(base64.b64decode(shot['data']))
            b.value("document.getElementById('showLoginBtn').click();document.getElementById('socialGoogleBtn').click()")
            self.assertIn('chưa được kích hoạt',b.value("document.getElementById('authMsg').textContent"))
            self.assertEqual(b.value('location.pathname'),'/')
            b.value("document.getElementById('loginPass').value='fixture_password';document.getElementById('toggleLoginPass').click()")
            self.assertEqual(b.value("document.getElementById('loginPass').type"),'text')
            b.value("document.getElementById('toggleLoginPass').click()")
            self.assertEqual(b.value("document.getElementById('loginPass').type"),'password')
            b.value("document.getElementById('loginUser').value='owner_fixture';document.getElementById('loginPass').dispatchEvent(new KeyboardEvent('keydown',{key:'Enter',bubbles:true}))")
            wait("document.getElementById('authOverlay').style.display==='none' && currentUser==='owner_fixture'")
            (ROOT/'Bin/session_1_latest/auth_redesign_layout_verification.json').write_text(json.dumps(checks,indent=2),encoding='utf-8')
        finally:b.close()
