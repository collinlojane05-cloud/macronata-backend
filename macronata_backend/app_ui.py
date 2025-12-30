import streamlit as st
import requests
from supabase import create_client, Client
import os
from dotenv import load_dotenv
import time
import mimetypes

load_dotenv()

# --- CONFIGURATION & FIXES ---
raw_url = os.environ.get("SUPABASE_URL")
key = os.environ.get("SUPABASE_KEY")

if not raw_url or not key:
    st.error("❌ API Keys missing! Check your .env file.")
    st.stop()

# FIX: Ensure URL is clean (removes trailing slash if present to prevent double-slashes)
# The library sometimes panics if the format isn't perfect.
supabase_url = raw_url.rstrip("/")
API_URL = "https://macronata-backend.onrender.com"  # Change to http://127.0.0.1:8000 for local backend

# Initialize Supabase Client
try:
    supabase: Client = create_client(supabase_url, key)
except Exception as e:
    st.error(f"Initialization Error: {e}")
    st.stop()

st.set_page_config(page_title="Macronata Academy", page_icon="🇿🇦", layout="wide")

# --- SESSION STATE ---
if "user" not in st.session_state: st.session_state.user = None
if "role" not in st.session_state: st.session_state.role = None 
if "session_token" not in st.session_state: st.session_state.session_token = None

# --- HELPER FUNCTIONS ---
def get_auth_headers():
    """Returns headers with the User's secure token"""
    if st.session_state.session_token:
        return {"Authorization": f"Bearer {st.session_state.session_token}"}
    return {}

def upload_file_secure(file_obj):
    """
    Uploads file using direct HTTP request to bypass Supabase Client RLS issues.
    """
    try:
        # 1. Prepare File Info
        file_ext = file_obj.name.split('.')[-1]
        file_name = f"{st.session_state.user.id}_{int(time.time())}.{file_ext}"
        mime_type = file_obj.type
        
        # 2. Prepare Headers (Must include Bearer Token AND API Key)
        headers = {
            "Authorization": f"Bearer {st.session_state.session_token}",
            "apikey": key,
            "Content-Type": mime_type
        }
        
        # 3. Construct URL (Standard Supabase Storage Endpoint)
        # We use the sanitized supabase_url to build the path reliably
        upload_endpoint = f"{supabase_url}/storage/v1/object/chat_assets/{file_name}"
        
        # 4. Perform Upload
        response = requests.post(upload_endpoint, data=file_obj.getvalue(), headers=headers)
        
        if response.status_code == 200:
            # 5. Return Public URL for viewing
            return f"{supabase_url}/storage/v1/object/public/chat_assets/{file_name}", mime_type
        else:
            st.error(f"Upload Failed ({response.status_code}): {response.text}")
            return None, None
            
    except Exception as e:
        st.error(f"Upload Error: {e}")
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
                    
                    try:
                        role_res = supabase.table("users").select("role").eq("id", res.user.id).single().execute()
                        st.session_state.role = role_res.data['role']
                    except:
                        st.session_state.role = "learner"
                    
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

# --- MAIN APP LOGIC ---
if st.session_state.user is None:
    show_login_page()
else:
    # Sidebar
    st.sidebar.title("Macronata 🇿🇦")
    st.sidebar.caption(f"{st.session_state.user.email}")
    if st.sidebar.button("Log Out"):
        st.session_state.user = None
        st.session_state.session_token = None
        st.rerun()
    
    menu = ["Messages", "Tinny (AI)", "Profile"]
    if st.session_state.role == "learner": menu.insert(1, "Find Tutor")
    page = st.sidebar.radio("Navigate", menu)

    # --- MESSAGES PAGE ---
    if page == "Messages":
        st.title("💬 Professional Chat")
        
        # Fetch Contacts
        try:
            users_res = requests.get(f"{API_URL}/tutors", headers=get_auth_headers())
            users = users_res.json() if users_res.status_code == 200 else []
        except: users = []
        
        # Filter out self
        user_map = {u.get('full_name', u.get('email', 'Unknown')): u['id'] for u in users if u['id'] != st.session_state.user.id}
        
        if not user_map:
            st.info("No contacts available.")
        
        selected_name = st.selectbox("Select Contact", list(user_map.keys()))
        
        if selected_name:
            receiver_id = user_map[selected_name]
            
            # Refresh Button
            if st.button("🔄 Refresh"): st.rerun()
            
            # Load History
            try:
                msgs_res = requests.get(f"{API_URL}/messages/{receiver_id}", headers=get_auth_headers())
                msgs = msgs_res.json() if msgs_res.status_code == 200 else []
            except: msgs = []

            # Chat Window
            with st.container(height=400):
                for m in msgs:
                    is_me = m['sender_id'] == st.session_state.user.id
                    avatar = "👤" if is_me else "🎓"
                    role = "user" if is_me else "assistant"
                    
                    with st.chat_message(role, avatar=avatar):
                        if m.get('content'): st.write(m['content'])
                        
                        # Media Handler
                        if m.get('media_url'):
                            m_type = m.get('media_type', '')
                            if "image" in m_type:
                                st.image(m['media_url'], width=250)
                            elif "audio" in m_type:
                                st.audio(m['media_url'])
                            elif "video" in m_type:
                                st.video(m['media_url'])
                            else:
                                st.link_button("📎 Download File", m['media_url'])
            
            # Input Area
            col_text, col_file = st.columns([5, 1])
            with col_file:
                uploaded_file = st.file_uploader("📎", label_visibility="collapsed")
            with col_text:
                text_msg = st.chat_input("Type a message...")
            
            # Send Logic
            if text_msg or uploaded_file:
                media_url, media_type = None, None
                
                if uploaded_file:
                    with st.spinner("Uploading file..."):
                        media_url, media_type = upload_file_secure(uploaded_file)
                        if not media_url: st.stop() # Stop if upload failed

                payload = {
                    "receiver_id": receiver_id,
                    "content": text_msg if text_msg else "",
                    "media_url": media_url,
                    "media_type": media_type
                }
                
                try:
                    res = requests.post(f"{API_URL}/messages", json=payload, headers=get_auth_headers())
                    if res.status_code == 200:
                        st.rerun()
                    else:
                        st.error("Failed to send.")
                except Exception as e:
                    st.error(f"Error: {e}")

    # --- TINNY AI ---
    elif page == "Tinny (AI)":
        st.title("🤖 Chat with Tinny")
        if "messages" not in st.session_state: st.session_state.messages = []
        
        for m in st.session_state.messages:
            with st.chat_message(m["role"]): st.markdown(m["content"])
            
        if prompt := st.chat_input("Ask Tinny..."):
            st.session_state.messages.append({"role": "user", "content": prompt})
            with st.chat_message("user"): st.markdown(prompt)
            
            # Format history for Gemini
            hist = []
            for m in st.session_state.messages[:-1]:
                role = "user" if m["role"] == "user" else "model"
                hist.append({"role": role, "parts": [m["content"]]})

            with st.chat_message("assistant"):
                try:
                    res = requests.post(f"{API_URL}/chat", json={"message": prompt, "history": hist}, headers=get_auth_headers())
                    if res.status_code == 200:
                        reply = res.json()["reply"]
                        st.markdown(reply)
                        st.session_state.messages.append({"role": "assistant", "content": reply})
                    else:
                        st.error("Tinny is sleeping (Error).")
                except: st.error("Connection Error.")

    # --- OTHER PAGES ---
    elif page == "Find Tutor":
        st.title("📚 Find a Tutor")
        try:
            tutors = requests.get(f"{API_URL}/tutors", headers=get_auth_headers()).json()
            for t in tutors:
                with st.container(border=True):
                    st.subheader(t.get('full_name', 'Tutor'))
                    st.write(f"**Email:** {t.get('email')}")
        except: st.error("Could not load tutors.")

    elif page == "Profile":
        st.title("👤 My Profile")
        st.write(f"**Email:** {st.session_state.user.email}")
        st.write(f"**Role:** {st.session_state.role.upper()}")