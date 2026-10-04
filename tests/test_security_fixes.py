import json
import os
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from tests.test_prize_web import JAVA, JAVAC, ROOT

HARNESS = r'''
import com.sun.net.httpserver.*;
import java.io.*;
import java.lang.reflect.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.util.*;
public class SecurityFixHarness {
 static class Exchange extends HttpExchange {
  Headers request=new Headers(),response=new Headers(); ByteArrayInputStream input; ByteArrayOutputStream output=new ByteArrayOutputStream(); int status; String method,path;
  Exchange(String method,String path,String body){this.method=method;this.path=path;input=new ByteArrayInputStream(body.getBytes(StandardCharsets.UTF_8));}
  public Headers getRequestHeaders(){return request;} public Headers getResponseHeaders(){return response;}
  public URI getRequestURI(){return URI.create(path);} public String getRequestMethod(){return method;}
  public HttpContext getHttpContext(){return null;} public void close(){} public InputStream getRequestBody(){return input;} public OutputStream getResponseBody(){return output;}
  public void sendResponseHeaders(int code,long size){status=code;} public int getResponseCode(){return status;}
  public InetSocketAddress getRemoteAddress(){return new InetSocketAddress("127.0.0.1",4321);} public InetSocketAddress getLocalAddress(){return new InetSocketAddress("127.0.0.1",8080);}
  public String getProtocol(){return "HTTP/1.1";} public Object getAttribute(String name){return null;} public void setAttribute(String name,Object value){} public void setStreams(InputStream input,OutputStream output){} public HttpPrincipal getPrincipal(){return null;}
  String text(){return new String(output.toByteArray(),StandardCharsets.UTF_8);}
 }
 static Exchange run(LottoWebServer server,String handler,String method,String path,String body,String cookie,String origin)throws Exception {
  Exchange ex=new Exchange(method,path,body); if(cookie!=null)ex.request.add("Cookie",cookie);if(origin!=null)ex.request.add("Origin",origin);
  Method action=LottoWebServer.class.getDeclaredMethod(handler,HttpExchange.class);action.setAccessible(true);
  try{action.invoke(server,ex);}catch(InvocationTargetException failure){if(ex.status!=413)throw failure;}
  return ex;
 }
 static void require(boolean value,String label){if(!value)throw new AssertionError(label);}
 static String enc(String text)throws Exception{return URLEncoder.encode(text,"UTF-8");}
 public static void main(String[] args)throws Exception {
  LottoWebServer server=new LottoWebServer();
  require(run(server,"handleRegister","POST","/api/register","username=owner&password=owner_fixture",null,null).status==200,"register owner");
  require(run(server,"handleRegister","POST","/api/register","username=member&password=member_fixture",null,null).status==200,"register member");
  require(run(server,"handleRecoverAdmin","POST","/api/recover-admin","password=attack_fixture",null,null).status==403,"recovery blocked");
  String admin=run(server,"handleLogin","POST","/api/login","username=owner&password=owner_fixture",null,null).response.getFirst("Set-Cookie");
  require(admin!=null,"admin password preserved");
  String user=run(server,"handleLogin","POST","/api/login","username=member&password=member_fixture",null,null).response.getFirst("Set-Cookie");
  require(user!=null,"member login");
  String claim="{\"paypalBalance\":9999999,\"diamondBalance\":9999999,\"luckyWheelStoredSpins\":999,\"walletVersion\":999,\"vipExpiresAt\":\"2099-01-01T00:00:00Z\",\"theme\":\"dark\"}";
  Exchange saved=run(server,"handleStore","POST","/api/store","store="+enc(claim),user,null);
  require(saved.status==200&&!saved.text().contains("9999999")&&!saved.text().contains("2099")&&run(server,"handleStore","GET","/api/store","",user,null).text().contains("dark"),"protected store fields and preferences");
  String escaped="{\"v\\u0069pExpiresAt\":\"2099-01-01T00:00:00Z\",\"paypalBalance\":7,\"paypalBalance\":8}";
  require(run(server,"handleStore","POST","/api/store","store="+enc(escaped),user,null).status==400,"duplicate keys rejected");
  require(run(server,"handleAiPredict","GET","/api/ai-predict?type=LOTO_6_45&engine=classic&predictionMode=vip&count=1","",user,null).status==403,"vip checked by server");
  require(run(server,"handleAdminVip","POST","/api/admin/vip","username=member&expiresAt="+enc("2099-01-01T00:00:00Z"),user,null).status==403,"member cannot grant vip");
  require(run(server,"handleAdminVip","POST","/api/admin/vip","username=member&expiresAt="+enc("2099-01-01T00:00:00Z"),admin,null).status==200,"admin can grant vip");
  require(run(server,"handleAiPredict","GET","/api/ai-predict?type=LOTO_6_45&engine=classic&predictionMode=vip&count=0","",user,null).status==400,"vip grant reaches count validation");
  require(run(server,"handleStore","POST","/api/store","store=%7B%7D",user,"https://evil.example").status==403,"untrusted origin rejected");
  require(run(server,"handleStore","GET","/api/store","",user,"http://localhost:8080").status==200,"trusted origin works");
  String transaction="action=spin&count=1&requestId=fixture_request_000001";
  Exchange first=run(server,"handleWheel","POST","/api/wheel",transaction,user,null);
  Exchange second=run(server,"handleWheel","POST","/api/wheel",transaction,user,null);
  require(first.status==200&&first.text().equals(second.text()),"wallet idempotency");
  require(first.text().contains("luckyWheelLastResult")&&first.text().contains("walletVersion\":1"),"server reward history and version");
  require(run(server,"handleWheel","POST","/api/wheel",transaction.replace("count=1","count=2"),user,null).status==400,"idempotency key binds operation");
  require(run(server,"handleWheel","POST","/api/wheel","action=spin&count=61&requestId=fixture_request_000002",user,null).status==400,"wallet limits");
  require(run(server,"handleWheel","POST","/api/wheel",transaction,null,null).status==401,"wallet authentication");
  String after=run(server,"handleStore","GET","/api/store","",user,null).text();
  run(server,"handleStore","POST","/api/store","store="+enc(claim),user,null);
  require(run(server,"handleStore","GET","/api/store","",user,null).text().equals(after),"stale client cannot overwrite reward");
  String huge=new String(new char[9*1024*1024]).replace('\0','x');
  require(run(server,"handleStore","POST","/api/store",huge,user,null).status==413,"stream body limit");
  for(int i=0;i<10;i++)run(server,"handleLogin","POST","/api/login","username=unknown&password=wrong",null,null);
  require(run(server,"handleLogin","POST","/api/login","username=unknown&password=wrong",null,null).status==429,"login rate limit");
  require(run(server,"handleAdminResetPassword","POST","/api/admin/reset-password","username=member&newPassword=changed_fixture",admin,null).status==200,"admin reset");
  require(run(server,"handleStore","GET","/api/store","",user,null).status==403,"password change invalidates session");
  System.out.println("{\"passed\":23}");
 }
}
'''


class SecurityFixTests(unittest.TestCase):
    @unittest.skipUnless(JAVA and JAVAC, 'JDK required')
    def test_real_java_auth_store_vip_and_wallet_handlers(self):
        with tempfile.TemporaryDirectory(dir=ROOT / 'runtime') as folder:
            work = Path(folder)
            (work / 'runtime').mkdir()
            (work / 'ai/predictors').mkdir(parents=True)
            (work / 'ai/predictors/ai_predict.py').touch()
            harness = work / 'SecurityFixHarness.java'
            harness.write_text(HARNESS, encoding='utf-8')
            shutil.copy2(ROOT / 'backend/lib/sqlite-jdbc-3.51.2.0.jar', work / 'sqlite-jdbc.jar')
            result = subprocess.run([JAVAC, '-encoding', 'UTF-8', '-d', str(work.relative_to(ROOT)),
                                     'backend/LottoWebServer.java', str(harness.relative_to(ROOT))], cwd=ROOT, capture_output=True)
            self.assertEqual(0, result.returncode, result.stderr.decode(errors='replace'))
            result = subprocess.run([JAVA, '-Dfile.encoding=UTF-8', '-cp', '.' + os.pathsep + 'sqlite-jdbc.jar',
                                     'SecurityFixHarness'], cwd=work, capture_output=True, timeout=30)
            self.assertEqual(0, result.returncode, result.stderr.decode(errors='replace'))
            self.assertEqual(23, json.loads(result.stdout)['passed'])


if __name__ == '__main__':
    unittest.main()
