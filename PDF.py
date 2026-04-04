import time

import fpdf, io, qrcode
from setting import localhost_ip


class PDF:
    def __init__(self, format=[100, 150]):
        self.pdf = fpdf.FPDF(format=format)

    def render(self, receiver, origin_id, customer_name, phone_number, tag, i=0):
        pdf = self.pdf
        pdf.add_page()

        pdf.set_font('Arial', '', 6)
        pdf.cell(50, 0, f'Customer Name: {customer_name}')
        pdf.ln(3)
        pdf.cell(46, 0, f'Receiver Name: {receiver}')
        pdf.ln(3)
        pdf.cell(50, 0, f'Phone Number: {phone_number}')

        pdf.ln(15)
        pdf.set_font('Arial', 'B', 50)
        pdf.cell(0, 5, tag.split('_')[0], 0, 0, 'C')
        pdf.ln(20)
        pdf.set_font('Arial', 'B', 60)
        pdf.cell(0, 5, tag.split('_')[1], 0, 0, 'C')
        pdf.set_font('Arial', '', 12)

        # bar = barcode.get('code128', origin_id, writer=ImageWriter())
        # output = bar.render(writer_options={'format': 'png'}, text='')
        # output.save('buffer', format='PNG')
        qrcode.make(f'http://{localhost_ip}:5000/normal/input?origin_id={origin_id}').save(f'buffer{i}.png')
        pdf.image(f'buffer{i}.png', 25, 60, 50, 50)
        pdf.set_font('Arial', '', 13)
        pdf.ln(60)
        pdf.cell(0, 10, '  '.join([s for s in str(origin_id)]), 0, 0, 'C')

    def get_bytes_io(self):
        self.pdf.close()
        return io.BytesIO(self.pdf.buffer.encode('latin-1'))

# def generate_pdf(format=[100, 150]):
#     return fpdf.FPDF(format=format)
#
#
# def render_pdf(pdf, transfer_id, origin_id, customer_name, phone_number, tag):
#     pdf.add_page()
#
#     pdf.set_font('Arial', '', 6)
#     pdf.cell(50, 0, f'Identity: {transfer_id}')
#     pdf.ln(3)
#     pdf.cell(46, 0, f'Customer Name: {customer_name}')
#     pdf.ln(3)
#     pdf.cell(50, 0, f'Phone Number: {phone_number}')
#
#     pdf.ln(33)
#     pdf.set_font('Arial', 'B', 95)
#     pdf.cell(0, 5, tag, 0, 0, 'C')
#     pdf.set_font('Arial', '', 12)
#
#     bar = barcode.get('code128', origin_id, writer=ImageWriter())
#     output = bar.render(writer_options={'format': 'png'}, text='')
#     output.save('buffer', format='PNG')
#     pdf.image('buffer', 0, 85, 100, 28, 'PNG')
#     pdf.set_font('Arial', '', 18)
#     pdf.ln(65)
#     pdf.cell(0, 10, ''.join([s + '  ' for s in str(origin_id)]).strip(), 0, 0, 'C')
#
#
# def get_pdf_bytes_buffer(pdf):
#     pdf.close()
#     return io.BytesIO(pdf.buffer.encode('latin-1'))
