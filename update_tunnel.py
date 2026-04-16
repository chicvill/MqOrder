"""
Cloudflare Tunnel Config Updater
Updates ai.chicvill.store -> http://127.0.0.1:10000 via API
"""
import urllib.request
import json
import os
from dotenv import load_dotenv

load_dotenv()

# ── Cloudflare 설정 ──
TUNNEL_ID  = "f950e561-4120-4b38-8754-dd8ae61b1cd3"
HOSTNAME   = "mq.chicvill.store"
SERVICE    = "http://127.0.0.1:10000"

# dash.cloudflare.com URL에서 확인
ACCOUNT_ID = input("Cloudflare Account ID 입력: ").strip()
API_TOKEN  = input("Cloudflare API Token 입력 (Zone:Edit + Tunnel:Edit 권한): ").strip()

url = f"https://api.cloudflare.com/client/v4/accounts/{ACCOUNT_ID}/cfd_tunnel/{TUNNEL_ID}/configurations"

config = {
    "config": {
        "ingress": [
            {
                "hostname": HOSTNAME,
                "service": SERVICE,
                "originRequest": {}
            },
            {
                "service": "http_status:404"
            }
        ],
        "warp-routing": {"enabled": False}
    }
}

data = json.dumps(config).encode("utf-8")
req = urllib.request.Request(
    url,
    data=data,
    method="PUT",
    headers={
        "Authorization": f"Bearer {API_TOKEN}",
        "Content-Type": "application/json"
    }
)

try:
    with urllib.request.urlopen(req) as resp:
        result = json.loads(resp.read())
        if result.get("success"):
            print(f"\nOK: Tunnel config updated!")
            print(f"   {HOSTNAME} -> {SERVICE}")
            print("\nRestart cloudflared to apply:")
            print("   Ctrl+C -> run.bat -> 2")
        else:
            print(f"\nERROR: {result.get('errors')}")
except Exception as e:
    print(f"\nERROR: {e}")
    print("\nIf 403: API token needs 'Cloudflare Tunnel' edit permission.")

input("\nPress Enter to exit...")
