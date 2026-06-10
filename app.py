from flask import Flask, render_template, request, redirect
import os, subprocess, json, hashlib

app = Flask(__name__)

USERS_FILE = "/etc/tinyproxy/users.txt"
GOST_LIMITER_FILE = "/tmp/gost_limiter.db"  # We'll use Gost just for rate limiting? Actually no.

# We'll use a simple in-memory counter reset on restart. For persistent limits we'd need a disk.
# For now, let's just manage users, and let's optionally track usage with iptables? Too complex.
# Alternative: Use a Python proxy that can enforce limits. Let's pivot: I'll make a simple Python HTTP proxy with auth and limits.

# This approach changes: Instead of Tinyproxy, we'll use a custom Python proxy that can authenticate and count bytes.
# This is more complex but I'll simplify for the answer.

# Actually, keep Tinyproxy for the proxy engine and just manage its user file.
# Then we need a way to track/limit usage. We can wrap Tinyproxy with a small Python forwarder that counts bytes? That's tricky.

# Better: Use mitmproxy or a Python http proxy library. Let's do a minimal implementation:

import http.server
import socketserver
import base64
import threading
import time
import json
import sys

# Store users and quotas in memory (lost on restart, but fine for free tier)
users = {}
quotas = {}
used_traffic = {}

def load_users():
    # Load from a file if exists
    try:
        with open("/data/users.json", "r") as f:
            data = json.load(f)
            for u in data:
                users[u] = data[u]["password"]
                quotas[u] = data[u]["quota"]  # bytes
    except:
        pass

def save_users():
    os.makedirs("/data", exist_ok=True)
    with open("/data/users.json", "w") as f:
        json.dump({u: {"password": users[u], "quota": quotas[u]} for u in users}, f)

class ProxyHTTPRequestHandler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        self.proxy_request()
    def do_POST(self):
        self.proxy_request()
    def do_CONNECT(self):
        self.handle_connect()

    def authenticate(self):
        auth_header = self.headers.get('Proxy-Authorization')
        if not auth_header or not auth_header.startswith('Basic '):
            self.send_response(407)
            self.send_header('Proxy-Authenticate', 'Basic realm="Proxy"')
            self.end_headers()
            return False
        creds = base64.b64decode(auth_header[6:]).decode('utf-8')
        username, password = creds.split(':', 1)
        if username in users and users[username] == password:
            self.username = username
            if username in used_traffic and used_traffic[username] >= quotas.get(username, 0):
                self.send_response(429, "Bandwidth limit exceeded")
                self.end_headers()
                return False
            return True
        self.send_response(407)
        self.send_header('Proxy-Authenticate', 'Basic realm="Proxy"')
        self.end_headers()
        return False

    def proxy_request(self):
        if not self.authenticate():
            return
        # Forward the request
        import urllib.request
        url = self.path
        body = None
        if self.command in ('POST', 'PUT'):
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length)
        req = urllib.request.Request(url, data=body, headers={k: v for k, v in self.headers.items() if k not in ('Proxy-Authorization',)})
        req.method = self.command
        try:
            resp = urllib.request.urlopen(req)
            self.send_response(resp.getcode())
            for k, v in resp.getheaders():
                self.send_header(k, v)
            self.end_headers()
            data = resp.read()
            self.wfile.write(data)
            # Update traffic
            used_traffic[self.username] = used_traffic.get(self.username, 0) + len(data)
        except Exception as e:
            self.send_error(502)

    def handle_connect(self):
        if not self.authenticate():
            return
        address = self.path
        try:
            host, port = address.split(':')
            port = int(port)
            self.send_response(200, 'Connection Established')
            self.end_headers()
            import socket
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.connect((host, port))
                # Tunnel data
                def forward(source, dest):
                    while True:
                        data = source.recv(4096)
                        if not data:
                            break
                        dest.sendall(data)
                        global used_traffic
                        used_traffic[self.username] = used_traffic.get(self.username, 0) + len(data)
                import threading
                t1 = threading.Thread(target=forward, args=(self.connection, s))
                t2 = threading.Thread(target=forward, args=(s, self.connection))
                t1.start()
                t2.start()
                t1.join()
                t2.join()
        except Exception as e:
            self.send_error(502)

def run_proxy():
    PORT = 8888
    server = socketserver.ThreadingTCPServer(('0.0.0.0', PORT), ProxyHTTPRequestHandler)
    server.serve_forever()

# Web panel routes
@app.route('/')
def index():
    return render_template('index.html', users=users, quotas=quotas, used=used_traffic)

@app.route('/add', methods=['POST'])
def add_user():
    username = request.form['username']
    password = request.form['password']
    quota_gb = int(request.form['quota_gb'])
    users[username] = password
    quotas[username] = quota_gb * 1024 * 1024 * 1024
    used_traffic[username] = 0
    save_users()
    return redirect('/')

@app.route('/delete/<username>')
def delete_user(username):
    users.pop(username, None)
    quotas.pop(username, None)
    used_traffic.pop(username, None)
    save_users()
    return redirect('/')

if __name__ == '__main__':
    load_users()
    # Start proxy in background thread
    proxy_thread = threading.Thread(target=run_proxy)
    proxy_thread.daemon = True
    proxy_thread.start()
    # Start Flask
    app.run(host='0.0.0.0', port=8080)
