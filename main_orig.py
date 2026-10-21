import os
from fastapi import FastAPI, Form, Response
from openai import OpenAI
from twilio.twiml.messaging_response import MessagingResponse

app = FastAPI()

# Initialize the OpenAI client (make sure your API key is set in your environment variables: export OPENAI_API_KEY="sk-...")
client = OpenAI()

# System prompt defining the AI agent's persona and company details
SYSTEM_PROMPT = """
You are the digital customer service representative for "IDL Answers", a cutting-edge technology and software solutions company.
Your role is to assist clients on WhatsApp in a professional, polite, concise, and straight-to-the-point manner.
If you do not know the answer to a specific product or service question, politely ask the client for their phone number for a callback or offer to connect them with a human representative.
Keep your tone friendly, approachable, and use one or two emojis where appropriate.
"""

# Dictionary to store conversation history per phone number (In-Memory Context)
# Format: { "whatsapp:+972500000000": [ {"role": "user", "content": "..."}, {"role": "assistant", "content": "..."} ] }
conversation_histories = {}

# Maximum number of past messages to keep per user (to prevent token limit overflow and manage memory)
MAX_HISTORY_LENGTH = 10

@app.post("/webhook")
async def whatsapp_webhook(From: str = Form(...), Body: str = Form(...)):
    """
    Webhook endpoint where Twilio sends incoming WhatsApp messages.
    From - The sender's phone number
    Body - The message content
    """
    print(f"From: {From}, Message: {Body}")

    # Initialize history for this user if it doesn't exist yet
    if From not in conversation_histories:
        conversation_histories[From] = []

    # Append the new user message to the user's history
    conversation_histories[From].append({"role": "user", "content": Body})

    # Keep only the last N messages to prevent the context window from growing indefinitely
    if len(conversation_histories[From]) > MAX_HISTORY_LENGTH:
        conversation_histories[From] = conversation_histories[From][-MAX_HISTORY_LENGTH:]

    try:
        # Build the full messages payload including system prompt and historical context
        messages_payload = [{"role": "system", "content": SYSTEM_PROMPT}] + conversation_histories[From]

        # Send the full conversation history to OpenAI's language model
        response = client.chat.completions.create(
            model="gpt-4o",  # Or gpt-4o-mini for cost efficiency
            messages=messages_payload,
            temperature=0.7,
            max_tokens=300
        )
        
        reply_text = response.choices[0].message.content

        # Append the assistant's reply to the user's history as well
        conversation_histories[From].append({"role": "assistant", "content": reply_text})

    except Exception as e:
        print(f"Error calling OpenAI: {e}")
        reply_text = "Hi there! I'm experiencing a momentary glitch. A human representative will get back to you shortly!"

    # Build the response in TwiML format required by Twilio to send the message back to WhatsApp
    twiml_resp = MessagingResponse()
    twiml_resp.message(reply_text)

    return Response(content=str(twiml_resp), media_type="application/xml")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)