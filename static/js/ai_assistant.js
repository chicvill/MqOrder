/**
 * MQnetAIAssistant Class (Chat Edition)
 * 객체 지향 및 이벤트 기반 설계로 어떤 웹 앱에도 즉시 이식이 가능한 AI 비서 엔진
 */
class MQnetAIAssistant {
    constructor(options = {}) {
        console.log("🚀 AI Assistant 객체 생성 시작...");
        this.storeSlug = options.storeSlug || 'none';
        this.userName = options.userName || '사용자';
        this.micBtnId = options.micBtnId || 'mgr-mic-btn';
        this.chatContainerId = options.chatContainerId || 'ai-chat-overlay';
        this.captionId = options.captionId || 'live-caption';
        
        this.onCommandProcessed = options.onCommandProcessed || null;
        this.onPartialResult = options.onPartialResult || null;
        
        this.endpoint = options.endpoint || (this.storeSlug !== 'none' 
            ? `/api/${this.storeSlug}/management-order` 
            : `/api/general/management-order`);
        
        this.isListening = false;
        this.recognition = null;
        this.synthesis = window.speechSynthesis;
        this.hideTimer = null;

        this.init();
    }

    init() {
        console.log(`🤖 MQnet AI Assistant 로딩 완료 (${this.storeSlug})`);
    }

    speak(text) {
        if (!this.synthesis) return;
        this.synthesis.cancel();
        
        const wasListening = this.isListening;
        if (wasListening) this.toggleListening();

        const uttr = new SpeechSynthesisUtterance(text);
        uttr.lang = 'ko-KR';
        const voices = this.synthesis.getVoices();
        const preferred = voices.find(v => v.lang === 'ko-KR' && (v.name.includes('Google') || v.name.includes('Female')));
        if (preferred) uttr.voice = preferred;
        
        uttr.onend = () => {
            if (wasListening && !this.isNavigating) {
                setTimeout(() => this.toggleListening(), 300);
            }
        };
        this.synthesis.speak(uttr);
    }

    handleAction(action) {
        if (!action || !action.type || action.type === 'none') return;
        
        switch (action.type) {
            case 'navigate':
                if (action.url) {
                    try {
                        const targetPath = new URL(action.url, window.location.origin).pathname.replace(/\/$/, "");
                        const currentPath = window.location.pathname.replace(/\/$/, "");

                        if (targetPath === currentPath) {
                            console.log("📍 [AI Assist] 이미 도착한 장소입니다.");
                            return;
                        }

                        // 이동 전 모든 리스너와 음성 중단 (루프 방지 원천 봉쇄)
                        this.isNavigating = true;
                        if (this.recognition) this.recognition.onend = null;
                        if (this.isListening) this.toggleListening();
                        if (this.synthesis) this.synthesis.cancel();
                        
                        this.addChatMessage("🖥️ 목적지로 안내하겠습니다.", false);
                        setTimeout(() => {
                            window.location.href = action.url;
                        }, 1000);
                    } catch (e) {
                        console.error("Critical Nav Error:", e);
                    }
                }
                break;
        }
    }

    addChatMessage(text, isUser = false, actions = []) {
        const container = document.getElementById(this.chatContainerId);
        if (!container) return;

        container.style.display = 'flex';
        
        const msgWrapper = document.createElement('div');
        msgWrapper.className = `ai-msg-wrapper ${isUser ? 'user' : 'bot'}`;
        
        let actionsHtml = "";
        if (!isUser && actions && actions.length > 0) {
            actionsHtml = `<div class="ai-msg-actions">
                ${actions.map(a => `<button onclick="window.location.href='${a.url}'" class="ai-action-chip">${a.label}</button>`).join('')}
            </div>`;
        }

        msgWrapper.innerHTML = `
            <div class="ai-bubble">
                <div class="ai-bubble-text">${text}</div>
                ${actionsHtml}
            </div>
        `;

        container.appendChild(msgWrapper);
        container.scrollTop = container.scrollHeight;

        if (!isUser) {
            clearTimeout(this.hideTimer);
            this.hideTimer = setTimeout(() => {
                // 필요 시 자동 숨김 로직 추가 가능
            }, 10000);
        }
    }

    getVisibleContext() {
        let ctx = "";
        document.querySelectorAll('.active, .selected').forEach(el => ctx += `[${el.innerText.trim()}] `);
        const main = document.querySelector('.main-content, .portal-container, body');
        ctx += "\n" + (main ? main.innerText.replace(/\s+/g, ' ').substring(0, 500) : "");
        return ctx;
    }

    toggleListening() {
        const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SR) return alert("음성 인식이 지원되지 않습니다.");

        if (this.isListening) {
            this.recognition.stop();
            return;
        }

        this.recognition = new SR();
        this.recognition.lang = 'ko-KR';
        this.recognition.interimResults = true;

        this.recognition.onstart = () => {
            this.synthesis.cancel();
            this.isListening = true;
            document.getElementById(this.micBtnId)?.classList.add('listening');
            const cap = document.getElementById(this.captionId);
            if (cap) { cap.style.display = 'block'; cap.innerText = "듣고 있어요..."; }
        };

        this.recognition.onend = () => {
            this.isListening = false;
            document.getElementById(this.micBtnId)?.classList.remove('listening');
            const cap = document.getElementById(this.captionId);
            if (cap) setTimeout(() => { cap.style.display = 'none'; }, 2000);
        };

        this.recognition.onresult = (e) => {
            let interim = "";
            for (let i = e.resultIndex; i < e.results.length; ++i) {
                if (e.results[i].isFinal) {
                    const msg = e.results[i][0].transcript;
                    this.addChatMessage(msg, true);
                    this.processCommand(msg);
                } else {
                    interim += e.results[i][0].transcript;
                }
            }
            const cap = document.getElementById(this.captionId);
            if (cap && interim) cap.innerText = interim;
        };

        this.recognition.start();
    }

    async processCommand(userText) {
        try {
            const res = await fetch(this.endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: userText, visible_info: this.getVisibleContext() })
            });
            const data = await res.json();
            
            let suggestedActions = [];
            if (data.action && data.action.type === 'navigate') {
                suggestedActions.push({ label: "페이지 이동하기", url: data.action.url });
            }

            this.addChatMessage(data.reply, false, suggestedActions);
            this.speak(data.reply);
            
            // [추가] AI의 '행동(Action)'을 실제로 수행합니다.
            if (data.action) {
                this.handleAction(data.action);
            }

            if (this.onCommandProcessed) this.onCommandProcessed(data);
        } catch (e) {
            console.error("AI Assistant Error:", e);
            this.addChatMessage("⚠️ 비서 엔진과 연결할 수 없습니다.", false);
        }
    }
}

/**
 * 전역 초기화 함수
 */
window.initMQnetAI = (options) => {
    if (window.MQnetAI) return; // 중복 생성 방지
    window.MQnetAI = new MQnetAIAssistant(options);
};
