"""
MQutils/db_migrate.py
DB 스키마 자동 보정 (ALTER TABLE) 모듈

사용법:
    from MQutils.db_migrate import run_migrations
    run_migrations(db)
"""
from sqlalchemy import text


# ─── ADD 목록 ───────────────────────────────────────────────
_ADD_COLUMNS = [
    # orders
    ("orders", "payment_method",    "VARCHAR(20)"),
    ("orders", "order_no",          "VARCHAR(10)"),
    ("orders", "depositor_name",    "VARCHAR(100)"),
    ("orders", "is_prepaid",        "BOOLEAN DEFAULT FALSE"),
    # users
    ("users",  "bank_name",         "VARCHAR(50)"),
    ("users",  "account_no",        "VARCHAR(50)"),
    ("users",  "hourly_rate",       "INTEGER DEFAULT 10000"),
    ("users",  "position",          "VARCHAR(50)"),
    ("users",  "work_schedule",     "JSON"),
    ("users",  "contract_start",    "DATE"),
    ("users",  "contract_end",      "DATE"),
    ("users",  "id_number_enc",     "TEXT"),
    # customers
    ("customers", "billing_key",    "VARCHAR(100)"),
    ("customers", "customer_key",   "VARCHAR(100)"),
    # stores
    ("stores", "disable_auto_logout", "BOOLEAN DEFAULT FALSE"),
    ("stores", "billing_key",       "VARCHAR(100)"),
]

# ─── DROP 목록 (파트너 기능 제거) ────────────────────────────
_DROP_COLUMNS = [
    ("stores", "recommended_by"),
    ("stores", "commission_rate"),
    ("stores", "signature_partner"),
    ("users",  "agreed_at"),
]


def run_migrations(db) -> None:
    """ADD/DROP COLUMN 보정 + PK 시퀀스 자동 복구를 한 번에 실행합니다."""
    try:
        with db.engine.connect() as conn:
            # ── 컬럼 추가 ──────────────────────────────────────
            for table, col, dtype in _ADD_COLUMNS:
                conn.execute(text(
                    f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS {col} {dtype}"
                ))
            # ── 컬럼 삭제 (파트너 기능 제거) ────────────────────
            for table, col in _DROP_COLUMNS:
                conn.execute(text(
                    f"ALTER TABLE {table} DROP COLUMN IF EXISTS {col}"
                ))
            # ── PK 시퀀스 자동 복구 (삭제 후 중복키 방지) ────────
            # users.id
            conn.execute(text(
                "SELECT setval('users_id_seq', "
                "GREATEST((SELECT COALESCE(MAX(id), 1) FROM users), 1))"
            ))
            # stores 는 varchar PK → 시퀀스 없음, 건너뜀

            conn.commit()
        print("🛠️ [DB 보정] 모든 테이블 컬럼 최신화 완료.")
    except Exception as e:
        print(f"⚠️ [DB 보정] 스킵됨 (이미 반영 또는 권한 이슈): {e}")
