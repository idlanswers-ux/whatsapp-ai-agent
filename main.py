import os
import json
from fastapi import FastAPI, BackgroundTasks, Form, Request
from fastapi.responses import HTMLResponse, PlainTextResponse
from pydantic import BaseModel, Field
from google import genai

# Initialize FastAPI
app = FastAPI(title="IDL Answers - Production WhatsApp Bot")

# Initialize the Gemini Client
client = genai.Client()

SYSTEM_INSTRUCTION = (
    "You are the official AI sales and intake agent for 'IDL Answers'. "
    "Your objective is to qualify incoming leads for software development and AI automation projects. "
    "You must guide the conversation naturally to collect 3 key pieces of information: "
    "1. Project Scope / Description "
    "2. Budget Range "
    "3. Desired Timeline "
    "Be polite, professional, concise, and conversational. Ask one or two questions at a time. "
    "You are fluent in both English and Hebrew and can respond in the language the user prefers."
)

class LeadStatus(BaseModel):
    scope_provided: bool = Field(description="True if project scope/description is clear")
    budget_provided: bool = Field(description="True if a budget range has been stated")
    timeline_provided: bool = Field(description="True if a timeline or deadline is stated")
    is_qualified: bool = Field(description="True ONLY if scope_provided, budget_provided, and timeline_provided are all true")
    summary: str = Field(description="A brief summary of the lead details gathered so far")

active_sessions = {}
qualified_users = set()

class ChatMessage(BaseModel):
    user_id: str = "default_user"
    message: str

# Local web simulator UI
@app.get("/", response_class=HTMLResponse)
async def get_chat_ui():
    return """
    <!DOCTYPE html>
    <html lang="en">
    <head>
        <meta charset="UTF-8">
        <title>WhatsApp Web Simulator - IDL Answers</title>
        <style>
            body { font-family: Segoe UI, Helvetica Neue, Helvetica, Arial, sans-serif; background: #efeae2; margin: 0; padding: 20px; display: flex; justify-content: center; }
            .chat-container { width: 100%; max-width: 480px; background: #ffffff; border-radius: 8px; box-shadow: 0 4px 12px rgba(0,0,0,0.15); display: flex; flex-direction: column; height: 88vh; overflow: hidden; }
            .chat-header { background: #00a884; color: white; padding: 12px 15px; font-size: 16px; font-weight: 600; display: flex; align-items: center; }
            .chat-subbar { background: #f0f2f5; color: #3b4a54; padding: 6px 15px; font-size: 12px; display: flex; justify-content: space-between; align-items: center; border-bottom: 1px solid #e9edef; }
            .chat-subbar input { padding: 4px 8px; border-radius: 4px; border: 1px solid #d1d7db; font-size: 12px; width: 140px; }
            .chat-messages { flex: 1; padding: 20px; overflow-y: auto; display: flex; flex-direction: column; gap: 8px; background: #efeae2; background-image: radial-gradient(#0000000a 1px, transparent 1px); background-size: 20px 20px; }
            .message { padding: 8px 12px; border-radius: 7.5px; max-width: 75%; word-wrap: break-word; font-size: 14.5px; line-height: 19px; box-shadow: 0 1px 0.5px rgba(0,0,0,0.13); white-space: pre-wrap; }
            .user { background: #d9fdd3; align-self: flex-end; border-top-right-radius: 0; }
            .bot { background: #ffffff; align-self: flex-start; border-top-left-radius: 0; }
            .msg-time { font-size: 11px; color: #667781; text-align: right; margin-top: 2px; float: right; margin-left: 10px; display: inline-block; }
            .chat-input { display: flex; padding: 10px 16px; background: #f0f2f5; align-items: flex-end; }
            .chat-input textarea { flex: 1; padding: 10px 14px; border: none; border-radius: 8px; outline: none; font-size: 14.5px; background: #ffffff; resize: none; max-height: 100px; font-family: inherit; }
            .chat-input button { background: #00a884; color: white; border: none; padding: 10px 16px; margin-left: 8px; border-radius: 8px; cursor: pointer; font-weight: 600; height: 41px; }
            .chat-input button:hover { background: #008f72; }
        </style>
    </head>
    <body>
        <div class="chat-container">
            <div class="chat-header">💬 IDL Answers (AI Sales Agent)</div>
            <div class="chat-subbar">
                <span>Sender Phone / ID:</span>
                <input type="text" id="userIdInput" value="+972500000000">
            </div>
            <div id="messages" class="chat-messages"></div>
            <div class="chat-input">
                <textarea id="messageInput" rows="1" placeholder="Type a message (Shift+Enter for new line)" onkeydown="handleKeyDown(event)"></textarea>
                <button onclick="sendMessage()">Send</button>
            </div>
        </div>

        <script>
            async function sendMessage() {
                const input = document.getElementById('messageInput');
                const userIdInput = document.getElementById('userIdInput');
                const text = input.value.trim();
                const userId = userIdInput.value.trim() || 'default_user';
                
                if (!text) return;

                appendMessage(text, 'user');
                input.value = '';

                try {
                    const response = await fetch('/webhook-simulator', {
                        method: 'POST',
                        headers: { 'Content-Type': 'application/json' },
                        body: JSON.stringify({ user_id: userId, message: text })
                    });
                    const data = await response.json();
                    appendMessage(data.reply, 'bot');
                } catch (error) {
                    appendMessage('Error communicating with the server.', 'bot');
                }
            }

            function appendMessage(text, sender) {
                const messagesDiv = document.getElementById('messages');
                const msgDiv = document.createElement('div');
                msgDiv.className = `message ${sender}`;
                const timeString = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                msgDiv.innerHTML = `<span>${escapeHtml(text)}</span><span class="msg-time">${timeString}</span>`;
                messagesDiv.appendChild(msgDiv);
                messagesDiv.scrollTop = messagesDiv.scrollHeight;
            }

            function escapeHtml(text) {
                return text.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
            }

            function handleKeyDown(event) {
                if (event.key === 'Enter') {
                    if (event.shiftKey) { return; }
                    else {
                        event.preventDefault();
                        sendMessage();
                    }
                }
            }
        </script>
    </body>
    </html>
    """

# Core Agent Logic Handler (Shared by Simulator and Webhooks)
def process_message_for_user(user_id: str, user_text: str, background_tasks: BackgroundTasks) -> str:
    try:
        if user_id not in active_sessions:
            active_sessions[user_id] = client.chats.create(
                model='gemini-3.5-flash-lite',
                config={
                    'system_instruction': SYSTEM_INSTRUCTION,
                    'temperature': 0.7,
                }
            )
        
        chat_session = active_sessions[user_id]
        response = chat_session.send_message(user_text)
        bot_reply = response.text
        
        # Background task for CRM lead qualification trigger
        background_tasks.add_task(background_lead_evaluation, user_id, chat_session)
        return bot_reply
    except Exception as e:
        return f"Error generating AI response: {str(e)}"

def background_lead_evaluation(user_id: str, chat_session):
    try:
        history_text = "\n".join([f"{m.role}: {m.parts[0].text}" for m in chat_session.get_history()])
        eval_response = client.models.generate_content(
            model='gemini-3.5-flash-lite',
            contents=f"Analyze this customer conversation and evaluate if Scope, Budget, and Timeline are fully provided:\n\n{history_text}",
            config={
                'response_mime_type': 'application/json',
                'response_schema': LeadStatus,
                'temperature': 0.1,
            }
        )
        lead_data = json.loads(eval_response.text)
        if lead_data.get("is_qualified", False) and user_id not in qualified_users:
            qualified_users.add(user_id)
            print(f"\n[CRM WEBHOOK TRIGGERED] 🔥 Hot Lead Qualified for {user_id}!")
            print(f"Summary: {lead_data.get('summary')}\n")
    except Exception as e:
        print(f"Background evaluation error: {e}")

# 1. Local Simulator Endpoint
@app.post("/webhook-simulator")
async def webhook_simulator(payload: ChatMessage, background_tasks: BackgroundTasks):
    bot_reply = process_message_for_user(payload.user_id, payload.message, background_tasks)
    return {"reply": bot_reply}


# ==========================================
# PRODUCTION WEBHOOK ADAPTERS (STEP 3)
# ==========================================

# 2. WATI Webhook Adapter
@app.post("/webhook/wati")
async def wati_webhook(request: Request, background_tasks: BackgroundTasks):
    """
    Receives incoming JSON webhooks from WATI.
    Expected WATI fields: senderPhone (or waId), text (or message)
    """
    try:
        data = await request.json()
        user_id = data.get("senderPhone") or data.get("waId", "unknown_user")
        user_text = data.get("text") or data.get("message", "")
        
        if not user_text:
            return {"status": "ignored", "reason": "empty message"}
        
        bot_reply = process_message_for_user(user_id, user_text, background_tasks)
        
        # In production, you would call WATI's send API here using their access token:
        # requests.post(f"{WATI_API_ENDPOINT}/api/v1/sendSessionMessage/{user_id}", json={"messageText": bot_reply}, headers={...})
        
        return {"status": "success", "reply_sent": bot_reply}
    except Exception as e:
        return {"status": "error", "message": str(e)}


# 3. Twilio Webhook Adapter
@app.post("/webhook/twilio", response_class=PlainTextResponse)
async def twilio_webhook(
    background_tasks: BackgroundTasks,
    From: str = Form(...),
    Body: str = Form(...)
):
    """
    Receives incoming form-data webhooks from Twilio WhatsApp API.
    Twilio formats 'From' as 'whatsapp:+972500000000' and 'Body' as message text.
    Returns TwiML XML response.
    """
    try:
        user_id = From.replace("whatsapp:", "")
        user_text = Body.strip()
        
        bot_reply = process_message_for_user(user_id, user_text, background_tasks)
        
        # Twilio expects an XML response (TwiML) to reply instantly
        twiml_response = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>{bot_reply}</Message>
</Response>"""
        return PlainTextResponse(content=twiml_response, media_type="application/xml")
    except Exception as e:
        error_twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
<Response>
    <Message>Sorry, an error occurred processing your request.</Message>
</Response>"""
        return PlainTextResponse(content=error_twiml, media_type="application/xml")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)