import streamlit as st
import requests
from supabase import create_client, Client
import os
from dotenv import load_dotenv
import time

load_dotenv()

# --- CONFIGURATION SWITCH ---
# CHANGE THIS TO 'False' BEFORE PUSHING TO GITHUB FOR RENDER!
IS_LOCAL = True 

if IS_LOCAL:
    # 1. Dev Mode (Localhost)
    APP_BASE_URL = "http://localhost:8501" 
    API_URL = "https://macronata-backend.onrender.com" # You can use Live backend even when local
else:
    # 2. Production Mode (Render)
    # REPLACE THIS with your actual Render Frontend URL after you deploy Step 2
    APP_BASE_URL = "https://macronata-frontend.onrender.com" 
    API_URL = "https://macronata-backend.onrender.com"

# --- SUPABASE SETUP ---
raw_url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")

if not raw_url or not key:
    st.error("❌ API Keys missing! Check your .env file or Render Env Vars.")
    st.stop()

supabase_url = raw_url.rstrip("/")
try:
    supabase: Client = create_client(supabase_url, key)
except Exception as e:
    st.error(f"Init Error: {e}")
    st.stop()

st.set_page_config(page_title="Macronata Academy", page_icon="🇿🇦", layout="wide")

# --- STATE ---
if "user" not in st.session_state: st.session_state.user = None
if "role" not in st.session_state: st.session_state.role = None 
if "session_token" not in st.session_state: st.session_state.session_token = None
if "uploader_key" not in st.session_state: st.session_state.uploader_key = 0 
if "messages" not in st.session_state: st.session_state.messages = []

# --- HELPERS ---
def get_auth_headers():
    return {"Authorization": f"Bearer {st.session_state.session_token}"} if st.session_state.session_token else {}

def upload_file_secure(file_obj, is_audio=False):
    try:
        ext = "wav" if is_audio else file_obj.name.split('.')[-1]
        file_name = f"{st.session_state.user.id}_{int(time.time())}.{ext}"
        mime_type = "audio/wav" if is_audio else file_obj.type
        headers = {"Authorization": f"Bearer {st.session_state.session_token}", "apikey": key, "Content-Type": mime_type}
        upload_endpoint = f"{supabase_url}/storage/v1/object/chat_assets/{file_name}"
        data = file_obj.getvalue() if hasattr(file_obj, 'getvalue') else file_obj
        res = requests.post(upload_endpoint, data=data, headers=headers)
        return (f"{supabase_url}/storage/v1/object/public/chat_assets/{file_name}", mime_type) if res.status_code == 200 else (None, None)
    except: return None, None

# --- AUTH ---
def show_login_page():
    st.markdown("<h1 style='text-align: center;'>🇿🇦 Macronata Academy</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        tab1, tab2 = st.tabs(["Login", "Sign Up"])
        with tab1:
            email = st.text_input("Email", key="l_e")
            password = st.text_input("Password", type="password", key="l_p")
            if st.button("Log In", use_container_width=True):
                try:
                    res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                    st.session_state.user = res.user
                    st.session_state.session_token = res.session.access_token
                    try:
                        role_res = supabase.table("users").select("role").eq("id", res.user.id).single().execute()
                        st.session_state.role = role_res.data['role']
                    except: st.session_state.role = "learner"
                    st.rerun()
                except Exception as e: st.error(f"Login failed: {e}")

        with tab2:
            st.subheader("Join the Marketplace")
            new_name = st.text_input("Full Name", key="s_n")
            new_email = st.text_input("Email", key="s_e")
            new_pass = st.text_input("Password", type="password", key="s_p")
            new_role = st.selectbox("I am a:", ["learner", "tutor"], key="s_r")
            if st.button("Sign Up", use_container_width=True):
                if new_name:
                    try:
                        res = supabase.auth.sign_up({"email": new_email, "password": new_pass})
                        if res.user:
                            supabase.table("users").insert({"id": res.user.id, "full_name": new_name, "email": new_email, "role": new_role}).execute()
                            st.success(f"Welcome {new_name}! Please log in.")
                    except Exception as e: st.error(f"Error: {e}")
                else: st.error("Name required.")

# --- MAIN APP ---
if st.session_state.user is None:
    show_login_page()
else:
    st.sidebar.title("Macronata 🇿🇦")
    st.sidebar.write(f"**{st.session_state.user.user_metadata.get('full_name', 'User')}**")
    menu = ["Messages", "Wallet", "Tinny (AI)", "Profile"]
    if st.session_state.role == "learner": menu.insert(1, "Find Tutor")
    page = st.sidebar.radio("Navigate", menu)
    
    if st.sidebar.button("Log Out"):
        st.session_state.user = None
        st.session_state.session_token = None
        st.session_state.messages = [] 
        st.rerun()

    if page == "Wallet":
        st.title("💰 Digital Wallet")
        try:
            res = requests.get(f"{API_URL}/my_wallet", headers=get_auth_headers())
            if res.status_code == 200:
                data = res.json()
                balance_zar = data['balance'] / 100
                st.metric(label="Current Balance", value=f"R {balance_zar:,.2f}")
                st.divider()
                c1, c2 = st.columns(2)
                with c1:
                    st.subheader("Top Up Wallet")
                    amount = st.number_input("Amount (ZAR)", min_value=10, value=200, step=10)
                    if st.button("Add Funds"):
                        with st.spinner("Creating Payment Link..."):
                            # PASS DYNAMIC URL
                            payload = {"amount_in_cents": int(amount * 100), "return_url": APP_BASE_URL}
                            pay_res = requests.post(f"{API_URL}/create_deposit", json=payload, headers=get_auth_headers())
                            if pay_res.status_code == 200:
                                p_data = pay_res.json()
                                if p_data.get('url'):
                                    st.link_button("👉 Pay on Yoco", p_data['url'])
                                    if st.button("✅ Simulate Success (Testing)"):
                                        requests.post(f"{API_URL}/confirm_deposit_simulated", json=payload, headers=get_auth_headers())
                                        st.success("Funds added!")
                                        time.sleep(1)
                                        st.rerun()
                with c2:
                    if st.session_state.role == "tutor":
                        st.subheader("Withdraw Funds")
                        w_amount = st.number_input("Withdraw Amount (ZAR)", min_value=50, max_value=int(balance_zar) if balance_zar > 0 else 0, step=50)
                        bank = st.text_input("Bank Details")
                        if st.button("Request Payout"):
                            if w_amount > balance_zar: st.error("Insufficient funds.")
                            else:
                                w_res = requests.post(f"{API_URL}/withdraw", json={"amount_in_cents": int(w_amount*100), "bank_details": bank}, headers=get_auth_headers())
                                if w_res.status_code == 200:
                                    st.success("Processed!")
                                    time.sleep(1)
                                    st.rerun()

                st.divider()
                st.subheader("Transaction History")
                for txn in data['history']:
                    color = "green" if txn['amount_cents'] > 0 else "red"
                    amount_fmt = f"R {abs(txn['amount_cents']/100):.2f}"
                    symbol = "+" if txn['amount_cents'] > 0 else "-"
                    st.markdown(f"**{txn['description']}** : <span style='color:{color}'>{symbol} {amount_fmt}</span>", unsafe_allow_html=True)
                    st.write("---")
        except: st.error("Connection Error.")

    elif page == "Find Tutor":
        st.title("📚 Book a Tutor")
        try:
            tutors = requests.get(f"{API_URL}/tutors", headers=get_auth_headers()).json()
            if not tutors: st.info("No tutors found.")
            for t in tutors:
                with st.container(border=True):
                    c1, c2 = st.columns([3, 1])
                    with c1:
                        st.subheader(t.get('full_name'))
                        st.write(f"**Email:** {t.get('email')}")
                    with c2:
                        st.write("**Rate:** R200.00 / session")
                        if st.button(f"Select Tutor", key=t['id']):
                            st.session_state['selected_tutor'] = t
                            st.rerun()
            if 'selected_tutor' in st.session_state:
                t = st.session_state['selected_tutor']
                st.divider()
                st.info(f"Booking: {t.get('full_name')}")
                d = st.date_input("Date")
                tm = st.time_input("Time")
                if st.button("Confirm Booking (Pay R200)"):
                    payload = {"tutor_id": t['id'], "scheduled_time": f"{d}T{tm}", "amount_in_cents": 20000, "return_url": APP_BASE_URL}
                    with st.spinner("Processing..."):
                        res = requests.post(f"{API_URL}/book_with_wallet", json=payload, headers=get_auth_headers())
                        if res.status_code == 200:
                            st.balloons()
                            st.success(f"✅ Booking Confirmed!")
                            time.sleep(3)
                            del st.session_state['selected_tutor']
                            st.rerun()
                        elif res.status_code == 402: st.error("❌ Insufficient Funds! Please Top Up.")
                        else: st.error(f"Booking Failed: {res.text}")
        except: st.error("Error.")

    elif page == "Messages":
        st.title("💬 Chat")
        try:
            users = requests.get(f"{API_URL}/users", headers=get_auth_headers()).json()
            user_map = {f"{u.get('full_name')} ({u.get('role')})": u['id'] for u in users if u['id'] != st.session_state.user.id}
            receiver_name = st.selectbox("Chat with:", list(user_map.keys())) if user_map else None
            if receiver_name:
                receiver_id = user_map[receiver_name]
                if st.button("Refresh"): st.rerun()
                msgs = requests.get(f"{API_URL}/messages/{receiver_id}", headers=get_auth_headers()).json()
                with st.container(height=450):
                    for m in msgs:
                        is_me = m['sender_id'] == st.session_state.user.id
                        with st.chat_message("user" if is_me else "assistant"):
                            if m.get('content'): st.write(m['content'])
                            if m.get('media_url'):
                                if "audio" in m.get('media_type', ''): st.audio(m['media_url'])
                                else: st.image(m['media_url'])
                c1, c2, c3 = st.columns([1, 1, 4])
                with c1: voice = st.audio_input("Mic", key=f"v_{st.session_state.uploader_key}")
                with c2: file = st.file_uploader("File", key=f"f_{st.session_state.uploader_key}", label_visibility="collapsed")
                with c3: txt = st.chat_input("Message...")
                if txt or file or voice:
                    url, mtype = None, None
                    if voice: url, mtype = upload_file_secure(voice, is_audio=True)
                    elif file: url, mtype = upload_file_secure(file)
                    requests.post(f"{API_URL}/messages", json={"receiver_id": receiver_id, "content": txt, "media_url": url, "media_type": mtype}, headers=get_auth_headers())
                    st.session_state.uploader_key += 1
                    time.sleep(0.5)
                    st.rerun()
        except: pass

    elif page == "Tinny (AI)":
        st.title("🤖 Chat with Tinny")
        for m in st.session_state.messages:
            with st.chat_message(m["role"]): st.markdown(m["content"])
        if p := st.chat_input():
            st.session_state.messages.append({"role": "user", "content": p})
            with st.chat_message("user"): st.markdown(p)
            hist = [{"role": ("user" if m["role"]=="user" else "model"), "parts": [m["content"]]} for m in st.session_state.messages[:-1]]
            try:
                r = requests.post(f"{API_URL}/chat", json={"message": p, "history": hist}, headers=get_auth_headers()).json()["reply"]
                st.markdown(r)
                st.session_state.messages.append({"role": "assistant", "content": r})
            except: st.error("Offline.")
    
    elif page == "Profile":
        st.title("👤 Profile")
        if st.session_state.user:
            st.write(f"Name: {st.session_state.user.user_metadata.get('full_name')}")
            st.write(f"Role: {st.session_state.role.upper()}")