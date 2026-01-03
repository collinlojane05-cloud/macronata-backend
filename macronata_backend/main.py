from fastapi import FastAPI, HTTPException, Depends, Header, UploadFile, File
from pydantic import BaseModel
import google.generativeai as genai
import os
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime, timedelta
from typing import Optional, List
import requests
import re 

load_dotenv()

# --- 1. CONFIGURATION ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
SUPABASE_KEY = SUPABASE_SERVICE_KEY or os.environ.get("SUPABASE_KEY")
YOCO_SECRET_KEY = os.environ.get("YOCO_SECRET_KEY") 

# --- SAFE STARTUP ---
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

# AI Setup
try:
    if GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-flash-latest", system_instruction="You are Tinny, a helpful AI tutor for Macronata Academy.")
except: pass

app = FastAPI()

# --- 2. SECURITY & UTILS ---
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
    """Luhn Algorithm to validate South African ID"""
    if not id_number or not re.match(r'^\d{13}$', id_number):
        return False
    total = 0
    for i, digit in enumerate(id_number):
        n = int(digit)
        if i % 2 == 1:
            n *= 2
            if n > 9: n -= 9
        total += n
    return total % 10 == 0

# --- 3. DATA MODELS ---
class ChatMessage(BaseModel):
    role: str
    parts: List[str]

class ChatRequest(BaseModel):
    message: str
    history: List[ChatMessage] = []

class DirectMessageRequest(BaseModel):
    receiver_id: str
    content: Optional[str] = None
    media_url: Optional[str] = None
    media_type: Optional[str] = None

class BookingRequest(BaseModel):
    tutor_id: str
    scheduled_time: str
    amount_in_cents: int = 20000 
    return_url: str 
    # New: Optional business ID if booking via an institute
    business_id: Optional[str] = None

class DepositRequest(BaseModel):
    amount_in_cents: int
    return_url: str 

class VerificationRequest(BaseModel):
    id_number: str
    phone_number: str

# NEW: Model for specialized registration
class RegistrationRequest(BaseModel):
    email: str
    password: str
    full_name: str
    role: str # 'learner', 'tutor', 'parent', 'business'
    company_name: Optional[str] = None 
    child_email: Optional[str] = None

# NEW: Model for Session Control (Escrow)
class SessionControl(BaseModel):
    session_id: str
    action: str # 'start' or 'end'

# --- 4. ENDPOINTS ---

@app.get("/")
def home():
    if startup_error: return {"status": "Critical Error", "detail": startup_error}
    return {"status": "Macronata Titan Online", "database": "Connected"}

# --- 👤 SELF-HEALING PROFILE ---
@app.get("/my_profile")
def get_my_profile(user = Depends(verify_token)):
    try:
        # 1. Try to fetch existing profile
        res = supabase.table("users").select("*").eq("id", user.id).execute()
        if res.data:
            return res.data[0]

        # 2. IF MISSING: Auto-Create it (Self-Healing)
        print(f"⚠️ User {user.id} not found in public DB. Auto-creating...")
        
        # Default to 'verified' to unblock you during dev
        new_profile = {
            "id": user.id,
            "email": user.email,
            "full_name": user.user_metadata.get("full_name", "Unknown User"),
            "role": user.user_metadata.get("role", "learner"),
            "verification_status": "verified" 
        }
        supabase.table("users").insert(new_profile).execute()
        return new_profile

    except Exception as e:
        print(f"❌ Profile Error: {e}")
        raise HTTPException(500, str(e))

# --- 📝 REGISTRATION (SPECIALIZED) ---
@app.post("/register_specialized")
def register_user(req: RegistrationRequest):
    try:
        # 1. Create Auth User in Supabase
        auth_res = supabase.auth.sign_up({
            "email": req.email, 
            "password": req.password,
            "options": {"data": {"full_name": req.full_name, "role": req.role}}
        })
        
        if not auth_res.user:
            raise HTTPException(400, "Registration failed or email requires confirmation.")
            
        user_id = auth_res.user.id
        
        # 2. Handle Specialized Roles (Insert into specific tables)
        if req.role == 'business':
            # Check if businesses table exists first
            try:
                supabase.table("businesses").insert({
                    "id": user_id,
                    "company_name": req.company_name or req.full_name,
                    "is_verified": False
                }).execute()
            except: pass # Table might not exist yet if SQL wasn't run
            
        elif req.role == 'parent':
            try:
                supabase.table("parents").insert({"id": user_id}).execute()
            except: pass

        # 3. Create Wallet for everyone
        supabase.table("wallets").insert({"user_id": user_id, "balance_cents": 0}).execute()
        
        return {"status": "created", "user_id": user_id, "role": req.role}
        
    except Exception as e:
        raise HTTPException(500, str(e))

# --- 🔍 DISCOVERY ---
@app.get("/users")
def get_all_users(user = Depends(verify_token)):
    try: return supabase.table("users").select("id, full_name, role").eq("verification_status", "verified").execute().data
    except: return []

@app.get("/tutors")
def get_tutors(user = Depends(verify_token)):
    try: return supabase.table("users").select("*").eq("role", "tutor").eq("verification_status", "verified").execute().data
    except: return []

# --- ✅ VERIFICATION ---
@app.post("/submit_verification")
def submit_verification(req: VerificationRequest, user = Depends(verify_token)):
    if not validate_sa_id(req.id_number):
        raise HTTPException(400, "Invalid South African ID Number.")
    
    try:
        supabase.table("users").update({
            "id_number": req.id_number,
            "phone_number": req.phone_number,
            "verification_status": "pending_approval"
        }).eq("id", user.id).execute()
        return {"status": "submitted"}
    except Exception as e: raise HTTPException(500, str(e))

@app.post("/upload_verification_doc")
def upload_verification_doc(file: UploadFile = File(...), user = Depends(verify_token)):
    try:
        filename = f"{user.id}/{int(datetime.now().timestamp())}_{file.filename}"
        file_content = file.file.read()
        supabase.storage.from_("verification-docs").upload(filename, file_content, {"content-type": file.content_type})
        return {"status": "uploaded", "path": filename}
    except Exception as e: raise HTTPException(500, f"Upload failed: {str(e)}")

# --- 💬 MESSAGING ---
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
        data = {"sender_id": user.id, "receiver_id": msg.receiver_id, "content": msg.content, "media_url": msg.media_url, "media_type": msg.media_type}
        return {"status": "sent", "data": supabase.table("direct_messages").insert(data).execute().data[0]}
    except Exception as e: raise HTTPException(500, str(e))

@app.post("/upload") # Public media (Chat)
def upload_public_file(file: UploadFile = File(...), user = Depends(verify_token)):
    try:
        filename = f"{user.id}/{int(datetime.now().timestamp())}_{file.filename}"
        file_content = file.file.read()
        supabase.storage.from_("chat-media").upload(filename, file_content, {"content-type": file.content_type})
        public_url = supabase.storage.from_("chat-media").get_public_url(filename)
        return {"url": public_url}
    except Exception as e: raise HTTPException(500, f"Upload failed: {str(e)}")

# --- 💳 WALLET & PAYMENTS ---
@app.get("/my_wallet")
def get_my_wallet(user = Depends(verify_token)):
    try:
        wallet = supabase.table("wallets").select("*").eq("user_id", user.id).maybe_single().execute()
        if not wallet.data:
            # Auto-create wallet if missing
            supabase.table("wallets").insert({"user_id": user.id, "balance_cents": 0}).execute()
            return {"balance": 0, "locked": 0, "history": []}
            
        history = supabase.table("wallet_transactions").select("*").eq("wallet_id", user.id).order("created_at", desc=True).execute()
        
        # Include locked balance if column exists, else 0
        locked = wallet.data.get('locked_balance_cents', 0)
        
        return {"balance": wallet.data['balance_cents'], "locked": locked, "history": history.data}
    except Exception as e: raise HTTPException(500, str(e))

@app.post("/create_deposit")
def create_deposit_link(req: DepositRequest, user = Depends(verify_token)):
    if not YOCO_SECRET_KEY: return {"url": None, "simulation": True}
    try:
        headers = {"Authorization": f"Bearer {YOCO_SECRET_KEY}", "Content-Type": "application/json"}
        payload = {
            "amount": req.amount_in_cents, "currency": "ZAR",
            "cancelUrl": req.return_url, "successUrl": req.return_url, 
            "metadata": {"type": "wallet_deposit", "user_id": user.id}
        }
        res = requests.post("https://payments.yoco.com/api/checkouts", json=payload, headers=headers)
        if res.status_code in [200, 201]: return {"url": res.json()['redirectUrl'], "simulation": False}
        else: raise HTTPException(400, f"Yoco Error: {res.text}")
    except Exception as e: raise HTTPException(500, str(e))

@app.post("/confirm_deposit_simulated")
def confirm_deposit_sim(req: DepositRequest, user = Depends(verify_token)):
    try:
        current = supabase.table("wallets").select("balance_cents").eq("user_id", user.id).single().execute()
        new_bal = current.data['balance_cents'] + req.amount_in_cents
        supabase.table("wallets").update({"balance_cents": new_bal}).eq("user_id", user.id).execute()
        supabase.table("wallet_transactions").insert({
            "wallet_id": user.id, "amount_cents": req.amount_in_cents, "transaction_type": "deposit", "description": "Top Up via Yoco (Simulated)"
        }).execute()
        return {"status": "Funds Added", "new_balance": new_bal}
    except Exception as e: raise HTTPException(500, str(e))

# --- ⏱️ SESSIONS & ESCROW (NEW LOGIC) ---

@app.post("/book_with_wallet")
def book_with_wallet(b: BookingRequest, user = Depends(verify_token)):
    """
    Creates a 'Scheduled' session. Money is NOT deducted yet.
    Money is deducted when the session actually STARTS (Escrow Lock).
    """
    try:
        dt = datetime.fromisoformat(b.scheduled_time)
        
        # Insert Session
        data = {
            "tutor_id": b.tutor_id, 
            "learner_id": user.id, 
            "scheduled_time": dt.isoformat(), 
            "status": "scheduled", 
            "hourly_rate_cents": b.amount_in_cents, # Assuming input is hourly rate
            "max_cost_cap_cents": b.amount_in_cents # We cap the session cost at 1 hour for now
        }
        
        if b.business_id:
            data['business_id'] = b.business_id
            
        supabase.table("sessions").insert(data).execute()
        return {"msg": "Booking Successful", "status": "scheduled"}
        
    except Exception as e: raise HTTPException(500, str(e))

@app.post("/session_control")
def control_session(ctrl: SessionControl, user = Depends(verify_token)):
    """
    Handles START (Lock Funds) and END (Calculate & Pay).
    """
    try:
        # Fetch Session
        session_res = supabase.table("sessions").select("*").eq("id", ctrl.session_id).execute()
        if not session_res.data: raise HTTPException(404, "Session not found")
        session = session_res.data[0]
        
        if ctrl.action == "start":
            # 1. LOCK FUNDS
            learner_id = session['learner_id']
            cost_cap = session['max_cost_cap_cents']
            
            # Check Balance
            wallet_res = supabase.table("wallets").select("*").eq("user_id", learner_id).single().execute()
            learner_wallet = wallet_res.data
            
            if learner_wallet['balance_cents'] < cost_cap:
                raise HTTPException(402, "Insufficient funds to start session")
                
            # Move funds: Balance -> Locked
            new_bal = learner_wallet['balance_cents'] - cost_cap
            new_locked = learner_wallet.get('locked_balance_cents', 0) + cost_cap
            
            supabase.table("wallets").update({
                "balance_cents": new_bal,
                "locked_balance_cents": new_locked
            }).eq("user_id", learner_id).execute()
            
            # Start Timer
            supabase.table("sessions").update({
                "status": "live",
                "start_time": datetime.now().isoformat()
            }).eq("id", ctrl.session_id).execute()
            
            return {"status": "Session Started", "locked_funds": cost_cap}

        elif ctrl.action == "end":
            # 2. CALCULATE FINAL COST
            if not session.get('start_time'):
                raise HTTPException(400, "Session was never started")
                
            start_time = datetime.fromisoformat(session['start_time'].replace('Z', '+00:00'))
            end_time = datetime.now(start_time.tzinfo) # Ensure timezone match
            duration_seconds = (end_time - start_time).total_seconds()
            
            # Calculate cost (Rate per hour / 3600 * seconds)
            rate_per_sec = session['hourly_rate_cents'] / 3600.0
            final_cost = int(duration_seconds * rate_per_sec)
            
            # Safety Cap
            locked_amt = session['max_cost_cap_cents']
            if final_cost > locked_amt: final_cost = locked_amt
            if final_cost < 0: final_cost = 0 # Safety
            
            refund_amt = locked_amt - final_cost
            
            # 3. DISTRIBUTE FUNDS
            # A. Refund Learner (Unlock unused funds)
            learner_id = session['learner_id']
            l_wallet = supabase.table("wallets").select("*").eq("user_id", learner_id).single().execute().data
            
            supabase.table("wallets").update({
                "locked_balance_cents": l_wallet.get('locked_balance_cents', locked_amt) - locked_amt,
                "balance_cents": l_wallet['balance_cents'] + refund_amt
            }).eq("user_id", learner_id).execute()
            
            # B. Pay Tutor (With Commission)
            commission_rate = 0.15
            # Check Business Exception (0% comm)
            if session.get('business_id'):
                # Fetch business details to check comm rate if needed
                commission_rate = 0.0
            
            platform_fee = int(final_cost * commission_rate)
            tutor_pay = final_cost - platform_fee
            
            pay_recipient_id = session.get('business_id') or session['tutor_id']
            
            t_wallet = supabase.table("wallets").select("*").eq("user_id", pay_recipient_id).single().execute().data
            if not t_wallet:
                 # Create wallet if missing
                 supabase.table("wallets").insert({"user_id": pay_recipient_id, "balance_cents": 0}).execute()
                 t_bal = 0
            else:
                 t_bal = t_wallet['balance_cents']
            
            supabase.table("wallets").update({
                "balance_cents": t_bal + tutor_pay
            }).eq("user_id", pay_recipient_id).execute()

            # C. Close Session
            supabase.table("sessions").update({
                "status": "completed",
                "end_time": end_time.isoformat(),
                "final_cost_cents": final_cost
            }).eq("id", ctrl.session_id).execute()
            
            # D. Record Transaction Log (Simplified)
            supabase.table("wallet_transactions").insert([
                {"wallet_id": learner_id, "amount_cents": -final_cost, "transaction_type": "payment", "description": "Session Cost"},
                {"wallet_id": pay_recipient_id, "amount_cents": tutor_pay, "transaction_type": "earning", "description": "Session Earnings"}
            ]).execute()

            return {"status": "Session Ended", "duration_sec": duration_seconds, "final_cost": final_cost}

    except Exception as e:
        print(f"Session Error: {e}")
        raise HTTPException(500, str(e))

@app.get("/my_bookings")
def get_my_bookings(user = Depends(verify_token)):
    return supabase.table("sessions").select("*, tutor:users!tutor_id(full_name)").eq("learner_id", user.id).execute().data

# --- 🤖 AI TUTOR ---
@app.post("/chat")
def chat_with_tinny(request: ChatRequest, user = Depends(verify_token)):
    try:
        hist = [{"role": m.role, "parts": m.parts} for m in request.history]
        res = model.start_chat(history=hist).send_message(request.message)
        return {"reply": res.text}
    except: return {"reply": "Tinny is offline."}