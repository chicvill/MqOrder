import os
import sys
from flask_socketio import SocketIO

# 로컬(Windows) 환경에서는 파이썬 3.12+ 호환성을 위해 threading을 사용합니다.
# 클라우드(Render/Linux)에서는 성능을 위해 기본값인 eventlet을 사용합니다.
async_mode = 'threading' if sys.platform == 'win32' else 'eventlet'

socketio = SocketIO(cors_allowed_origins="*", async_mode=async_mode)
