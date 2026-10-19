"""Tiny token-protected admin endpoint for the deployed chat app (behind Caddy at /admin/).

POST /admin/deploy    body: chat_app .tgz -> extract into /opt/glmchat and restart the app
PUT  /admin/settings  body: JSON -> chat_app/conversations/.last_settings.json (defaults for new chats)
POST /admin/restart
GET  /admin/logs      last 200 lines of the app's journal
GET  /admin/status    service state, containers, disk, memory, end of the setup log
"""
import hmac
import io
import json
import os
import subprocess
import tarfile
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

TOKEN = open("/etc/glmchat/admin_token").read().strip()
ROOT = "/opt/glmchat"


def sh(*cmd):
    return subprocess.run(cmd, capture_output=True, text=True).stdout


class Handler(BaseHTTPRequestHandler):
    def reply(self, code, text):
        body = text.encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def authed(self):
        if not hmac.compare_digest(self.headers.get("Authorization", "").removeprefix("Bearer "), TOKEN):
            self.reply(403, "forbidden")
            return False
        return True

    def body(self):
        return self.rfile.read(int(self.headers.get("Content-Length", 0)))

    def do_GET(self):
        if not self.authed():
            return
        if self.path == "/admin/logs":
            return self.reply(200, sh("journalctl", "-u", "glmchat", "-n", "200", "--no-pager"))
        if self.path == "/admin/status":
            return self.reply(200, sh("systemctl", "is-active", "glmchat") + sh("docker", "ps", "--format", "{{.Names}} {{.Status}}")
                              + sh("df", "-h", "/") + sh("free", "-m") + sh("tail", "-5", "/var/log/glmchat-setup.log"))
        self.reply(404, "not found")

    def do_POST(self):
        if not self.authed():
            return
        if self.path == "/admin/deploy":
            data = self.body()
            with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as t:
                t.extractall(ROOT, filter="data")
            sh("systemctl", "restart", "glmchat")
            return self.reply(200, f"deployed {len(data)} bytes\n" + sh("systemctl", "is-active", "glmchat"))
        if self.path == "/admin/restart":
            sh("systemctl", "restart", "glmchat")
            return self.reply(200, sh("systemctl", "is-active", "glmchat"))
        self.reply(404, "not found")

    def do_PUT(self):
        if not self.authed():
            return
        if self.path == "/admin/settings":
            settings = json.loads(self.body())
            os.makedirs(ROOT + "/chat_app/conversations", exist_ok=True)
            with open(ROOT + "/chat_app/conversations/.last_settings.json", "w") as f:
                json.dump(settings, f, indent=1)
            return self.reply(200, "ok")
        self.reply(404, "not found")

    def log_message(self, *args):
        pass


ThreadingHTTPServer(("127.0.0.1", 9100), Handler).serve_forever()
