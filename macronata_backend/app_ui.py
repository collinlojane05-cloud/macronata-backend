import streamlit as st
import requests
import os
from supabase import create_client

# --- 1. CONFIGURATION ---
IS_LOCAL = False # Set to FALSE for Render

if IS_LOCAL:
    API_URL = "http://127.0.0.1:8000"
    APP_URL = "http://localhost:8501"
else:
    API_URL = "https://macronata-backend.onrender.com"
    APP_URL = "https://macronata-frontend.onrender.com"

# --- 2. SUPABASE AUTH ---
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("⚠️ Critical Error: Supabase Keys missing.")
    st.stop()

supabase = create_client(SUPABASE_URL, SUPABASE_KEY)

# --- 3. SESSION STATE ---
if "user" not in st.session_state: st.session_state.user = None
if "auth_token" not in st.session_state: st.session_state.auth_token = None
if "navigation" not in st.session_state: st.session_state.navigation = "Home"

# --- 4. HELPERS ---
def get_headers():
    return {"Authorization": f"Bearer {st.session_state.auth_token}"}

def fetch_data(endpoint):
    try:
        res = requests.get(f"{API_URL}{endpoint}", headers=get_headers())
        if res.status_code == 200: return res.json()
        return []
    except: return []

def login(email, password):
    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        if res.user:
            st.session_state.user = res.user
            st.session_state.auth_token = res.session.access_token
            st.rerun()
    except Exception as e: st.error(f"Login Failed: {e}")

def logout():
    supabase.auth.sign_out()
    st.session_state.user = None
    st.session_state.auth_token = None
    st.rerun()

# --- 5. MAIN APP ---
st.set_page_config(page_title="Macronata Academy", page_icon="🎓")

with st.sidebar:
    st.title("Macronata 🇿🇦")
    if st.session_state.user:
        st.write(f"Hello, {st.session_state.user.user_metadata.get('full_name', 'User')}")
        st.divider()
        if st.button("🏠 Home"): st.session_state.navigation = "Home"
        if st.button("🔍 Find Tutor"): st.session_state.navigation = "Tutors"
        if st.button("💳 Wallet"): st.session_state.navigation = "Wallet"
        if st.button("💬 Messages"): st.session_state.navigation = "Messages"
        if st.button("🤖 Ask Tinny"): st.session_state.navigation = "Tinny"
        st.divider()
        if st.button("Log Out"): logout()
    else:
        st.write("Please Log In.")

if not st.session_state.user:
    # LOGIN / SIGNUP
    t1, t2 = st.tabs(["Log In", "Sign Up"])
    with t1:
        e = st.text_input("Email")
        p = st.text_input("Password", type="password")
        if st.button("Log In"): login(e, p)
    with t2:
        ne = st.text_input("New Email")
        np = st.text_input("New Password", type="password")
        nf = st.text_input("Full Name")
        nr = st.selectbox("I am a:", ["learner", "tutor"])
        if st.button("Sign Up"):
            try:
                res = supabase.auth.sign_up({"email": ne, "password": np, "options": {"data": {"full_name": nf, "role": nr}}})
                st.success("Account created! Please Log In.")
            except Exception as e: st.error(str(e))

else:
    # --- LOGGED IN ---
    
    if st.session_state.navigation == "Home":
        st.title("Welcome Back 🎓")
        st.subheader("📅 Your Bookings")
        bookings = fetch_data("/my_bookings")
        if bookings:
            for b in bookings:
                st.info(f"Session with {b['tutor']['full_name']} on {b['scheduled_time'][:10]}")
        else: st.write("No active bookings.")

    elif st.session_state.navigation == "Tutors":
        st.title("Find a Tutor 👩‍🏫")
        tutors = fetch_data("/tutors")
        for t in tutors:
            with st.container(border=True):
                c1, c2 = st.columns([3, 1])
                c1.subheader(t['full_name'])
                if c2.button(f"Book", key=t['id']):
                    st.session_state.selected_tutor = t['id']
                    st.session_state.navigation = "Book"
                    st.rerun()

    elif st.session_state.navigation == "Book":
        st.title("Complete Booking")
        d = st.date_input("Date")
        t = st.time_input("Time")
        if st.button("Confirm & Pay R200"):
            payload = {"tutor_id": st.session_state.selected_tutor, "scheduled_time": f"{d} {t}", "return_url": APP_URL}
            res = requests.post(f"{API_URL}/book_with_wallet", json=payload, headers=get_headers())
            if res.status_code == 200:
                st.balloons()
                st.success("Booked!")
            else: st.error(res.text)

    elif st.session_state.navigation == "Wallet":
        st.title("My Wallet 💳")
        w = fetch_data("/my_wallet")
        if w:
            st.metric("Balance", f"R {w.get('balance',0)/100:.2f}")
            amt = st.number_input("Top Up (ZAR)", value=100)
            if st.button("Pay with Yoco"):
                res = requests.post(f"{API_URL}/create_deposit", json={"amount_in_cents": int(amt*100), "return_url": APP_URL}, headers=get_headers())
                if res.status_code == 200: 
                    if res.json()['url']: st.link_button("Pay Now", res.json()['url'])
                    else: st.info("Simulating...")
            
            if st.button("✅ Simulate Payment"):
                requests.post(f"{API_URL}/confirm_deposit_simulated", json={"amount_in_cents": int(amt*100), "return_url": APP_URL}, headers=get_headers())
                st.success("Added!")
                st.rerun()

    elif st.session_state.navigation == "Messages":
        st.title("Messages 💬")
        users = fetch_data("/users")
        others = [u for u in users if u['id'] != st.session_state.user.id] if users else []
        
        if others:
            user_map = {u['full_name']: u['id'] for u in others}
            target = st.selectbox("Chat with:", list(user_map.keys()))
            rec_id = user_map[target]
            
            # CALL BUTTON & STATUS
            c1, c2 = st.columns([3, 1])
            c1.caption("🟢 Online")
            if c2.button("📞 Call"):
                link = f"https://meet.jit.si/Macronata-{st.session_state.user.id[:4]}-{rec_id[:4]}"
                requests.post(f"{API_URL}/messages", json={"receiver_id": rec_id, "content": f"📞 Join call: {link}"}, headers=get_headers())
                st.rerun()

            # CHAT HISTORY
            msgs = fetch_data(f"/messages/{rec_id}")
            cnt = st.container(height=400, border=True)
            with cnt:
                if msgs:
                    for m in msgs:
                        role = "user" if m['sender_id'] == st.session_state.user.id else "assistant"
                        with st.chat_message(role):
                            if m['content']: st.write(m['content'])
                            if m.get('media_url'):
                                if m['media_type'] == 'image': st.image(m['media_url'])
                                elif m['media_type'] == 'audio': st.audio(m['media_url'])
                else: st.write("No messages.")

            # INPUT AREA
            with st.form("chat"):
                c_txt, c_up = st.columns([4, 1])
                txt = c_txt.text_input("Message...")
                up = c_up.file_uploader("📎", type=["png","jpg","mp3"], label_visibility="collapsed")
                
                if st.form_submit_button("Send"):
                    media_url, media_type = None, None
                    if up:
                        try:
                            files = {"file": (up.name, up.getvalue(), up.type)}
                            r = requests.post(f"{API_URL}/upload", files=files, headers=get_headers())
                            if r.status_code == 200:
                                media_url = r.json()['url']
                                media_type = 'image' if 'image' in up.type else 'audio'
                        except Exception as e: st.error(f"Upload fail: {e}")
                    
                    if txt or media_url:
                        requests.post(f"{API_URL}/messages", json={"receiver_id": rec_id, "content": txt, "media_url": media_url, "media_type": media_type}, headers=get_headers())
                        st.rerun()

    elif st.session_state.navigation == "Tinny":
        st.title("Ask Tinny 🤖")
        if "chat_history" not in st.session_state: st.session_state.chat_history = []
        for msg in st.session_state.chat_history:
            st.chat_message(msg["role"]).write(msg["parts"][0])
        
        prompt = st.chat_input("Ask me...")
        if prompt:
            st.chat_message("user").write(prompt)
            st.session_state.chat_history.append({"role": "user", "parts": [prompt]})
            res = requests.post(f"{API_URL}/chat", json={"message": prompt, "history": st.session_state.chat_history}, headers=get_headers())
            if res.status_code == 200:
                reply = res.json()['reply']
                st.chat_message("model").write(reply)
                st.session_state.chat_history.append({"role": "model", "parts": [reply]})