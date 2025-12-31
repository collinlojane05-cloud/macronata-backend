import streamlit as st
import requests
from supabase import create_client, Client
import os
from dotenv import load_dotenv
import time

load_dotenv()

# --- CONFIGURATION ---
raw_url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")

if not raw_url or not key:
    st.error("❌ API Keys missing! Check your .env file.")
    st.stop()

supabase_url = raw_url.rstrip("/")
# IMPORTANT: Ensure this matches your live backend URL
API_URL = "https://macronata-backend.onrender.com" 

try:
    supabase: Client = create_client(supabase_url, key)
except Exception as e:
    st.error(f"Init Error: {e}")
    st.stop()

st.set_page_config(page_title="Macronata Academy", page_icon="🇿🇦", layout="wide")

# --- STATE INITIALIZATION (CRITICAL FIX) ---
# We initialize ALL session variables here to prevent crashes
if "user" not in st.session_state: st.session_state.user = None
if "role" not in st.session_state: st.session_state.role = None 
if "session_token" not in st.session_state: st.session_state.session_token = None
if "uploader_key" not in st.session_state: st.session_state.uploader_key = 0 
if "messages" not in st.session_state: st.session_state.messages = []  # <--- FIX FOR YOUR ERROR

# --- HELPER FUNCTIONS ---
def get_auth_headers():
    return {"Authorization": f"Bearer {st.session_state.session_token}"} if st.session_state.session_token else {}

def upload_file_secure(file_obj, is_audio=False):
    """Handles both file uploads and voice notes"""
    try:
        ext = "wav" if is_audio else file_obj.name.split('.')[-1]
        file_name = f"{st.session_state.user.id}_{int(time.time())}.{ext}"
        mime_type = "audio/wav" if is_audio else file_obj.type
        
        headers = {
            "Authorization": f"Bearer {st.session_state.session_token}",
            "apikey": key,
            "Content-Type": mime_type
        }
        
        upload_endpoint = f"{supabase_url}/storage/v1/object/chat_assets/{file_name}"
        # .getvalue() works for both UploadedFile and AudioInput
        data = file_obj.getvalue() if hasattr(file_obj, 'getvalue') else file_obj
        
        response = requests.post(upload_endpoint, data=data, headers=headers)
        
        if response.status_code == 200:
            return f"{supabase_url}/storage/v1/object/public/chat_assets/{file_name}", mime_type
        else:
            st.error(f"Upload Failed: {response.text}")
            return None, None
            
    except Exception as e:
        st.error(f"Upload Error: {e}")
        return None, None

# --- AUTH PAGES ---
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
                            supabase.table("users").insert({
                                "id": res.user.id, "full_name": new_name,
                                "email": new_email, "role": new_role
                            }).execute()
                            st.success(f"Welcome {new_name}! Please log in.")
                    except Exception as e: st.error(f"Error: {e}")
                else: st.error("Name required.")

# --- MAIN APPLICATION ---
if st.session_state.user is None:
    show_login_page()
else:
    st.sidebar.title("Macronata 🇿🇦")
    st.sidebar.write(f"**{st.session_state.user.user_metadata.get('full_name', 'User')}**")
    if st.sidebar.button("Log Out"):
        st.session_state.user = None
        st.session_state.session_token = None
        st.session_state.messages = [] # Clear chat on logout
        st.rerun()
    
    menu = ["Messages", "Tinny (AI)", "Profile"]
    if st.session_state.role == "learner": menu.insert(1, "Find Tutor")
    page = st.sidebar.radio("Navigate", menu)

    # --- FEATURE 1: MULTIMEDIA CHAT ---
    if page == "Messages":
        st.title("💬 Professional Chat")
        
        try:
            users = requests.get(f"{API_URL}/users", headers=get_auth_headers()).json()
        except: users = []
        
        # Build dictionary for dropdown
        user_map = {f"{u.get('full_name')} ({u.get('role')})": u['id'] for u in users if u['id'] != st.session_state.user.id}
        
        if not user_map:
            st.info("No contacts found.")
            receiver_name = None
        else:
            receiver_name = st.selectbox("Chat with:", list(user_map.keys()))
        
        if receiver_name:
            receiver_id = user_map[receiver_name]
            if st.button("Refresh"): st.rerun()
            
            # Load Msgs
            try:
                msgs = requests.get(f"{API_URL}/messages/{receiver_id}", headers=get_auth_headers()).json()
            except: msgs = []

            with st.container(height=450):
                for m in msgs:
                    is_me = m['sender_id'] == st.session_state.user.id
                    with st.chat_message("user" if is_me else "assistant", avatar="👤" if is_me else "🎓"):
                        if m.get('content'): st.write(m['content'])
                        
                        # MEDIA DISPLAY
                        url = m.get('media_url')
                        if url:
                            m_type = m.get('media_type', '')
                            if "audio" in m_type: st.audio(url)
                            elif "image" in m_type: st.image(url)
                            else: st.link_button("File", url)

            # INPUTS
            c1, c2, c3 = st.columns([1, 1, 4])
            with c1: 
                voice_note = st.audio_input("🎤 Record", key=f"mic_{st.session_state.uploader_key}")
            with c2:
                uploaded = st.file_uploader("📎", label_visibility="collapsed", key=f"up_{st.session_state.uploader_key}")
            with c3:
                txt = st.chat_input("Message...")
            
            if txt or uploaded or voice_note:
                media_url, media_type = None, None
                
                with st.spinner("Sending..."):
                    if voice_note:
                        media_url, media_type = upload_file_secure(voice_note, is_audio=True)
                    elif uploaded:
                        media_url, media_type = upload_file_secure(uploaded)
                    
                    if (voice_note or uploaded) and not media_url: st.stop()

                    payload = {
                        "receiver_id": receiver_id, "content": txt if txt else "",
                        "media_url": media_url, "media_type": media_type
                    }
                    requests.post(f"{API_URL}/messages", json=payload, headers=get_auth_headers())
                    
                    st.session_state.uploader_key += 1
                    time.sleep(0.5)
                    st.rerun()

    # --- FEATURE 2: YOCO PAYMENTS (DEBUG VERSION) ---
    elif page == "Find Tutor":
        st.title("💳 Book a Tutor")
        try:
            tutors = requests.get(f"{API_URL}/tutors", headers=get_auth_headers()).json()
            if not tutors:
                st.info("No tutors available right now.")
            
            for t in tutors:
                with st.container(border=True):
                    c1, c2 = st.columns([3, 1])
                    with c1:
                        st.subheader(t.get('full_name'))
                        st.write(f"**Email:** {t.get('email')}")
                    with c2:
                        st.write("**Price:** R200.00")
                        if st.button(f"Pay & Book", key=t['id']):
                            st.session_state['pay_tutor'] = t
                            st.rerun()
            
            # Payment Dialog
            if 'pay_tutor' in st.session_state:
                t = st.session_state['pay_tutor']
                st.divider()
                st.info(f"Booking session with {t.get('full_name')}")
                
                d = st.date_input("Date")
                tm = st.time_input("Time")
                
                if st.button("Confirm & Generate Link"):
                    payload = {
                        "tutor_id": t['id'], "scheduled_time": f"{d}T{tm}", "amount_in_cents": 20000
                    }
                    
                    with st.spinner("Contacting Yoco..."):
                        try:
                            res = requests.post(f"{API_URL}/create_payment", json=payload, headers=get_auth_headers())
                            
                            if res.status_code == 200:
                                data = res.json()
                                if data.get('simulation'):
                                    st.warning(data['message'])
                                    # Simulate booking
                                    requests.post(f"{API_URL}/book_session", json=payload, headers=get_auth_headers())
                                    st.success("✅ Payment Simulated & Booked!")
                                    time.sleep(2)
                                    del st.session_state['pay_tutor']
                                    st.rerun()
                                elif data.get('payment_url'):
                                    st.success("Link Generated!")
                                    st.link_button("👉 Click Here to Pay via Yoco", data['payment_url'])
                                else:
                                    st.error("No link returned. Response:")
                                    st.json(data)
                            else:
                                st.error(f"Yoco Failed ({res.status_code}):")
                                st.write(res.text) # Prints exact error from Backend
                        except Exception as e:
                            st.error(f"Network Error: {e}")

        except Exception as e: 
            st.error(f"Error loading tutors: {e}")

    # --- TINNY (AI) ---
    elif page == "Tinny (AI)":
        st.title("🤖 Chat with Tinny")
        
        # Display existing messages
        for m in st.session_state.messages:
            with st.chat_message(m["role"]): st.markdown(m["content"])
            
        if p := st.chat_input():
            st.session_state.messages.append({"role": "user", "content": p})
            with st.chat_message("user"): st.markdown(p)
            
            # Format history
            hist = [{"role": ("user" if m["role"]=="user" else "model"), "parts": [m["content"]]} for m in st.session_state.messages[:-1]]
            
            with st.chat_message("assistant"):
                try:
                    res = requests.post(f"{API_URL}/chat", json={"message": p, "history": hist}, headers=get_auth_headers())
                    if res.status_code == 200:
                        r = res.json()["reply"]
                        st.markdown(r)
                        st.session_state.messages.append({"role": "assistant", "content": r})
                    else:
                        st.error("Tinny is sleeping.")
                except: st.error("Connection Error.")

    elif page == "Profile":
        st.title("👤 Profile")
        if st.session_state.user:
            st.write(f"Name: {st.session_state.user.user_metadata.get('full_name')}")
            st.write(f"Role: {st.session_state.role.upper()}")