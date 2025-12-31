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

# Use Service Key to allow Backend to manage all wallets securely
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
    amount_in_cents: int = 20000 # Default R200.00

class DirectMessageRequest(BaseModel):
    receiver_id: str
    content: Optional[str] = None
    media_url: Optional[str] = None
    media_type: Optional[str] = None

class DepositRequest(BaseModel):
    amount_in_cents: int

class WithdrawRequest(BaseModel):
    amount_in_cents: int
    bank_details: str

# --- ENDPOINTS: WALLET SYSTEM ---

@app.get("/my_wallet")
def get_my_wallet(user = Depends(verify_token)):
    """Fetches user balance and transaction history."""
    try:
        # 1. Fetch Balance
        wallet = supabase.table("wallets").select("*").eq("user_id", user.id).maybe_single().execute()
        
        # Auto-create wallet if missing (fail-safe)
        if not wallet.data:
            wallet_data = {"user_id": user.id, "balance_cents": 0}
            supabase.table("wallets").insert(wallet_data).execute()
            balance = 0
        else:
            balance = wallet.data['balance_cents']

        # 2. Fetch History
        history = supabase.table("wallet_transactions").select("*").eq("wallet_id", user.id).order("created_at", desc=True).execute()
        
        return {"balance": balance, "history": history.data}
    except Exception as e: raise HTTPException(500, str(e))

@app.post("/create_deposit")
def create_deposit_link(req: DepositRequest, user = Depends(verify_token)):
    """Creates a Yoco link to top up the digital wallet."""
    if not YOCO_SECRET_KEY:
        return {"url": None, "simulation": True}

    try:
        headers = {"Authorization": f"Bearer {YOCO_SECRET_KEY}", "Content-Type": "application/json"}
        # REPLACE with your actual Streamlit URL
        APP_URL = "https://macronata-academy.streamlit.app/" 
        
        payload = {
            "amount": req.amount_in_cents,
            "currency": "ZAR",
            "cancelUrl": APP_URL,
            "successUrl": APP_URL, 
            "metadata": {
                "type": "wallet_deposit",
                "user_id": user.id
            }
        }
        res = requests.post("https://payments.yoco.com/api/checkouts", json=payload, headers=headers)
        if res.status_code in [200, 201]:
            return {"url": res.json()['redirectUrl'], "simulation": False}
        else:
            raise HTTPException(400, f"Yoco Error: {res.text}")
    except Exception as e: raise HTTPException(500, str(e))

@app.post("/confirm_deposit_simulated")
def confirm_deposit_sim(req: DepositRequest, user = Depends(verify_token)):
    """
    Simulates a successful deposit. In production, a Yoco Webhook would trigger this.
    """
    try:
        # Get current balance
        current = supabase.table("wallets").select("balance_cents").eq("user_id", user.id).single().execute()
        new_bal = current.data['balance_cents'] + req.amount_in_cents
        
        # Update Wallet
        supabase.table("wallets").update({"balance_cents": new_bal}).eq("user_id", user.id).execute()
        
        # Log Transaction
        supabase.table("wallet_transactions").insert({
            "wallet_id": user.id,
            "amount_cents": req.amount_in_cents,
            "transaction_type": "deposit",
            "description": "Top Up via Yoco (Simulated)"
        }).execute()
        
        return {"status": "Funds Added", "new_balance": new_bal}
    except Exception as e: raise HTTPException(500, str(e))

@app.post("/book_with_wallet")
def book_with_wallet(b: BookingRequest, user = Depends(verify_token)):
    """
    Learner pays Tutor using Wallet Balance.
    Split: 85% to Tutor, 15% Platform Fee.
    """
    try:
        cost = b.amount_in_cents
        tutor_share = int(cost * 0.85)
        # Platform fee stays in the system (we don't credit it to anyone, effectively it's ours)
        
        # 1. CHECK LEARNER FUNDS
        learner_wallet = supabase.table("wallets").select("balance_cents").eq("user_id", user.id).single().execute()
        if not learner_wallet.data or learner_wallet.data['balance_cents'] < cost:
            raise HTTPException(402, "Insufficient Funds. Please Top Up your Wallet.")
        
        learner_new_bal = learner_wallet.data['balance_cents'] - cost

        # 2. GET TUTOR WALLET
        tutor_wallet = supabase.table("wallets").select("balance_cents").eq("user_id", b.tutor_id).single().execute()
        # If tutor has no wallet yet, assume 0
        tutor_old_bal = tutor_wallet.data['balance_cents'] if tutor_wallet.data else 0
        tutor_new_bal = tutor_old_bal + tutor_share

        # 3. EXECUTE TRANSFERS
        # A. Deduct from Learner
        supabase.table("wallets").update({"balance_cents": learner_new_bal}).eq("user_id", user.id).execute()
        supabase.table("wallet_transactions").insert({
            "wallet_id": user.id,
            "amount_cents": -cost,
            "transaction_type": "payment",
            "description": f"Booking Session",
            "reference_id": b.tutor_id
        }).execute()

        # B. Credit Tutor
        # Handle case where tutor wallet didn't exist
        if not tutor_wallet.data:
             supabase.table("wallets").insert({"user_id": b.tutor_id, "balance_cents": tutor_share}).execute()
        else:
             supabase.table("wallets").update({"balance_cents": tutor_new_bal}).eq("user_id", b.tutor_id).execute()
             
        supabase.table("wallet_transactions").insert({
            "wallet_id": b.tutor_id,
            "amount_cents": tutor_share,
            "transaction_type": "receiving",
            "description": "Session Payment Received",
            "reference_id": user.id
        }).execute()

        # 4. CREATE SESSION RECORD
        dt = datetime.fromisoformat(b.scheduled_time)
        session_data = {
            "tutor_id": b.tutor_id, "learner_id": user.id, 
            "scheduled_time": dt.isoformat(), "status": "confirmed", "total_cost_zar": cost/100
        }
        supabase.table("sessions").insert(session_data).execute()

        return {"msg": "Booking Successful", "balance_remaining": learner_new_bal}

    except HTTPException as he: raise he
    except Exception as e: raise HTTPException(500, str(e))

@app.post("/withdraw")
def request_withdrawal(req: WithdrawRequest, user = Depends(verify_token)):
    """Allows a tutor to withdraw funds."""
    try:
        wallet = supabase.table("wallets").select("balance_cents").eq("user_id", user.id).single().execute()
        if not wallet.data or wallet.data['balance_cents'] < req.amount_in_cents:
            raise HTTPException(400, "Insufficient funds for withdrawal.")
        
        new_bal = wallet.data['balance_cents'] - req.amount_in_cents
        
        # Deduct Funds
        supabase.table("wallets").update({"balance_cents": new_bal}).eq("user_id", user.id).execute()
        
        # Log Transaction
        supabase.table("wallet_transactions").insert({
            "wallet_id": user.id,
            "amount_cents": -req.amount_in_cents,
            "transaction_type": "withdrawal",
            "description": f"Withdrawal to {req.bank_details}"
        }).execute()
        
        return {"msg": "Withdrawal processed", "new_balance": new_bal}
    except Exception as e: raise HTTPException(500, str(e))


# --- STANDARD ENDPOINTS (Users, Chat, etc) ---

@app.get("/")
def home(): return {"status": "Macronata Wallet System Online"}

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

@app.post("/whatsapp")
async def whatsapp_webhook(Body: str = Form(...), From: str = Form(...)):
    print(f"WhatsApp from {From}: {Body}")
    try:
        chat = model.start_chat()
        res = chat.send_message(Body)
        tinny_reply = res.text
    except:
        tinny_reply = "I'm having trouble thinking right now. Try again later."

    twiml = f"""<?xml version="1.0" encoding="UTF-8"?>
    <Response><Message>{tinny_reply}</Message></Response>"""
    return PlainTextResponse(content=twiml, media_type="application/xml")

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