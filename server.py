import os
import re
import json
import asyncio
from datetime import datetime
from typing import Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel
from google import genai
from google.genai import types

API_KEY = os.environ.get("GEMINI_API_KEY", "AQ.Ab8RN6KnX4PwA3c7qda9nMp13jLJoHxlM0ykfUS45ItH8jt2gg")
client = genai.Client(api_key=API_KEY)

app = FastAPI()

connected_pc_ws: Optional[WebSocket] = None
latest_screen_base64: str = ""
pending_command_futures = {}

@app.websocket("/ws/pc")
async def pc_websocket_endpoint(websocket: WebSocket):
    global connected_pc_ws, latest_screen_base64
    await websocket.accept()
    connected_pc_ws = websocket
    try:
        while True:
            data = await websocket.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "screen_result":
                latest_screen_base64 = msg.get("image", "")
                task_id = msg.get("task_id")
                if task_id in pending_command_futures:
                    pending_command_futures[task_id].set_result(msg)
            elif msg.get("type") == "cmd_result":
                task_id = msg.get("task_id")
                if task_id in pending_command_futures:
                    pending_command_futures[task_id].set_result(msg)
    except WebSocketDisconnect:
        connected_pc_ws = None

HTML_MOBILE_APP = """<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <title>나나 AI 비서</title>
    <meta name="mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-capable" content="yes">
    <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
    <meta name="theme-color" content="#FF6B8B">
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; }
        body { background: #FFF5F7; height: 100vh; display: flex; flex-direction: column; overflow: hidden; }
        .header { background: #FF6B8B; color: white; padding: 14px; font-weight: bold; display: flex; justify-content: space-between; align-items: center; box-shadow: 0 2px 8px rgba(255,107,139,0.3); }
        .header-title { display: flex; align-items: center; gap: 8px; font-size: 1.1rem; }
        .status-badge { font-size: 0.75rem; padding: 4px 8px; border-radius: 12px; background: #6C757D; color: white; }
        
        .voice-bar { background: #FFE8EE; padding: 8px 12px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #FFCCD7; }
        .voice-status { font-size: 0.85rem; color: #D6336C; font-weight: bold; }
        .btn-voice-toggle { background: #FF477E; color: white; border: none; padding: 6px 12px; border-radius: 14px; font-size: 0.8rem; font-weight: bold; cursor: pointer; }
        .btn-voice-toggle.listening { background: #28A745; animation: pulse 1.5s infinite; }

        @keyframes pulse {
            0% { transform: scale(1); }
            50% { transform: scale(1.04); }
            100% { transform: scale(1); }
        }

        .quick-actions { display: grid; grid-template-columns: repeat(4, 1fr); gap: 6px; padding: 8px 10px; background: #FFF0F5; }
        .btn-quick { background: white; border: 1px solid #FFCCD7; color: #FF477E; padding: 8px 2px; border-radius: 8px; font-size: 0.75rem; font-weight: bold; cursor: pointer; text-align: center; }
        .btn-screen { background: #FF477E; color: white; border: none; }
        
        .chat-box { flex: 1; overflow-y: auto; padding: 12px; display: flex; flex-direction: column; gap: 10px; }
        .msg { max-width: 85%; padding: 10px 14px; border-radius: 14px; font-size: 0.95rem; line-height: 1.4; word-break: break-all; }
        .msg.user { align-self: flex-end; background: #4A54F1; color: white; border-bottom-right-radius: 2px; }
        .msg.nana { align-self: flex-start; background: white; color: #333; border: 1px solid #FFE0E9; border-bottom-left-radius: 2px; box-shadow: 0 1px 4px rgba(0,0,0,0.05); }
        .screen-img { width: 100%; max-width: 320px; border-radius: 8px; border: 2px solid #FFCCD7; margin-top: 6px; display: block; }

        .input-bar { display: flex; gap: 8px; padding: 10px; background: white; border-top: 1px solid #FFE0E9; }
        .input-bar input { flex: 1; border: 1px solid #FFCCD7; border-radius: 20px; padding: 10px 16px; font-size: 1rem; outline: none; }
        .input-bar button { background: #FF6B8B; color: white; border: none; border-radius: 20px; padding: 0 18px; font-weight: bold; cursor: pointer; }
    </style>
</head>
<body>
    <div class="header">
        <div class="header-title">🌸 나나 비서</div>
        <span class="status-badge" id="pcStatus">연결 확인 중...</span>
    </div>
    
    <div class="voice-bar">
        <span class="voice-status" id="voiceStatus">🎙️ 마이크 대기 꺼짐</span>
        <button class="btn-voice-toggle" id="btnVoice" onclick="toggleVoiceListening()">호출 대기 켜기</button>
    </div>

    <div class="quick-actions">
        <button class="btn-quick btn-screen" onclick="requestScreen()">📸 화면 보기</button>
        <button class="btn-quick" onclick="sendQuickCmd('바탕화면 보여줘')">🖥️ 바탕화면</button>
        <button class="btn-quick" onclick="sendQuickCmd('메이플스토리 켜줘')">🍁 메이플</button>
        <button class="btn-quick" onclick="sendQuickCmd('유튜브 켜줘')">▶️ 유튜브</button>
    </div>

    <div class="chat-box" id="chat">
        <div class="msg nana">안녕! 휴대폰에서도 PC 제어와 모든 API 기능을 다 쓸 수 있어. 편하게 말해줘!</div>
    </div>

    <div class="input-bar">
        <input type="text" id="msgInput" placeholder="명령 또는 대화 입력..." onkeypress="if(event.keyCode==13) sendMsg()">
        <button onclick="sendMsg()">전송</button>
    </div>

    <script>
        let isListening = false;
        let isSpeaking = false;
        let recognition = null;

        async function checkStatus() {
            try {
                const res = await fetch('/api/status');
                const data = await res.json();
                const badge = document.getElementById('pcStatus');
                if (data.pc_online) {
                    badge.innerHTML = 'PC 연결됨';
                    badge.style.background = '#28A745';
                } else {
                    badge.innerHTML = 'PC 꺼짐';
                    badge.style.background = '#6C757D';
                }
            } catch (e) {}
        }
        setInterval(checkStatus, 3000);
        checkStatus();

        function speakText(text) {
            if (!window.speechSynthesis) return;
            const cleanText = text.replace(/\[PC_CMD:.+?\]/g, '').trim();
            const utter = new SpeechSynthesisUtterance(cleanText);
            utter.lang = 'ko-KR';
            utter.rate = 1.05;
            utter.pitch = 1.1;

            isSpeaking = true;
            utter.onend = () => { isSpeaking = false; };
            utter.onerror = () => { isSpeaking = false; };

            window.speechSynthesis.speak(utter);
        }

        function initRecognition() {
            const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
            if (!SpeechRecognition) {
                alert("현재 브라우저에서 음성 인식을 지원하지 않습니다.");
                return null;
            }
            const rec = new SpeechRecognition();
            rec.lang = 'ko-KR';
            rec.continuous = true;
            rec.interimResults = false;

            rec.onresult = (event) => {
                if (isSpeaking) return;

                const transcript = event.results[event.results.length - 1][0].transcript.trim();
                const vStatus = document.getElementById('voiceStatus');
                vStatus.innerText = `🎙️ 인식: "${transcript}"`;

                if (transcript.includes("나나") || transcript.includes("나나야") || isListening) {
                    let cmd = transcript.replace(/^(나나야|나나)\s*/, '');
                    if (!cmd) cmd = "안녕";
                    sendVoiceMsg(cmd);
                }
            };

            rec.onend = () => {
                if (isListening) {
                    try { rec.start(); } catch (e) {}
                }
            };
            return rec;
        }

        function toggleVoiceListening() {
            const btn = document.getElementById('btnVoice');
            const status = document.getElementById('voiceStatus');
            if (!recognition) recognition = initRecognition();
            if (!recognition) return;

            isListening = !isListening;
            if (isListening) {
                try {
                    recognition.start();
                    btn.classList.add('listening');
                    btn.innerText = '대기 끄기';
                    status.innerText = '👂 "나나야" 부르는 중...';
                } catch (e) {}
            } else {
                try {
                    recognition.stop();
                    btn.classList.remove('listening');
                    btn.innerText = '호출 대기 켜기';
                    status.innerText = '🎙️ 마이크 대기 꺼짐';
                } catch (e) {}
            }
        }

        async function requestScreen() {
            const chat = document.getElementById('chat');
            chat.innerHTML += `<div class="msg user">📸 화면 보여줘</div>`;
            chat.scrollTop = chat.scrollHeight;

            const res = await fetch('/api/screen');
            const data = await res.json();
            if (data.image) {
                chat.innerHTML += `
                    <div class="msg nana">
                        현재 PC 화면이야!
                        <img src="${data.image}" class="screen-img" onclick="window.open(this.src)">
                    </div>
                `;
            } else {
                chat.innerHTML += `<div class="msg nana">${data.reply || 'PC가 꺼져 있어.'}</div>`;
                speakText(data.reply || 'PC가 꺼져 있어.');
            }
            chat.scrollTop = chat.scrollHeight;
        }

        function sendQuickCmd(t) {
            document.getElementById('msgInput').value = t;
            sendMsg();
        }

        async function sendVoiceMsg(text) {
            sendMsgCore(text);
        }

        async function sendMsg() {
            const inp = document.getElementById('msgInput');
            const t = inp.value.trim();
            if (!t) return;
            inp.value = '';
            sendMsgCore(t);
        }

        async function sendMsgCore(t) {
            const chat = document.getElementById('chat');
            chat.innerHTML += `<div class="msg user">${t}</div>`;
            chat.scrollTop = chat.scrollHeight;

            if (t.includes("화면") && (t.includes("봐") || t.includes("보여") || t.includes("캡처") || t.includes("찍어"))) {
                requestScreen();
                return;
            }

            const res = await fetch('/api/chat', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({text: t})
            });
            const data = await res.json();
            chat.innerHTML += `<div class="msg nana">${data.reply}</div>`;
            speakText(data.reply);
            chat.scrollTop = chat.scrollHeight;
        }
    </script>
</body>
</html>"""

class ChatRequest(BaseModel):
    text: str

@app.get("/", response_class=HTMLResponse)
async def serve_home():
    return HTML_MOBILE_APP

@app.get("/api/status")
async def get_status():
    return {"pc_online": connected_pc_ws is not None}

@app.get("/api/screen")
async def get_screen():
    global connected_pc_ws
    if not connected_pc_ws:
        return {"image": None, "reply": "지금 집 컴퓨터가 꺼져 있어."}
    task_id = f"task_{datetime.now().timestamp()}"
    loop = asyncio.get_event_loop()
    fut = loop.create_future()
    pending_command_futures[task_id] = fut
    try:
        await connected_pc_ws.send_text(json.dumps({"type": "get_screen", "task_id": task_id}))
        result = await asyncio.wait_for(fut, timeout=6.0)
        return {"image": result.get("image")}
    except Exception:
        return {"image": None, "reply": "화면을 가져오는 데 실패했어."}
    finally:
        pending_command_futures.pop(task_id, None)

@app.post("/api/chat")
async def handle_chat(req: ChatRequest):
    global connected_pc_ws
    pc_online = (connected_pc_ws is not None)
    system_instruction = f"너의 이름은 나나야. 사용자의 모바일 및 PC 제어와 스케줄 관리를 돕는 만능 20대 버추얼 AI 비서야. PC 상태: {'온라인' if pc_online else '오프라인'}. PC 제어나 프로그램 실행 요청 시 [PC_CMD: 명령어] 형식을 포함해서 다정한 반말로 답해줘."
    try:
        response = client.models.generate_content(
            model="gemini-3.6-flash",
            contents=req.text,
            config=types.GenerateContentConfig(system_instruction=system_instruction, temperature=0.6)
        )
        reply = response.text.strip() if response.text else "확인했어!"
        if "[PC_CMD:" in reply and pc_online:
            match = re.search(r'\[PC_CMD:\s*(.+?)\]', reply)
            if match:
                cmd_raw = match.group(1).strip()
                task_id = f"task_{datetime.now().timestamp()}"
                loop = asyncio.get_event_loop()
                fut = loop.create_future()
                pending_command_futures[task_id] = fut
                await connected_pc_ws.send_text(json.dumps({"type": "run_command", "task_id": task_id, "query": cmd_raw}))
                clean_reply = re.sub(r'\[PC_CMD:.+?\]', '', reply).strip()
                return {"reply": clean_reply if clean_reply else f"{cmd_raw} 실행 완료!"}
        clean_reply = re.sub(r'\[PC_CMD:.+?\]', '', reply).strip()
        return {"reply": clean_reply}
    except Exception as e:
        return {"reply": f"오류 발생: {e}"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
