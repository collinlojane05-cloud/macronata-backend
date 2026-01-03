from fastapi import FastAPI, HTTPException, Depends, Header, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
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

# --- 1. CONFIGURATION ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
# CRITICAL: We prioritize the Service Key for backend operations
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
SUPABASE_KEY = SUPABASE_SERVICE_KEY or os.environ.get("SUPABASE_KEY")
YOCO_SECRET_KEY = os.environ.get("YOCO_SECRET_KEY") 
# Helper to switch between Localhost and Production URL easily
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000/login")

# --- STARTUP ---
supabase: Optional[Client] = None
startup_error = None

print("--- STARTING MACRONATA BACKEND ---")
if not SUPABASE_URL or not SUPABASE_KEY:
    startup_error = "Missing Database Keys"
else:
    try:
        # We use the Service Key if available to allow Admin actions (creating wallets, etc.)
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

# --- 2. SECURITY & CORS (THE FIX) ---
# This block tells the server: "It's okay to talk to the Frontend"
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all origins (Change to specific URL in production for better security)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

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
class RegistrationRequest(BaseModel):
    email: str
    password: str
    full_name: str
    role: str # 'learner', 'tutor', 'parent', 'business'
    company_name: Optional[str] = None 
    child_email: Optional[str] = None

class SessionControl(BaseModel):
    session_id: str
    action: str # 'start' or 'end'

class LinkChildRequest(BaseModel):
    child_email: str

class ChatRequest(BaseModel):
    message: str
    history: List[dict] = []

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
    business_id: Optional[str] = None

class DepositRequest(BaseModel):
    amount_in_cents: int
    return_url: str 

class VerificationRequest(BaseModel):
    id_number: str
    phone_number: str

# --- 4. ENDPOINTS ---

@app.get("/")
def home():
    if startup_error: return {"status": "Critical Error", "detail": startup_error}
    return {"status": "Macronata Titan Online", "database": "Connected"}

# --- 📝 REGISTRATION (SPECIALIZED) ---
@app.post("/register_specialized")
def register_user(req: RegistrationRequest):
    try:
        # 1. Create Auth User in Supabase
        # We tell Supabase to send the user back to FRONTEND_URL after clicking the email link
        auth_res = supabase.auth.sign_up({
            "email": req.email, 
            "password": req.password,
            "options": {
                "data": {
                    "full_name": req.full_name, 
                    "role": req.role
                },
                "email_redirect_to": FRONTEND_URL 
            }
        })
        
        if not auth_res.user:
            # If user exists but is unverified, Supabase might return success but no session
            # If it fails completely, it raises an error usually caught below.
            pass
            
        # If sign_up returns a user (even if unverified), we can use that ID to set up their profile/wallet
        # IF we are using the Service Role Key.
        user_id = auth_res.user.id
        
        # 2. Handle Specialized Roles (Insert into specific tables)
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

        # 3. Create Wallet for everyone
        try:
            supabase.table("wallets").insert({"user_id": user_id, "balance_cents": 0}).execute()
        except: pass
        
        return {"status": "created", "user_id": user_id, "role": req.role}
        
    except Exception as e:
        # Catch duplicates or other errors
        raise HTTPException(400, str(e))

# --- 👤 SELF-HEALING PROFILE ---
@app.get("/my_profile")
def get_my_profile(user = Depends(verify_token)):
    try:
        res = supabase.table("users").select("*").eq("id", user.id).execute()
        if res.data: return res.data[0]
        
        # Self-Healing
        new_profile = {
            "id": user.id, "email": user.email,
            "full_name": user.user_metadata.get("full_name", "Unknown"),
            "role": user.user_metadata.get("role", "learner"),
            "verification_status": "verified"
        }
        supabase.table("users").insert(new_profile).execute()
        return new_profile
    except Exception as e: raise HTTPException(500, str(e))

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
                "stats": {"sessions_count": len(sessions), "total_spend_zar": total_spend / 100, "last_active": last_seen}
            })
        return enhanced_data
    except Exception as e: raise HTTPException(500, str(e))

# --- 🔍 DISCOVERY & VERIFICATION ---
@app.get("/users")
def get_all_users(user = Depends(verify_token)):
    try: return supabase.table("users").select("id, full_name, role").eq("verification_status", "verified").execute().data
    except: return []

@app.get("/tutors")
def get_tutors(user = Depends(verify_token)):
    try: return supabase.table("users").select("*").eq("role", "tutor").eq("verification_status", "verified").execute().data
    except: return []

@app.post("/submit_verification")
def submit_verification(req: VerificationRequest, user = Depends(verify_token)):
    if not validate_sa_id(req.id_number): raise HTTPException(400, "Invalid South African ID Number.")
    try:
        supabase.table("users").update({
            "id_number": req.id_number, "phone_number": req.phone_number, "verification_status": "pending_approval"
        }).eq("id", user.id).execute()
        return {"status": "submitted"}
    except Exception as e: raise HTTPException(500, str(e))

@app.post("/upload_verification_doc")
def upload_verification_doc(file: UploadFile = File(...), user = Depends(verify_token)):
    try:
        filename = f"{user.id}/{int(datetime.now().timestamp())}_{file.filename}"
        supabase.storage.from_("verification-docs").upload(filename, file.file.read(), {"content-type": file.content_type})
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

# --- 💳 WALLET & PAYMENTS ---
@app.get("/my_wallet")
def get_my_wallet(user = Depends(verify_token)):
    try:
        wallet = supabase.table("wallets").select("*").eq("user_id", user.id).maybe_single().execute()
        if not wallet.data:
            supabase.table("wallets").insert({"user_id": user.id, "balance_cents": 0}).execute()
            return {"balance": 0, "locked": 0, "history": []}
        history = supabase.table("wallet_transactions").select("*").eq("wallet_id", user.id).order("created_at", desc=True).execute()
        return {"balance": wallet.data['balance_cents'], "locked": wallet.data.get('locked_balance_cents', 0), "history": history.data}
    except Exception as e: raise HTTPException(500, str(e))

@app.post("/create_deposit")
def create_deposit_link(req: DepositRequest, user = Depends(verify_token)):
    if not YOCO_SECRET_KEY: return {"url": None, "simulation": True}
    try:
        headers = {"Authorization": f"Bearer {YOCO_SECRET_KEY}", "Content-Type": "application/json"}
        payload = {"amount": req.amount_in_cents, "currency": "ZAR", "cancelUrl": req.return_url, "successUrl": req.return_url, "metadata": {"type": "wallet_deposit", "user_id": user.id}}
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
        supabase.table("wallet_transactions").insert({"wallet_id": user.id, "amount_cents": req.amount_in_cents, "transaction_type": "deposit", "description": "Top Up via Yoco (Simulated)"}).execute()
        return {"status": "Funds Added", "new_balance": new_bal}
    except Exception as e: raise HTTPException(500, str(e))

# --- ⏱️ SESSIONS & ESCROW ---
@app.post("/book_with_wallet")
def book_with_wallet(b: BookingRequest, user = Depends(verify_token)):
    try:
        dt = datetime.fromisoformat(b.scheduled_time)
        data = {"tutor_id": b.tutor_id, "learner_id": user.id, "scheduled_time": dt.isoformat(), "status": "scheduled", "hourly_rate_cents": b.amount_in_cents, "max_cost_cap_cents": b.amount_in_cents}
        if b.business_id: data['business_id'] = b.business_id
        supabase.table("sessions").insert(data).execute()
        return {"msg": "Booking Successful", "status": "scheduled"}
    except Exception as e: raise HTTPException(500, str(e))

@app.post("/session_control")
def control_session(ctrl: SessionControl, user = Depends(verify_token)):
    try:
        session_res = supabase.table("sessions").select("*").eq("id", ctrl.session_id).single().execute()
        if not session_res.data: raise HTTPException(404, "Session not found")
        session = session_res.data
        
        if ctrl.action == "start":
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
            start_time = datetime.fromisoformat(session['start_time'].replace('Z', '+00:00'))
            end_time = datetime.now(start_time.tzinfo)
            duration = (end_time - start_time).total_seconds()
            rate_per_sec = session['hourly_rate_cents'] / 3600.0
            final_cost = int(duration * rate_per_sec)
            locked_amt = session['max_cost_cap_cents']
            if final_cost > locked_amt: final_cost = locked_amt
            refund_amt = locked_amt - final_cost
            
            learner_id = session['learner_id']
            l_wallet = supabase.table("wallets").select("*").eq("user_id", learner_id).single().execute().data
            supabase.table("wallets").update({
                "locked_balance_cents": l_wallet.get('locked_balance_cents', locked_amt) - locked_amt,
                "balance_cents": l_wallet['balance_cents'] + refund_amt
            }).eq("user_id", learner_id).execute()
            
            pay_recipient_id = session.get('business_id') or session['tutor_id']
            t_wallet = supabase.table("wallets").select("*").eq("user_id", pay_recipient_id).single().execute().data
            if not t_wallet: 
                 supabase.table("wallets").insert({"user_id": pay_recipient_id, "balance_cents": 0}).execute()
                 t_bal = 0
            else: t_bal = t_wallet['balance_cents']
            
            supabase.table("wallets").update({"balance_cents": t_bal + final_cost}).eq("user_id", pay_recipient_id).execute()
            supabase.table("sessions").update({"status": "completed", "end_time": end_time.isoformat(), "final_cost_cents": final_cost}).eq("id", ctrl.session_id).execute()
            
            supabase.table("wallet_transactions").insert([
                {"wallet_id": learner_id, "amount_cents": -final_cost, "transaction_type": "payment", "description": "Session Cost"},
                {"wallet_id": pay_recipient_id, "amount_cents": final_cost, "transaction_type": "earning", "description": "Session Earnings"}
            ]).execute()

            return {"status": "Session Ended", "cost": final_cost}
    except Exception as e: raise HTTPException(500, str(e))

@app.get("/my_bookings")
def get_my_bookings(user = Depends(verify_token)):
    return supabase.table("sessions").select("*, tutor:users!tutor_id(full_name)").eq("learner_id", user.id).execute().data

# --- 🤖 AI TUTOR ---
@app.post("/chat")
def chat_with_tinny(request: ChatRequest, user = Depends(verify_token)):
    try:
        hist = [{"role": m['role'], "parts": m['parts']} for m in request.history]
        res = model.start_chat(history=hist).send_message(request.message)
        return {"reply": res.text}
    except: return {"reply": "Tinny is offline."}