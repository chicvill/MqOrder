// MQnet Dashboard Core Library
// ---------------------------------------------------------

/**
 * 매장 탭 전환 (Dashboard Tabs)
 */
function switchStoreTab(storeId, btn) {
    document.querySelectorAll('.store-pane').forEach(p => p.classList.remove('active'));
    document.querySelectorAll('.store-tab-btn').forEach(b => b.classList.remove('active'));
    
    const targetPane = document.getElementById('tab-pane-' + storeId);
    if (targetPane) targetPane.classList.add('active');
    if (btn) btn.classList.add('active');
}

/**
 * 매장 복제 시스템 (Partner Only)
 */
async function cloneStore(sid) {
    if(!confirm("이 매장을 복제하여 시연용 데모 매장을 만드시겠습니까?\n(원본의 메뉴와 디자인 설정이 그대로 복사됩니다)")) return;
    try {
        const r = await fetch('/api/admin/store/clone', {
            method: 'POST', 
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({source_id: sid})
        });
        const d = await r.json();
        if(d.status === 'success') {
            alert(d.message);
            location.reload();
        } else {
            alert(d.message);
        }
    } catch(e) { 
        alert('복제 실패: ' + e); 
    }
}

/**
 * 데모 매장 삭제 (Partner Only)
 */
async function deleteDemo(sid) {
    if(!confirm("[주의] 데모 매장을 삭제하시겠습니까?\n모든 데이터가 영구 삭제됩니다.")) return;
    try {
        const r = await fetch(`/admin/stores/${sid}/delete`, { method: 'POST' });
        if(r.ok) {
            location.reload();
        } else {
            alert('삭제 권한이 없거나 오류가 발생했습니다.');
        }
    } catch(e) { 
        alert('삭제 실패: ' + e); 
    }
}

/**
 * 현장 근로자 출근 처리
 */
async function workerCheckIn(slug) {
    if(!confirm('출근 처리하시겠습니까?')) return;
    const r = await fetch(`/api/${slug}/attendance/check-in`, { method: 'POST' });
    const d = await r.json();
    if (d.status === 'error') alert(d.message);
    return d;
}

/**
 * 현장 근로자 퇴근 처리
 */
async function workerCheckOut(slug) {
    if(!confirm('퇴근 처리하시겠습니까?')) return;
    const r = await fetch(`/api/${slug}/attendance/check-out`, { method: 'POST' });
    const d = await r.json();
    if (d.status === 'error') alert(d.message);
    return d;
}
