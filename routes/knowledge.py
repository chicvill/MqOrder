from flask import Blueprint, render_template, request, jsonify, session, redirect, url_for, flash
import os
from models import db, KnowledgeNote
from datetime import datetime
from functools import wraps

knowledge_bp = Blueprint('knowledge', __name__)

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('login', next=request.url))
        if session.get('role') not in ['admin', 'owner']:
            flash("권한이 없습니다.")
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

@knowledge_bp.route('/knowledge')
@admin_required
def index():
    notes = KnowledgeNote.query.order_by(KnowledgeNote.category, KnowledgeNote.title).all()
    # Unique categories for filtering
    categories = sorted(list(set(note.category for note in notes)))
    return render_template('knowledge.html', notes=notes, categories=categories)

@knowledge_bp.route('/knowledge/save', methods=['POST'])
@admin_required
def save_note():
    try:
        data = request.json
        note_id = data.get('id')
        
        if note_id:
            note = KnowledgeNote.query.get(note_id)
            if not note:
                return jsonify({'success': False, 'message': 'Note not found'}), 404
        else:
            note = KnowledgeNote()
            db.session.add(note)

        note.category = data.get('category')
        note.title = data.get('title')
        note.content = data.get('content')
        note.links = data.get('links', [])
        
        db.session.commit()
        return jsonify({'success': True, 'id': note.id})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

@knowledge_bp.route('/knowledge/delete/<int:note_id>', methods=['DELETE'])
@admin_required
def delete_note(note_id):
    try:
        note = KnowledgeNote.query.get(note_id)
        if not note:
            return jsonify({'success': False, 'message': 'Note not found'}), 404
        
        db.session.delete(note)
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500

from MQutils.crypto import crypto

@knowledge_bp.route('/knowledge/decrypt', methods=['POST'])
@admin_required
def decrypt_content():
    try:
        data = request.json
        encrypted_text = data.get('text')
        # Check if it's already decrypted (toggle back)
        if data.get('is_visible'):
            # Just returning success to let UI handle the re-hiding
            return jsonify({'success': True, 'action': 'hide'})
            
        if encrypted_text and encrypted_text.startswith('gAAAA'):
            decrypted = crypto.decrypt(encrypted_text)
            return jsonify({'success': True, 'decrypted': decrypted, 'action': 'show'})
        return jsonify({'success': False, 'message': 'Invalid encrypted text'}), 400
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)}), 500

@knowledge_bp.route('/knowledge/backup')
@admin_required
def backup_data():
    notes = KnowledgeNote.query.all()
    data = [n.to_dict() for n in notes]
    import json
    from flask import Response
    return Response(
        json.dumps(data, ensure_ascii=False, indent=4),
        mimetype='application/json',
        headers={'Content-Disposition': 'attachment;filename=mqnet_knowledge_backup.json'}
    )

@knowledge_bp.route('/knowledge/restore', methods=['POST'])
@admin_required
def restore_data():
    if 'file' not in request.files:
        return jsonify({'success': False, 'message': 'No file uploaded'})
    
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'message': 'No selected file'})

    try:
        import json
        data = json.load(file)
        # Clear existing and restore
        KnowledgeNote.query.delete()
        for item in data:
            note = KnowledgeNote(
                category=item['category'],
                title=item['title'],
                content=item['content'],
                links=item.get('links', [])
            )
            db.session.add(note)
        db.session.commit()
        return jsonify({'success': True, 'message': f'{len(data)}개의 노트를 성공적으로 복구했습니다.'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})

@knowledge_bp.route('/knowledge/ai_ask', methods=['POST'])
@admin_required
def ai_ask():
    try:
        from openai import OpenAI
        client = OpenAI(api_key=os.getenv('OPENAI_API_KEY'))
        
        question = request.json.get('question')
        if not question:
            return jsonify({'success': False, 'message': 'No question provided'})
            
        # 모든 노트를 가져와서 컨텍스트 구성 (노트가 아주 많아지면 RAG 방식으로 개선 필요)
        notes = KnowledgeNote.query.all()
        context = "\n\n".join([f"Category: {n.category}\nTitle: {n.title}\nContent: {n.content}" for n in notes])
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=[
                {"role": "system", "content": f"당신은 사용자의 기술 지붕 지식 창고를 관리하는 똑똑한 비서입니다. 제공된 [지식 내역]을 바탕으로 사용자의 질문에 친절하고 정확하게 답변하세요. 답변은 마크다운 형식을 사용하세요.\n\n[지식 내역]\n{context}"},
                {"role": "user", "content": question}
            ]
        )
        
        answer = response.choices[0].message.content
        return jsonify({'success': True, 'answer': answer})
    except Exception as e:
        return jsonify({'success': False, 'message': str(e)})

@knowledge_bp.route('/knowledge/init', methods=['POST'])
@admin_required
def init_data():
    """Initializes the knowledge base with the 8 core topics."""
    try:
        # Check if already initialized to avoid duplicates (optional)
        if KnowledgeNote.query.first():
            return jsonify({'success': False, 'message': 'Data already exists'})

        initial_data = [
            {
                "category": "네트워크",
                "title": "Network & Hosting",
                "content": "### Flask (Backend)\n- 파이썬 기반 마이크로 웹 프레임워크.\n- **용도**: API 서버 구축, 데이터 처리 로직 수행.\n\n### Cloudflare (Security)\n- **용도**: DNS 관리, SSL 보호, WAF 보안.\n\n### Render (PaaS)\n- 서버 호스팅 및 자동 배포 기술.",
                "links": ["https://render.com", "https://cloudflare.com"]
            },
            {
                "category": "시스템 구축",
                "title": "SaaS Architecture",
                "content": "### 전체 구성도\n- 가비아(도메인) -> Cloudflare(DNS) -> GitHub(코드) -> Render/Vercel(배포) -> Supabase(DB)\n- **관리 전략**: 모든 인프라를 클라우드로 구성하여 무중단 운영 목표.",
                "links": []
            },
            # ... other topics can be added here or via UI
        ]
        
        for item in initial_data:
            note = KnowledgeNote(
                category=item['category'],
                title=item['title'],
                content=item['content'],
                links=item['links']
            )
            db.session.add(note)
        
        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'message': str(e)})
