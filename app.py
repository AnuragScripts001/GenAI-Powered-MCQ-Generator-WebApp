from flask import Flask, request, render_template, send_file
import os
import pdfplumber
import docx
from werkzeug.utils import secure_filename
import google.generativeai as genai
from fpdf import FPDF
import re

# Set up Google Generative AI API
os.environ["GOOGLE_API_KEY"] = "AIzaSyC4i4zvhAmJrrc5wkPWi4RbE5TgW8C0Nyk"
genai.configure(api_key=os.environ["GOOGLE_API_KEY"])

# Load Gemini model
model = genai.GenerativeModel('gemini-1.5-flash')

# Initialize Flask app
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'uploads/'
app.config['RESULT_FOLDER'] = 'results/'
app.config['ALLOWED_EXTENSIONS'] = {'pdf', 'docx', 'txt', 'csv'}


# Utility: Allowed file check
def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in app.config['ALLOWED_EXTENSIONS']


# Utility: Extract text from uploaded document
def extract_text(file_path):
    ext = file_path.rsplit('.', 1)[1].lower()
    if ext == 'pdf':
        with pdfplumber.open(file_path) as pdf:
            return '\n'.join([page.extract_text() or '' for page in pdf.pages])
    elif ext == 'docx':
        doc = docx.Document(file_path)
        return '\n'.join([para.text for para in doc.paragraphs])
    elif ext == 'txt':
        with open(file_path, 'r', encoding='utf-8') as file:
            return file.read()
    return "Unsupported file type."


# Gemini Prompt for MCQ generation
def quetion_mcqs_generator(input_text, num_questions):
    prompt = f"""
You are an expert educator and question setter.

Based on the following content, generate {num_questions} multiple-choice questions (MCQs).

### Instructions:
- Each question must be fact-based and relevant to the text.
- Provide **4 options** (A, B, C, D) for each question.
- Clearly indicate the **correct answer**.
- Use a **numbered list** for the questions.
- Avoid repeating questions or overlapping options.
- Maintain a clear and concise language.

### Content:
\"\"\"
{input_text}
\"\"\"

### Output Format:
1. Question text  
   A. Option A  
   B. Option B  
   C. Option C  
   D. Option D  
   **Answer:** Option Letter (e.g., A, B)

Only include the questions and answers in the output.
"""
    response = model.generate_content(prompt)
    return response.text


# Parse Gemini response into structured MCQ list
def parse_mcqs(mcq_text):
    mcqs = []
    pattern = re.compile(
        r"\d+\.\s*(.*?)\n\s*A\.\s*(.*?)\n\s*B\.\s*(.*?)\n\s*C\.\s*(.*?)\n\s*D\.\s*(.*?)\n\s*\*\*Answer:\*\*\s*([A-D])",
        re.DOTALL
    )
    for match in pattern.finditer(mcq_text):
        question, a, b, c, d, answer = match.groups()
        mcqs.append({
            "question": question.strip(),
            "options": [f"A. {a.strip()}", f"B. {b.strip()}", f"C. {c.strip()}", f"D. {d.strip()}"],
            "answer": answer.strip()
        })
    return mcqs


@app.route('/')
def index():
    return render_template('index.html')


@app.route("/generate", methods=["POST"])
def generate():
    try:
        file = request.files.get("file")
        if not file or not allowed_file(file.filename):
            return render_template("result.html", mcqs=[], txt_filename=None, pdf_filename=None, 
                                error="Invalid file type or no file uploaded.")

        filename = secure_filename(file.filename)
        file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        file.save(file_path)

        # Extract and validate text
        text = extract_text(file_path)
        print(f"Extracted text length: {len(text) if text else 0}")
        if not text:
            return render_template("result.html", mcqs=[], txt_filename=None, pdf_filename=None, 
                                error="No text extracted from file.")

        # Generate MCQs
        num_questions = request.form.get("num_questions", type=int)
        mcq_text = quetion_mcqs_generator(text, num_questions)
        print(f"Generated MCQ text:\n{mcq_text}")
        
        mcqs = parse_mcqs(mcq_text)
        print(f"Parsed MCQs count: {len(mcqs)}")

        if not mcqs:
            return render_template("result.html", mcqs=[], txt_filename=None, pdf_filename=None, 
                                error="MCQ generation failed. Please try again.")

        # Ensure result folder exists
        os.makedirs(app.config['RESULT_FOLDER'], exist_ok=True)

        try:
            # Save to TXT
            txt_filename = f"{os.path.splitext(filename)[0]}_mcqs.txt"
            txt_file_path = os.path.join(app.config['RESULT_FOLDER'], txt_filename)
            with open(txt_file_path, 'w', encoding='utf-8') as txt_file:
                for mcq in mcqs:
                    txt_file.write(f"{mcq['question']}\n")
                    for option in mcq['options']:
                        txt_file.write(f"{option}\n")
                    txt_file.write(f"Answer: {mcq['answer']}\n\n")
            print(f"TXT file saved: {txt_file_path}")

            # Save to PDF
            pdf_filename = f"{os.path.splitext(filename)[0]}_mcqs.pdf"
            pdf_file_path = os.path.join(app.config['RESULT_FOLDER'], pdf_filename)
            pdf = FPDF()
            pdf.add_page()
            pdf.set_font("Arial", size=12)
            for mcq in mcqs:
                pdf.multi_cell(0, 10, mcq['question'])
                for option in mcq['options']:
                    pdf.multi_cell(0, 10, option)
                pdf.multi_cell(0, 10, f"Answer: {mcq['answer']}\n")
            pdf.output(pdf_file_path)
            print(f"PDF file saved: {pdf_file_path}")

            return render_template(
                "result.html",
                mcqs=mcqs,
                filename=filename,
                txt_filename=txt_filename,
                pdf_filename=pdf_filename
            )

        except Exception as e:
            print(f"Error saving files: {str(e)}")
            return render_template("result.html", mcqs=mcqs, txt_filename=None, pdf_filename=None,
                                error="Error saving files. Please try again.")

    except Exception as e:
        print(f"Unexpected error: {str(e)}")
        return render_template("result.html", mcqs=[], txt_filename=None, pdf_filename=None,
                            error="An unexpected error occurred. Please try again.")

@app.route("/download/<filename>")
def download_file(filename):
    try:
        file_path = os.path.join(app.config['RESULT_FOLDER'], filename)
        if not os.path.exists(file_path):
            return render_template("result.html", mcqs=[], txt_filename=None, pdf_filename=None,
                                error="File not found. Please generate MCQs first.")
        return send_file(file_path, as_attachment=True, download_name=filename)
    except Exception as e:
        print(f"Download error: {str(e)}")
        return render_template("result.html", mcqs=[], txt_filename=None, pdf_filename=None,
                            error="Error downloading file. Please try again.")
if __name__ == "__main__":
    os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
    os.makedirs(app.config['RESULT_FOLDER'], exist_ok=True)
    app.run(debug=True)
