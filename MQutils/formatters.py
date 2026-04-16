import re

def format_phone(value):
    """전화번호 하이픈(-) 자동 삽입 포맷터 (500 에러 원천 차단)"""
    try:
        if not value: return "-"
        s_val = str(value).strip()
        # 숫자만 추출
        clean = re.sub(r'[^0-9]', '', s_val)
        
        if not clean: return s_val 
        
        if len(clean) == 11:
            return f"{clean[:3]}-{clean[3:7]}-{clean[7:]}"
        elif len(clean) == 10:
            if clean.startswith('010'): # 010-123-4567
                return f"{clean[:3]}-{clean[3:6]}-{clean[6:]}"
            elif clean.startswith('02'):
                return f"02-{clean[2:6]}-{clean[6:]}" if len(clean) == 10 else f"02-{clean[2:5]}-{clean[5:]}"
            else:
                return f"{clean[:3]}-{clean[3:6]}-{clean[6:]}"
        return s_val
    except:
        return str(value) if value else "-"
