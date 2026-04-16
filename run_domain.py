"""
MQnet Domain Launcher
.env의 CLOUDFLARE_TUNNEL_TOKEN을 사용하여
Flask 서버 + Cloudflare Tunnel을 동시에 실행합니다.
"""
import os
import sys
import subprocess
import time
from dotenv import load_dotenv

# 가상환경 경로 보정
_venv_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".venv", "Lib", "site-packages")
if os.path.exists(_venv_path) and _venv_path not in sys.path:
    sys.path.insert(0, _venv_path)

load_dotenv()

def main():
    os.system('cls')
    PORT = int(os.environ.get('PORT', 10000))

    print("=" * 60)
    print("  🌐 MQnet — 도메인 연결 모드")
    print("=" * 60)

    # ── 1. 의존성 점검 ──
    try:
        import flask, sqlalchemy, dotenv
        try:
            import psycopg2
        except ImportError:
            import pg8000
        print("✅ [1/3] 의존성 확인 완료")
    except ImportError as e:
        print(f"❌ 필수 패키지 누락: {e}")
        print("   run.bat → 4번(venv 재설치)을 먼저 실행해 주세요.")
        input("\n엔터를 누르면 종료됩니다...")
        return

    # ── 2. Cloudflare 토큰 확인 ──
    token = os.getenv("CLOUDFLARE_TUNNEL_TOKEN", "").strip()
    if not token:
        print("❌ .env 파일에 CLOUDFLARE_TUNNEL_TOKEN이 없습니다.")
        print("   .env 파일을 확인하고 다시 실행해 주세요.")
        input("\n엔터를 누르면 종료됩니다...")
        return

    # 'service install <TOKEN>' 형식 처리
    if "service install" in token:
        token = token.split("service install")[-1].strip().strip('"').strip("'")
    elif "--token" in token:
        token = token.split("--token")[-1].strip().split()[0].strip('"').strip("'")

    print(f"✅ [2/3] Cloudflare 토큰 확인: {token[:12]}...{token[-8:]}")

    # -- 3. Start Flask server (skip if already running on port) --
    PORT = int(os.environ.get('PORT', 10000))
    print(f"\n[3/3] MQnet server on port {PORT}...")

    import socket
    def is_port_open(port):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.settimeout(1)
            return s.connect_ex(('127.0.0.1', port)) == 0

    def check_server_response(port):
        """서버 응답 체크포인트: 루트 경로의 HTTP 상태 및 리다이렉트 확인"""
        import urllib.request
        import urllib.error
        try:
            # allow_redirects=False 효과: redirect 따라가지 않음
            opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler())
            class NoRedirect(urllib.request.HTTPRedirectHandler):
                def redirect_request(self, req, fp, code, msg, headers, newurl):
                    return None  # 리다이렉트 차단
            no_redir_opener = urllib.request.build_opener(NoRedirect())
            try:
                resp = no_redir_opener.open(f"http://localhost:{port}/", timeout=5)
                print(f"   ✅ [CHECKPOINT] GET / → HTTP {resp.status} (리다이렉트 없음)")
                print(f"      Content-Type: {resp.headers.get('Content-Type', '?')}")
            except urllib.error.HTTPError as e:
                loc = e.headers.get('Location', '없음')
                print(f"   ⚠️  [CHECKPOINT] GET / → HTTP {e.code}")
                if e.code in (301, 302, 303, 307, 308):
                    print(f"      🔀 리다이렉트 감지! Location: {loc}")
                    print(f"      → 앱 내부에서 /login 으로 보내고 있습니다.")
                else:
                    print(f"      오류: {e.reason}")
        except Exception as ex:
            print(f"   ❌ [CHECKPOINT] 서버 응답 확인 실패: {ex}")

    server_proc = None
    env = os.environ.copy()
    env["DOMAIN_MODE"] = "1"
    env["PORT"] = str(PORT)

    py_exe = os.path.join(".venv", "Scripts", "python.exe")
    if not os.path.exists(py_exe):
        py_exe = sys.executable

    if is_port_open(PORT):
        print(f"   Server already running on port {PORT} — skipping app.py launch.")
        check_server_response(PORT)
    else:
        try:
            server_proc = subprocess.Popen([py_exe, "app.py"], env=env, text=True)
            print("   Waiting for server (3s)...")
            time.sleep(3)
            if server_proc.poll() is not None:
                print("ERROR: Server exited immediately. Check app.py for errors.")
                input("Press Enter to exit...")
                return
            print(f"   Server started -> http://localhost:{PORT}")
            check_server_response(PORT)
        except Exception as e:
            print(f"ERROR: Failed to start server: {e}")
            input("Press Enter to exit...")
            return

    # ── 4. Cloudflare Tunnel 가동 ──
    cf_exe = os.path.join(os.path.dirname(os.path.abspath(__file__)), "cloudflared.exe")
    if not os.path.exists(cf_exe):
        print(f"❌ cloudflared.exe를 찾을 수 없습니다: {cf_exe}")
        print("   Ai_order 폴더에서 복사해 주세요.")
        if server_proc:
            server_proc.terminate()
        input("\n엔터를 누르면 종료됩니다...")
        return

    print(f"\nStarting Cloudflare Tunnel...")
    print("-" * 60)

    cmd = [cf_exe, "tunnel", "run", "--token", token, "--protocol", "http2"]

    try:
        while True:
            try:
                result = subprocess.run(cmd)
                if result.returncode != 0:
                    print(f"\nTunnel exited (code {result.returncode}). Retrying in 5s...")
                    time.sleep(5)
            except KeyboardInterrupt:
                raise
    except KeyboardInterrupt:
        print("\n\nShutting down MQnet domain service...")
    finally:
        if server_proc:
            server_proc.terminate()
        print("All systems shut down safely.")

if __name__ == "__main__":
    main()
