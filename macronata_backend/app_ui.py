import streamlit as st
import requests
from supabase import create_client, Client
import os
from dotenv import load_dotenv
import time
import mimetypes

load_dotenv()
url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")

if not url or not key:
    st.error("❌ API Keys missing!")
    st.stop()

supabase: Client = create_client(url, key)

st.set_page_config(page_title="Macronata Academy", page_icon="🇿🇦", layout="wide")
API_URL = "https://macronata-backend.onrender.com" 

# --- SESSION SETUP ---
if "user" not in st.session_state: st.session_state.user = None
if "role" not in st.session_state: st.session_state.role = None 
if "session_token" not in st.session_state: st.session_state.session_token = None

def get_auth_headers():
    return {"Authorization": f"Bearer {st.session_state.session_token}"} if st.session_state.session_token else {}

def upload_file(file_obj):
    """Uploads file directly to Supabase Storage and returns public URL"""
    try:
        file_ext = file_obj.name.split('.')[-1]
        file_name = f"{st.session_state.user.id}_{int(time.time())}.{file_ext}"
        bucket = "chat_assets"
        
        # Read file bytes
        file_bytes = file_obj.getvalue()
        
        # Upload
        supabase.storage.from_(bucket).upload(file_name, file_bytes, {"content-type": file_obj.type})
        
        # Get Public URL
        public_url = supabase.storage.from_(bucket).get_public_url(file_name)
        return public_url, file_obj.type
    except Exception as e:
        st.error(f"Upload failed: {e}")
        return None, None

def show_login_page():
    st.markdown("<h1 style='text-align: center;'>🇿🇦 Macronata Academy</h1>", unsafe_allow_html=True)
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        tab1, tab2 = st.tabs(["Login", "Sign Up"])
        with tab1:
            email = st.text_input("Email", key="l_email")
            password = st.text_input("Password", type="password", key="l_pass")
            if st.button("Log In", use_container_width=True):
                try:
                    res = supabase.auth.sign_in_with_password({"email": email, "password": password})
                    st.session_state.user = res.user
                    st.session_state.session_token = res.session.access_token
                    
                    # Fetch Role
                    role_res = supabase.table("users").select("role").eq("id", res.user.id).single().execute()
                    st.session_state.role = role_res.data['role'] if role_res.data else "learner"
                    st.rerun()
                except Exception as e: st.error(f"Login failed: {e}")
        with tab2:
            n_email = st.text_input("Email", key="s_email")
            n_pass = st.text_input("Password", type="password", key="s_pass")
            if st.button("Sign Up", use_container_width=True):
                try:
                    res = supabase.auth.sign_up({"email": n_email, "password": n_pass})
                    if res.user:
                        supabase.table("users").insert({"id": res.user.id, "email": n_email, "role": "learner"}).execute()
                        st.success("Account created!")
                except Exception as e: st.error(f"Signup failed: {e}")

if st.session_state.user is None:
    show_login_page()
else:
    # --- SIDEBAR ---
    st.sidebar.title("Macronata 🇿🇦")
    st.sidebar.write(f"Logged in as: **{st.session_state.role.upper()}**")
    if st.sidebar.button("Log Out"):
        st.session_state.user = None
        st.rerun()
    
    # --- NAVIGATION ---
    menu_options = ["Messages", "Tinny (AI)", "Profile"]
    if st.session_state.role == "learner":
        menu_options.insert(1, "Find Tutor")
    else:
        menu_options.insert(1, "My Schedule")
        
    page = st.sidebar.radio("Navigate", menu_options)

    # --- MESSAGING PAGE ---
    if page == "Messages":
        st.title("💬 Professional Chat")
        
        # 1. Select User to Chat With
        # Simplified: Getting list of all users. In production, filter by booking relationship.
        try:
            users_res = supabase.table("users").select("id, full_name, email, role").neq("id", st.session_state.user.id).execute()
            users = users_res.data
        except: users = []
        
        user_map = {u['full_name'] or u['email']: u['id'] for u in users}
        selected_name = st.selectbox("Select Contact", list(user_map.keys()))
        
        if selected_name:
            receiver_id = user_map[selected_name]
            
            # 2. Fetch History
            # Simple Polling Mechanism (Manual Refresh button is better for Streamlit)
            if st.button("🔄 Refresh Chat"):
                st.rerun()
                
            try:
                res = requests.get(f"{API_URL}/messages/{receiver_id}", headers=get_auth_headers())
                messages = res.json() if res.status_code == 200 else []
            except: messages = []
            
            # 3. Display Messages
            with st.container(height=400):
                for msg in messages:
                    is_me = msg['sender_id'] == st.session_state.user.id
                    align = "end" if is_me else "start"
                    role_name = "You" if is_me else selected_name
                    avatar = "👤" if is_me else "🎓"
                    
                    with st.chat_message(name=role_name, avatar=avatar):
                        if msg.get('content'):
                            st.write(msg['content'])
                        
                        # Handle Media
                        if msg.get('media_url'):
                            m_type = msg.get('media_type', '')
                            if "image" in m_type:
                                st.image(msg['media_url'], width=250)
                            elif "audio" in m_type:
                                st.audio(msg['media_url'])
                            elif "video" in m_type:
                                st.video(msg['media_url'])
                            else:
                                st.link_button("📎 Download File", msg['media_url'])
                            
                        st.caption(f"{msg['created_at'][11:16]}")

            st.divider()
            
            # 4. Input Area
            col_text, col_upload = st.columns([4, 1])
            
            with col_upload:
                # File Uploader (Images, Audio, Video, PDF)
                uploaded_file = st.file_uploader("📎", type=['png','jpg','mp3','wav','mp4','pdf'], label_visibility="collapsed")
            
            with col_text:
                text_input = st.chat_input("Type a message...")

            # Logic to send message
            if text_input or uploaded_file:
                media_url = None
                media_type = None
                
                if uploaded_file:
                    with st.spinner("Uploading..."):
                        media_url, media_type = upload_file(uploaded_file)
                
                if text_input or media_url:
                    payload = {
                        "receiver_id": receiver_id,
                        "content": text_input if text_input else "",
                        "media_url": media_url,
                        "media_type": media_type
                    }
                    requests.post(f"{API_URL}/messages", json=payload, headers=get_auth_headers())
                    st.rerun()

    # --- TINNY AI ---
    elif page == "Tinny (AI)":
        st.title("🤖 Chat with Tinny")
        if "messages" not in st.session_state: st.session_state.messages = []
        
        for msg in st.session_state.messages:
            with st.chat_message(msg["role"]): st.markdown(msg["content"])

        if prompt := st.chat_input("Ask Tinny..."):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"): st.markdown(prompt)
            
            hist = [{"role": ("user" if m["role"]=="user" else "model"), "parts": [m["content"]]} for m in st.session_state.messages[:-1]]
            
            with st.chat_message("assistant"):
                try:
                    res = requests.post(f"{API_URL}/chat", json={"message": prompt, "history": hist}, headers=get_auth_headers())
                    reply = res.json()["reply"]
                    st.markdown(reply)
                    st.session_state.messages.append({"role": "assistant", "content": reply})
                except: st.error("Offline.")

    # --- PROFILE / SCHEDULE ---
    elif page == "My Schedule" or page == "Profile":
        st.title("📅 Schedule")
        endpoint = "/tutor_bookings" if st.session_state.role == "tutor" else "/my_bookings"
        try:
            res = requests.get(f"{API_URL}{endpoint}", headers=get_auth_headers())
            bookings = res.json()
            for b in bookings:
                st.info(f"{b['scheduled_time'][:16].replace('T',' ')} | Status: {b['status']}")
        except: st.write("No bookings.")

    # --- FIND TUTOR ---
    elif page == "Find Tutor":
        st.title("Find a Tutor")
        try:
            tutors = requests.get(f"{API_URL}/tutors", headers=get_auth_headers()).json()
            for t in tutors:
                with st.container(border=True):
                    st.subheader(t.get('full_name', 'Tutor'))
                    if st.button("Book", key=t['id']):
                        st.session_state['selected_tutor'] = t['id']
                        st.rerun()
            
            if 'selected_tutor' in st.session_state:
                st.warning("Booking feature is minimal for this demo.")
                if st.button("Confirm Booking"):
                    requests.post(f"{API_URL}/book_session", json={"tutor_id": st.session_state['selected_tutor'], "scheduled_time": "2025-01-01T10:00:00"}, headers=get_auth_headers())
                    st.success("Booked!")
        except: st.error("Load failed.")