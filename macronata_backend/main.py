from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
import google.generativeai as genai
import os
from dotenv import load_dotenv
from supabase import create_client, Client
from datetime import datetime

load_dotenv()

# --- SETUP ---
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-1.5-flash")

SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

app = FastAPI()

# --- STRICT DATA MODELS ---
# We update this to match your new database columns exactly
class ChatRequest(BaseModel):
    message: str

class BookingRequest(BaseModel):
    tutor_id: str
    learner_id: str
    scheduled_time: str  # We receive "2025-12-18T15:30"
    total_cost_zar: float # RENAMED: Matches your database column

# --- ENDPOINTS ---

@app.get("/")
def home():
    return {"message": "Macronata Academy Enterprise System Online"}

@app.get("/tutors")
def get_tutors():
    try:
        # Fetch tutors (users with role 'tutor')
        response = supabase.table("users").select("*").eq("role", "tutor").execute()
        return response.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/chat")
def chat_with_tinny(request: ChatRequest):
    try:
        response = model.generate_content(request.message)
        return {"reply": response.text}
    except Exception as e:
        return {"reply": "Connection error."}

@app.post("/book_session")
def book_session(booking: BookingRequest):
    try:
        # 1. Parse the date string into a real Timestamp for Postgres
        # This converts "2025-12-18T15:30" into a format the database loves
        dt_object = datetime.fromisoformat(booking.scheduled_time)
        
        # 2. Prepare the payload with STRICT keys
        data = {
            "tutor_id": booking.tutor_id,
            "learner_id": booking.learner_id,
            "scheduled_time": dt_object.isoformat(), 
            "status": "booked",            # This MUST exist in your 'statuses' table
            "total_cost_zar": booking.total_cost_zar # Matches column name
        }
        
        # 3. Insert into the new table
        response = supabase.table("sessions").insert(data).execute()
        return {"message": "Session booked successfully!", "data": response.data[0]}
    except Exception as e:
        print(f"DATABASE ERROR: {e}") # This prints to your terminal for debugging
        raise HTTPException(status_code=500, detail=f"Database Rejection: {str(e)}")
    