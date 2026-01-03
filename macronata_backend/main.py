from fastapi import FastAPI, HTTPException, Depends, Header, UploadFile, File
from pydantic import BaseModel
import google.generativeai as genai
import os
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime
from typing import Optional, List
import requests
import re 

load_dotenv()

# --- CONFIGURATION ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
SUPABASE_KEY = SUPABASE_SERVICE_KEY or os.environ.get("SUPABASE_KEY")
YOCO_SECRET_KEY = os.environ.get("YOCO_SECRET_KEY") 

# --- STARTUP ---
supabase: Optional[Client] = None
startup_error = None

print("--- STARTING MACRONATA BACKEND ---")
if not SUPABASE_URL or not SUPABASE_KEY:
    startup_error = "Missing Database Keys"
else:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("✅ Database Connected.")
    except Exception as e:
        startup_error = f"Database Connection Failed: {str(e)}"

try:
    if GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-flash-latest", system_instruction="You are Tinny, a helpful AI tutor.")
except: pass

app = FastAPI()

# --- UTILS ---
def verify_token(authorization: Optional[str] = Header(None)):
    if not supabase: raise HTTPException(500, "Server Error: Database not connected.")
    if not authorization: raise HTTPException(401, "Missing Token")
    try:
        token = authorization.split(" ")[1]
        user = supabase.auth.get_user(token)
        if not user.user: raise Exception()
        return user.user
    except: raise HTTPException(401, "Invalid Token")

def validate_sa_id(id_number):
    if not id_number or not re.match(r'^\d{13}$', id_number): return False
    total = 0
    for i, digit in enumerate(id_number):
        n = int(digit)
        if i % 2 == 1:
            n *= 2
            if n > 9: n -= 9
        total += n
    return total % 10 == 0

# --- MODELS ---
class RegistrationRequest(BaseModel):
    email: str
    password: str
    full_name: str
    role: str 
    company_name: Optional[str] = None 
    child_email: Optional[str] = None

class SessionControl(BaseModel):
    session_id: str
    action: str 

class LinkChildRequest(BaseModel):
    child_email: str

class ChatRequest(BaseModel):
    message: str
    history: List[dict] = []

class BookingRequest(BaseModel):
    tutor_id: str
    scheduled_time: str
    amount_in_cents: int = 20000 
    return_url: str 
    business_id: Optional[str] = None

# --- ENDPOINTS ---

@app.get("/")
def home():
    return {"status": "Macronata Titan Online", "database": "Connected"}

# --- 📝 REGISTRATION (WITH EMAIL VERIFICATION) ---
@app.post("/register_specialized")
def register_user(req: RegistrationRequest):
    try:
        # 1. Create Auth User in Supabase
        # 'email_redirect_to' ensures they come back to your Login page after clicking the email link
        auth_res = supabase.auth.sign_up({
            "email": req.email, 
            "password": req.password,
            "options": {
                "data": {
                    "full_name": req.full_name, 
                    "role": req.role
                },
                "email_redirect_to": "http://localhost:3000/login" 
            }
        })
        
        if not auth_res.user:
            raise HTTPException(400, "Registration failed.")
            
        user_id = auth_res.user.id
        
        # 2. Handle Specialized Roles
        if req.role == 'business':
            try:
                supabase.table("businesses").insert({
                    "id": user_id,
                    "company_name": req.company_name or req.full_name,
                    "is_verified": False
                }).execute()
            except: pass 
            
        elif req.role == 'parent':
            try:
                supabase.table("parents").insert({"id": user_id}).execute()
            except: pass

        # 3. Create Wallet
        try:
            supabase.table("wallets").insert({"user_id": user_id, "balance_cents": 0}).execute()
        except: pass
        
        return {"status": "created", "user_id": user_id, "role": req.role}
        
    except Exception as e:
        raise HTTPException(500, str(e))

# --- 👨‍👩‍👧 PARENT FEATURES ---
@app.post("/link_child")
def link_child(req: LinkChildRequest, user = Depends(verify_token)):
    try:
        parent_check = supabase.table("parents").select("id").eq("id", user.id).execute()
        if not parent_check.data: raise HTTPException(403, "Only Parents can link children.")

        child_res = supabase.table("users").select("id, role").eq("email", req.child_email).single().execute()
        if not child_res.data: raise HTTPException(404, "Learner account not found.")
        
        child = child_res.data
        if child['role'] != 'learner': raise HTTPException(400, "You can only link 'Learner' accounts.")

        supabase.table("users").update({"parent_id": user.id}).eq("id", child['id']).execute()
        return {"status": "Child Linked Successfully"}
    except Exception as e: raise HTTPException(500, str(e))

@app.get("/my_children")
def get_my_children(user = Depends(verify_token)):
    try:
        children = supabase.table("users").select("*").eq("parent_id", user.id).execute().data
        enhanced_data = []
        for child in children:
            sessions = supabase.table("sessions").select("*").eq("learner_id", child['id']).eq("status", "completed").execute().data
            total_spend = sum(s['final_cost_cents'] for s in sessions)
            last_seen = sessions[0]['end_time'] if sessions else "New"
            
            enhanced_data.append({
                "profile": child,
                "stats": {
                    "sessions_count": len(sessions),
                    "total_spend_zar": total_spend / 100,
                    "last_active": last_seen
                }
            })
        return enhanced_data
    except Exception as e: raise HTTPException(500, str(e))

# --- ⏱️ SESSIONS & ESCROW ---
@app.post("/session_control")
def control_session(ctrl: SessionControl, user = Depends(verify_token)):
    try:
        session_res = supabase.table("sessions").select("*").eq("id", ctrl.session_id).single().execute()
        if not session_res.data: raise HTTPException(404, "Session not found")
        session = session_res.data
        
        if ctrl.action == "start":
            # LOCK FUNDS
            learner_id = session['learner_id']
            cost_cap = session['max_cost_cap_cents']
            
            w_res = supabase.table("wallets").select("*").eq("user_id", learner_id).single().execute()
            learner_wallet = w_res.data
            
            if learner_wallet['balance_cents'] < cost_cap: raise HTTPException(402, "Insufficient funds")
                
            supabase.table("wallets").update({
                "balance_cents": learner_wallet['balance_cents'] - cost_cap,
                "locked_balance_cents": learner_wallet.get('locked_balance_cents', 0) + cost_cap
            }).eq("user_id", learner_id).execute()
            
            supabase.table("sessions").update({
                "status": "live", "start_time": datetime.now().isoformat()
            }).eq("id", ctrl.session_id).execute()
            
            return {"status": "Session Started"}

        elif ctrl.action == "end":
            # CALCULATE COST
            start_time = datetime.fromisoformat(session['start_time'].replace('Z', '+00:00'))
            end_time = datetime.now(start_time.tzinfo)
            duration = (end_time - start_time).total_seconds()
            
            rate_per_sec = session['hourly_rate_cents'] / 3600.0
            final_cost = int(duration * rate_per_sec)
            locked_amt = session['max_cost_cap_cents']
            
            if final_cost > locked_amt: final_cost = locked_amt
            refund_amt = locked_amt - final_cost
            
            # REFUND LEARNER
            learner_id = session['learner_id']
            l_wallet = supabase.table("wallets").select("*").eq("user_id", learner_id).single().execute().data
            supabase.table("wallets").update({
                "locked_balance_cents": l_wallet.get('locked_balance_cents', locked_amt) - locked_amt,
                "balance_cents": l_wallet['balance_cents'] + refund_amt
            }).eq("user_id", learner_id).execute()
            
            # PAY TUTOR/BUSINESS
            pay_recipient_id = session.get('business_id') or session['tutor_id']
            t_wallet = supabase.table("wallets").select("*").eq("user_id", pay_recipient_id).single().execute().data
            if not t_wallet: # Create if missing
                 supabase.table("wallets").insert({"user_id": pay_recipient_id, "balance_cents": 0}).execute()
                 t_bal = 0
            else: t_bal = t_wallet['balance_cents']

            supabase.table("wallets").update({"balance_cents": t_bal + final_cost}).eq("user_id", pay_recipient_id).execute()

            # CLOSE SESSION
            supabase.table("sessions").update({
                "status": "completed", "end_time": end_time.isoformat(), "final_cost_cents": final_cost
            }).eq("id", ctrl.session_id).execute()
            
            return {"status": "Session Ended", "cost": final_cost}

    except Exception as e: raise HTTPException(500, str(e))

# --- 🤖 AI TUTOR ---
@app.post("/chat")
def chat_with_tinny(request: ChatRequest, user = Depends(verify_token)):
    try:
        res = model.start_chat(history=[]).send_message(request.message)
        return {"reply": res.text}
    except: return {"reply": "Tinny is offline."}