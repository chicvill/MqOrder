"""
MQutils/tunnel.py
Cloudflare Tunnel 백그라운드 실행 모듈
"""
import os
import sys
import threading


def start_cloudflare_tunnel(base_dir: str, is_render: bool) -> None:
    """Cloudflare 터널을 백그라운드 스레드에서 실행합니다.

    Args:
        base_dir: 프로젝트 루트 경로 (cloudflared.exe 위치 탐색용)
        is_render: Render 클라우드 환경 여부 (http2 프로토콜 강제용)
    """
    token = os.getenv("CLOUDFLARE_TUNNEL_TOKEN")
    if not token:
        print("⚠️ [Tunnel] CLOUDFLARE_TUNNEL_TOKEN이 없어 도메인 연결을 건너뜁니다.")
        return

    def _run():
        import subprocess
        import time

        cf_exe = os.path.join(base_dir, "cloudflared.exe") if sys.platform == "win32" else "cloudflared"
        protocol = "http2" if is_render else "quic"
        print(f"🔗 [Step 2/2] 도메인 터널(Cloudflare) 연결 중... (Protocol: {protocol})")

        cmd = [cf_exe, "tunnel", "run", "--token", token, "--protocol", protocol]
        while True:
            try:
                subprocess.run(cmd, check=False)
                print(f"🔄 [Tunnel] 재연결 시도 중... (Protocol: {protocol})")
                time.sleep(5)
            except Exception as e:
                print(f"❌ [Tunnel] 실행 오류: {e}")
                break

    # 중복 실행 방지
    if not os.environ.get("TUNNEL_RUNNING"):
        os.environ["TUNNEL_RUNNING"] = "true"
        threading.Thread(target=_run, daemon=True).start()
