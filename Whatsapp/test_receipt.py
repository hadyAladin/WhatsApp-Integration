from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

def generate_test_receipt(filename="test_receipt.pdf"):
    c = canvas.Canvas(filename, pagesize=letter)

    c.setFont("Helvetica-Bold", 18)
    c.drawString(200, 750, "Payment Receipt")

    c.setFont("Helvetica", 12)
    c.drawString(100, 700, "Date: October 3, 2025")
    c.drawString(100, 680, "Participant ID: P-12345")
    c.drawString(100, 660, "Service: Travel Reimbursement")
    c.drawString(100, 640, "Amount: $42.00")
    c.drawString(100, 620, "Paid To: John Doe")

    c.line(100, 600, 500, 600)
    c.drawString(100, 580, "Thank you for your participation in the clinical trial.")

    c.save()
    print(f"✅ {filename} created successfully")



if __name__ == "__main__":
    # Generate PDF
    pdf_path = generate_test_receipt()