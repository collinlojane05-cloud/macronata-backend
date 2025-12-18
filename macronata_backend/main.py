from fastapi import FastAPI, HTTPException
from supabase import create_client, Client
import os
from dotenv import load_dotenv
from pydantic import BaseModel
import google.generativeai as genai
from datetime import datetime

# 1. Load environment variables
load_dotenv()

# 2. Initialize Supabase Client
url: str = os.environ.get("SUPABASE_URL")
key: str = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(url, key)

# 3. Initialize Google Gemini (Tinny)
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))

TINNY_INSTRUCTIONS = """
Role: You are Tinny, the AI tutor for Macronata Academy.
Context: You are tutoring South African students (CAPS and IEB curriculum).
Personality: Patient, encouraging, and clear. Use local context (e.g., Rands for money, SA cities).
"""

model = genai.GenerativeModel(
    model_name="gemini-flash-latest",
    system_instruction=TINNY_INSTRUCTIONS
)

# 4. Initialize FastAPI App
app = FastAPI(title="Macronata Academy API")

# --- DATA MODELS ---
class UserSignup(BaseModel):
    email: str
    password: str
    full_name: str
    role: str

class ChatRequest(BaseModel):
    message: str

class BookSessionRequest(BaseModel):
    tutor_id: str
    learner_id: str
    scheduled_time: str  # e.g., "2025-12-20T14:00:00"
    total_cost_zar: float

class CompleteSessionRequest(BaseModel):
    session_id: str

# --- ROUTES ---

@app.get("/")
def read_root():
    return {"message": "Macronata Academy Money Engine is Online!"}

# 1. REGISTER USER
@app.post("/register")
def register_user(user: UserSignup):
    auth_response = supabase.auth.sign_up({
        "email": user.email,
        "password": user.password,
    })
    if not auth_response.user:
         raise HTTPException(status_code=400, detail="Registration failed")
    
    data = {
        "id": auth_response.user.id,
        "email": user.email,
        "full_name": user.full_name,
        "role": user.role
    }
    try:
        response = supabase.table("users").insert(data).execute()
        return {"message": "User registered successfully", "user": response.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 2. CHAT WITH TINNY
@app.post("/chat")
def chat_with_tinny(request: ChatRequest):
    try:
        response = model.generate_content(request.message)
        return {"reply": response.text}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI Error: {str(e)}")

# 3. BOOK A SESSION (New!)
@app.post("/book_session")
def book_session(request: BookSessionRequest):
    data = {
        "tutor_id": request.tutor_id,
        "learner_id": request.learner_id,
        "scheduled_time": request.scheduled_time,
        "total_cost_zar": request.total_cost_zar,
        "status": "confirmed"
    }
    try:
        response = supabase.table("sessions").insert(data).execute()
        return {"message": "Session Booked!", "session": response.data}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 4. COMPLETE SESSION & PAYOUT (The Money Engine!)
@app.post("/complete_session")
def complete_session(request: CompleteSessionRequest):
    # Step A: Get the session details to find the cost
    try:
        session_data = supabase.table("sessions").select("*").eq("id", request.session_id).single().execute()
        session = session_data.data
        
        # Step B: Calculate the Commission (15%)
        total = float(session['total_cost_zar'])
        platform_fee = total * 0.15
        tutor_payout = total * 0.85
        
        # Step C: Record the Transaction
        transaction_data = {
            "session_id": request.session_id,
            "total_amount": total,
            "platform_fee": platform_fee,   # This is your profit
            "tutor_payout": tutor_payout    # This goes to the student
        }
        supabase.table("transactions").insert(transaction_data).execute()

        # Step D: Mark session as Completed
        supabase.table("sessions").update({"status": "completed"}).eq("id", request.session_id).execute()
        
        return {
            "message": "Session completed and funds split.",
            "financials": {
                "total": total,
                "macronata_revenue": platform_fee,
                "tutor_earnings": tutor_payout
            }
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    