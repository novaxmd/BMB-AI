import os
import uuid
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.middleware.cors import CORSMiddleware
from openai import OpenAI

# Optional language detection - used to choose system prompt language
try:
    from langdetect import detect, DetectorFactory
    DetectorFactory.seed = 0
except Exception:
    # Fallback: no language detection available
    def detect(text):
        return ""

# Import Supabase helpers (existing file)
from supabase_config import (
    SUPABASE,
    download_model_from_supabase,
    save_chat_to_supabase,
    get_memory,
)

# Import local model helpers if present (train_model, predict_input)
try:
    from model import train_model, predict_input
except Exception:
    # provide stub functions to avoid import errors if module not present
    def train_model(a, b=None):
        return None

    def predict_input(a):
        return "Model not available."

# Setup OpenAI/OpenRouter client
client = OpenAI(
    base_url="https://openrouter.ai/api/v1",
    api_key=os.getenv("OPENAI_API_KEY")
)

app = FastAPI()

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

MODEL_FILE = "models/model.pkl"
DATA_FILE = "data/training_data.jsonl"

# Allow browser access
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Helper: choose system message based on language code
def choose_system_msg(lang_code: str) -> str:
    """Return a system message in the detected language code (prefix match)."""
    if not lang_code:
        return "You are FankyGPT, an intelligent assistant. Reply in the user's language."

    lc = lang_code.lower()
    if lc.startswith("sw"):  # Swahili
        return "You are FankyGPT, an intelligent assistant named FankyGPT. Reply in Swahili."
    if lc.startswith("id") or lc.startswith("in"):  # Indonesian
        # Keep a friendly English fallback for consistency; model will reply in user's language when possible
        return "You are FankyGPT, an intelligent assistant. Reply in the user's language."
    if lc.startswith("en"):
        return "You are FankyGPT, an intelligent assistant. Reply in English."
    # fallback
    return "You are FankyGPT, an intelligent assistant. Reply in the user's language."

# Admin verification using Supabase token (returns user info or raises HTTPException)
def verify_supabase_admin(request: Request):
    token = request.headers.get("Authorization")
    if not token:
        raise HTTPException(status_code=401, detail="Missing token")

    user = SUPABASE.auth.get_user(token.replace("Bearer ", ""))
    if not user or not user.user or not user.user.email:
        raise HTTPException(status_code=401, detail="Invalid token")

    user_email = user.user.email
    result = SUPABASE.table("profiles").select("role").eq("email", user_email).single().execute()
    
    if not result.data or result.data.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Not an admin")

    return {
        "email": user_email,
        "role": result.data.get("role")
    }

# Endpoint /admin used by client to check admin status
@app.get("/admin")
async def get_admin_info(request: Request):
    return verify_supabase_admin(request)

# Startup: download model from Supabase if not present
@app.on_event("startup")
def startup_event():
    if not os.path.exists(MODEL_FILE):
        try:
            download_model_from_supabase(MODEL_FILE)
        except Exception as e:
            print(f"[Startup Error] Failed to download model: {e}")

# Middleware: assign user_id cookie if missing
@app.middleware("http")
async def assign_user_id(request: Request, call_next):
    user_id = request.cookies.get("user_id")
    if not user_id:
        user_id = str(uuid.uuid4())
        response = await call_next(request)
        response.set_cookie("user_id", user_id)
        return response
    return await call_next(request)

# Index page: determine greeting from Accept-Language and pass messages
@app.get("/", response_class=HTMLResponse)
def index(request: Request):
    user_id = request.cookies.get("user_id")
    chat_history = get_memory(user_id) if user_id else []

    # Determine language preference from Accept-Language header (simple parsing)
    accept = request.headers.get("accept-language", "")
    lang = None
    if accept:
        lang = accept.split(",")[0].strip()[:2]  # e.g. 'en', 'id', 'sw'

    if lang == "sw":
        greeting = "Hello! I'm FankyGPT. Ask me anything. (Swahili supported)"
    elif lang == "id":
        greeting = "Hello! I'm FankyGPT. Ask me anything. (Indonesian supported)"
    elif lang == "en":
        greeting = "Hello! I'm FankyGPT. Ask me anything."
    else:
        greeting = "Hello! I'm FankyGPT. Ask me anything."

    return templates.TemplateResponse("index.html", {
        "request": request,
        "messages": chat_history,
        "greeting": greeting
    })

@app.get("/lokal", response_class=HTMLResponse)
def lokal_page(request: Request):
    # Render the local page; templates/lokal.html should be updated to English as well
    return templates.TemplateResponse("lokal.html", {"request": request})

# Chat endpoint that returns an HTML page (non-JSON)
@app.post("/chat-gpt", response_class=HTMLResponse)
async def chat_gpt(request: Request):
    form = await request.form()
    user_input = form.get("message")
    try:
        try:
            lang = detect(user_input) if user_input else ""
        except Exception:
            lang = ""
        system_msg = choose_system_msg(lang)

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_input}
            ]
        )
        reply = response.choices[0].message.content
        # Save chat: note save_chat_to_supabase expects user_id in some places; provide None if not available
        try:
            save_chat_to_supabase(user_input, reply)
        except TypeError:
            # older function signature might require user_id; ignore here
            pass
        train_model(user_input, reply)
        return templates.TemplateResponse("index.html", {
            "request": request,
            "chat_input": user_input,
            "chat_response": reply
        })
    except Exception as e:
        return HTMLResponse(f"<p style='color:red;'>Failed to contact ChatGPT/OpenAI: {e}</p>")

# Chat endpoint that returns JSON (used by JS in the frontend)
@app.post("/chat-gpt-json")
async def chat_gpt_json(request: Request):
    form = await request.form()
    user_input = form.get("message")
    user_id = request.cookies.get("user_id")

    try:
        try:
            lang = detect(user_input) if user_input else ""
        except Exception:
            lang = ""
        system_msg = choose_system_msg(lang)

        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_input}
            ]
        )
        reply = response.choices[0].message.content.strip()

        if user_id:
            # save with user_id if function accepts it
            try:
                save_chat_to_supabase(user_input, reply, user_id)
            except TypeError:
                # fallback if signature differs
                try:
                    save_chat_to_supabase(user_input, reply)
                except Exception:
                    pass

        train_model(user_input, reply)

        return {"reply": reply}
    except Exception as e:
        return {"reply": f"❌ Failed: {e}"}

# Math expression evaluator and local model predict/training endpoints
from sympy import sympify, SympifyError

def evaluate_expression(text):
    try:
        result = sympify(text).evalf()
        return str(int(result)) if result == int(result) else str(result)
    except (SympifyError, Exception):
        return None

@app.post("/lokal/predict")
async def predict_local(request: Request, input_text: str = Form(...)):
    math_result = evaluate_expression(input_text)
    if math_result:
        return templates.TemplateResponse("lokal.html", {
            "request": request,
            "response": f"Math Result: {math_result}",
            "last_input": input_text
        })

    try:
        result = predict_input(input_text)
        return templates.TemplateResponse("lokal.html", {
            "request": request,
            "response": result or "❌ Model did not return a prediction.",
            "last_input": input_text
        })
    except Exception as e:
        return templates.TemplateResponse("lokal.html", {
            "request": request,
            "response": f"❌ Error during prediction: {str(e)}",
            "last_input": input_text
        })

@app.post("/lokal/train")
async def train_local(request: Request, input_text: str = Form(...), output_text: str = Form(...)):
    train_model(input_text, output_text)
    return RedirectResponse("/lokal", status_code=302)

# (Additional lokal endpoints like /lokal/show, /lokal/hapus-model should be updated similarly in the codebase)
