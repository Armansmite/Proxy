import http.server
import socketserver
import urllib.request
import urllib.parse
import base64
import json
import os
import threading
import time

DATA_DIR = "/data"
os.makedirs(DATA_DIR, exist_ok=True)
USERS_FILE = os.path.join(DATA_DIR, "users.json")

# users = { username: { "password": str, "quota": int (bytes), "used": int (bytes), "disabled": bool } }
users = {}

def load_users():
    global users
    try:
        with open(USERS_FILE, "r") as f:
            users = json.load(f)
    except:
        users = {}

def save_users():
    with open(USERS_FILE, "w") as f:
        json.dump(users, f)

load_users()

def usage_percent(user):
    quota = user.get("quota", 10*1024**3)
    if quota == 0:
        return 0
    return min(100, (user.get("used", 0) / quota) * 100)

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
        user = users.get(username)
        if not user or user["password"] != password:
            self.send_response(407)
            self.send_header("Proxy-Authenticate", 'Basic realm="Proxy"')
            self.end_headers()
            return False
        if user.get("disabled", False):
            self.send_response(403, "Account disabled")
            self.end_headers()
            return False
        if user["used"] >= user.get("quota", 10*1024**3):
            self.send_response(429, "Bandwidth limit exceeded")
            self.end_headers()
            return False
        self.username = username
        return True

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
            users[self.username]["used"] = users[self.username].get("used", 0) + len(data)
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
                        users[self.username]["used"] = users[self.username].get("used", 0) + len(data)
                        save_users()
                t1 = threading.Thread(target=forward, args=(self.connection, remote))
                t2 = threading.Thread(target=forward, args=(remote, self.connection))
                t1.start(); t2.start(); t1.join(); t2.join()
        except Exception as e:
            self.send_error(502, str(e))

    def web_ui_request(self):
        path = urllib.parse.urlparse(self.path).path

        if path == "/":
            return self.serve_dashboard()
        elif path == "/add" and self.command == "POST":
            return self.add_user()
        elif path.startswith("/delete/"):
            return self.delete_user(path.split("/")[-1])
        elif path.startswith("/toggle/"):
            return self.toggle_user(path.split("/")[-1])
        elif path.startswith("/reset/"):
            return self.reset_user(path.split("/")[-1])
        elif path == "/export":
            return self.export_config()
        else:
            self.send_error(404)

    # ---- Helper to send HTML responses ----
    def send_html(self, content, code=200):
        self.send_response(code)
        self.send_header("Content-type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(content.encode())

    def redirect(self, location="/"):
        self.send_response(302)
        self.send_header("Location", location)
        self.end_headers()

    # ---- Web UI actions ----
    def add_user(self):
        content_length = int(self.headers.get("Content-Length", 0))
        body = self.rfile.read(content_length).decode()
        params = urllib.parse.parse_qs(body)
        username = params.get("username", [""])[0].strip()
        password = params.get("password", [""])[0].strip()
        quota_gb = int(params.get("quota_gb", ["10"])[0])

        if not username or not password:
            return self.redirect("/?error=Username+and+password+required")
        if username in users:
            return self.redirect(f"/?error=User+{username}+already+exists")
        if quota_gb < 1:
            return self.redirect("/?error=Quota+must+be+at+least+1+GB")

        users[username] = {
            "password": password,
            "quota": quota_gb * 1024**3,
            "used": 0,
            "disabled": False
        }
        save_users()
        return self.redirect("/?success=User+created")

    def delete_user(self, username):
        if username in users:
            del users[username]
            save_users()
            return self.redirect("/?success=User+deleted")
        return self.redirect("/?error=User+not+found")

    def toggle_user(self, username):
        if username in users:
            users[username]["disabled"] = not users[username].get("disabled", False)
            save_users()
            status = "disabled" if users[username]["disabled"] else "enabled"
            return self.redirect(f"/?success=User+{username}+{status}")
        return self.redirect("/?error=User+not+found")

    def reset_user(self, username):
        if username in users:
            users[username]["used"] = 0
            save_users()
            return self.redirect(f"/?success=Traffic+reset+for+{username}")
        return self.redirect("/?error=User+not+found")

    def export_config(self):
        # Generate a simple text file with proxy info
        host = self.headers.get("Host", "your-app.onrender.com")
        content = "HTTP Proxy Configurations\n" + "="*30 + "\n\n"
        for username, data in users.items():
            content += f"User: {username}\nPassword: {data['password']}\nProxy URL: http://{username}:{data['password']}@{host}:80\n\n"
        self.send_response(200)
        self.send_header("Content-Disposition", "attachment; filename=proxy-config.txt")
        self.send_header("Content-type", "text/plain")
        self.end_headers()
        self.wfile.write(content.encode())

    def serve_dashboard(self):
        host = self.headers.get("Host", "your-app.onrender.com")
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        error = params.get("error", [None])[0]
        success = params.get("success", [None])[0]

        total_users = len(users)
        active_users = sum(1 for u in users.values() if not u.get("disabled", False))
        total_used = sum(u.get("used", 0) for u in users.values())
        total_quota = sum(u.get("quota", 10*1024**3) for u in users.values())

        html = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Proxy Manager</title>
    <link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
    <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/bootstrap-icons@1.10.5/font/bootstrap-icons.css">
    <style>
        body {{ background-color: #f8f9fa; }}
        .card {{ border-radius: 1rem; }}
        .user-card {{ transition: transform .2s; }}
        .user-card:hover {{ transform: scale(1.01); }}
        .progress {{ height: 1.5rem; border-radius: 1rem; }}
        .badge-disabled {{ background-color: #6c757d; }}
        .btn-group .btn {{ border-radius: 0.5rem; }}
        .toast {{ position: fixed; top: 20px; right: 20px; z-index: 9999; }}
    </style>
</head>
<body>
    <!-- Toast notifications -->
    <div aria-live="polite" aria-atomic="true" class="position-fixed top-0 end-0 p-3" style="z-index: 9999">
        <div id="liveToast" class="toast align-items-center text-bg-success border-0" role="alert" aria-live="assertive" aria-atomic="true">
            <div class="d-flex">
                <div class="toast-body"></div>
                <button type="button" class="btn-close me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
            </div>
        </div>
    </div>

    <div class="container py-4">
        <div class="d-flex justify-content-between align-items-center mb-4">
            <h1 class="mb-0"><i class="bi bi-shield-lock"></i> Proxy Manager</h1>
            <a href="/export" class="btn btn-outline-primary"><i class="bi bi-download"></i> Export config</a>
        </div>

        <!-- Stats cards -->
        <div class="row g-3 mb-4">
            <div class="col-md-3">
                <div class="card text-bg-light">
                    <div class="card-body text-center">
                        <h5 class="card-title"><i class="bi bi-people"></i> Total Users</h5>
                        <h2>{total_users}</h2>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card text-bg-light">
                    <div class="card-body text-center">
                        <h5 class="card-title"><i class="bi bi-person-check"></i> Active</h5>
                        <h2>{active_users}</h2>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card text-bg-light">
                    <div class="card-body text-center">
                        <h5 class="card-title"><i class="bi bi-graph-up"></i> Used Today</h5>
                        <h2>{total_used / (1024**3):.1f} GB</h2>
                    </div>
                </div>
            </div>
            <div class="col-md-3">
                <div class="card text-bg-light">
                    <div class="card-body text-center">
                        <h5 class="card-title"><i class="bi bi-hdd"></i> Total Quota</h5>
                        <h2>{total_quota / (1024**3):.0f} GB</h2>
                    </div>
                </div>
            </div>
        </div>

        <!-- Add user form -->
        <div class="card mb-4 shadow-sm">
            <div class="card-header"><h5 class="mb-0"><i class="bi bi-person-plus"></i> Add new user</h5></div>
            <div class="card-body">
                <form method="post" action="/add" class="row g-2 align-items-end">
                    <div class="col-md-4">
                        <label class="form-label">Username</label>
                        <input type="text" name="username" class="form-control" placeholder="username" required>
                    </div>
                    <div class="col-md-4">
                        <label class="form-label">Password</label>
                        <input type="password" name="password" class="form-control" placeholder="••••••" required>
                    </div>
                    <div class="col-md-2">
                        <label class="form-label">Quota (GB)</label>
                        <input type="number" name="quota_gb" class="form-control" value="10" min="1" required>
                    </div>
                    <div class="col-md-2">
                        <button type="submit" class="btn btn-primary w-100"><i class="bi bi-check-lg"></i> Create</button>
                    </div>
                </form>
            </div>
        </div>

        <!-- Notifications -->
        {"<div class='alert alert-danger'>" + error + "</div>" if error else ""}
        {"<div class='alert alert-success'>" + success + "</div>" if success else ""}

        <!-- User list -->
        <div class="row g-3">
"""

        if not users:
            html += '<div class="col-12"><div class="alert alert-info">No users yet. Create one above.</div></div>'
        else:
            for username, data in users.items():
                used_gb = data.get("used", 0) / (1024**3)
                quota_gb = data.get("quota", 10*1024**3) / (1024**3)
                percent = usage_percent(data)
                disabled = data.get("disabled", False)
                status_class = "disabled" if disabled else ("danger" if percent >= 100 else "success")
                status_text = "Disabled" if disabled else ("Limit reached" if percent >= 100 else "Active")
                proxy_url = f"http://{username}:{data['password']}@{host}:80"

                html += f"""
            <div class="col-md-6 col-lg-4">
                <div class="card user-card border-{status_class} shadow-sm">
                    <div class="card-body">
                        <div class="d-flex justify-content-between align-items-start mb-2">
                            <h5 class="card-title mb-0">{username}</h5>
                            <span class="badge bg-{status_class}">{status_text}</span>
                        </div>
                        <p class="card-text small text-muted">Password: {'*'*len(data['password'])}</p>
                        <div class="progress mb-2">
                            <div class="progress-bar bg-{status_class}" role="progressbar" style="width: {percent:.0f}%"
                                 aria-valuenow="{percent:.0f}" aria-valuemin="0" aria-valuemax="100">
                                {percent:.1f}%
                            </div>
                        </div>
                        <div class="d-flex justify-content-between small text-muted mb-3">
                            <span>{used_gb:.1f} GB used</span>
                            <span>{quota_gb:.0f} GB limit</span>
                        </div>
                        <div class="btn-group w-100" role="group">
                            <button class="btn btn-sm btn-outline-secondary" onclick="copyProxy('{proxy_url}')" title="Copy proxy URL">
                                <i class="bi bi-clipboard"></i> Copy
                            </button>
                            <a href="/toggle/{username}" class="btn btn-sm btn-outline-warning">
                                <i class="bi bi-{"toggle-on" if not disabled else "toggle-off"}"></i> {"Disable" if not disabled else "Enable"}
                            </a>
                            <a href="/reset/{username}" class="btn btn-sm btn-outline-info" onclick="return confirm('Reset traffic for {username}?')">
                                <i class="bi bi-arrow-counterclockwise"></i> Reset
                            </a>
                            <a href="/delete/{username}" class="btn btn-sm btn-outline-danger" onclick="return confirm('Delete {username} permanently?')">
                                <i class="bi bi-trash"></i>
                            </a>
                        </div>
                    </div>
                </div>
            </div>"""

        html += """
        </div>
    </div>

    <script src="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/js/bootstrap.bundle.min.js"></script>
    <script>
        function copyProxy(text) {
            navigator.clipboard.writeText(text).then(() => {
                const toastEl = document.getElementById('liveToast');
                toastEl.querySelector('.toast-body').textContent = 'Proxy URL copied!';
                const toast = new bootstrap.Toast(toastEl);
                toast.show();
            });
        }
        // Auto-dismiss alerts after 4 seconds
        window.setTimeout(() => {
            document.querySelectorAll('.alert').forEach(el => el.style.display = 'none');
        }, 4000);
    </script>
</body>
</html>"""
        self.send_html(html)

PORT = 8080
server = socketserver.ThreadingTCPServer(("0.0.0.0", PORT), ProxyHandler)
print(f"Server started on port {PORT}")
server.serve_forever()
