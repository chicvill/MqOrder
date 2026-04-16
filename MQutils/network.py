# C:\Users\USER\Dev\왕궁중화요리\MQutils\network.py
import socket

def get_local_ip():
    """로컬 IP 주소를 반환합니다."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        # DNS로 연결을 시도하여 실제 외부 네트워크 IP를 가져옵니다. (실제 전송 X)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        # 실패 시 호스트네임으로 대체
        return socket.gethostbyname(socket.gethostname())
