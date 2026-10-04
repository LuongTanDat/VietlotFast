"""Run real Java handlers against a disposable database and fake HTTP requests."""
from pathlib import Path
import json
import os
import shutil
import subprocess
import tempfile
import sys

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
from tests.test_prize_web import JAVA, JAVAC

source = r'''
import com.sun.net.httpserver.*;
import java.io.*;
import java.lang.reflect.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
public class SecurityAuditHarness {
  static class Exchange extends HttpExchange {
    Headers request = new Headers(), response = new Headers();
    ByteArrayInputStream input; ByteArrayOutputStream output = new ByteArrayOutputStream();
    int status; String method, path;
    Exchange(String method,String path,String body) {this.method=method; this.path=path; input=new ByteArrayInputStream(body.getBytes(StandardCharsets.UTF_8));}
    public Headers getRequestHeaders(){return request;}
    public Headers getResponseHeaders(){return response;}
    public URI getRequestURI(){return URI.create(path);}
    public String getRequestMethod(){return method;}
    public HttpContext getHttpContext(){return null;}
    public void close(){}
    public InputStream getRequestBody(){return input;}
    public OutputStream getResponseBody(){return output;}
    public void sendResponseHeaders(int code,long size){status=code;}
    public int getResponseCode(){return status;}
    public InetSocketAddress getRemoteAddress(){return new InetSocketAddress("127.0.0.1",4321);}
    public InetSocketAddress getLocalAddress(){return new InetSocketAddress("127.0.0.1",8080);}
    public String getProtocol(){return "HTTP/1.1";}
    public Object getAttribute(String name){return null;}
    public void setAttribute(String name,Object value){}
    public void setStreams(InputStream input,OutputStream output){}
    public HttpPrincipal getPrincipal(){return null;}
    String text(){return new String(output.toByteArray(),StandardCharsets.UTF_8);}
  }
  static Exchange run(LottoWebServer server,String handler,String method,String path,String body,String cookie) throws Exception {
    Exchange exchange = new Exchange(method,path,body);
    if(cookie!=null) exchange.request.add("Cookie",cookie);
    Method action = LottoWebServer.class.getDeclaredMethod(handler,HttpExchange.class);
    action.setAccessible(true); action.invoke(server,exchange); return exchange;
  }
  public static void main(String[] args) throws Exception {
    LottoWebServer server = new LottoWebServer();
    Exchange registration = run(server,"handleRegister","POST","/api/register","username=audit_owner&password=before_fixture_only",null);
    Exchange recovery = run(server,"handleRecoverAdmin","POST","/api/recover-admin","password=after_fixture_only",null);
    Exchange login = run(server,"handleLogin","POST","/api/login","username=audit_owner&password=after_fixture_only",null);
    String cookie = login.response.getFirst("Set-Cookie");
    String claim = "{\"paypalBalance\":9999999,\"diamondBalance\":8888888,\"vipExpiresAt\":\"2099-01-01T00:00:00Z\"}";
    Exchange store = run(server,"handleStore","POST","/api/store","store="+URLEncoder.encode(claim,"UTF-8"),cookie);
    Exchange read = run(server,"handleStore","GET","/api/store","",cookie);
    System.out.println("{\"registration_status\":"+registration.status+",\"unauthenticated_admin_recovery_status\":"+recovery.status+",\"login_with_reset_password_status\":"+login.status+",\"client_asset_store_status\":"+store.status+",\"asset_claim_persisted\":"+read.text().contains("9999999")+",\"vip_claim_persisted\":"+read.text().contains("2099-01-01")+"}");
  }
}'''
with tempfile.TemporaryDirectory(prefix='security-fixture-',dir=OUT) as folder:
    work = Path(folder)
    (work/'runtime').mkdir()
    shutil.copy2(ROOT/'backend/lib/sqlite-jdbc-3.51.2.0.jar',work/'sqlite-jdbc.jar')
    harness = work/'SecurityAuditHarness.java'
    harness.write_text(source,encoding='utf-8')
    compiled = subprocess.run([JAVAC,'-encoding','UTF-8','-d',str(work.relative_to(ROOT)),'backend/LottoWebServer.java',str(harness.relative_to(ROOT))],cwd=ROOT,capture_output=True)
    assert compiled.returncode==0,compiled.stderr.decode(errors='replace')
    result = subprocess.run([JAVA,'-Dfile.encoding=UTF-8','-cp','.'+os.pathsep+'sqlite-jdbc.jar','SecurityAuditHarness'],cwd=work,capture_output=True,timeout=20)
    assert result.returncode==0,result.stderr.decode(errors='replace')
    payload = json.loads(result.stdout.decode('utf-8'))
    (OUT/'security_probe.json').write_text(json.dumps(payload,indent=2),encoding='utf-8')
    print(json.dumps(payload,indent=2))
