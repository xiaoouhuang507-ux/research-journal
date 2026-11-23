"""Generate an original two-page synthetic reference for local demonstrations."""
from pathlib import Path
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject

output = Path(__file__).resolve().parents[1] / 'demo-data' / 'sample-reference.pdf'
writer = PdfWriter()
pages = [
    ['SYNTHETIC DEMO REFERENCE - NOT A PUBLISHED PAPER',
     'AnchorBridge: A sample method for incomplete views',
     'Problem: missing view information reduces feature coverage.',
     'Method overview: build anchors and propagate reliable weights.'],
    ['METHOD DETAILS - SYNTHETIC CONTENT',
     'Step one: create anchors from available observations.',
     'Step two: propagate reliable feature weights across views.',
     'Limitation: no real experiment or benchmark was performed.']
]
for lines in pages:
    page = writer.add_blank_page(width=612, height=792)
    font = DictionaryObject({NameObject('/Type'): NameObject('/Font'), NameObject('/Subtype'): NameObject('/Type1'), NameObject('/BaseFont'): NameObject('/Helvetica')})
    page[NameObject('/Resources')] = DictionaryObject({NameObject('/Font'): DictionaryObject({NameObject('/F1'): writer._add_object(font)})})
    operators = ['BT /F1 11 Tf 42 730 Td 22 TL']
    for index, line in enumerate(lines):
        safe = line.replace('\\', '\\\\').replace('(', '\\(').replace(')', '\\)')
        if index:
            operators.append('T*')
        operators.append('(' + safe + ') Tj')
    operators.append('ET')
    stream = DecodedStreamObject()
    stream.set_data('\n'.join(operators).encode('ascii'))
    page[NameObject('/Contents')] = writer._add_object(stream)
writer.add_metadata({'/Title': 'AnchorBridge Synthetic Demo Reference'})
output.parent.mkdir(parents=True, exist_ok=True)
with output.open('wb') as handle:
    writer.write(handle)
print('Created: demo-data/sample-reference.pdf (2 synthetic pages)')
