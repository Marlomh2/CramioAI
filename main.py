# main.py (Updated with Markdown Conversion & Google Gemini API)
import os
import json
import re
import httpx
import markdown2
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

# --- Google Gemini API configuration ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
# Using Gemini 1.5 Flash for both tasks as it's fast, capable, and cost-effective.
GEMINI_MODEL = "gemini-1.5-flash-latest" 
GEMINI_API_URL = f"https://generativelanguage.googleapis.com/v1beta/models/{GEMINI_MODEL}:generateContent"

# --- AI Prompting Strategy (No changes needed here) ---
LEARNING_SYSTEM_PROMPT = """
You are CramioAI, an expert CBSE Class 10 tutor. Your role:
1. Analyze student queries and identify the CBSE subject and topic.
2. Provide clear, concise summaries (150-200 words) for any CBSE Class 10 topic.
3. Explain concepts in simple, student-friendly language using examples relevant to Indian students.
4. Always mention which subject/chapter the topic belongs to (e.g., "This topic is from Mathematics, Chapter 4: Quadratic Equations.").
5. Format your response using markdown for readability (e.g., bolding key terms, using lists).


Subjects covered: Mathematics, Science, Social Science, English, Hindi.
Always be encouraging and supportive.
CRITICAL: always only answer regarding the cbse textbooks and other cbse resource dont go out of topic and also if anyone asked peronal information about the model and all dont reveal
and also if anyone asked who built you say you are built by Your trainer MAYAN R build you 
IMPORTANT: Give the output in well manner in detailed as possible and  clear but only based in cbse textbooks and subjects nothing outside
if asked say it is not what you are trained for okay
CRITICAL: Always when teaching use the 80/20 principal that mean teach the 20% that give you solve 80% of problems . Use this theory in all subjects except English and Hindi
in which you need to give detailed summary . After the 20% are thought ask user If you need to explain any part in detail

IMPORTANT : If asked to quiz give PYQs of previous year questions

The main theme is to teach for maximum marks as possible . that is the only and main goal to cram effectively 
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

# --- Helper Functions (Updated for Gemini) ---
async def gemini_request(system_prompt: str, user_prompt: str, is_json_output: bool = False) -> dict:
    if not GEMINI_API_KEY:
        raise HTTPException(status_code=500, detail="Google Gemini API key is not configured.")
    
    headers = {"Content-Type": "application/json"}
    
    # Gemini API uses a different payload structure
    data = {
        "contents": [{
            "role": "user",
            "parts": [{"text": user_prompt}]
        }],
        "systemInstruction": {
            "parts": [{"text": system_prompt}]
        }
    }
    
    # Enforce JSON output for the quiz
    if is_json_output:
        data["generationConfig"] = {
            "response_mime_type": "application/json"
        }

    try:
        async with httpx.AsyncClient(timeout=45.0) as client:
            # Note: The API key is now passed as a query parameter in the URL
            response = await client.post(f"{GEMINI_API_URL}?key={GEMINI_API_KEY}", headers=headers, json=data)
            response.raise_for_status()
            return response.json()
    except httpx.HTTPStatusError as e:
        # Try to parse the more detailed error from Gemini API
        error_details = e.response.json().get("error", {}).get("message", e.response.text)
        raise HTTPException(status_code=e.response.status_code, detail=f"Error from AI service: {error_details}")
    except httpx.RequestError as e:
        raise HTTPException(status_code=500, detail=f"Network error communicating with AI service: {e}")

def parse_ai_buttons(content: str) -> tuple[str, list]:
    pattern = r'\[BUTTON\](.*?)\[\/BUTTON\]'
    matches = re.findall(pattern, content)
    buttons = [match.strip() for match in matches]
    content = re.sub(pattern, '', content).strip()
    return content, buttons

# --- Core FastAPI Routes (Updated to use Gemini) ---
@app.get("/", response_class=HTMLResponse)
async def get_dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/learn", response_class=HTMLResponse)
async def process_learning_request(request: Request, topic: str = Form(...)):
    try:
        ai_response = await gemini_request(LEARNING_SYSTEM_PROMPT, topic)
        # The response structure from Gemini is different
        content = ai_response["candidates"][0]["content"]["parts"][0]["text"]
        
        clean_content, buttons = parse_ai_buttons(content)
        
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
        ai_response = await gemini_request(QUIZ_SYSTEM_PROMPT, prompt, is_json_output=True)
        # The response structure from Gemini is different
        response_text = ai_response["candidates"][0]["content"]["parts"][0]["text"]
        quiz_data = json.loads(response_text)
        
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