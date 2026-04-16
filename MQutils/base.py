# C:\Users\USER\Dev\왕궁중화요리\MQutils\base.py
import threading

class Singleton(type):
    """싱글톤 패턴을 구현하기 위한 메타클래스입니다."""
    _instances = {}
    _lock = threading.Lock()
    
    def __call__(cls, *args, **kwargs):
        if cls not in cls._instances:
            with cls._lock:
                if cls not in cls._instances:
                    cls._instances[cls] = super(Singleton, cls).__call__(*args, **kwargs)
        return cls._instances[cls]
