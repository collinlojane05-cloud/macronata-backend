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
class ChatRequest(BaseModel):
    message: str

class BookingRequest(BaseModel):
    tutor_id: str
    learner_id: str
    scheduled_time: str
    total_cost_zar: float

# --- ENDPOINTS ---

@app.get("/")
def home():
    return {"message": "Macronata Academy Enterprise System Online"}

@app.get("/tutors")
def get_tutors():
    try:
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
        dt_object = datetime.fromisoformat(booking.scheduled_time)
        
        data = {
            "tutor_id": booking.tutor_id,
            "learner_id": booking.learner_id,
            "scheduled_time": dt_object.isoformat(), 
            "status": "booked",
            "total_cost_zar": booking.total_cost_zar
        }
        
        response = supabase.table("sessions").insert(data).execute()
        return {"message": "Session booked successfully!", "data": response.data[0]}
    except Exception as e:
        print(f"DATABASE ERROR: {e}")
        raise HTTPException(status_code=500, detail=f"Database Rejection: {str(e)}")

# --- NEW ENDPOINT: BOOKING HISTORY ---
@app.get("/my_bookings/{learner_id}")
def get_my_bookings(learner_id: str):
    try:
        # We select all columns from sessions AND join with users to get the tutor's full name
        response = supabase.table("sessions").select(
            "*, tutor:users!tutor_id(full_name)"
        ).eq("learner_id", learner_id).order("scheduled_time").execute()
        
        return response.data
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    