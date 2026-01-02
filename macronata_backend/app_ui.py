import streamlit as st
import requests
import os
from supabase import create_client
import time

# --- 1. CONFIGURATION ---
IS_LOCAL = False # False = Live on Render

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

if "nav" in st.query_params:
    target_page = st.query_params["nav"]
    if st.session_state.user:
        st.session_state.navigation = target_page
        st.query_params.clear()

# --- 4. HELPERS ---
def get_headers():
    return {"Authorization": f"Bearer {st.session_state.auth_token}"}

def fetch_data(endpoint):
    """Robust fetch with retry"""
    retries = 0
    max_retries = 3
    while retries < max_retries:
        try:
            res = requests.get(f"{API_URL}{endpoint}", headers=get_headers(), timeout=5)
            if res.status_code == 200: return res.json()
            time.sleep(2)
            retries += 1
        except:
            time.sleep(5)
            retries += 1
    return []

def login(email, password):
    try:
        res = supabase.auth.sign_in_with_password({"email": email, "password": password})
        if res.user:
            st.session_state.user = res.user
            st.session_state.auth_token = res.session.access_token
            if "nav" in st.query_params:
                st.session_state.navigation = st.query_params["nav"]
                st.query_params.clear()
            st.rerun()
    except Exception as e: st.error(f"Login Failed: {e}")

def logout():
    supabase.auth.sign_out()
    st.session_state.user = None
    st.session_state.auth_token = None
    st.rerun()

# --- 5. MAIN APP ---
st.set_page_config(page_title="Macronata Academy", page_icon="🇿🇦")

if not st.session_state.user:
    # --- LOGIN / SIGNUP ---
    st.markdown("<h1 style='text-align: center;'>Macronata Academy 🎓</h1>", unsafe_allow_html=True)
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
    # --- AUTHENTICATED ---
    # Fetch Profile to Check Verification Status
    try:
        res = requests.get(f"{API_URL}/my_profile", headers=get_headers())
        profile = res.json() if res.status_code == 200 else {}
    except: profile = {}
    
    status = profile.get("verification_status", "pending_submission")
    user_role = profile.get("role", "learner")

    # === GATEKEEPER LOGIC ===
    
    if status == "pending_submission":
        st.title("🔐 Identity Verification")
        st.warning("Per South African law, we must verify your identity.")
        
        with st.form("verify_form"):
            st.write("### 1. Personal Details")
            id_num = st.text_input("SA ID Number (13 Digits)", max_chars=13)
            phone = st.text_input("Phone Number")
            
            st.write("### 2. Proof of Credibility")
            if user_role == 'tutor':
                st.info("Upload: Matric Certificate or University Transcript")
            else:
                st.info("Upload: ID Document or School Report")
            doc = st.file_uploader("Document (PDF/Image)", type=['pdf','png','jpg'])
            
            if st.form_submit_button("Submit for Verification"):
                if not id_num or len(id_num) != 13:
                    st.error("Invalid ID Number.")
                elif not doc:
                    st.error("Document required.")
                else:
                    with st.spinner("Encrypting..."):
                        # Upload Doc
                        files = {"file": (doc.name, doc.getvalue(), doc.type)}
                        r_up = requests.post(f"{API_URL}/upload_verification_doc", files=files, headers=get_headers())
                        if r_up.status_code == 200:
                            # Submit Data
                            payload = {"id_number": id_num, "phone_number": phone}
                            r_sub = requests.post(f"{API_URL}/submit_verification", json=payload, headers=get_headers())
                            if r_sub.status_code == 200:
                                st.success("Submitted successfully!")
                                time.sleep(2)
                                st.rerun()
                            else: st.error(f"Error: {r_sub.text}")
                        else: st.error("Document upload failed.")

    elif status == "pending_approval":
        st.title("⏳ Under Review")
        st.info("Your documents have been received. Verification takes ~24 hours.")
        if st.button("Check Status"): st.rerun()
        
    elif status == "verified":
        # === FULL APP ACCESS ===
        
        with st.sidebar:
            st.title("Macronata 🇿🇦")
            st.caption(f"✅ Verified {user_role.capitalize()}")
            st.divider()
            if st.button("🏠 Home"): st.session_state.navigation = "Home"
            if st.button("🔍 Find Tutor"): st.session_state.navigation = "Tutors"
            if st.button("💳 Wallet"): st.session_state.navigation = "Wallet"
            if st.button("💬 Messages"): st.session_state.navigation = "Messages"
            if st.button("🤖 Ask Tinny"): st.session_state.navigation = "Tinny"
            st.divider()
            if st.button("Log Out"): logout()

        if st.session_state.navigation == "Home":
            st.title("Welcome Back 🎓")
            bookings = fetch_data("/my_bookings")
            if bookings:
                for b in bookings:
                    st.info(f"Session with {b['tutor']['full_name']} on {b['scheduled_time'][:10]}")
            else: st.write("No active bookings.")

        elif st.session_state.navigation == "Tutors":
            st.title("Find a Tutor 👩‍🏫")
            tutors = fetch_data("/tutors")
            if tutors:
                for t in tutors:
                    with st.container(border=True):
                        c1, c2 = st.columns([3, 1])
                        c1.subheader(t['full_name'])
                        if c2.button(f"Book", key=t['id']):
                            st.session_state.selected_tutor = t['id']
                            st.session_state.navigation = "Book"
                            st.rerun()
            else: st.info("No verified tutors found yet.")

        elif st.session_state.navigation == "Book":
            st.title("Complete Booking")
            d = st.date_input("Date")
            t = st.time_input("Time")
            if st.button("Confirm & Pay R200"):
                link = f"{APP_URL}?nav=Home"
                payload = {"tutor_id": st.session_state.selected_tutor, "scheduled_time": f"{d} {t}", "return_url": link}
                res = requests.post(f"{API_URL}/book_with_wallet", json=payload, headers=get_headers())
                if res.status_code == 200:
                    st.balloons()
                    st.success("Booked!")
                    time.sleep(2)
                    st.session_state.navigation = "Home"
                    st.rerun()
                else: st.error(res.text)

        elif st.session_state.navigation == "Wallet":
            st.title("My Wallet 💳")
            w = fetch_data("/my_wallet")
            if w:
                st.metric("Balance", f"R {w.get('balance',0)/100:.2f}")
                amt = st.number_input("Top Up (ZAR)", value=100)
                
                c1, c2 = st.columns(2)
                with c1:
                    if st.button("Pay with Yoco"):
                        link = f"{APP_URL}?nav=Wallet"
                        res = requests.post(f"{API_URL}/create_deposit", json={"amount_in_cents": int(amt*100), "return_url": link}, headers=get_headers())
                        if res.status_code == 200: 
                            if res.json()['url']: st.link_button("👉 Pay Now", res.json()['url'])
                            else: st.info("Simulating...")
                with c2:
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
                
                c1, c2 = st.columns([3, 1])
                c1.caption("🟢 Online")
                if c2.button("📞 Call"):
                    link = f"https://meet.jit.si/Macronata-{st.session_state.user.id[:4]}-{rec_id[:4]}"
                    requests.post(f"{API_URL}/messages", json={"receiver_id": rec_id, "content": f"📞 Join call: {link}"}, headers=get_headers())
                    st.rerun()

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
                            except: pass
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