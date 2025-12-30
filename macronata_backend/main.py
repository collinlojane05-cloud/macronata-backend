from fastapi import FastAPI, HTTPException, Depends, Header
from pydantic import BaseModel
import google.generativeai as genai
import os
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime
from typing import Optional, List

load_dotenv()

# --- DIAGNOSTICS & SETUP ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
SUPABASE_URL = os.environ.get("SUPABASE_URL")

# CRITICAL: specific check for the Service Key (Admin Key)
SERVICE_KEY = os.environ.get("SUPABASE_SERVICE_KEY")

if not SERVICE_KEY:
    print("⚠️ WARNING: SUPABASE_SERVICE_KEY is missing! Messaging might fail RLS checks.")
    # Fallback only to prevent crash on startup, but DB writes might fail
    SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
else:
    print("✅ SUCCESS: Found SUPABASE_SERVICE_KEY. Admin mode active.")
    SUPABASE_KEY = SERVICE_KEY

if not all([GEMINI_API_KEY, SUPABASE_URL, SUPABASE_KEY]):
    print("CRITICAL: One or more API Keys are completely missing.")

# AI Configuration
try:
    genai.configure(api_key=GEMINI_API_KEY)
    model = genai.GenerativeModel("gemini-flash-latest", system_instruction="You are Tinny, a helpful AI tutor for Macronata Academy.")
except Exception as e: 
    print(f"AI Config Error: {e}")

# Client Initialization (Uses Service Key if available to bypass RLS for writes)
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
app = FastAPI()

# --- SECURITY ---
def verify_token(authorization: Optional[str] = Header(None)):
    """
    Verifies the Bearer Token sent by the Frontend.
    Returns the user object if valid.
    """
    if not authorization:
        raise HTTPException(status_code=401, detail="Missing Token")
    try:
        token = authorization.split(" ")[1]
        # We use the token ONLY to check who the user is
        user_response = supabase.auth.get_user(token)
        if not user_response.user: raise Exception()
        return user_response.user
    except:
        raise HTTPException(status_code=401, detail="Invalid Token")

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

class DirectMessageRequest(BaseModel):
    receiver_id: str
    content: Optional[str] = None
    media_url: Optional[str] = None
    media_type: Optional[str] = None

# --- ENDPOINTS ---

@app.get("/")
def home(): 
    # This endpoint helps debug key status on Render
    status = "Admin Mode (Secure)" if SERVICE_KEY else "Guest Mode (Restricted)"
    return {"status": "Online", "mode": status}

@app.get("/users")
def get_all_users(user = Depends(verify_token)):
    """
    Fetches basic profile info for ALL users.
    Required for Tutors and Learners to find each other in Chat.
    """
    try:
        response = supabase.table("users").select("id, full_name, email, role").execute()
        return response.data
    except Exception as e:
        print(f"Error fetching users: {e}")
        return []

@app.get("/tutors")
def get_tutors(user = Depends(verify_token)):
    """
    Specific endpoint for 'Find Tutor' page (filters only tutors).
    """
    try:
        response = supabase.table("users").select("*").eq("role", "tutor").execute()
        return response.data
    except Exception as e:
        return []

# --- MESSAGING ---

@app.get("/messages/{other_user_id}")
def get_chat_history(other_user_id: str, user = Depends(verify_token)):
    try:
        # Fetch conversation where (Sender=Me & Receiver=Them) OR (Sender=Them & Receiver=Me)
        response = supabase.table("direct_messages").select("*")\
            .or_(f"and(sender_id.eq.{user.id},receiver_id.eq.{other_user_id}),and(sender_id.eq.{other_user_id},receiver_id.eq.{user.id})")\
            .order("created_at")\
            .execute()
        return response.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/messages")
def send_message(msg: DirectMessageRequest, user = Depends(verify_token)):
    try:
        # DATA PREPARATION
        data = {
            "sender_id": user.id, 
            "receiver_id": msg.receiver_id,
            "content": msg.content,
            "media_url": msg.media_url,
            "media_type": msg.media_type
        }
        
        # Insert using Service Key (Bypasses "Users can send messages" RLS policy if needed)
        response = supabase.table("direct_messages").insert(data).execute()
        return {"status": "sent", "data": response.data[0]}
    except Exception as e:
        print(f"MESSAGE FAILED: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Database Error: {str(e)}")

# --- TINNY AI & BOOKINGS ---

@app.post("/chat")
def chat_with_tinny(request: ChatRequest, user = Depends(verify_token)):
    try:
        # Convert Pydantic history to Gemini history format
        hist = [{"role": m.role, "parts": m.parts} for m in request.history]
        chat_session = model.start_chat(history=hist)
        res = chat_session.send_message(request.message)
        return {"reply": res.text}
    except Exception as e:
        print(f"AI Error: {e}")
        return {"reply": "Tinny is offline or having trouble connecting."}

@app.post("/book_session")
def book_session(b: BookingRequest, user = Depends(verify_token)):
    try:
        dt = datetime.fromisoformat(b.scheduled_time)
        
        # Check availability
        existing = supabase.table("sessions").select("id").eq("tutor_id", b.tutor_id).eq("scheduled_time", dt.isoformat()).execute()
        if existing.data: raise HTTPException(status_code=409, detail="Slot already booked")
        
        data = {
            "tutor_id": b.tutor_id, 
            "learner_id": user.id, 
            "scheduled_time": dt.isoformat(), 
            "status": "booked", 
            "total_cost_zar": 200.0
        }
        supabase.table("sessions").insert(data).execute()
        return {"msg": "Success"}
    except HTTPException as h: raise h
    except Exception as e: raise HTTPException(status_code=500, detail=str(e))

@app.get("/my_bookings")
def get_my_bookings(user = Depends(verify_token)):
    return supabase.table("sessions").select("*, tutor:users!tutor_id(full_name)").eq("learner_id", user.id).order("scheduled_time").execute().data

@app.get("/tutor_bookings")
def get_tutor_bookings(user = Depends(verify_token)):
    return supabase.table("sessions").select("*, learner:users!learner_id(full_name, email)").eq("tutor_id", user.id).order("scheduled_time").execute().data