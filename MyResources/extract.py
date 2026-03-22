import os
import docx
import PyPDF2

def extract_from_docx(filepath):
    try:
        doc = docx.Document(filepath)
        return "\n".join([p.text for p in doc.paragraphs])
    except Exception as e:
        return f"Error reading docx: {e}"

def extract_from_pdf(filepath):
    try:
        reader = PyPDF2.PdfReader(filepath)
        text = ""
        for page in reader.pages:
            text += page.extract_text() + "\n"
        return text
    except Exception as e:
        return f"Error reading pdf: {e}"

def main():
    directory = r"d:\FYP Assisted AI with XR\Resources"
    output_file = os.path.join(directory, "extracted_text.txt")
    
    files_to_read = [
        "Fyp Proposal_ Ai-powered Xr Assistive Guidance System.docx",
        "Approach Report 1.docx",
        "Approach report 2.docx",
        "more detailed approach 1.docx",
        "more deatiled approach 2.docx",
        "Notes.txt"
    ]
    
    with open(output_file, "w", encoding="utf-8") as out:
        for filename in files_to_read:
            filepath = os.path.join(directory, filename)
            out.write(f"\n\n{'='*50}\n==== FILE: {filename} ====\n{'='*50}\n\n")
            
            if not os.path.exists(filepath):
                out.write("File not found.")
                continue
                
            if filename.endswith(".docx"):
                text = extract_from_docx(filepath)
                out.write(text)
            elif filename.endswith(".pdf"):
                text = extract_from_pdf(filepath)
                out.write(text)
            elif filename.endswith(".txt"):
                with open(filepath, "r", encoding="utf-8") as f:
                    out.write(f.read())
            
    print(f"Extraction complete. Output written to {output_file}")

if __name__ == "__main__":
    main()
