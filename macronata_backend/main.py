from fastapi import FastAPI, HTTPException, Depends, Header, Request, Form
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel
import google.generativeai as genai
import os
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime
from typing import Optional, List
import requests

load_dotenv()

# --- CONFIGURATION ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
YOCO_SECRET_KEY = os.environ.get("YOCO_SECRET_KEY") 

SUPABASE_KEY = SUPABASE_SERVICE_KEY or os.environ.get("SUPABASE_KEY")

if not all([GEMINI_API_KEY, SUPABASE_URL, SUPABASE_KEY]):
    print("CRITICAL: Missing Core Keys.")

# AI Setup
try:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-flash-latest", system_instruction="You are Tinny, a helpful AI tutor for Macronata Academy.")
except: pass

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
app = FastAPI()

# --- SECURITY ---
def verify_token(authorization: Optional[str] = Header(None)):
    if not authorization: raise HTTPException(401, "Missing Token")
    try:
        token = authorization.split(" ")[1]
        user = supabase.auth.get_user(token)
        if not user.user: raise Exception()
        return user.user
    except: raise HTTPException(401, "Invalid Token")

# --- MODELS ---
class ChatMessage(BaseModel):
    role: str
    parts: List[str]

class ChatRequest(BaseModel):
    message: str
    history: List[ChatMessage] = []

class BookingRequest(BaseModel):
    tutor_id: str
    scheduled_time: str
    amount_in_cents: int = 20000 

class DirectMessageRequest(BaseModel):
    receiver_id: str
    content: Optional[str] = None
    media_url: Optional[str] = None
    media_type: Optional[str] = None

# --- ENDPOINTS ---

@app.get("/")
def home(): return {"status": "Macronata Titan Online"}

@app.get("/users")
def get_all_users(user = Depends(verify_token)):
    try:
        return supabase.table("users").select("id, full_name, email, role").execute().data
    except: return []

@app.get("/tutors")
def get_tutors(user = Depends(verify_token)):
    try:
        return supabase.table("users").select("*").eq("role", "tutor").execute().data
    except: return []

# --- MESSAGING ---
@app.get("/messages/{other_user_id}")
def get_chat_history(other_user_id: str, user = Depends(verify_token)):
    try:
        return supabase.table("direct_messages").select("*")\
            .or_(f"and(sender_id.eq.{user.id},receiver_id.eq.{other_user_id}),and(sender_id.eq.{other_user_id},receiver_id.eq.{user.id})")\
            .order("created_at").execute().data
    except Exception as e: raise HTTPException(500, str(e))

@app.post("/messages")
def send_message(msg: DirectMessageRequest, user = Depends(verify_token)):
    try:
        data = {
            "sender_id": user.id, "receiver_id": msg.receiver_id,
            "content": msg.content, "media_url": msg.media_url, "media_type": msg.media_type
        }
        return {"status": "sent", "data": supabase.table("direct_messages").insert(data).execute().data[0]}
    except Exception as e: raise HTTPException(500, str(e))

# --- FEATURE 2: YOCO PAYMENTS (FIXED SUCCESS CHECK) ---
@app.post("/create_payment")
def create_payment(booking: BookingRequest, user = Depends(verify_token)):
    """
    Creates a Yoco Checkout session.
    """
    if not YOCO_SECRET_KEY:
        return {"payment_url": None, "simulation": True, "message": "Yoco Key Missing - Simulating Payment"}
    
    try:
        yoco_url = "https://payments.yoco.com/api/checkouts"
        
        headers = {
            "Authorization": f"Bearer {YOCO_SECRET_KEY}", 
            "Content-Type": "application/json"
        }
        
        payload = {
            "amount": booking.amount_in_cents,
            "currency": "ZAR",
            "cancelUrl": "http://localhost:8501/", 
            "successUrl": "http://localhost:8501/",
            "metadata": {
                "tutor_id": booking.tutor_id,
                "learner_id": user.id,
                "scheduled_time": booking.scheduled_time
            }
        }
        
        res = requests.post(yoco_url, json=payload, headers=headers)
        
        # FIX: Accept both 200 and 201 as success
        if res.status_code in [200, 201]:
            return {"payment_url": res.json()['redirectUrl'], "simulation": False}
        else:
            raise HTTPException(400, f"Yoco Error: {res.text}")
            
    except Exception as e:
        raise HTTPException(500, str(e))

@app.post("/book_session")
def book_session(b: BookingRequest, user = Depends(verify_token)):
    try:
        dt = datetime.fromisoformat(b.scheduled_time)
        data = {
            "tutor_id": b.tutor_id, "learner_id": user.id, 
            "scheduled_time": dt.isoformat(), "status": "booked", "total_cost_zar": b.amount_in_cents/100
        }
        supabase.table("sessions").insert(data).execute()
        return {"msg": "Success"}
    except Exception as e: raise HTTPException(500, str(e))

# --- FEATURE 3: WHATSAPP BOT ---
@app.post("/whatsapp")
async def whatsapp_webhook(Body: str = Form(...), From: str = Form(...)):
    print(f"WhatsApp from {From}: {Body}")
    try:
        chat = model.start_chat()
        response = chat.send_message(Body)
        tinny_reply = response.text
    except:
        tinny_reply = "I'm having trouble thinking right now. Try again later."

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <Response>
        <Message>{tinny_reply}</Message>
    </Response>"""
    return PlainTextResponse(content=twiml, media_type="application/xml")

# --- STANDARD AI CHAT ---
@app.post("/chat")
def chat_with_tinny(request: ChatRequest, user = Depends(verify_token)):
    try:
        hist = [{"role": m.role, "parts": m.parts} for m in request.history]
        res = model.start_chat(history=hist).send_message(request.message)
        return {"reply": res.text}
    except: return {"reply": "Tinny is offline."}

@app.get("/my_bookings")
def get_my_bookings(user = Depends(verify_token)):
    return supabase.table("sessions").select("*, tutor:users!tutor_id(full_name)").eq("learner_id", user.id).execute().data

@app.get("/tutor_bookings")
def get_tutor_bookings(user = Depends(verify_token)):
    return supabase.table("sessions").select("*, learner:users!learner_id(full_name, email)").eq("tutor_id", user.id).execute().data