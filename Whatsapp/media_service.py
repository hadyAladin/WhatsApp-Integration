import pymupdf
from .adapter_meta import download_media

def save_pdf(media_id, filename="temp.pdf"):
    data = download_media(media_id)
    with open(filename, "wb") as f:
        f.write(data)
    return filename

def extract_pdf_text(path):
    doc = pymupdf.open(path)
    text = "".join([page.get_text() for page in doc])
    doc.close()
    return text
