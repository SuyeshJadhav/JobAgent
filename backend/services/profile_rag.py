import os
import re
from pathlib import Path
from backend.services.llm_client import get_llm_client, get_model_name

PROFILE_DIR = Path(__file__).parent.parent.parent / "profile"

def load_profile_file(filename: str) -> str:
    path = PROFILE_DIR / filename
    if path.exists():
        with open(path, "r", encoding="utf-8") as f:
            return f.read()
    return ""

def search_profile(query: str) -> str:
    """
    Search profile files for relevant sections based on a query.
    Uses a simple keyword term overlap scoring.
    """
    query_terms = set(query.lower().split())
    if not query_terms:
        return ""
        
    chunks = []
    
    for filename in ["work_experience.md", "projects.md", "education.md", "skills.md", "essay_bank.md"]:
        content = load_profile_file(filename)
        # Split by markdown headers
        sections = re.split(r'\n(?=#+ )', content)
        for section in sections:
            if not section.strip():
                continue
            section_lower = section.lower()
            # Score section based on word overlap
            score = sum(1 for term in query_terms if term in section_lower)
            if score > 0:
                chunks.append((score, section.strip()))
                
    # Sort chunks by score descending and take top 3
    chunks.sort(key=lambda x: x[0], reverse=True)
    top_chunks = [c[1] for c in chunks[:3]]
    return "\n\n---\n\n".join(top_chunks)

def extract_standard_field(field_name: str) -> str:
    """Fast LLM extraction of standard fields using specific markdown files to ensure accuracy."""
    file_map = {
        "first name": "personal_info.md",
        "last name": "personal_info.md",
        "email": "personal_info.md",
        "phone": "personal_info.md",
        "linkedin": "personal_info.md",
        "github": "personal_info.md",
        "work authorization": "visa.md",
        "visa sponsorship": "visa.md",
        "graduation date": "education.md",
        "gpa": "education.md"
    }
    
    target_file = file_map.get(field_name.lower())
    if not target_file:
        return ""
        
    content = load_profile_file(target_file)
    if not content:
        return ""
        
    client = get_llm_client()
    model = get_model_name()
    
    prompt = f"Extract exactly the requested field value from this markdown document. Return ONLY the value, no extra text, no markdown. Field to extract: '{field_name}'.\n\nDocument:\n{content}"
    try:
         resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            max_tokens=50,
            temperature=0.0
         )
         return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error extracting standard field '{field_name}': {e}")
        return ""

def fill_field(field_name: str, field_context: str, job_context: str) -> str:
    """
    Fills an application form field.
    Standard fields map directly to basic extraction from specific files (e.g., name, email).
    Essay fields perform a RAG search over work experience and essay blanks to craft an answer.
    """
    field_lower = field_name.lower()
    
    standard_fields = [
        "first name", "last name", "email", "phone", "linkedin", 
        "github", "work authorization", "visa sponsorship", 
        "graduation date", "gpa"
    ]
    
    # Try to map to standard field extraction first
    for std in standard_fields:
        if std in field_lower or (len(field_name) < 25 and field_lower in std):
            val = extract_standard_field(std)
            if val:
                # Basic cleanup
                if val.lower().startswith("not ") and "applicable" not in val.lower():
                    pass # sometimes LLM says "Not specified"
                return val
                
    # If not a standard field, it's an essay or unstructured input requiring RAG
    rag_context = search_profile(f"{field_name} {field_context}")
    
    prompt = f"""
You are an AI assistant helping a candidate fill out a job application.
The form requires an answer for this field: "{field_name}"
Additional Context from form: "{field_context}"
Job Context: "{job_context}"

Here is relevant information extracted from the candidate's profile and previously answered essays:
{rag_context}

Instructions:
1. Answer the question specifically and honestly using ONLY the candidate's provided profile information.
2. If it's a short text field (like a URL or a 1-word string), return a concise answer.
3. If it's an essay, cover letter snippet, or open-ended question, provide a solid answer with a maximum of 150 words (unless the field context explicitly requests more/less).
4. Do not lie or fabricate. If the profile lacks the necessary information, output: "Not specified in profile."
5. Return ONLY the final text to be placed in the input field. Do not include introductory conversational text.
"""
    try:
        client = get_llm_client()
        model = get_model_name()
        
        resp = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.7,
            max_tokens=300
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"Error handling essay field '{field_name}': {e}")
        return ""

if __name__ == "__main__":
    # Ensure profile directories exist for testing and write a sample personal_info.md
    PROFILE_DIR.mkdir(parents=True, exist_ok=True)
    pi_path = PROFILE_DIR / "personal_info.md"
    if not pi_path.exists():
        with open(pi_path, "w") as f:
            f.write("# Personal Info\nFirst Name: Suyesh\nLast Name: Jadhav\nEmail: test@example.com\nLinkedIn: https://linkedin.com/in/suyesh\n")
            
    visa_path = PROFILE_DIR / "visa.md"
    if not visa_path.exists():
        with open(visa_path, "w") as f:
            f.write("# Visa\nWork Authorization: F1\nVisa Sponsorship: Yes\n")

    print(f"Email check: {fill_field('Email', '', '')}")
    print(f"Visa check: {fill_field('Visa Sponsorship', '', '')}")
    
    print("\nEssay check (Why AI?):")
    print(fill_field("Why are you passionate about AI?", "Maximum 150 words.", "Machine Learning Intern at OpenAI"))
