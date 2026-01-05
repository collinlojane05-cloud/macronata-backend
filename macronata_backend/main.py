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
SUPABASE_SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")
SUPABASE_KEY = SUPABASE_SERVICE_KEY or os.environ.get("SUPABASE_KEY")
FRONTEND_URL = os.environ.get("FRONTEND_URL", "http://localhost:3000/login")

supabase: Optional[Client] = None

if not SUPABASE_URL or not SUPABASE_KEY:
    print("❌ Error: Missing Database Keys")
else:
    try:
        supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
        print("✅ Database Connected.")
    except Exception as e:
        print(f"❌ Connection Failed: {e}")

# AI Setup
try:
    if GEMINI_API_KEY:
        genai.configure(api_key=GEMINI_API_KEY)
        model = genai.GenerativeModel("gemini-flash-latest", system_instruction="You are Tinny, a helpful AI tutor for Macronata Academy.")
except: pass

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- 2. SECURITY HELPER ---
def verify_token(authorization: Optional[str] = Header(None)):
    if not supabase: raise HTTPException(500, "Server Error: Database not connected.")
    if not authorization: raise HTTPException(401, "Missing Token")
    try:
        token = authorization.split(" ")[1]
        user = supabase.auth.get_user(token)
        if not user.user: raise Exception()
        return user.user
    except: raise HTTPException(401, "Invalid Token")

# --- 3. DATA MODELS ---
class RegistrationRequest(BaseModel):
    email: str
    password: str
    full_name: str
    role: str 
    company_name: Optional[str] = None 

class SessionControl(BaseModel):
    session_id: str
    action: str 

class LinkChildRequest(BaseModel):
    child_email: str

class BookingRequest(BaseModel):
    tutor_id: str
    scheduled_time: str
    amount_in_cents: int 
    return_url: str 
    business_id: Optional[str] = None

class DepositRequest(BaseModel):
    amount_in_cents: int
    return_url: str 

class TutorProfileUpdate(BaseModel):
    hourly_rate_cents: int
    subjects: List[str]
    bio: str
    meeting_link: Optional[str] = None 

class AddStudentRequest(BaseModel):
    student_email: str

# --- 4. ENDPOINTS ---

@app.get("/")
def home():
    return {"status": "Macronata Titan Online", "database": "Connected" if supabase else "Disconnected"}

# --- 📝 REGISTRATION (ROBUST) ---
@app.post("/register_specialized")
def register_user(req: RegistrationRequest):
    try:
        # 1. Create Auth User
        auth_res = supabase.auth.sign_up({
            "email": req.email, "password": req.password,
            "options": {"data": {"full_name": req.full_name, "role": req.role}, "email_redirect_to": FRONTEND_URL}
        })
        user_id = auth_res.user.id if auth_res.user else None
        
        if user_id:
            # 2. Force Insert into Public Profile
            try:
                supabase.table("users").insert({
                    "id": user_id, "email": req.email, "full_name": req.full_name, "role": req.role, "verification_status": "verified"
                }).execute()
            except Exception as e: print(f"Profile creation warning: {e}")

            # 3. Create Role Tables
            if req.role == 'business':
                try: supabase.table("businesses").insert({"id": user_id, "company_name": req.company_name or req.full_name}).execute()
                except: pass
            elif req.role == 'parent':
                try: supabase.table("parents").insert({"id": user_id}).execute()
                except: pass
            
            # 4. Create Wallet
            try: supabase.table("wallets").insert({"user_id": user_id, "balance_cents": 0}).execute()
            except: pass

        return {"status": "created", "user_id": user_id, "role": req.role}
    except Exception as e: raise HTTPException(400, str(e))

# --- 👤 LEARNER DASHBOARD (CRASH-PROOF) ---
@app.get("/learner_dashboard")
def get_learner_dashboard(user = Depends(verify_token)):
    try:
        # 1. 👤 SAFELY GET PROFILE
        profile_res = supabase.table("users").select("*").eq("id", user.id).maybe_single().execute()
        
        if not profile_res.data:
            print(f"⚠️ Profile missing for {user.id}. Auto-healing...")
            new_profile = {
                "id": user.id, "email": user.email,
                "full_name": user.user_metadata.get("full_name", "Student"),
                "role": "learner", "verification_status": "verified"
            }
            try: supabase.table("users").insert(new_profile).execute()
            except: pass # Ignore if parallel request created it
            profile = new_profile
        else:
            profile = profile_res.data

        # 2. 💳 SAFELY GET WALLET
        wallet_res = supabase.table("wallets").select("balance_cents").eq("user_id", user.id).maybe_single().execute()
        if not wallet_res.data:
            try: supabase.table("wallets").insert({"user_id": user.id, "balance_cents": 0}).execute()
            except: pass
            balance = 0
        else:
            balance = wallet_res.data['balance_cents']

        # 3. 📅 SAFELY GET SESSIONS
        sessions = []
        try:
            sessions_res = supabase.table("sessions").select("*, tutor:users!tutor_id(full_name)").eq("learner_id", user.id).in_("status", ["scheduled", "live"]).order("scheduled_time").execute()
            sessions = sessions_res.data if sessions_res.data else []
        except: pass

        # 4. 📊 STATS
        past_sessions = []
        try:
            past_res = supabase.table("sessions").select("final_cost_cents").eq("learner_id", user.id).eq("status", "completed").execute()
            past_sessions = past_res.data if past_res.data else []
        except: pass
        
        total_spent = sum(s['final_cost_cents'] for s in past_sessions)

        return {
            "profile": profile, 
            "wallet": {"balance_zar": balance / 100}, 
            "stats": {"total_spent_zar": total_spent / 100, "completed_count": len(past_sessions), "upcoming_count": len(sessions)}, 
            "upcoming_sessions": sessions
        }
    except Exception as e:
        print(f"CRITICAL DASHBOARD ERROR: {str(e)}")
        # Fail-safe return
        return {
            "profile": {"full_name": "Student", "email": user.email},
            "wallet": {"balance_zar": 0},
            "stats": {"total_spent_zar": 0, "completed_count": 0, "upcoming_count": 0},
            "upcoming_sessions": []
        }

@app.get("/tutor_dashboard")
def get_tutor_dashboard(user = Depends(verify_token)):
    try:
        profile = supabase.table("users").select("*").eq("id", user.id).single().execute().data
        sessions = supabase.table("sessions").select("*, learner:users!learner_id(full_name)").eq("tutor_id", user.id).order("scheduled_time").execute().data
        completed = [s for s in sessions if s['status'] == 'completed']
        upcoming = [s for s in sessions if s['status'] in ['scheduled', 'live']]
        total_earnings = sum(s['final_cost_cents'] for s in completed)
        return {"profile": profile, "stats": {"total_earnings_zar": total_earnings / 100, "completed_count": len(completed), "upcoming_count": len(upcoming)}, "upcoming_sessions": upcoming}
    except Exception as e: raise HTTPException(500, str(e))

# --- 🏢 BUSINESS DASHBOARD ---
@app.get("/my_business_dashboard")
def get_business_dashboard(user = Depends(verify_token)):
    try:
        # 1. Profile
        profile_res = supabase.table("businesses").select("*").eq("id", user.id).maybe_single().execute()
        profile = profile_res.data if profile_res.data else {"company_name": "My Business"}
        
        # 2. Students
        students_res = supabase.table("users").select("id, full_name, email").eq("parent_id", user.id).execute()
        students = students_res.data if students_res.data else []
        
        # 3. Stats logic could go here (mocked for now to prevent crash)
        return {
            "profile": profile,
            "students": students,
            "stats": {"total_students": len(students), "total_sessions": 0, "active_now": 0}
        }
    except Exception as e:
        print(e)
        return {"profile": {"company_name": "My Business"}, "students": [], "stats": {"total_students": 0, "total_sessions": 0, "active_now": 0}}

@app.post("/add_student_to_business")
def add_student_business(req: AddStudentRequest, user = Depends(verify_token)):
    try:
        # Verify student exists
        student = supabase.table("users").select("id, role").eq("email", req.student_email).single().execute()
        if not student.data or student.data['role'] != 'learner':
            raise HTTPException(404, "Student email not found or not a learner.")
        
        # Link them
        supabase.table("users").update({"parent_id": user.id}).eq("id", student.data['id']).execute()
        return {"status": "Linked"}
    except Exception as e: raise HTTPException(400, str(e))

@app.post("/update_tutor_profile")
def update_tutor_profile(req: TutorProfileUpdate, user = Depends(verify_token)):
    try:
        update_data = {"hourly_rate_cents": req.hourly_rate_cents, "subjects": req.subjects, "bio": req.bio}
        if req.meeting_link:
            clean_link = req.meeting_link.replace("https://", "").replace("http://", "")
            update_data["meeting_link"] = clean_link
        supabase.table("users").update(update_data).eq("id", user.id).execute()
        return {"status": "Profile Updated"}
    except Exception as e: raise HTTPException(500, str(e))

# --- 👨‍👩‍👧 PARENT FEATURES ---
@app.post("/link_child")
def link_child(req: LinkChildRequest, user = Depends(verify_token)):
    try:
        child_res = supabase.table("users").select("id, role").eq("email", req.child_email).single().execute()
        if not child_res.data or child_res.data['role'] != 'learner': raise HTTPException(404, "Learner account not found.")
        supabase.table("users").update({"parent_id": user.id}).eq("id", child_res.data['id']).execute()
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
            enhanced_data.append({"profile": child, "stats": {"sessions_count": len(sessions), "total_spend_zar": total_spend / 100}})
        return enhanced_data
    except Exception as e: raise HTTPException(500, str(e))

# --- 🔍 MARKETPLACE ---
@app.get("/tutors")
def get_tutors(user = Depends(verify_token)):
    return supabase.table("users").select("*").eq("role", "tutor").execute().data

# --- 💳 WALLET (SELF-HEALING) ---
@app.get("/my_wallet")
def get_my_wallet(user = Depends(verify_token)):
    try:
        wallet = supabase.table("wallets").select("*").eq("user_id", user.id).maybe_single().execute()
        if not wallet.data:
            print(f"⚠️ Creating wallet for {user.id}")
            try: supabase.table("wallets").insert({"user_id": user.id, "balance_cents": 0}).execute()
            except: pass
            return {"balance": 0, "locked": 0, "history": []}
        
        history = supabase.table("wallet_transactions").select("*").eq("wallet_id", user.id).order("created_at", desc=True).execute()
        return {"balance": wallet.data['balance_cents'], "locked": wallet.data.get('locked_balance_cents', 0), "history": history.data}
    except Exception as e: return {"balance": 0, "locked": 0, "history": []}

@app.post("/confirm_deposit_simulated")
def confirm_deposit_sim(req: DepositRequest, user = Depends(verify_token)):
    try:
        # 1. Check if wallet exists
        res = supabase.table("wallets").select("balance_cents").eq("user_id", user.id).maybe_single().execute()
        
        if not res.data:
            # Create Wallet with funds
            supabase.table("wallets").insert({
                "user_id": user.id, 
                "balance_cents": req.amount_in_cents
            }).execute()
        else:
            # Update Wallet
            new_bal = res.data['balance_cents'] + req.amount_in_cents
            supabase.table("wallets").update({"balance_cents": new_bal}).eq("user_id", user.id).execute()
            
        # 2. Log Transaction
        supabase.table("wallet_transactions").insert({
            "wallet_id": user.id, 
            "amount_cents": req.amount_in_cents, 
            "transaction_type": "deposit", 
            "description": "Top Up (Simulated)"
        }).execute()
        
        return {"status": "Funds Added"}
    except Exception as e:
        print(f"Deposit Error: {e}")
        raise HTTPException(500, f"Deposit failed: {str(e)}")

# --- ⏱️ SESSIONS & BOOKING ---
# --- REPLACE IN MAIN.PY ---

@app.post("/book_with_wallet")
def book_with_wallet(b: BookingRequest, user = Depends(verify_token)):
    # 1. Get Wallet Balance
    wallet_res = supabase.table("wallets").select("balance_cents").eq("user_id", user.id).maybe_single().execute()
    
    # Debug Logging 🖨️
    print(f"--- BOOKING DEBUG ---")
    print(f"User ID: {user.id}")
    print(f"Wallet Found? {wallet_res.data}")
    
    current_balance = wallet_res.data['balance_cents'] if wallet_res.data else 0
    cost_to_book = b.amount_in_cents
    
    print(f"💰 Balance: {current_balance}")
    print(f"🧾 Cost: {cost_to_book}")
    
    # 2. The Check
    if current_balance < cost_to_book:
        print("❌ INSUFFICIENT FUNDS TRIGGERED")
        raise HTTPException(402, f"Insufficient Funds. Balance: {current_balance}, Cost: {cost_to_book}")
    
    # 3. Book
    print("✅ FUNDS OK. BOOKING...")
    data = {
        "tutor_id": b.tutor_id, "learner_id": user.id, 
        "scheduled_time": datetime.fromisoformat(b.scheduled_time.replace("Z", "")).isoformat(), 
        "status": "scheduled", 
        "hourly_rate_cents": b.amount_in_cents, "max_cost_cap_cents": b.amount_in_cents
    }
    if b.business_id: data['business_id'] = b.business_id
    supabase.table("sessions").insert(data).execute()
    return {"msg": "Booking Successful"}

@app.post("/session_control")
def control_session(ctrl: SessionControl, user = Depends(verify_token)):
    s = supabase.table("sessions").select("*").eq("id", ctrl.session_id).single().execute().data
    if not s: raise HTTPException(404, "Session not found")
    
    if ctrl.action == "end":
        start_time = datetime.fromisoformat(s['start_time'].replace('Z', ''))
        end_time = datetime.now()
        duration = (end_time - start_time).total_seconds()
        
        # Calculate Cost
        final_cost = int(duration * (s['hourly_rate_cents'] / 3600.0))
        final_cost = min(final_cost, s['max_cost_cap_cents']) # Cap it
        
        # Move Money (Learner -> Tutor)
        l_wallet = supabase.table("wallets").select("*").eq("user_id", s['learner_id']).single().execute().data
        pay_id = s.get('business_id') or s['tutor_id']
        t_wallet = supabase.table("wallets").select("*").eq("user_id", pay_id).maybe_single().execute().data
        
        if not t_wallet:
             supabase.table("wallets").insert({"user_id": pay_id, "balance_cents": 0}).execute()
             t_wallet = {"balance_cents": 0}

        supabase.table("wallets").update({"balance_cents": l_wallet['balance_cents'] - final_cost}).eq("user_id", s['learner_id']).execute()
        supabase.table("wallets").update({"balance_cents": t_wallet['balance_cents'] + final_cost}).eq("user_id", pay_id).execute()
        
        supabase.table("sessions").update({"status": "completed", "end_time": end_time.isoformat(), "final_cost_cents": final_cost}).eq("id", ctrl.session_id).execute()
        
        supabase.table("wallet_transactions").insert([
            {"wallet_id": s['learner_id'], "amount_cents": -final_cost, "transaction_type": "payment", "description": "Class Payment"},
            {"wallet_id": pay_id, "amount_cents": final_cost, "transaction_type": "earning", "description": "Class Earnings"}
        ]).execute()

        return {"status": "Session Ended", "cost": final_cost}
    
    elif ctrl.action == "start":
        supabase.table("sessions").update({"status": "live", "start_time": datetime.now().isoformat()}).eq("id", ctrl.session_id).execute()
        return {"status": "Started"}