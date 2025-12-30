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
# Use Render URL for backend (switch to http://127.0.0.1:8000 if testing backend locally)
API_URL = "https://macronata-backend.onrender.com" 

# Initialize Client
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
if "uploader_key" not in st.session_state: st.session_state.uploader_key = 0 

# --- HELPER FUNCTIONS ---
def get_auth_headers():
    if st.session_state.session_token:
        return {"Authorization": f"Bearer {st.session_state.session_token}"}
    return {}

def upload_file_secure(file_obj):
    try:
        file_ext = file_obj.name.split('.')[-1]
        file_name = f"{st.session_state.user.id}_{int(time.time())}.{file_ext}"
        mime_type = file_obj.type
        
        headers = {
            "Authorization": f"Bearer {st.session_state.session_token}",
            "apikey": key,
            "Content-Type": mime_type
        }
        
        upload_endpoint = f"{supabase_url}/storage/v1/object/chat_assets/{file_name}"
        response = requests.post(upload_endpoint, data=file_obj.getvalue(), headers=headers)
        
        if response.status_code == 200:
            return f"{supabase_url}/storage/v1/object/public/chat_assets/{file_name}", mime_type
        else:
            st.error(f"Upload Failed ({response.status_code}): {response.text}")
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
            st.subheader("Create New Account")
            new_name = st.text_input("Full Name", key="signup_name")
            new_email = st.text_input("Email", key="s_email")
            new_pass = st.text_input("Password", type="password", key="s_pass")
            # FIX: ROLE SELECTION ADDED
            new_role = st.selectbox("I am a:", ["learner", "tutor"], key="signup_role")
            
            if st.button("Sign Up", use_container_width=True):
                if not new_name:
                    st.error("Please enter your full name.")
                else:
                    try:
                        res = supabase.auth.sign_up({"email": new_email, "password": new_pass})
                        if res.user:
                            supabase.table("users").insert({
                                "id": res.user.id, 
                                "full_name": new_name,
                                "email": new_email, 
                                "role": new_role # <--- Sending Selected Role
                            }).execute()
                            st.success(f"Account created as {new_role}! Log in now.")
                    except Exception as e: 
                        st.error(f"Signup failed: {e}")

# --- MAIN APP ---
if st.session_state.user is None:
    show_login_page()
else:
    st.sidebar.title("Macronata 🇿🇦")
    st.sidebar.caption(f"{st.session_state.user.email}")
    if st.sidebar.button("Log Out"):
        st.session_state.user = None
        st.session_state.session_token = None
        st.rerun()
    
    menu = ["Messages", "Tinny (AI)", "Profile"]
    if st.session_state.role == "learner": menu.insert(1, "Find Tutor")
    page = st.sidebar.radio("Navigate", menu)

    # --- MESSAGES (FIXED CONTACT LIST) ---
    if page == "Messages":
        st.title("💬 Professional Chat")
        
        # 1. Fetch ALL Users (Not just tutors)
        try:
            # Changed endpoint from /tutors to /users to ensure visibility
            users_res = requests.get(f"{API_URL}/users", headers=get_auth_headers())
            users = users_res.json() if users_res.status_code == 200 else []
        except: users = []
        
        user_map = {}
        for u in users:
            if u['id'] != st.session_state.user.id:
                # Add role to name for clarity: "John Doe (Tutor)"
                label = f"{u.get('full_name', 'Unknown')} ({u.get('role', 'user').title()})"
                user_map[label] = u['id']
        
        if not user_map:
            st.info("No contacts found.")
        
        selected_name = st.selectbox("Select Contact", list(user_map.keys()))
        
        if selected_name:
            receiver_id = user_map[selected_name]
            
            if st.button("🔄 Refresh"): st.rerun()
            
            # Display History
            try:
                msgs_res = requests.get(f"{API_URL}/messages/{receiver_id}", headers=get_auth_headers())
                msgs = msgs_res.json() if msgs_res.status_code == 200 else []
            except: msgs = []

            with st.container(height=400):
                if not msgs:
                    st.caption("No messages yet. Say hello!")
                for m in msgs:
                    is_me = m['sender_id'] == st.session_state.user.id
                    role = "user" if is_me else "assistant"
                    with st.chat_message(role, avatar="👤" if is_me else "🎓"):
                        if m.get('content'): st.write(m['content'])
                        if m.get('media_url'):
                            if "image" in m.get('media_type', ''):
                                st.image(m['media_url'], width=300)
                            else:
                                st.link_button("Download File", m['media_url'])

            # --- INPUT AREA ---
            col_text, col_file = st.columns([5, 1])
            with col_file:
                uploaded_file = st.file_uploader("📎", label_visibility="collapsed", key=f"uploader_{st.session_state.uploader_key}")
            with col_text:
                text_msg = st.chat_input("Type a message...")
            
            if text_msg or uploaded_file:
                media_url, media_type = None, None
                
                if uploaded_file:
                    with st.spinner("Uploading..."):
                        media_url, media_type = upload_file_secure(uploaded_file)
                        if not media_url: st.stop()

                payload = {
                    "receiver_id": receiver_id,
                    "content": text_msg if text_msg else "",
                    "media_url": media_url,
                    "media_type": media_type
                }
                
                try:
                    res = requests.post(f"{API_URL}/messages", json=payload, headers=get_auth_headers())
                    if res.status_code == 200:
                        st.session_state.uploader_key += 1 
                        st.toast("Message Sent!")           
                        time.sleep(1)                       
                        st.rerun()                          
                    else:
                        st.error(f"Send Failed: {res.text}")
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
                        st.error("Tinny is sleeping.")
                except: st.error("Connection Error.")

    # --- OTHER PAGES ---
    elif page == "Find Tutor":
        st.title("📚 Find a Tutor")
        try:
            # We still use the specific /tutors endpoint for this page
            tutors = requests.get(f"{API_URL}/tutors", headers=get_auth_headers()).json()
            if not tutors: st.info("No tutors found.")
            for t in tutors:
                with st.container(border=True):
                    st.subheader(t.get('full_name', 'Tutor'))
                    st.write(f"**Email:** {t.get('email')}")
        except: st.error("Load failed.")

    elif page == "Profile":
        st.title("👤 My Profile")
        st.write(f"**Name:** {st.session_state.user.user_metadata.get('full_name', 'Not set')}")
        st.write(f"**Email:** {st.session_state.user.email}")
        st.write(f"**Role:** {st.session_state.role.upper()}")