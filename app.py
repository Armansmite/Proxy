import http.server
import socketserver
import urllib.request
import urllib.parse
import base64
import json
import os
import threading

DATA_DIR = "/data"
os.makedirs(DATA_DIR, exist_ok=True)
USERS_FILE = os.path.join(DATA_DIR, "users.json")

users, quotas, used_traffic = {}, {}, {}

def load_users():
    global users, quotas, used_traffic
    try:
        with open(USERS_FILE, "r") as f:
            data = json.load(f)
            users = data.get("users", {})
            quotas = data.get("quotas", {})
            used_traffic = data.get("used_traffic", {})
    except:
        pass

def save_users():
    with open(USERS_FILE, "w") as f:
        json.dump({"users": users, "quotas": quotas, "used_traffic": used_traffic}, f)

load_users()

class ProxyHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        self.handle_request()
    def do_POST(self):
        self.handle_request()
    def do_CONNECT(self):
        self.handle_connect()

    def handle_request(self):
        parsed = urllib.parse.urlparse(self.path)
        if parsed.scheme in ("http", "https"):
            return self.proxy_request()
        return self.web_ui_request()

    def authenticate(self):
        auth = self.headers.get("Proxy-Authorization")
        if not auth or not auth.startswith("Basic "):
            self.send_response(407)
            self.send_header("Proxy-Authenticate", 'Basic realm="Proxy"')
            self.end_headers()
            return False
        creds = base64.b64decode(auth[6:]).decode()
        username, password = creds.split(":", 1)
        if username in users and users[username] == password:
            if used_traffic.get(username, 0) >= quotas.get(username, 10*1024*1024*1024):
                self.send_response(429, "Bandwidth limit exceeded")
                self.end_headers()
                return False
            self.username = username
            return True
        self.send_response(407)
        self.send_header("Proxy-Authenticate", 'Basic realm="Proxy"')
        self.end_headers()
        return False

    def proxy_request(self):
        if not self.authenticate():
            return
        url = self.path
        try:
            body = None
            if self.command in ("POST", "PUT"):
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length)
            req = urllib.request.Request(url, data=body, method=self.command)
            for key in list(self.headers.keys()):
                if key.lower() in ("proxy-authorization", "proxy-connection", "host"):
                    continue
                req.add_header(key, self.headers[key])
            resp = urllib.request.urlopen(req)
            self.send_response(resp.getcode())
            for k, v in resp.getheaders():
                self.send_header(k, v)
            self.end_headers()
            data = resp.read()
            self.wfile.write(data)
            used_traffic[self.username] = used_traffic.get(self.username, 0) + len(data)
            save_users()
        except Exception as e:
            self.send_error(502, str(e))

    def handle_connect(self):
        if not self.authenticate():
            return
        host, port = self.path.split(":")
        port = int(port)
        self.send_response(200, "Connection Established")
        self.end_headers()
        try:
            import socket
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as remote:
                remote.connect((host, port))
                def forward(src, dst):
                    while True:
                        data = src.recv(8192)
                        if not data:
                            break
                        dst.sendall(data)
                        used_traffic[self.username] = used_traffic.get(self.username, 0) + len(data)
                        save_users()
                t1 = threading.Thread(target=forward, args=(self.connection, remote))
                t2 = threading.Thread(target=forward, args=(remote, self.connection))
                t1.start(); t2.start(); t1.join(); t2.join()
        except Exception as e:
            self.send_error(502, str(e))

    def web_ui_request(self):
        if self.path == "/":
            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()
            host = self.headers.get("Host", "your-app.onrender.com")
            html = f"""<!DOCTYPE html>
<html>
<head><title>HTTP Proxy Manager</title>
<style>body{{font-family:sans-serif;max-width:600px;margin:auto;padding:20px}}
table{{width:100%;border-collapse:collapse}}td,th{{padding:8px;border-bottom:1px solid #ddd}}th{{background:#f5f5f5}}form{{margin:20px 0}}input,button{{padding:6px}}</style></head>
<body>
<h1>HTTP Proxy Manager</h1>
<p><strong>Proxy address:</strong> {host} (port 80/443)</p>
<h2>Add user (10 GB quota)</h2>
<form method="post" action="/add">
<input name="username" placeholder="Username" required>
<input name="password" type="password" placeholder="Password" required>
<input name="quota_gb" type="number" value="10" min="1" required>
<button type="submit">Create</button>
</form>
<h2>Active users</h2>
<table>
<tr><th>Username</th><th>Password</th><th>Quota (GB)</th><th>Used (GB)</th><th>Action</th></tr>"""
            for u in users:
                quota_gb = quotas.get(u, 10*1024*1024*1024) / (1024**3)
                used_gb = used_traffic.get(u, 0) / (1024**3)
                html += f"<tr><td>{u}</td><td>{'*'*len(users[u])}</td><td>{quota_gb:.1f}</td><td>{used_gb:.2f}</td><td><a href='/delete/{u}'>Delete</a></td></tr>"
            html += "</table></body></html>"
            self.wfile.write(html.encode())
        elif self.path.startswith("/delete/"):
            username = self.path.split("/")[-1]
            users.pop(username, None)
            quotas.pop(username, None)
            used_traffic.pop(username, None)
            save_users()
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()
        elif self.path == "/add" and self.command == "POST":
            content_length = int(self.headers.get("Content-Length", 0))
            body = self.rfile.read(content_length).decode()
            params = urllib.parse.parse_qs(body)
            username = params.get("username", [""])[0]
            password = params.get("password", [""])[0]
            quota_gb = int(params.get("quota_gb", ["10"])[0])
            users[username] = password
            quotas[username] = quota_gb * 1024**3
            used_traffic[username] = 0
            save_users()
            self.send_response(302)
            self.send_header("Location", "/")
            self.end_headers()
        else:
            self.send_error(404)

PORT = 8080
server = socketserver.ThreadingTCPServer(("0.0.0.0", PORT), ProxyHandler)
print(f"Server started on port {PORT}")
server.serve_forever()
