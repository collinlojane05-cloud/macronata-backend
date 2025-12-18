import google.generativeai as genai
import os
from dotenv import load_dotenv

# Load your API key
load_dotenv()
api_key = os.environ.get("GEMINI_API_KEY")

if not api_key:
    print("❌ ERROR: Could not find GEMINI_API_KEY in .env file.")
else:
    print(f"✅ Found API Key: {api_key[:5]}...")
    
    try:
        genai.configure(api_key=api_key)
        print("\n--- ASKING GOOGLE FOR AVAILABLE MODELS ---")
        
        # List all models
        for m in genai.list_models():
            # Only show models that can generate text (Chat)
            if 'generateContent' in m.supported_generation_methods:
                print(f"✅ AVAILABLE: {m.name}")
                
    except Exception as e:
        print(f"\n❌ CRITICAL ERROR: {e}")