from fastapi import FastAPI, HTTPException, Depends, Header
from pydantic import BaseModel
import google.generativeai as genai
import os
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime
from typing import Optional, List

load_dotenv()

# --- CONFIGURATION ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not all([GEMINI_API_KEY, SUPABASE_URL, SUPABASE_KEY]):
    # This print helps debug logs in Render
    print("CRITICAL: Missing Environment Variables")

# Configure AI with a Persona
try:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel(
        "gemini-flash-latest",
        system_instruction="You are Tinny, an advanced AI tutor for Macronata Academy. You are helpful, patient, and knowledgeable. Keep answers concise."
    )
except Exception as e:
    print(f"AI Config Error: {e}")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
app = FastAPI()

# --- SECURITY DEPENDENCY ---
def verify_token(authorization: Optional[str] = Header(None)):
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Authorization Header")
    try:
        token = authorization.split(" ")[1] 
        user_response = supabase.auth.get_user(token)
        if not user_response or not user_response.user:
            raise HTTPException(status_code=401, detail="Invalid Token")
        return user_response.user
    except Exception:
        raise HTTPException(status_code=401, detail="Authentication Failed")

# --- DATA MODELS ---
class ChatMessage(BaseModel):
    role: str
    parts: List[str]

class ChatRequest(BaseModel):
    message: str
    history: List[ChatMessage] = []

class BookingRequest(BaseModel):
    tutor_id: str
    scheduled_time: str
    # REMOVED learner_id and cost to match your error fix

# --- ENDPOINTS ---

@app.get("/")
def home():
    return {"message": "Macronata Academy Secure System Online"}

@app.get("/tutors")
def get_tutors(user = Depends(verify_token)):
    try:
        response = supabase.table("users").select("*").eq("role", "tutor").execute()
        return response.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat")
def chat_with_tinny(request: ChatRequest, user = Depends(verify_token)):
    try:
        formatted_history = [{"role": msg.role, "parts": msg.parts} for msg in request.history]
        chat_session = model.start_chat(history=formatted_history)
        response = chat_session.send_message(request.message)
        return {"reply": response.text}
    except Exception:
        return {"reply": "I'm having trouble connecting right now. Please try again."}

@app.post("/book_session")
def book_session(booking: BookingRequest, user = Depends(verify_token)):
    try:
        dt_object = datetime.fromisoformat(booking.scheduled_time)
        
        # Check for double booking
        existing = supabase.table("sessions").select("id").eq("tutor_id", booking.tutor_id).eq("scheduled_time", dt_object.isoformat()).execute()
        if existing.data:
            raise HTTPException(status_code=409, detail="Slot already booked")

        # Insert using ID from token
        data = {
            "tutor_id": booking.tutor_id,
            "learner_id": user.id,      # SECURE: Comes from token
            "scheduled_time": dt_object.isoformat(), 
            "status": "booked",
            "total_cost_zar": 200.0     # HARDCODED PRICE
        }
        
        response = supabase.table("sessions").insert(data).execute()
        return {"message": "Session booked successfully!", "data": response.data[0]}
    except HTTPException as he:
        raise he
    except Exception as e:
        print(f"DB ERROR: {e}")
        raise HTTPException(status_code=500, detail="Database Rejection")

@app.get("/my_bookings")
def get_my_bookings(user = Depends(verify_token)):
    try:
        response = supabase.table("sessions").select("*, tutor:users!tutor_id(full_name)").eq("learner_id", user.id).order("scheduled_time").execute()
        return response.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tutor_bookings")
def get_tutor_bookings(user = Depends(verify_token)):
    try:
        response = supabase.table("sessions").select("*, learner:users!learner_id(full_name, email)").eq("tutor_id", user.id).order("scheduled_time").execute()
        return response.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))