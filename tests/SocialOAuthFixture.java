// Only this disposable test entry point installs a fake HTTPS transport.
import java.io.*;
import java.net.*;
import java.nio.charset.StandardCharsets;
import java.nio.file.*;
import java.util.*;

public class SocialOAuthFixture {
    public static void main(String[] args) throws Exception {
        URL.setURLStreamHandlerFactory(protocol -> "https".equals(protocol) ? new URLStreamHandler() {
            protected URLConnection openConnection(URL url) { return new MockConnection(url); }
        } : null);
        LottoWebServer.main(new String[0]);
    }
    static class MockConnection extends HttpURLConnection {
        ByteArrayOutputStream body = new ByteArrayOutputStream();
        MockConnection(URL url) { super(url); }
        public void connect() {}
        public void disconnect() {}
        public boolean usingProxy() { return false; }
        public OutputStream getOutputStream() { return body; }
        String parameter(String name) {
            String query = url.getQuery() == null ? body.toString() : url.getQuery();
            for (String item : query.split("&")) {
                String[] pair = item.split("=",2);
                try { if (URLDecoder.decode(pair[0],"UTF-8").equals(name)) return pair.length > 1 ? URLDecoder.decode(pair[1],"UTF-8") : ""; }
                catch (Exception ignore) {}
            }
            return "";
        }
        public int getResponseCode() { return "rejected".equals(parameter("code")) ? 400 : 200; }
        public InputStream getInputStream() throws IOException {
            String host=url.getHost(), path=url.getPath(), result;
            if (path.endsWith("/token") || path.endsWith("/access_token")) {
                String code=parameter("code");
                if (code.isEmpty()) throw new IOException("Fixture code missing");
                result="{\"access_token\":\"fixture_"+code+"\"}";
                Files.write(Paths.get("runtime/oauth_fixture_requests.txt"),(host+" "+path+" "+body.toString()+"\n").getBytes(StandardCharsets.UTF_8),StandardOpenOption.CREATE,StandardOpenOption.APPEND);
            } else if (path.endsWith("/debug_token")) {
                String id=parameter("input_token").replace("fixture_","");
                result="{\"data\":{\"is_valid\":true,\"app_id\":\""+(id.equals("wrong_app")?"other_app":getRequestProperty("Authorization").replace("Bearer ","").split("[|]")[0])+"\",\"user_id\":\""+id+"\"}}";
            } else if (path.endsWith("/userinfo") || path.endsWith("/me")) {
                String token=getRequestProperty("Authorization");
                if (token==null) token=getRequestProperty("access_token");
                if (token==null) throw new IOException("Fixture token missing");
                String id=token.replace("Bearer fixture_","").replace("fixture_","");
                String key=host.equals("openidconnect.googleapis.com")?"sub":"id";
                String jsonId=id.matches("[0-9]+")?id:"\""+id+"\"";
                result=id.equals("invalid_profile")?"{\"name\":\"owner_fixture\"}":"{\""+key+"\":"+jsonId+",\"name\":\"owner_fixture\",\"email\":\"owner@example.test\"}";
            } else throw new IOException("Unexpected HTTPS in fixture");
            return new ByteArrayInputStream(result.getBytes(StandardCharsets.UTF_8));
        }
    }
}
