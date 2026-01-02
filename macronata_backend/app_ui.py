import streamlit as st
import requests
import os
from supabase import create_client

# --- 1. CONFIGURATION & PRODUCTION SWITCH ---
# Set this to False so the app talks to the Internet, not your laptop
IS_LOCAL = False 

if IS_LOCAL:
    # Local Testing (VS Code)
    API_URL = "http://127.0.0.1:8000"
    APP_URL = "http://localhost:8501"
else:
    # Live Production (Render)
    # IMPORTANT: Ensure this matches your exact Backend URL from Render
    API_URL = "https://macronata-backend.onrender.com"
    APP_URL = "https://macronata-frontend.onrender.com"

# --- 2. SUPABASE CONNECTION (FOR AUTH ONLY) ---
# The Frontend needs this to log users in.
# Ensure SUPABASE_URL and SUPABASE_KEY are set in Render -> Frontend -> Environment
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("⚠️ Critical Error: Supabase Keys are missing in Render Environment Variables.")
    st.stop()

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- 3. SESSION STATE SETUP ---
if "user" not in st.session_state:
    st.session_state.user = None
if "auth_token" not in st.session_state:
    st.session_state.auth_token = None
if "navigation" not in st.session_state:
    st.session_state.navigation = "Home"

# --- 4. AUTHENTICATION FUNCTIONS ---
def login(email, password):
    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        if res.user:
            st.session_state.user = res.user
            st.session_state.auth_token = res.session.access_token
            st.success("Login Successful!")
            st.rerun()
    except Exception as e:
        st.error(f"Login Failed: {e}")

def signup(email, password, full_name, role):
    try:
        res = supabase.auth.sign_up({"email": email, "password": password, "options": {"data": {"full_name": full_name, "role": role}}})
        if res.user:
            # Add to our public 'users' table via the Backend API to keep data in sync
            st.success("Account created! Please Log In.")
    except Exception as e:
        st.error(f"Signup Failed: {e}")

def logout():
    supabase.auth.sign_out()
    st.session_state.user = None
    st.session_state.auth_token = None
    st.rerun()

# --- 5. DATA FETCHING (TALKING TO THE BRAIN) ---
def get_headers():
    return {"Authorization": f"Bearer {st.session_state.auth_token}"}

def fetch_data(endpoint):
    """Safe data fetching that doesn't crash the app if backend is waking up"""
    try:
        res = requests.get(f"{API_URL}{endpoint}", headers=get_headers())
        if res.status_code == 200:
            return res.json()
        return []
    except:
        st.warning("Connecting to Macronata Backend... (If this persists, the server might be restarting)")
        return []

# --- 6. MAIN APP INTERFACE ---
st.set_page_config(page_title="Macronata Academy", page_icon="🎓")

# --- SIDEBAR ---
with st.sidebar:
    st.title("Macronata 🇿🇦")
    if st.session_state.user:
        st.write(f"Hello, {st.session_state.user.user_metadata.get('full_name', 'User')}")
        st.divider()
        if st.button("🏠 Home"): st.session_state.navigation = "Home"
        if st.button("🔍 Find Tutor"): st.session_state.navigation = "Tutors"
        if st.button("💳 Wallet"): st.session_state.navigation = "Wallet"
        if st.button("💬 Messages"): st.session_state.navigation = "Messages"
        if st.button("🤖 Ask Tinny (AI)"): st.session_state.navigation = "Tinny"
        st.divider()
        if st.button("Log Out"): logout()
    else:
        st.write("Please Log In to access the academy.")

# --- MAIN PAGES ---

if not st.session_state.user:
    # --- LOGIN / SIGNUP PAGE ---
    tab1, tab2 = st.tabs(["Log In", "Sign Up"])
    with tab1:
        e = st.text_input("Email")
        p = st.text_input("Password", type="password")
        if st.button("Log In"): login(e, p)
    with tab2:
        ne = st.text_input("New Email")
        np = st.text_input("New Password", type="password")
        nf = st.text_input("Full Name")
        nr = st.selectbox("I am a:", ["learner", "tutor"])
        if st.button("Sign Up"): signup(ne, np, nf, nr)

else:
    # --- LOGGED IN PAGES ---
    
    # 1. HOME
    if st.session_state.navigation == "Home":
        st.title("Welcome to Macronata Academy 🎓")
        st.write("Your gateway to personalized learning and AI tutoring.")
        
        # Show upcoming sessions
        st.subheader("📅 Your Upcoming Bookings")
        bookings = fetch_data("/my_bookings")
        if bookings:
            for b in bookings:
                with st.expander(f"Session on {b['scheduled_time'][:10]}"):
                    st.write(f"**Status:** {b['status']}")
                    st.write(f"**Cost:** R{b.get('total_cost_zar', '0.00')}")
        else:
            st.info("No bookings yet. Go to 'Find Tutor' to start!")

    # 2. FIND TUTOR
    elif st.session_state.navigation == "Tutors":
        st.title("Find a Tutor 👩‍🏫")
        tutors = fetch_data("/tutors")
        
        if tutors:
            for t in tutors:
                with st.container(border=True):
                    c1, c2 = st.columns([3, 1])
                    with c1:
                        st.subheader(t['full_name'])
                        st.write("✨ Verified Tutor")
                    with c2:
                        if st.button(f"Book {t['full_name'].split()[0]}", key=t['id']):
                            # Store tutor ID in session state for booking flow
                            st.session_state.selected_tutor = t['id']
                            st.session_state.navigation = "Book"
                            st.rerun()
        else:
            st.warning("No tutors found or Backend is syncing.")

    # 3. BOOKING FLOW (Hidden Page)
    elif st.session_state.navigation == "Book":
        st.title("Complete Booking ✅")
        date = st.date_input("Select Date")
        time = st.time_input("Select Time")
        
        st.info("Session Cost: **R200.00**")
        
        if st.button("Confirm & Pay with Wallet"):
            # Combine date and time
            dt_str = f"{date} {time}"
            payload = {
                "tutor_id": st.session_state.selected_tutor,
                "scheduled_time": str(dt_str),
                "amount_in_cents": 20000,
                "return_url": APP_URL
            }
            try:
                res = requests.post(f"{API_URL}/book_with_wallet", json=payload, headers=get_headers())
                if res.status_code == 200:
                    st.balloons()
                    st.success("Booking Confirmed! Funds deducted.")
                else:
                    st.error(f"Booking Failed: {res.text}")
            except Exception as e:
                st.error(f"Connection Error: {e}")

    # 4. WALLET
    elif st.session_state.navigation == "Wallet":
        st.title("My Wallet 💳")
        
        # Get Wallet Data
        wallet_data = fetch_data("/my_wallet")
        
        if wallet_data:
            balance = wallet_data.get('balance', 0) / 100  # Convert cents to Rands
            st.metric("Available Balance", f"R {balance:.2f}")
            
            # TOP UP SECTION
            st.divider()
            st.subheader("Top Up Funds")
            amount = st.number_input("Amount (ZAR)", min_value=10, value=100)
            
            c1, c2 = st.columns(2)
            with c1:
                if st.button("Pay with Yoco (Card)"):
                    payload = {"amount_in_cents": int(amount * 100), "return_url": APP_URL}
                    res = requests.post(f"{API_URL}/create_deposit", json=payload, headers=get_headers())
                    if res.status_code == 200:
                        data = res.json()
                        if data['url']:
                            st.link_button("👉 Proceed to Yoco Payment", data['url'])
                        else:
                            st.info("Yoco Keys missing. Use Simulation.")
            with c2:
                # Simulation for testing
                if st.button("✅ Simulate Successful Payment"):
                    payload = {"amount_in_cents": int(amount * 100), "return_url": APP_URL}
                    requests.post(f"{API_URL}/confirm_deposit_simulated", json=payload, headers=get_headers())
                    st.success("Funds added (Simulation)!")
                    st.rerun()

            # HISTORY
            st.divider()
            st.subheader("Transaction History")
            history = wallet_data.get('history', [])
            if history:
                for h in history:
                    color = "green" if h['amount_cents'] > 0 else "red"
                    st.markdown(f":{color}[R {h['amount_cents']/100:.2f}] - {h['description']}")
        else:
            st.warning("Could not load wallet. Backend might be restarting.")

    # 5. MESSAGES (REAL SYSTEM)
    elif st.session_state.navigation == "Messages":
        st.title("Messages 💬")
        
        # 1. Select who to chat with
        # We fetch all users so you can pick one.
        all_users = fetch_data("/users")
        
        # Filter out yourself
        others = [u for u in all_users if u['id'] != st.session_state.user.id]
        
        if not others:
            st.info("No other users found yet.")
        else:
            # Create a dropdown to select a person
            user_map = {u['full_name']: u['id'] for u in others}
            selected_name = st.selectbox("Chat with:", list(user_map.keys()))
            receiver_id = user_map[selected_name]
            
            # 2. Fetch Chat History
            # We use a unique key for the container to force a refresh when you switch users
            chat_container = st.container(height=400, border=True)
            
            # Load messages
            msgs = fetch_data(f"/messages/{receiver_id}")
            
            with chat_container:
                if not msgs:
                    st.write("No messages yet. Say hi! 👋")
                else:
                    for m in msgs:
                        # Align right if I sent it, Left if they sent it
                        if m['sender_id'] == st.session_state.user.id:
                            with st.chat_message("user"):
                                st.write(m['content'])
                        else:
                            with st.chat_message("assistant"): # Using 'assistant' icon for others
                                st.write(m['content'])

            # 3. Send a Message
            prompt = st.chat_input(f"Message {selected_name}...")
            if prompt:
                payload = {"receiver_id": receiver_id, "content": prompt}
                try:
                    res = requests.post(f"{API_URL}/messages", json=payload, headers=get_headers())
                    if res.status_code == 200:
                        st.rerun() # Refresh to show new message
                    else:
                        st.error("Failed to send.")
                except Exception as e:
                    st.error(f"Error: {e}")
        
    # 6. TINNY AI
    elif st.session_state.navigation == "Tinny":
        st.title("Ask Tinny 🤖")
        
        if "chat_history" not in st.session_state:
            st.session_state.chat_history = []

        # Display Chat
        for msg in st.session_state.chat_history:
            with st.chat_message(msg["role"]):
                st.write(msg["parts"][0])
        
        # Input
        prompt = st.chat_input("Ask me about Math, Science, or English...")
        if prompt:
            # User Message
            st.chat_message("user").write(prompt)
            st.session_state.chat_history.append({"role": "user", "parts": [prompt]})
            
            # AI Response (via Backend)
            payload = {"message": prompt, "history": st.session_state.chat_history}
            try:
                res = requests.post(f"{API_URL}/chat", json=payload, headers=get_headers())
                if res.status_code == 200:
                    reply = res.json()['reply']
                    st.chat_message("model").write(reply)
                    st.session_state.chat_history.append({"role": "model", "parts": [reply]})
                else:
                    st.error("Tinny is sleeping (Backend Error).")
            except:
                st.error("Tinny is unreachable.")