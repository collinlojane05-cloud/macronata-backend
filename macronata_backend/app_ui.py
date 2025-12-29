import streamlit as st
import requests
from supabase import create_client, Client
import os
from dotenv import load_dotenv
import time

load_dotenv()
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")

if not url or not key:
    st.error("❌ API Keys missing! Check your .env file.")
    st.stop()

supabase: Client = create_client(url, key)

st.set_page_config(page_title="Macronata Academy", page_icon="🇿🇦", layout="wide")
# ENSURE THIS MATCHES YOUR RENDER URL
API_URL = "https://macronata-backend.onrender.com" 

if "user" not in st.session_state:
    st.session_state.user = None
if "role" not in st.session_state:
    st.session_state.role = None 
if "session_token" not in st.session_state:
    st.session_state.session_token = None

def get_auth_headers():
    if st.session_state.session_token:
        return {"Authorization": f"Bearer {st.session_state.session_token}"}
    return {}

def fetch_user_role(user_id):
    try:
        response = supabase.table("users").select("role").eq("id", user_id).single().execute()
        if response.data:
            return response.data.get("role")
    except:
        return "learner" 
    return "learner"

def show_login_page():
    st.markdown("<h1 style='text-align: center;'>🇿🇦 Macronata Academy</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        tab1, tab2 = st.tabs(["Login", "Sign Up"])
        with tab1:
            email = st.text_input("Email", key="login_email")
            password = st.text_input("Password", type="password", key="login_pass")
            if st.button("Log In", use_container_width=True):
                try:
                    response = supabase.auth.sign_in_with_password({"email": email, "password": password})
                    st.session_state.user = response.user
                    st.session_state.session_token = response.session.access_token
                    role = fetch_user_role(response.user.id)
                    st.session_state.role = role
                    st.success(f"Welcome back! Logging in as {role}...")
                    st.rerun()
                except Exception as e:
                    st.error(f"Login failed: {e}")

        with tab2:
            new_email = st.text_input("Email", key="signup_email")
            new_pass = st.text_input("Password", type="password", key="signup_pass")
            if st.button("Sign Up", use_container_width=True):
                try:
                    response = supabase.auth.sign_up({"email": new_email, "password": new_pass})
                    if response.user:
                        supabase.table("users").insert({
                            "id": response.user.id, 
                            "full_name": new_email, 
                            "email": new_email,     
                            "role": "learner"
                        }).execute()
                        st.success("Account created! Check email or log in.")
                except Exception as e:
                    st.error(f"Signup failed: {e}")

if st.session_state.user is None:
    show_login_page()
else:
    st.sidebar.title("Macronata 🇿🇦")
    st.sidebar.caption(f"User: {st.session_state.user.email}")
    st.sidebar.markdown(f"**Role:** `{st.session_state.role.upper()}`")
    
    if st.sidebar.button("Log Out"):
        st.session_state.user = None
        st.session_state.role = None
        st.session_state.session_token = None
        st.rerun()

    if st.session_state.role == 'tutor':
        st.title("🎓 Tutor Workstation")
        with st.spinner("Loading bookings..."):
            try:
                res = requests.get(f"{API_URL}/tutor_bookings", headers=get_auth_headers())
                bookings = res.json() if res.status_code == 200 else []
            except:
                bookings = []
        
        if bookings:
            for b in bookings:
                with st.container(border=True):
                    col1, col2 = st.columns([3, 1])
                    with col1:
                        st.subheader(f"📅 {b.get('scheduled_time', '')[:16].replace('T', ' ')}")
                        learner = b.get('learner', {})
                        st.write(f"**Student:** {learner.get('full_name', 'Unknown')}")
                    with col2:
                        st.success("CONFIRMED")
        else:
            st.info("No bookings yet.")

    else:
        page = st.sidebar.radio("Navigate", ["Tinny (AI Tutor)", "Find a Tutor", "My Profile"])

        if page == "Tinny (AI Tutor)":
            st.title("🤖 Chat with Tinny")
            
            if "messages" not in st.session_state:
                st.session_state.messages = []

            for message in st.session_state.messages:
                with st.chat_message(message["role"]):
                    st.markdown(message["content"])

            if prompt := st.chat_input("Ask a question..."):
                st.session_state.messages.append({"role": "user", "content": prompt})
                with st.chat_message("user"):
                    st.markdown(prompt)
                
                gemini_history = []
                for msg in st.session_state.messages[:-1]:
                    role = "user" if msg["role"] == "user" else "model"
                    gemini_history.append({"role": role, "parts": [msg["content"]]})

                with st.chat_message("assistant"):
                    try:
                        res = requests.post(
                            f"{API_URL}/chat", 
                            json={"message": prompt, "history": gemini_history},
                            headers=get_auth_headers()
                        )
                        reply = res.json()["reply"]
                        st.markdown(reply)
                        st.session_state.messages.append({"role": "assistant", "content": reply})
                    except:
                        st.error("Tinny is offline.")

        elif page == "Find a Tutor":
            st.title("📚 Find a Tutor")
            tutors = []
            try:
                res = requests.get(f"{API_URL}/tutors", headers=get_auth_headers())
                tutors = res.json() if res.status_code == 200 else []
            except:
                st.error("Could not load tutors.")

            for tutor in tutors:
                with st.container(border=True):
                    col1, col2 = st.columns([1, 4])
                    with col1: st.markdown("<h1>🎓</h1>", unsafe_allow_html=True)
                    with col2:
                        name = tutor.get("full_name") or "Tutor"
                        st.subheader(name)
                        if st.button("Book Session", key=tutor['id']):
                            st.session_state['selected_tutor_id'] = tutor['id']
                            st.session_state['selected_tutor_name'] = name
                            st.rerun()

            if 'selected_tutor_id' in st.session_state:
                st.divider()
                st.info(f"Booking with **{st.session_state['selected_tutor_name']}**")
                with st.form("booking_form"):
                    date = st.date_input("Date")
                    time_val = st.time_input("Time")
                    if st.form_submit_button("Confirm Payment (R200)"):
                        payload = {
                            "tutor_id": st.session_state['selected_tutor_id'],
                            "scheduled_time": f"{date}T{time_val}"
                        }
                        try:
                            res = requests.post(f"{API_URL}/book_session", json=payload, headers=get_auth_headers())
                            if res.status_code == 200:
                                st.balloons()
                                st.success("✅ Booked!")
                                del st.session_state['selected_tutor_id']
                                time.sleep(2)
                                st.rerun()
                            else:
                                st.error(f"Failed: {res.text}")
                        except Exception as e:
                            st.error(f"Error: {e}")

        elif page == "My Profile":
            st.title("👤 My Profile")
            try:
                res = requests.get(f"{API_URL}/my_bookings", headers=get_auth_headers())
                bookings = res.json() if res.status_code == 200 else []
                for b in bookings:
                    st.write(f"📅 {b['scheduled_time'][:16]} with {b['tutor']['full_name']}")
            except:
                st.write("No bookings found.")