from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import google.generativeai as genai
import os
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime

# 1. Load Environment Variables
load_dotenv()

# 2. Setup Google AI (Tinny)
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)

# Tinny's Personality
TINNY_INSTRUCTIONS = """
You are Tinny, a warm and encouraging AI tutor for South African school kids (CAPS & IEB curriculum).
- You speak English with South African flair (use 'shame', 'lekker', 'howzit' naturally).
- You NEVER do the homework for the student. You guide them.
- If asked to write an essay, ask guiding questions instead.
- Keep answers short, punchy, and helpful.
"""

# Use the model that works for you (Switch to 'gemini-flash-latest' if needed)
model = genai.GenerativeModel(
    model_name="gemini-flash-latest",
    system_instruction=TINNY_INSTRUCTIONS
)

# 3. Setup Supabase (Database)
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# 4. Initialize the App
app = FastAPI()

# --- DATA MODELS ---
class ChatRequest(BaseModel):
    message: str

class BookingRequest(BaseModel):
    tutor_id: str
    learner_id: str
    scheduled_time: datetime
    total_cost_zar: float

class SessionCompleteRequest(BaseModel):
    session_id: str

# --- ENDPOINTS ---

@app.get("/")
def home():
    return {"message": "Macronata Academy Money Engine is Online!"}

# 1. AI Chat Endpoint
@app.post("/chat")
def chat_with_tinny(request: ChatRequest):
    try:
        response = model.generate_content(request.message)
        return {"reply": response.text}
    except Exception as e:
        # Fallback if AI fails (e.g. Quota issues)
        return {"reply": "Eish! My brain is a bit slow right now. Try again later."}

# 2. Booking Endpoint
@app.post("/book_session")
def book_session(booking: BookingRequest):
    try:
        data = {
            "tutor_id": booking.tutor_id,
            "learner_id": booking.learner_id,
            "scheduled_time": booking.scheduled_time.isoformat(),
            "status": "booked",
            "total_cost": booking.total_cost_zar
        }
        # Insert into Supabase 'sessions' table
        response = supabase.table("sessions").insert(data).execute()
        return {"message": "Session booked successfully!", "data": response.data[0]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 3. Payout Endpoint (The Money Engine)
@app.post("/complete_session")
def complete_session(request: SessionCompleteRequest):
    try:
        # 1. Get the session details
        session_response = supabase.table("sessions").select("*").eq("id", request.session_id).execute()
        
        if not session_response.data:
            raise HTTPException(status_code=404, detail="Session not found")
        
        session = session_response.data[0]
        total_amount = session['total_cost']
        
        # 2. Calculate the split (85% to Tutor, 15% to Macronata)
        tutor_share = total_amount * 0.85
        macronata_share = total_amount * 0.15
        
        # 3. Record the Transaction
        transaction_data = {
            "session_id": request.session_id,
            "amount_paid": total_amount,
            "macronata_revenue": macronata_share,
            "tutor_earnings": tutor_share,
            "payout_status": "pending"
        }
        
        tx_response = supabase.table("transactions").insert(transaction_data).execute()
        
        return {
            "message": "Payout calculated",
            "total": total_amount,
            "macronata_revenue": macronata_share,
            "tutor_earnings": tutor_share
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# 4. NEW: Get Tutors (Marketplace Endpoint)
@app.get("/tutors")
def get_tutors():
    """Fetches a list of all available tutors from Supabase."""
    try:
        # Query users where the role is 'tutor'
        response = supabase.table("users").select("*").eq("role", "tutor").execute()
        return response.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    