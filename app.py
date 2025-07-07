from flask import Flask, flash, session, redirect, render_template, url_for, request, jsonify
import random
import time
import google.generativeai as genai
import json
from datetime import datetime, timedelta
import os
from dotenv import load_dotenv
import sqlite3
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import fitz  # PyMuPDF
from io import BytesIO
from email.mime.application import MIMEApplication
import string

app = Flask(__name__)
app.secret_key = 'your_secret_key_here'

# Load environment variables
load_dotenv()

# Initialize model as None by default
model = None

# Configure Gemini API
try:
    api_key = os.getenv("GOOGLE_API_KEY")
    if not api_key:
        print("⚠️ Warning: GOOGLE_API_KEY is empty in .env file!")
    else:
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel("gemini-1.5-flash")
        print("✅ Gemini API configured successfully")
except Exception as e:
    print(f"❌ Error configuring Gemini API: {e}")
    model = None  # Explicit fallback to None

# Database initialization
def init_db():
    conn = sqlite3.connect('quiz_app.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            email TEXT UNIQUE NOT NULL,
            contact TEXT,
            address TEXT,
            password TEXT NOT NULL,
            is_verified BOOLEAN DEFAULT 0,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS otps (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL,
            otp TEXT NOT NULL,
            created_at TEXT DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (email) REFERENCES users(email)
        )
    ''')
    
    conn.commit()
    conn.close()

init_db()

def get_db_connection():
    conn = sqlite3.connect('quiz_app.db')
    conn.row_factory = sqlite3.Row
    return conn

# Helper functions
def generate_otp():
    """Generate a 6-digit OTP"""
    return ''.join(random.choices(string.digits, k=6))

def send_otp_email(receiver_email, otp):
    """Send OTP to user's email"""
    sender_email = os.getenv('GMAIL_USER')
    app_password = os.getenv('GMAIL_APP_PASSWORD')
    
    if not sender_email or not app_password:
        print("⚠️ Warning: Email credentials not configured!")
        return False
    
    try:
        msg = MIMEMultipart()
        msg["From"] = sender_email
        msg["To"] = receiver_email
        msg["Subject"] = "Your QuizMaster Verification Code"
        
        body = f"""Hello,
        
Your verification code for QuizMaster is: {otp}
        
This code will expire in 10 minutes.
        
If you didn't request this, please ignore this email.
"""
        msg.attach(MIMEText(body, "plain"))
        
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, app_password)
            server.sendmail(sender_email, receiver_email, msg.as_string())
        
        print(f"✅ OTP sent to {receiver_email}")
        return True
    
    except Exception as e:
        print(f"❌ Error sending OTP email: {str(e)}")
        return False

def is_otp_valid(email, otp):
    """Check if OTP is valid and not expired"""
    conn = get_db_connection()
    try:
        # Lowercase email to avoid mismatches
        email = email.lower().strip()
        otp = str(otp).strip()
        
        # Get most recent OTP for this email
        otp_record = conn.execute('''
            SELECT * FROM otps 
            WHERE email = ?
            ORDER BY created_at DESC 
            LIMIT 1
        ''', (email,)).fetchone()
        
        if not otp_record:
            print(f"DEBUG: No OTP found for email: {email}")
            return False
        
        db_otp = str(otp_record['otp']).strip()
        if db_otp != otp:
            print(f"DEBUG: OTP mismatch. DB: {db_otp}, Input: {otp}")
            return False
        
        # Parse datetime correctly
        created_at = otp_record['created_at']
        if isinstance(created_at, str):
            try:
                created_at = datetime.strptime(created_at, '%Y-%m-%d %H:%M:%S')
            except ValueError:
                created_at = datetime.fromisoformat(created_at)
        
        # Check expiry
        time_elapsed = datetime.utcnow() - created_at
        if time_elapsed > timedelta(minutes=10):
            print("DEBUG: OTP expired")
            return False
        
        return True
        
    except Exception as e:
        print(f"ERROR in is_otp_valid: {str(e)}")
        return False
    finally:
        conn.close()


# Routes
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email'].lower().strip()
        contact = request.form['contact']
        address = request.form['address']
        password = request.form['password']
        confirm_password = request.form['confirm_password']
        
        if password != confirm_password:
            flash('Passwords do not match!', 'error')
            return redirect(url_for('register'))
        
        conn = get_db_connection()
        try:
            # Check if email exists (even unverified)
            existing_user = conn.execute('SELECT * FROM users WHERE email = ?', (email,)).fetchone()
            
            if existing_user:
                if existing_user['is_verified']:
                    flash('Email already exists!', 'error')
                    return redirect(url_for('register'))
                else:
                    # Delete unverified user and old OTPs
                    conn.execute('DELETE FROM users WHERE email = ?', (email,))
                    conn.execute('DELETE FROM otps WHERE email = ?', (email,))
                    conn.commit()
            
            # Insert new user as unverified
            conn.execute('''
                INSERT INTO users (name, email, contact, address, password, is_verified) 
                VALUES (?, ?, ?, ?, ?, ?)
            ''', (name, email, contact, address, password, False))
            
            # Generate and store OTP (delete old ones first)
            conn.execute('DELETE FROM otps WHERE email = ?', (email,))
            otp = generate_otp()
            conn.execute('INSERT INTO otps (email, otp) VALUES (?, ?)', (email, otp))
            
            conn.commit()
            
            # Send OTP email
            if send_otp_email(email, otp):
                flash('Registration successful! Please check your email for the verification code.', 'success')
                session['pending_email'] = email
                return redirect(url_for('verify_email'))
            else:
                flash('Failed to send verification email. Please try again.', 'error')
                return redirect(url_for('register'))
                
        except Exception as e:
            flash('An error occurred during registration. Please try again.', 'error')
            print(f"Registration error: {str(e)}")
            return redirect(url_for('register'))
        finally:
            conn.close()
    
    return render_template('register.html')

@app.route('/verify-email', methods=['GET', 'POST'])
def verify_email():
    if 'pending_email' not in session:
        return redirect(url_for('register'))
    
    if request.method == 'POST':
        otp = request.form['otp']
        email = session['pending_email']
        
        if is_otp_valid(email, otp):
            # Mark user as verified and clean up OTPs
            conn = get_db_connection()
            try:
                conn.execute('UPDATE users SET is_verified = 1 WHERE email = ?', (email,))
                conn.execute('DELETE FROM otps WHERE email = ?', (email,))
                conn.commit()
                
                flash('Email verified successfully! You can now login.', 'success')
                session.pop('pending_email', None)
                return redirect(url_for('login'))
            finally:
                conn.close()
        else:
            flash('Invalid or expired OTP. Please try again.', 'error')
    
    return render_template('verify_email.html')

@app.route('/resend-otp')
def resend_otp():
    if 'pending_email' not in session:
        return redirect(url_for('register'))
    
    email = session['pending_email']
    otp = generate_otp()
    
    conn = get_db_connection()
    try:
        # Delete old OTPs first
        conn.execute('DELETE FROM otps WHERE email = ?', (email,))
        conn.execute('INSERT INTO otps (email, otp) VALUES (?, ?)', (email, otp))
        conn.commit()
        
        if send_otp_email(email, otp):
            flash('New verification code sent! Please check your email.', 'success')
        else:
            flash('Failed to resend verification code. Please try again.', 'error')
    finally:
        conn.close()
    
    return redirect(url_for('verify_email'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        conn = get_db_connection()
        user = conn.execute('SELECT * FROM users WHERE email = ? AND password = ?', 
                           (email, password)).fetchone()
        conn.close()
        
        if user:
            session['user_id'] = user['id']
            session['user_name'] = user['name']
            flash('Login successful!', 'success')
            return redirect(url_for('index'))  # Changed from 'home' to 'index'
        else:
            flash('Invalid email or password!', 'error')
    
    return render_template('login.html')

@app.route('/index')
def index():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return render_template('index.html')


@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('home'))


# Store quiz data
quiz_sessions = {}



@app.route('/')
def home():
    return render_template('home.html')

@app.route('/start/<quiz_type>')
def start_quiz(quiz_type):
    return render_template('difficulty.html', quiz_type=quiz_type)

@app.route('/generate_quiz/<quiz_type>/<difficulty>')
def generate_quiz(quiz_type, difficulty):
    # Generate questions based on quiz type and difficulty using Gemini
    prompt = f"""
    You are a quiz generator. Generate exactly 15 multiple choice questions in valid JSON format for the following inputs:

    Quiz Type: {quiz_type}  
    Difficulty: {difficulty}  

    Each question must contain:
    - "id": Question number (1 to 15)
    - "text": A clearly stated question
    - "options": A list of 4 plausible answer choices (A, B, C, D)
    - "answer": The correct option string
    - "explanation": A brief justification of the correct answer

    Return ONLY valid JSON:
    {{
    "questions": [
        {{
        "id": "1",
        "text": "Your question here?",
        "options": ["A", "B", "C", "D"],
        "answer": "Correct Option",
        "explanation": "Why this is the correct answer."
        }},
        ...
    ]
    }}

    ### Difficulty Definitions (enforced for **all 15 questions**):
    - Easy: Each question must require **only 1 logical step** (e.g., direct calculation, definition, simple pattern).
    - Medium: Each question must require **exactly 3 logical reasoning steps** to solve. Avoid 1-step or 2-step questions.
    - Hard: Each question must require **4 or more logical steps**, involving complex reasoning, abstraction, or multi-layered analysis. No simplification.

    ### Quiz Type Definitions:
    - Logical Reasoning: Focus on Time-Speed-Distance, Blood Relations, Coding-Decoding, Directions, Number Series, Age, and Ratios.
    - Technical: Topics include Python/Java programming, Data Structures, Databases, OOP, OS, Networking.
    - English: Grammar, Vocabulary, Sentence Correction, Idioms, Comprehension.
    - General Knowledge: Static facts, History, Geography, Current Affairs, Science, Awards.

    ### Output Rules:
    - All 15 questions must match the selected difficulty level in reasoning complexity.
    - Return only clean JSON output, no Markdown or comments outside the JSON block. """

    
    try:
        if not model:  # If Gemini failed to initialize
            raise Exception("Gemini model not available")
            
        response = model.generate_content(prompt)
        questions_data = response.text
        
        # Clean the response to get proper JSON
        questions_data = questions_data.strip()
        if questions_data.startswith("```json"):
            questions_data = questions_data[7:-3].strip()
        elif questions_data.startswith("```"):
            questions_data = questions_data[3:-3].strip()
        
        questions = json.loads(questions_data)["questions"]
        
        # Ensure we have exactly 15 questions
        if len(questions) > 15:
            questions = questions[:15]
        elif len(questions) < 15:
            questions.extend(generate_fallback_questions(15 - len(questions)))
            
    except Exception as e:
        print(f"Error generating questions: {str(e)}")
        print(f"Response was: {questions_data if 'questions_data' in locals() else 'N/A'}")
        # Fallback to local questions if API fails
        questions = generate_fallback_questions(15)
    
    # Create a session ID
    session_id = f"{int(time.time())}{random.randint(1000, 9999)}"
    quiz_sessions[session_id] = {
        'questions': questions,
        'answers': {},
        'start_time': time.time(),
        'quiz_type': quiz_type,
        'difficulty': difficulty,
        'completed': False
    }
    
    return render_template('instructions.html', 
                         quiz_type=quiz_type, 
                         session_id=session_id,
                         difficulty=difficulty)

def generate_fallback_questions(num_questions):
    # Fallback question generation if API fails
    questions = []
    for i in range(num_questions):
        questions.append({
            "id": str(i+1),
            "text": f"Sample question {i+1}?",
            "options": ["Option A", "Option B", "Option C", "Option D"],
            "answer": random.choice(["Option A", "Option B", "Option C", "Option D"]),
            "explanation": "This is a sample question explanation."
        })
    return questions

@app.route('/quiz/<session_id>')
def take_quiz(session_id):
    quiz_data = quiz_sessions.get(session_id)
    if not quiz_data:
        return "Quiz session not found", 404
    
    if quiz_data.get('completed', False):
        return render_template('quiz_completed.html')
    
    return render_template('quiz.html', 
                         questions=quiz_data['questions'],
                         session_id=session_id)

@app.route('/submit_answer', methods=['POST'])
def submit_answer():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided'}), 400
    
    try:
        session_id = data['session_id']
        question_id = str(data['question_id'])
        answer = data['answer']
    except KeyError as e:
        return jsonify({'error': f'Missing key: {str(e)}'}), 400
    
    if session_id not in quiz_sessions:
        return jsonify({'error': 'Invalid session ID'}), 404
    
    # Initialize answers if not exists
    if 'answers' not in quiz_sessions[session_id]:
        quiz_sessions[session_id]['answers'] = {}
    
    quiz_sessions[session_id]['answers'][question_id] = answer
    return jsonify({'status': 'success'})

@app.route('/get_question/<session_id>/<int:question_index>')
def get_question(session_id, question_index):
    quiz_data = quiz_sessions.get(session_id)
    if not quiz_data:
        return jsonify({'error': 'Session not found'}), 404
    
    if question_index >= len(quiz_data['questions']):
        return jsonify({'error': 'Question index out of range'}), 404
    
    question = quiz_data['questions'][question_index]
    user_answer = quiz_data['answers'].get(str(question['id']))
    
    return jsonify({
        'question': question,
        'user_answer': user_answer,
        'total_questions': len(quiz_data['questions'])
    })

@app.route('/submit_quiz/<session_id>', methods=['POST'])
def submit_quiz(session_id):
    quiz_data = quiz_sessions.get(session_id)
    if not quiz_data:
        return jsonify({'error': 'Session not found'}), 404
    
    # Mark as completed and calculate results
    quiz_data['completed'] = True
    quiz_data['end_time'] = time.time()
    
    # Return the redirect URL
    return jsonify({
        'status': 'success',
        'redirect_url': url_for('show_results', session_id=session_id)
    })

import fitz  # PyMuPDF
from io import BytesIO
from email.mime.application import MIMEApplication





def generate_and_email_results(receiver_email, quiz_data, score, results, time_taken, date_completed):
    sender_email = os.getenv('GMAIL_USER')
    app_password = os.getenv('GMAIL_APP_PASSWORD')
    
    try:
        # Create PDF document
        doc = fitz.open()
        
        # --- Page 1: Cover Page ---
        page1 = doc.new_page()
        # Insert logo on page1
        logo_rect = fitz.Rect(450, 30, 520, 90)  # X, Y position and size
        page1.insert_image(logo_rect, filename="logo.jpeg")

        # Title
        page1.insert_text(
            fitz.Point(50, 100),
            "Quiz Results Report",
            fontsize=24,
            fontname="helv",
            color=(0, 0, 0))
        
        # Quiz Summary Box
        summary_box = fitz.Rect(50, 150, 400, 250)
        page1.draw_rect(summary_box, color=(0.8, 0.8, 0.8), fill=(0.95, 0.95, 0.95))
        
        summary_text = [
            f"Participant: {receiver_email}",
            f"Quiz Type: {quiz_data['quiz_type']}",
            f"Difficulty: {quiz_data['difficulty']}",
            f"Date Completed: {date_completed}",
            f"Time Taken: {time_taken}",
            "",
            f"Final Score: {score}/{len(results)} ({int(score/len(results)*100)}%)"
        ]
        
        for i, line in enumerate(summary_text):
            page1.insert_text(
                fitz.Point(60, 170 + i*20),
                line,
                fontsize=12,
                fontname="helv",
                color=(0, 0, 0))
        
        # Decorative element
        #page1.draw_circle(fitz.Point(500, 100), 30, color=(0.2, 0.5, 0.8))
        
        # --- Page 2: Detailed Results ---
        page2 = doc.new_page()
        # Insert logo on page2
        logo_rect = fitz.Rect(450, 30, 520, 90)
        page2.insert_image(logo_rect, filename="logo.jpeg")

        # Page Title
        page2.insert_text(
            fitz.Point(50, 50),
            "Detailed Question Analysis",
            fontsize=18,
            fontname="helv",
            color=(0, 0, 0))
        
        # Questions List
        y_position = 80
        for i, result in enumerate(results, 1):
            # Question Header
            page2.insert_text(
                fitz.Point(50, y_position),
                f"Question {i}: {result['question']}",
                fontsize=12,
                fontname="helv",
                color=(0, 0, 0))
            y_position += 20
            
            # Answer Comparison
            answer_status = "✓" if result['is_correct'] else "✗"
            answer_color = (0, 0.5, 0) if result['is_correct'] else (0.8, 0, 0)
            
            page2.insert_text(
                fitz.Point(55, y_position),
                f"Your answer: {answer_status} {result['user_answer']}",
                fontsize=11,
                fontname="helv",
                color=answer_color)
            y_position += 18
            
            page2.insert_text(
                fitz.Point(55, y_position),
                f"Correct answer: {result['correct_answer']}",
                fontsize=11,
                fontname="helv",
                color=(0, 0, 0))
            y_position += 18
            
            # Explanation
            page2.insert_text(
                fitz.Point(55, y_position),
                f"Explanation: {result['explanation']}",
                fontsize=11,
                fontname="tiro",  # Times Italic
                color=(0.3, 0.3, 0.3))
            y_position += 30
            
            # Separator line
            if i < len(results):  # Don't add after last question
                page2.draw_line(
                    fitz.Point(50, y_position),
                    fitz.Point(550, y_position),
                    color=(0.9, 0.9, 0.9),
                    width=0.5)
                y_position += 20
            
            # Force new page if running out of space
            if y_position > 700 and i < len(results):
                page2 = doc.new_page()
                y_position = 50
        


        
        # Save PDF to memory buffer
        pdf_buffer = BytesIO()
        doc.save(pdf_buffer)
        doc.close()
        pdf_buffer.seek(0)
        
        # --- Email Setup ---
        msg = MIMEMultipart()
        msg["From"] = sender_email
        msg["To"] = receiver_email
        msg["Subject"] = f"Your {quiz_data['quiz_type']} Quiz Results (2-Page PDF)"
        
        # Email body
        body = f"""Dear Participant,
        
Attached is your 2-page quiz results report containing:
1. Score summary and key metrics
2. Detailed question-by-question analysis

Quiz Type: {quiz_data['quiz_type']}
Score: {score}/{len(results)}
Time Taken: {time_taken}

Thank you for participating!
"""
        msg.attach(MIMEText(body, "plain"))
        
        # Attach PDF
        msg.attach(MIMEApplication(
            pdf_buffer.read(),
            _subtype="pdf",
            filename=f"QuizReport_{date_completed[:10]}.pdf"
        ))
        
        # Send email
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, app_password)
            server.sendmail(sender_email, receiver_email, msg.as_string())
        
        print(f"✅ 2-page PDF sent to {receiver_email}")
        return True
    
    except Exception as e:
        print(f"❌ PDF generation failed: {str(e)}")
        return False
    

@app.route('/results/<session_id>')
def show_results(session_id):
    quiz_data = quiz_sessions.get(session_id)
    if not quiz_data:
        return "Quiz session not found", 404
    
    if not quiz_data.get('completed', False):
        return "Quiz not completed yet", 400
    
    # Calculate score and prepare results
    score = 0
    results = []
    for question in quiz_data['questions']:
        user_answer = quiz_data['answers'].get(str(question['id']))  # Convert ID to string

        is_correct = user_answer == question['answer']
        if is_correct:
            score += 1
        
        results.append({
            'question': question['text'],
            'user_answer': user_answer,
            'correct_answer': question['answer'],
            'explanation': question.get('explanation', 'No explanation provided.'),
            'is_correct': is_correct,
            'options': question['options']
        })
    
    # Calculate time taken
    time_taken_sec = quiz_data['end_time'] - quiz_data['start_time']
    minutes = int(time_taken_sec // 60)
    seconds = int(time_taken_sec % 60)
    time_taken = f"{minutes}m {seconds}s"
    date_completed = datetime.fromtimestamp(quiz_data['end_time']).strftime('%Y-%m-%d %H:%M:%S')
    
    # Get user email and send PDF
    conn = get_db_connection()
    user = conn.execute('SELECT email FROM users WHERE id = ?', (session['user_id'],)).fetchone()
    conn.close()
    
    email_sent = False
    if user:
        email_sent = generate_and_email_results(
            receiver_email=user['email'],
            quiz_data=quiz_data,
            score=score,
            results=results,
            time_taken=time_taken,
            date_completed=date_completed
        )
    
    return render_template('results.html',
                         score=score,
                         total=len(quiz_data['questions']),
                         results=results,
                         quiz_type=quiz_data['quiz_type'],
                         difficulty=quiz_data['difficulty'],
                         time_taken=time_taken,
                         date_completed=date_completed,
                         email_sent=email_sent)


if __name__ == '__main__':
    app.run(debug=True)
