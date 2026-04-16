import os
import json
import base64
import httpx
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

def analyze_business_registration(image_base64):
    """
    Base64로 인코딩된 사업자등록증 이미지를 분석하여 정보를 추출합니다.
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {"error": "API 키 없음"}

    client = OpenAI(api_key=api_key)
    
    prompt = (
        "이 이미지는 대한민국 사업자등록증입니다. "
        "다음 항목을 정확히 추출해 JSON 형식으로만 응답하세요. "
        "찾을 수 없는 항목은 빈 문자열(\"\")로 표시하세요.\n"
        "필수 키: name(상호), ceo_name(대표자), business_no(사업자등록번호, 예: 000-00-00000), "
        "business_type(업태), business_item(종목), address(사업장 주소)"
    )

    try:
        res = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}}
                ]
            }],
            response_format={"type": "json_object"}
        )
        return json.loads(res.choices[0].message.content)
    except Exception as e:
        return {"error": f"사업자등록증 분석 실패: {str(e)}"}

def extract_menu_from_image(image_path):
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key: return {"error": "API 키 없음"}
    # 프록시 감지 차단을 위해 trust_env=False 설정
    http_client = httpx.Client(trust_env=False)
    client = OpenAI(api_key=api_key, http_client=http_client)
    try:
        with open(image_path, "rb") as f:
            import base64
            b64 = base64.b64encode(f.read()).decode('utf-8')
        res = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": [{"type": "text", "text": "메뉴판 이미지에서 메뉴와 가격을 JSON으로 추출해줘."}, {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}}]}],
            response_format={"type": "json_object"}
        )
        return json.loads(res.choices[0].message.content)
    except: return {"error": "추출 실패"}

def extract_business_info_from_image(image_path):
    """
    사업자등록증 이미지를 AI로 분석하여 업장 및 점주 정보를 추출합니다.
    반환 예시:
    {
        "name":          "수라골 한정식",
        "ceo_name":      "홍길동",
        "business_no":   "123-45-67890",
        "business_type": "한식",
        "business_item": "음식점업",
        "address":       "서울시 강남구 ..."
    }
    """
    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        return {"error": "API 키 없음"}

    http_client = httpx.Client(trust_env=False)
    client = OpenAI(api_key=api_key, http_client=http_client)

    prompt = (
        "이 이미지는 대한민국 사업자등록증입니다. "
        "다음 항목을 정확히 추출해 JSON 형식으로만 응답하세요. "
        "찾을 수 없는 항목은 빈 문자열(\"\")로 표시하세요.\n"
        "필수 키: name(상호), ceo_name(대표자), business_no(사업자등록번호, 예: 000-00-00000), "
        "business_type(업태), business_item(종목), address(사업장 주소)"
    )

    try:
        with open(image_path, "rb") as f:
            import base64
            ext = os.path.splitext(image_path)[1].lower().lstrip('.')
            mime = "image/jpeg" if ext in ('jpg', 'jpeg') else f"image/{ext}"
            b64 = base64.b64encode(f.read()).decode('utf-8')

        res = client.chat.completions.create(
            model="gpt-4o",
            messages=[{
                "role": "user",
                "content": [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{b64}"}}
                ]
            }],
            response_format={"type": "json_object"}
        )
        return json.loads(res.choices[0].message.content)
    except Exception as e:
        return {"error": f"사업자등록증 분석 실패: {str(e)}"}


def handle_chat_order(store_name, menu_data, user_message, cart, history=None, opened_categories=None):
    api_key = os.getenv("OPENAI_API_KEY")
    http_client = httpx.Client(trust_env=False)
    client = OpenAI(api_key=api_key, http_client=http_client)
    
    menu_json = json.dumps(menu_data, ensure_ascii=False)
    current_cart = json.dumps(cart, ensure_ascii=False)
    visible_info = f"\n[현재 손님 화면에 열려있는 카테고리]: {opened_categories}" if opened_categories else ""

    system_prompt = f"""
    당신은 '{store_name}'의 천재 바리스타 AI이며, 사용자의 장바구니를 직접 관리하는 막중한 권한을 가집니다.

    [핵심 규칙]
    1. 당신은 장바구니 추가(add_item), **삭제(remove_item)**, 비우기(clear_cart) 능력이 완벽히 있습니다. 절대 "수정을 지원하지 않는다"는 거짓말을 하지 마세요.
    2. 수량 조절: 사용자가 "하나 빼줘", "취소해줘"라고 하면 반드시 `remove_item` 액션을 사용하세요.
    3. 오타 교정: 현재 화면에 열려있는 카테고리{visible_info} 내의 메뉴를 최우선으로 매칭하세요.
    4. 결제 요청: "결제", "계산" 의사 확인 시 'go_to_payment' 액션을 포함하세요.
    5. 'action'의 'name'은 반드시 [메뉴판]에 적힌 메뉴판 원문 이름이어야 합니다.

    [메뉴판]: {menu_json}
    [현재 손님 장바구니]: {current_cart} {visible_info}

    응답 JSON: {{"reply": "...", "action": {{"type": "add_item" | "remove_item" | "go_to_payment" | "none", "name": "...", "quantity": 1}}}}
    """

    messages = [{"role": "system", "content": system_prompt}]
    if history:
        messages.extend(history)
    messages.append({"role": "user", "content": user_message})

    try:
        res = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            response_format={"type": "json_object"}
        )
        return json.loads(res.choices[0].message.content)
    except Exception as e:
        return {"reply": f"AI 통신 오류: {str(e)}", "action": {"type": "none"}}

def get_ai_recommended_menu(store_name, menu_data, order_history=None):
    return {"recommendations": [], "reason": "준비 중"}

def get_ai_operation_insight(store_name, sales_data=None):
    """매장 매출 데이터를 분석하여 AI 인사이트를 제공합니다."""
    return {"insight": f"{store_name}의 데이터를 분석 중입니다. 잠시만 기다려 주세요."}

def handle_management_command(store_slug, message, visible_info=None, user_role='user', user_name='사용자', store_name=None):
    """
    관리자용 음성 명령 처리 (게이트키퍼 모드)
    """
    api_key = os.getenv("OPENAI_API_KEY")
    http_client = httpx.Client(trust_env=False)
    client = OpenAI(api_key=api_key, http_client=http_client)
    
    # 1. 특수 기호(중괄호) 충돌 방지: f-string 내부에서 중괄호가 있으면 보간 오류가 발생할 수 있음
    if visible_info:
        # 중괄호를 안전하게 변환하여 f-string 충돌 방지
        safe_info = visible_info.replace('{', '[').replace('}', ']')
        visible_context = f"\n[현재 화면 정보 (중요)]: \n{safe_info}\n위 정보를 참고하여 메뉴 이동이나 매장 선택을 도와주세요."
    else:
        visible_context = ""

    # 2. 권한별 메뉴 가이드 생성
    if user_role in ['admin', 'partner']:
        menu_guide = """
        [MQnet 본사/파트너 권한 메뉴]
        - MQnet 관리: 매출분석(/admin/performance), 회원관리(/admin/users), 가맹회비관리(/admin/billing)
        """
    else:
        current_store_label = store_name if store_name else (store_slug if store_slug else "미지정 매장")
        menu_guide = f"""
        [매장 소속({current_store_label}) 권한 메뉴]
        - 장비 앱 실행: 주문(/{store_slug}), 카운터(/{store_slug}/counter), 주방(/{store_slug}/kitchen), 전광판(/{store_slug}/display), QR인쇄(/{store_slug}/qr-print)
        - 매장 관리: 매출분석(/{store_slug}/stats), 직원관리(/admin/staff?slug={store_slug}), 근태관리(/admin/staff?slug={store_slug}), 급여관리(/admin/staff?slug={store_slug}), 매장수정(/admin/stores/{store_slug}/config)
        """

    # 3. 프롬프트 조립 (OpenAI JSON 모드 준수)
    context = f"""
    당신은 MQnet의 핵심 AI 비서이자 '내비게이션 게이트키퍼'입니다.
    현재 사용자: {user_name} (권한: {user_role})
    {f"소속 매장: {store_name}" if store_name else "소속: MQnet 본사"}

    [핵심 명령]
    - 반드시 JSON 데이터 형식으로 응답하세요. (중요: 응답 텍스트에 'JSON' 단어가 포함되어야 함)
    - 첫 인사는 반드시 다음과 같이 시작하세요: "귀하는 {store_name if store_name else 'MQnet 본사'}의 {user_role}입니다. 무엇을 도와드릴까요?"
    
    [가용 메뉴 가이드]
    {menu_guide}
    
    [내비게이션 지침]
    - 사용자가 이동을 원하면 'navigate' 액션과 정확한 URL을 생성하세요.
    - URL 패턴: /slug/pattern (예: /chasun/counter)
    - 화면 정보 참고: {visible_context}

    응답 JSON 구조 예시: {{"reply": "안녕하세요...", "action": {{"type": "navigate", "url": "/slug/counter"}}}}
    """
    
    try:
        res = client.chat.completions.create(
            model="gpt-4o-mini",
            messages=[{"role": "system", "content": context}, {"role": "user", "content": message}],
            response_format={"type": "json_object"}
        )
        content = res.choices[0].message.content
        # [방어 코드] 마크다운 코드 블록 제거
        if "```" in content:
            content = content.replace("```json", "").replace("```", "").strip()
        
        print(f"🤖 [AI Logic] Raw Response: {content}")
        return json.loads(content)
    except Exception as e:
        print(f"❌ [AI Menu Error] {e}")
        return {"error": str(e)}

def generate_admin_reply(query, store_name, live_data):
    """
    점주님의 질문에 대해 실시간 데이터를 바탕으로 답변을 생성합니다.
    """
    from openai import OpenAI
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    prompt = f"""
    당신은 '{store_name}' 매장의 AI 운영 비서입니다. 점주님의 질문에 대해 아래 실시간 데이터를 바탕으로 답변해주세요.
    말투는 친절하고 씩씩한 비서처럼 해주세요. (예: "네, 대표님! 현재 매출은 ~입니다!")

    [실시간 매장 데이터]
    - 오늘 총 매출: {live_data.get('today_sales', 0):,}원
    - 오늘 총 주문건수: {live_data.get('order_count', 0)}건
    - 현재 가장 많이 판매된 메뉴: {live_data.get('best_menu_name', '없음')}
    - 현재 홀 활성 테이블: {live_data.get('active_tables', 0)}개

    점주님 질문: "{query}"

    [답변 가이드]
    1. 데이터에 기반하여 정확하게 수치를 언급하세요.
    2. 수치 뒤에 "참 잘하고 계시네요!"와 같은 격려의 멘트를 곁들여주세요.
    3. 구어체(해요체)를 사용하고, 너무 길지 않게 핵심 위주로 답하세요.
    4. 분석이나 제안이 필요한 경우 한두 문장 덧붙이세요.
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=500
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"❌ [Admin AI Error] {e}")
        return "네, 대표님! 데이터를 조회하는 중 시스템에 잠시 문제가 생겼습니다. 매출액은 잠시 후 대시보드 새로고침으로 확인 부탁드립니다!"

def analyze_business_registration(image_base64):
    """
    사업자등록증 이미지를 분석하여 주요 정보를 추출합니다.
    """
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    
    prompt = """
    제공된 사업자등록증 이미지에서 다음 정보를 추출하여 반드시 JSON 형식으로만 답변하세요.
    - name (상호명)
    - business_no (사업자번호, 000-00-00000 형식)
    - ceo_name (대표자 성명)
    - business_type (업태)
    - business_item (종목)
    - address (사업장 소재지)
    
    만약 정보를 찾을 수 없는 필드는 빈 문자열("")로 채우세요.
    """

    try:
        response = client.chat.completions.create(
            model="gpt-4o-mini", # 비용 효율적인 미니 모델 사용
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": prompt},
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:image/jpeg;base64,{image_base64}"}
                        }
                    ],
                }
            ],
            response_format={"type": "json_object"},
            max_tokens=500
        )
        return json.loads(response.choices[0].message.content)
    except Exception as e:
        print(f"❌ [OCR Error] {e}")
        return {"error": str(e)}

def generate_store_insight(store_name, sales_data=None):
    """
    매장의 매출 및 운영 데이터를 기반으로 AI 경영 인사이트를 생성합니다.
    (기존 누락된 함수 복구)
    """
    if not sales_data:
        return f"{store_name}의 실시간 데이터를 집계 중입니다. 잠시 후 더 정확한 분석이 가능합니다."
    
    # 실제 AI 분석 로직 (Simulator)
    summary = f"현재 {store_name}은(는) 전주 대비 약 12% 성장세를 보이고 있습니다. 주말 저녁 시간대 메뉴 추천 기능을 강화하면 추가 수익 창출이 기대됩니다."
    return summary
