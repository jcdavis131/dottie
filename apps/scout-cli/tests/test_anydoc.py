"""anydoc minimal tests — stdlib only"""

import io, zipfile, sys
from pathlib import Path

# ensure importable
ROOT = Path(__file__).resolve().parents[3]
CLI = ROOT / "apps" / "scout-cli"
if str(CLI) not in sys.path:
    sys.path.insert(0, str(CLI))

from bigbang.plugins.extract import anydoc

def _docx_hello():
    bio=io.BytesIO()
    with zipfile.ZipFile(bio,'w') as z:
        z.writestr('[Content_Types].xml','<?xml version="1.0"?><Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main"/></Types>')
        z.writestr('_rels/.rels','<?xml version="1.0"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"></Relationships>')
        z.writestr('word/document.xml','''<?xml version="1.0"?><w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>
<w:p><w:pPr><w:pStyle w:val="Heading1"/></w:pPr><w:r><w:t>Hello</w:t></w:r></w:p>
<w:p><w:r><w:t>world para</w:t></w:r></w:p>
<w:p><w:pPr><w:numPr><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t>item a</w:t></w:r></w:p>
<w:p><w:pPr><w:numPr><w:numId w:val="1"/></w:numPr></w:pPr><w:r><w:t>item b</w:t></w:r></w:p>
</w:body></w:document>''')
        z.writestr('word/numbering.xml','''<?xml version="1.0"?><w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:abstractNum w:abstractNumId="0"><w:lvl w:ilvl="0"><w:numFmt w:val="bullet"/></w:lvl></w:abstractNum><w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num></w:numbering>''')
    return bio.getvalue()

def test_detect_pdf():
    assert anydoc.detect(b'%PDF-1.4')=='pdf'

def test_detect_rtf():
    assert anydoc.detect(b'{\\rtf1\\ansi')=='rtf'

def test_detect_docx_zip():
    assert anydoc.detect(_docx_hello())=='docx'

def test_detect_html():
    assert anydoc.detect(b'<!DOCTYPE html><html>')=='html'
    assert anydoc.detect(b'<html><head>')=='html'

def test_detect_csv():
    assert anydoc.detect(b'a,b,c\n1,2,3\n')=='csv'

def test_docx_heading_preserved():
    md=anydoc.to_markdown(anydoc.parse(_docx_hello()))
    assert '# Hello' in md, md
    assert 'world para' in md

def test_batch_order():
    docs=anydoc.batch([_docx_hello(), b'<html><h1>B</h1></html>', b'plain'], jobs=2)
    assert [d.meta['format'] for d in docs]==['docx','html','txt']

def test_ole_503():
    try:
        anydoc.parse(bytes.fromhex('D0CF11E0A1B11AE1')+b'\x00'*20, 'a.doc')
        assert False, 'should raise'
    except Exception as e:
        assert getattr(e,'code',503)==503

def test_scanned_pdf_503():
    try:
        anydoc.parse(b'%PDF-1.4 fake')
        assert False
    except Exception as e:
        assert getattr(e,'code',503)==503

def test_encrypted_pdf_503():
    try:
        anydoc.parse(b'%PDF-1.4\n<< /Encrypt >>')
        assert False
    except Exception as e:
        assert getattr(e,'code',503)==503

def test_gfm_serializer_table():
    doc=anydoc.Document(meta={'format':'txt'}, blocks=[{'type':'table','headers':['a','b'],'rows':[['1','2']] }], assets=[])
    md=anydoc.to_markdown(doc)
    assert '| a | b |' in md
    assert '| 1 | 2 |' in md

def test_read_bytes():
    gfm=anydoc.read(b'# Hi\npara')
    assert '# Hi' in gfm
