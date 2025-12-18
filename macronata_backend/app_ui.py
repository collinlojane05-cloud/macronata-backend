import streamlit as st
import requests
from supabase import create_client, Client
import os
from dotenv import load_dotenv

# 1. Load Environment Variables (Your Keys)
load_dotenv()
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")

# Check if keys are found
if not url or not key:
    st.error("❌ API Keys missing! Make sure your .env file is in this folder.")
    st.stop()

# 2. Initialize Supabase
supabase: Client = create_client(url, key)

# 3. App Config
st.set_page_config(page_title="Macronata Academy", page_icon="🇿🇦", layout="wide")
API_URL = "https://macronata-backend.onrender.com" # Your LIVE Render URL

# --- AUTHENTICATION LOGIC ---
if "user" not in st.session_state:
    st.session_state.user = None

def show_login_page():
    st.markdown("<h1 style='text-align: center;'>🇿🇦 Macronata Academy</h1>", unsafe_allow_html=True)
    st.markdown("<p style='text-align: center;'>The future of South African Education</p>", unsafe_allow_html=True)
    
    col1, col2, col3 = st.columns([1,2,1])
    
    with col2:
        tab1, tab2 = st.tabs(["Login", "Sign Up"])
        
        # LOGIN TAB
        with tab1:
            email = st.text_input("Email", key="login_email")
            password = st.text_input("Password", type="password", key="login_pass")
            if st.button("Log In", use_container_width=True):
                try:
                    response = supabase.auth.sign_in_with_password({"email": email, "password": password})
                    st.session_state.user = response.user
                    st.success("Login successful!")
                    st.rerun()
                except Exception as e:
                    st.error(f"Login failed: {e}")

        # SIGN UP TAB
        with tab2:
            st.write("Create a new student account.")
            new_email = st.text_input("Email", key="signup_email")
            new_pass = st.text_input("Password", type="password", key="signup_pass")
            if st.button("Sign Up", use_container_width=True):
                try:
                    # 1. Create Auth User
                    response = supabase.auth.sign_up({"email": new_email, "password": new_pass})
                    
                    # 2. Add to your 'users' table
                    if response.user:
                        user_id = response.user.id
                        # Default role is 'learner'
                        supabase.table("users").insert({"id": user_id, "name": new_email, "role": "learner"}).execute()
                        st.success("Account created! Check your email or try logging in.")
                except Exception as e:
                    st.error(f"Signup failed: {e}")

# --- MAIN APP LOGIC ---
if st.session_state.user is None:
    show_login_page()
else:
    # Sidebar Navigation
    st.sidebar.title("🇿🇦 Macronata")
    st.sidebar.caption(f"Logged in as: {st.session_state.user.email}")
    
    page = st.sidebar.radio("Go to", ["Tinny (AI Tutor)", "Find a Tutor", "My Profile"])
    
    st.sidebar.divider()
    if st.sidebar.button("Log Out"):
        st.session_state.user = None
        st.rerun()

    # --- PAGE 1: TINNY ---
    if page == "Tinny (AI Tutor)":
        st.title("🤖 Chat with Tinny")
        st.caption("Your AI Tutor for CAPS & IEB Curriculum")

        if "messages" not in st.session_state:
            st.session_state.messages = []

        for message in st.session_state.messages:
            with st.chat_message(message["role"]):
                st.markdown(message["content"])

        if prompt := st.chat_input("Ask Tinny a question..."):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"):
                st.markdown(prompt)

            with st.chat_message("assistant"):
                with st.spinner("Tinny is thinking..."):
                    try:
                        response = requests.post(f"{API_URL}/chat", json={"message": prompt})
                        if response.status_code == 200:
                            reply = response.json()["reply"]
                            st.markdown(reply)
                            st.session_state.messages.append({"role": "assistant", "content": reply})
                        else:
                            st.error("Tinny is sleeping (Server Error).")
                    except Exception as e:
                        st.error(f"Connection Error: {e}")

    # --- PAGE 2: MARKETPLACE (BOOKING) ---
    elif page == "Find a Tutor":
        st.title("📚 Find Your Perfect Tutor")
        st.caption("Browse our top-rated university tutors.")

        # 1. Fetch Tutors from Backend
        with st.spinner("Loading Tutors..."):
            try:
                tutors_response = requests.get(f"{API_URL}/tutors")
                if tutors_response.status_code == 200:
                    tutors = tutors_response.json()
                else:
                    st.error("Could not load tutors.")
                    tutors = []
            except Exception as e:
                st.error(f"Connection Error: {e}")
                tutors = []

        # 2. Display Tutors
        if tutors:
            for tutor in tutors:
                with st.container(border=True):
                    col1, col2 = st.columns([1, 4])
                    with col1:
                        st.markdown("<h1>🎓</h1>", unsafe_allow_html=True)
                    with col2:
                        st.subheader(tutor.get("name", "Unknown Tutor"))
                        st.write(f"**Specialty:** {tutor.get('role', 'General').title()}")
                        
                        if st.button(f"Book Session", key=tutor['id']):
                            st.session_state['selected_tutor_id'] = tutor['id']
                            st.session_state['selected_tutor_name'] = tutor['name']
                            st.rerun()

            # 3. Booking Form (Only shows if a tutor is selected)
            if 'selected_tutor_id' in st.session_state:
                st.divider()
                st.info(f"You are booking a session with **{st.session_state['selected_tutor_name']}**")
                
                with st.form("final_booking_form"):
                    date = st.date_input("Select Date")
                    time = st.time_input("Select Time")
                    submitted = st.form_submit_button("Confirm Payment (R200)")
                    
                    if submitted:
                        scheduled_time = f"{date}T{time}"
                        payload = {
                            "tutor_id": st.session_state['selected_tutor_id'],
                            "learner_id": st.session_state.user.id,
                            "scheduled_time": str(scheduled_time),
                            "total_cost_zar": 200.0
                        }
                        
                        with st.spinner("Processing Secure Transaction..."):
                            try:
                                res = requests.post(f"{API_URL}/book_session", json=payload)
                                if res.status_code == 200:
                                    st.balloons()
                                    st.success("✅ Session Booked! The tutor has been notified.")
                                else:
                                    st.error("Booking Failed.")
                            except Exception as e:
                                st.error(f"Error: {e}")
        else:
            st.info("No tutors found. (Did you add users with role 'tutor' in Supabase?)")

    # --- PAGE 3: PROFILE ---
    elif page == "My Profile":
        st.title("👤 Student Profile")
        st.write(f"**Email:** {st.session_state.user.email}")
        st.write(f"**User ID:** {st.session_state.user.id}")
        st.info("Course history and grades coming soon!")