import os
from cryptography.fernet import Fernet
from dotenv import load_dotenv

# .env 로드
load_dotenv()

class CryptoManager:
    def __init__(self):
        self.key = os.getenv('MASTER_CRYPTO_KEY')
        if not self.key:
            # 키가 없으면 생성하여 .env에 저장하도록 유도하거나 기본키 생성 (실운영에선 .env에 미리 설정 권장)
            self.key = Fernet.generate_key().decode()
            print(f"⚠️ [Security] MASTER_CRYPTO_KEY가 없습니다. 새 키를 생성했습니다: {self.key}")
            print("이 키를 .env 파일에 MASTER_CRYPTO_KEY=... 형식으로 저장하세요.")
        
        self.cipher_suite = Fernet(self.key.encode())

    def encrypt(self, plain_text):
        if not plain_text: return None
        return self.cipher_suite.encrypt(plain_text.encode()).decode()

    def decrypt(self, encrypted_text):
        if not encrypted_text: return None
        try:
            return self.cipher_suite.decrypt(encrypted_text.encode()).decode()
        except Exception:
            return "[Decryption Error: Invalid Key]"

crypto = CryptoManager()
