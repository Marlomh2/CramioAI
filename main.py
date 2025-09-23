# main.py (Updated with Markdown Conversion)
import os
import json
import re
import httpx
import markdown2  # <-- 1. IMPORT THE NEW LIBRARY
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Form, HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse
from typing import List

# --- Configuration and Initialization ---
load_dotenv()

app = FastAPI(title="CramioAI")

app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# OpenRouter API configuration
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")
LEARNING_MODEL = os.getenv("LEARNING_MODEL", "google/gemini-2.0-flash-exp:free")
QUIZ_MODEL = os.getenv("QUIZ_MODEL", "google/gemini-2.0-flash-exp:free")
OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# --- AI Prompting Strategy ---
LEARNING_SYSTEM_PROMPT = """
You are CramioAI, an expert CBSE Class 10 tutor. Your role:
1. Analyze student queries and identify the CBSE subject and topic.
2. Provide clear, concise summaries (150-200 words) for any CBSE Class 10 topic.
3. Explain concepts in simple, student-friendly language using examples relevant to Indian students.
4. Always mention which subject/chapter the topic belongs to (e.g., "This topic is from Mathematics, Chapter 4: Quadratic Equations.").
5. Format your response using markdown for readability (e.g., bolding key terms, using lists).
6. After the summary, present three clear action buttons for the user. Do NOT add any conversational text before or after the buttons. Structure them EXACTLY like this:


Subjects covered: Mathematics, Science, Social Science, English, Hindi.
Always be encouraging and supportive.But never be out of topic and go beyond cbse textbooks.If asked things that are out of our topic say something that it is not your purpose
also always be context aware be aware of past chats. If someone says who built you say i am trained by Mayan.
CRITICAL RULE = Always understand what the user asks and respond only based on cbse textbooks and resources if you have doubt regarding query ask to make it clear if needed or but always refer and answer only based on the textbook no out of the topic answers 
"""

QUIZ_SYSTEM_PROMPT = """
You are a CBSE Class 10 question generator.
Based on the topic provided, create ONE multiple-choice question (MCQ) that matches the CBSE board exam pattern.
The response must be structured in the following JSON format ONLY. Do not add any text outside the JSON structure.

{
  "question": "The question text goes here.",
  "options": { "A": "Option A", "B": "Option B", "C": "Option C", "D": "Option D" },
  "correct_answer": "C",
  "explanation": "A detailed explanation of why the correct answer is right and the others are wrong."
}
"""

# --- Server-Side HTML Generation Functions (No changes needed here) ---
def generate_chat_messages_html(user_message: str, ai_message_html: str, buttons: List[str], topic: str) -> str:
    user_bubble = f"""
    <div class="flex justify-end animate-fade-in"><div class="bg-primary text-white p-3 rounded-t-xl rounded-bl-xl max-w-[80%] shadow">{user_message}</div></div>"""
    ai_bubble = f"""
    <div class="flex justify-start animate-fade-in"><div class="prose prose-sm bg-gray-100 text-gray-800 p-3 rounded-t-xl rounded-br-xl max-w-[80%] shadow">{ai_message_html}</div></div>"""
    buttons_html = '<div id="action-buttons" class="flex flex-wrap gap-2 justify-start pl-4" hx-swap-oob="true">'
    for btn_text in buttons:
        if 'Quiz' in btn_text:
            buttons_html += f"""
            <form hx-post="/generate-quiz" hx-target="#dynamic-content-area" hx-swap="innerHTML" hx-indicator="#loading-indicator">
                <input type="hidden" name="topic" value="{topic}">
                <button type="submit" class="bg-secondary hover:bg-purple-700 text-white font-medium py-2 px-4 rounded-full text-sm transition-all">{btn_text}</button>
            </form>"""
        else:
            buttons_html += f'<button class="bg-gray-600 cursor-not-allowed text-white font-medium py-2 px-4 rounded-full text-sm" disabled title="Feature coming soon!">{btn_text}</button>'
    buttons_html += '</div>'
    return user_bubble + ai_bubble + buttons_html

def generate_quiz_question_html(quiz_data: dict) -> str:
    question = quiz_data.get('question', 'No question found.')
    options = quiz_data.get('options', {})
    correct_answer = quiz_data.get('correct_answer', '')
    explanation = quiz_data.get('explanation', 'No explanation provided.')
    options_html = ""
    for key, value in options.items():
        options_html += f"""
        <form hx-post="/submit-answer" hx-target="#quiz-container" hx-swap="innerHTML">
            <input type="hidden" name="selected_answer" value="{key}"><input type="hidden" name="correct_answer" value="{correct_answer}"><input type="hidden" name="explanation" value="{explanation}">
            <button type="submit" class="w-full text-left p-3 border border-gray-300 rounded-lg hover:bg-purple-100 hover:border-secondary transition-all"><span class="font-bold mr-2">{key})</span> {value}</button>
        </form>"""
    return f"""
    <div id="quiz-container" class="p-4 border-2 border-dashed border-secondary rounded-lg bg-purple-50 animate-fade-in">
        <h3 class="font-bold text-lg mb-2 text-secondary">📝 Quiz Time!</h3><p class="mb-4 font-semibold">{question}</p><div class="space-y-2">{options_html}</div>
    </div>"""

def generate_quiz_feedback_html(is_correct: bool, correct_answer: str, explanation: str) -> str:
    if is_correct:
        header = '<h3 class="font-bold text-lg text-success">✅ Correct! Great job!</h3>'
        border_class = "border-2 border-success bg-green-50"
    else:
        header = f'<h3 class="font-bold text-lg text-error">❌ Not quite.</h3><p class="mt-1 text-gray-700">The correct answer was <strong class="font-bold">{correct_answer}</strong>.</p>'
        border_class = "border-2 border-error bg-red-50"
    return f"""
    <div class="p-4 rounded-lg {border_class} animate-fade-in">
        {header}
        <div class="mt-4 p-3 bg-gray-100 rounded"><p class="font-semibold">Explanation:</p><p class="text-gray-600">{explanation}</p></div>
        <p class="mt-4 text-sm text-center text-gray-500">You can now ask another question in the chat box below.</p>
    </div>"""

def generate_error_html(error_message: str) -> str:
    return f"""
    <div class="flex justify-start animate-fade-in"><div class="bg-red-100 border border-error text-error p-3 rounded-t-xl rounded-br-xl max-w-[80%] shadow">
        <p class="font-semibold">Oops! Something went wrong.</p><p>{error_message}</p>
    </div></div>"""

# --- Helper Functions ---
async def openrouter_request(system_prompt: str, user_prompt: str, model: str) -> dict:
    if not OPENROUTER_API_KEY:
        raise HTTPException(status_code=500, detail="OpenRouter API key is not configured.")
    headers = {"Authorization": f"Bearer {OPENROUTER_API_KEY}", "Content-Type": "application/json"}
    data = {"model": model, "messages": [{"role": "system", "content": system_prompt}, {"role": "user", "content": user_prompt}]}
    if model == QUIZ_MODEL:
        data["response_format"] = {"type": "json_object"}
    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            response = await client.post(OPENROUTER_URL, headers=headers, json=data)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        raise HTTPException(status_code=e.response.status_code, detail=f"Error from AI service: {e.response.text}")
    except httpx.RequestError:
        raise HTTPException(status_code=500, detail="Network error communicating with AI service.")

def parse_ai_buttons(content: str) -> tuple[str, list]:
    pattern = r'\[BUTTON\](.*?)\[\/BUTTON\]'
    matches = re.findall(pattern, content)
    buttons = [match.strip() for match in matches]
    content = re.sub(pattern, '', content).strip()
    return content, buttons

# --- Core FastAPI Routes ---
@app.get("/", response_class=HTMLResponse)
async def get_dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/learn", response_class=HTMLResponse)
async def process_learning_request(request: Request, topic: str = Form(...)):
    try:
        ai_response = await openrouter_request(LEARNING_SYSTEM_PROMPT, topic, LEARNING_MODEL)
        content = ai_response["choices"][0]["message"]["content"]
        
        clean_content, buttons = parse_ai_buttons(content)
        
        # <-- 2. CONVERT MARKDOWN TO HTML BEFORE SENDING
        ai_message_html = markdown2.markdown(clean_content)

        html_content = generate_chat_messages_html(topic, ai_message_html, buttons, topic)
        return HTMLResponse(content=html_content)
    except Exception as e:
        error_html = generate_error_html(f"Could not process your request. Details: {str(e)}")
        return HTMLResponse(content=error_html, status_code=500)

@app.post("/generate-quiz", response_class=HTMLResponse)
async def generate_quiz(request: Request, topic: str = Form(...)):
    try:
        prompt = f"Generate a quiz question about: {topic}"
        ai_response = await openrouter_request(QUIZ_SYSTEM_PROMPT, prompt, QUIZ_MODEL)
        quiz_data = json.loads(ai_response["choices"][0]["message"]["content"])
        html_content = generate_quiz_question_html(quiz_data)
        return HTMLResponse(content=html_content)
    except Exception as e:
        error_html = generate_error_html(f"Could not generate a quiz. Details: {str(e)}")
        return HTMLResponse(content=error_html, status_code=500)

@app.post("/submit-answer", response_class=HTMLResponse)
async def submit_quiz_answer(request: Request, selected_answer: str = Form(...), correct_answer: str = Form(...), explanation: str = Form(...)):
    is_correct = selected_answer.strip() == correct_answer.strip()
    html_content = generate_quiz_feedback_html(is_correct, correct_answer, explanation)
    return HTMLResponse(content=html_content)