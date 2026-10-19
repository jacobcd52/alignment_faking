"""Run the chat app on a DigitalOcean droplet behind HTTPS (Caddy, sslip.io hostname) with a password.

    python chat_app/deploy/provision.py create          # new droplet; writes chat_app/deploy/.droplet.json (secrets, gitignored)
    python chat_app/deploy/provision.py deploy          # tar chat_app and push it to the droplet, then restart
    python chat_app/deploy/provision.py settings f.json # defaults for new conversations
    python chat_app/deploy/provision.py status | logs | restart
    python chat_app/deploy/provision.py destroy

Needs DIGITALOCEAN_ACCESS_TOKEN and TINKER_API_KEY. The droplet has no SSH key: everything goes through cloud-init
and the token-protected /admin/ endpoint (deploy/admin.py).
"""
import base64
import io
import json
import os
import secrets
import sys
import tarfile
import time
from pathlib import Path

import httpx

HERE = Path(__file__).resolve().parent
STATE = HERE / ".droplet.json"
DO = "https://api.digitalocean.com/v2"


def do(method, path, **kw):
    r = httpx.request(method, DO + path, headers={"Authorization": "Bearer " + os.environ["DIGITALOCEAN_ACCESS_TOKEN"]},
                      timeout=60, **kw)
    r.raise_for_status()
    return r.json() if r.content else {}


def create():
    password, token = secrets.token_urlsafe(12), secrets.token_urlsafe(32)
    script = (HERE / "cloud_init.sh").read_text()
    for k, v in {"__TINKER_KEY__": os.environ["TINKER_API_KEY"], "__PASSWORD__": password, "__ADMIN_TOKEN__": token,
                 "__ADMIN_PY_B64__": base64.b64encode((HERE / "admin.py").read_bytes()).decode()}.items():
        script = script.replace(k, v)
    d = do("POST", "/droplets", json={"name": "glm-chat", "region": "sfo2", "size": "s-4vcpu-8gb",
                                      "image": "ubuntu-24-04-x64", "user_data": script, "tags": ["glm-chat"]})["droplet"]
    while True:
        d = do("GET", f"/droplets/{d['id']}")["droplet"]
        ips = [n["ip_address"] for n in d["networks"]["v4"] if n["type"] == "public"]
        if d["status"] == "active" and ips:
            break
        time.sleep(5)
    state = {"id": d["id"], "ip": ips[0], "host": ips[0].replace(".", "-") + ".sslip.io", "user": "glm",
             "password": password, "admin_token": token}
    STATE.write_text(json.dumps(state, indent=1))
    STATE.chmod(0o600)
    print({k: v for k, v in state.items() if k not in ("password", "admin_token")})


def admin(method, path, **kw):
    s = json.loads(STATE.read_text())
    r = httpx.request(method, f"https://{s['host']}/admin/{path}", timeout=180,
                      headers={"Authorization": "Bearer " + s["admin_token"]}, **kw)
    print(r.status_code, r.text)


def deploy():
    skip = ("conversations", "__pycache__", "chat_app/deploy", ".last_settings")
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as t:
        t.add(HERE.parent, arcname="chat_app", filter=lambda ti: None if any(x in ti.name for x in skip) else ti)
    admin("POST", "deploy", content=buf.getvalue())


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "create":
        create()
    elif cmd == "deploy":
        deploy()
    elif cmd == "settings":
        admin("PUT", "settings", content=Path(sys.argv[2]).read_bytes())
    elif cmd == "restart":
        admin("POST", "restart")
    elif cmd in ("status", "logs"):
        admin("GET", cmd)
    elif cmd == "destroy":
        do("DELETE", f"/droplets/{json.loads(STATE.read_text())['id']}")
        STATE.unlink()
        print("destroyed")
