# Solo personal project, no connection to employer, built with public/free-tier only
"""anydoc-py v1.0.0 — unified Document IR, single GFM, stdlib only, honest 503"""
from __future__ import annotations
import base64,csv,hashlib,io,json,re,zipfile,zlib
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass,field
from html.parser import HTMLParser
from pathlib import Path
from typing import Any,Dict,List,Union
import xml.etree.ElementTree as ET

VERSION="1.0.0"
tier="stdlib"
SUPPORTED_FORMATS=["docx","pptx","xlsx","odt","ods","odp","epub","pdf","rtf","html","csv","txt","md","json","doc","xls","ppt","ole"]

class AnyDocError(Exception):
    def __init__(self,code:int,reason:str,fmt:str="",extra:dict|None=None):
        self.code=code;self.reason=reason;self.format=fmt;self.extra=extra or {}
        super().__init__(f"[{code}] {reason} (format={fmt})")
class ScannedPDFError(AnyDocError):
    def __init__(self,fmt="pdf"): super().__init__(503,"SCANNED_PDF_NO_TEXT",fmt,{"error":"scanned pdf"})
class EncryptedPDFError(AnyDocError):
    def __init__(self): super().__init__(503,"ENCRYPTED_PDF","pdf",{"error":"encrypted pdf"})
class OleUnsupportedError(AnyDocError):
    def __init__(self,fmt="ole"): super().__init__(503,"OLE_UNSUPPORTED",fmt,{"error":f"OLE legacy {fmt}"})
class UnsupportedFormatError(AnyDocError):
    def __init__(self,fmt): super().__init__(503,"UNSUPPORTED_FORMAT",fmt)

def _slug(s:str)->str:
    s=re.sub(r'[^a-z0-9]+','-',s.strip().lower()).strip('-')
    return s[:64] or "section"
def _clean(s:str)->str:
    return re.sub(r"[ \t]+"," ",s.replace("\r\n","\n").replace("\r","\n")).strip()
def _meta_base(fmt:str,source:str|None=None,extra:dict|None=None)->dict:
    m={"format":fmt,"version":VERSION,"tier":tier}
    if source: m["source"]=source
    if extra: m.update(extra)
    return m

@dataclass
class Document:
    meta:Dict[str,Any]=field(default_factory=dict)
    blocks:List[Dict[str,Any]]=field(default_factory=list)
    assets:List[Dict[str,Any]]=field(default_factory=list)
    def to_dict(self): return {"meta":self.meta,"blocks":self.blocks,"assets":[{"k":(f"<{len(v)} bytes>" if k=="bytes" and isinstance(v,(bytes,bytearray)) else v) for k,v in a.items()} for a in self.assets]}
    def to_full_dict(self): return {"meta":dict(self.meta),"blocks":list(self.blocks),"assets":list(self.assets)}

_OLE_MAGIC=bytes.fromhex("D0CF11E0A1B11AE1")

def detect(data:bytes,filename:str|None=None)->str:
    if not isinstance(data,(bytes,bytearray)): 
        try: data=bytes(data)  # type: ignore
        except: return "txt"
    b=data[:8192]; lh=b[:4096].lower()
    if b.startswith(b"%PDF-"): return "pdf"
    if b.lstrip().startswith(b"{\\rtf"): return "rtf"
    if b.startswith(_OLE_MAGIC):
        if filename:
            ext=Path(filename).suffix.lower().lstrip(".")
            if ext in ("doc","dot"): return "doc"
            if ext in ("xls","xlt"): return "xls"
            if ext in ("ppt","pot","pps"): return "ppt"
        return "ole"
    if b.startswith(b"PK\x03\x04") or zipfile.is_zipfile(io.BytesIO(data[:65536] if len(data)>65536 else data)):
        try:
            z=zipfile.ZipFile(io.BytesIO(data))
            names=set(z.namelist())
            try: mt=z.read("mimetype")[:256] if "mimetype" in names else b""
            except: mt=b""
            if "word/document.xml" in names: return "docx"
            if "ppt/presentation.xml" in names: return "pptx"
            if "xl/workbook.xml" in names or "xl/_rels/workbook.xml.rels" in names: return "xlsx"
            if "content.xml" in names:
                if b"vnd.oasis.opendocument.spreadsheet" in mt: return "ods"
                if b"vnd.oasis.opendocument.presentation" in mt: return "odp"
                if b"vnd.oasis.opendocument.text" in mt: return "odt"
                try:
                    cn=z.read("content.xml")[:2000]
                    if b"office:spreadsheet" in cn: return "ods"
                    if b"office:presentation" in cn: return "odp"
                    return "odt"
                except: return "odt"
            if mt.startswith(b"application/epub"): return "epub"
            if "META-INF/container.xml" in names and any(n.endswith(".opf") for n in names): return "epub"
        except: pass
    if any(m in lh for m in (b"<html",b"<!doctype",b"<head",b"<body",b"<div",b"<article",b"<main")): return "html"
    if filename and Path(filename).suffix.lower()==".csv": return "csv"
    try:
        txt=b[:4096].decode("utf-8",errors="ignore")
        if "," in txt and "\n" in txt:
            lines=[l for l in txt.splitlines() if l.strip()][:5]
            if len(lines)>=2:
                commas=[l.count(",") for l in lines]
                if min(commas)>0 and max(commas)-min(commas)<=1 and not txt.strip().startswith(("{","[")):
                    return "csv"
    except: pass
    if filename:
        ext=Path(filename).suffix.lower().lstrip(".")
        if ext in ("md","markdown"): return "md"
        if ext=="json": return "json"
        if ext in ("txt",): return "txt"
        if ext in SUPPORTED_FORMATS: return ext
    try:
        t=data[:4096].decode("utf-8",errors="ignore").strip()
        if t.startswith("{") or t.startswith("["):
            try: json.loads(data[:65536].decode("utf-8")); return "json"
            except: pass
        if re.search(r'^#{1,6}\s+\S',t,re.M): return "md"
        if "```" in t and (t.count("#")>0 or t.count("- ")>2): return "md"
    except: pass
    return "txt"

# ---- docx ----
_W="http://schemas.openxmlformats.org/wordprocessingml/2006/main"
def _parse_docx(data:bytes,filename:str|None=None)->Document:
    try: z=zipfile.ZipFile(io.BytesIO(data))
    except Exception as e: raise AnyDocError(503,f"BAD_ZIP_DOCX:{e}","docx")
    try: xb=z.read("word/document.xml")
    except KeyError: raise AnyDocError(503,"DOCX_MISSING_DOCUMENT_XML","docx")
    num_ordered={}
    try:
        if "word/numbering.xml" in z.namelist():
            nb=z.read("word/numbering.xml"); rn=ET.fromstring(nb)
            abs_ord={}
            for absn in rn.findall(f".//{{{_W}}}abstractNum"):
                aid=absn.get(f"{{{_W}}}abstractNumId") or absn.get("abstractNumId") or ""
                ord_=False
                for lvl in absn.findall(f".//{{{_W}}}lvl"):
                    nf=lvl.find(f"{{{_W}}}numFmt")
                    if nf is not None:
                        v=nf.get(f"{{{_W}}}val") or nf.get("val") or ""
                        if v in ("decimal","lowerLetter","upperLetter","lowerRoman","upperRoman","decimalZero"): ord_=True; break
                abs_ord[aid]=ord_
            for num in rn.findall(f".//{{{_W}}}num"):
                nid=num.get(f"{{{_W}}}numId") or num.get("numId") or ""
                ae=num.find(f"{{{_W}}}abstractNumId")
                if ae is not None:
                    aid=ae.get(f"{{{_W}}}val") or ae.get("val") or ""
                    num_ordered[nid]=abs_ord.get(aid,True)
    except: pass
    root=ET.fromstring(xb); body=root.find(f".//{{{_W}}}body"); 
    if body is None: body=root
    blocks=[]; cur_items=[]; cur_ord=False; cur_nid=None
    def flush():
        nonlocal cur_items,cur_ord,cur_nid
        if cur_items: blocks.append({"type":"list","ordered":cur_ord,"items":list(cur_items)}); cur_items=[]; cur_ord=False; cur_nid=None
    def render_p(p_el):
        pPr=p_el.find(f"{{{_W}}}pPr"); style=""; head=0; numId=None; ordered=False; is_list=False
        if pPr is not None:
            ps=pPr.find(f"{{{_W}}}pStyle")
            if ps is not None:
                v=ps.get(f"{{{_W}}}val") or ps.get("val") or ""; style=v
                m=re.match(r"Heading([1-6])",v,re.I)
                if m: head=int(m.group(1))
                elif v.lower().startswith("heading"):
                    mm=re.search(r"(\d)",v)
                    if mm: head=int(mm.group(1))
            np=pPr.find(f"{{{_W}}}numPr")
            if np is not None:
                is_list=True
                nid_el=np.find(f"{{{_W}}}numId")
                if nid_el is not None:
                    numId=nid_el.get(f"{{{_W}}}val") or nid_el.get("val")
                    ordered=num_ordered.get(str(numId),False) if numId else False
                    if numId and str(numId) not in num_ordered: ordered=True
        parts=[]
        for r in p_el.findall(f"{{{_W}}}r"):
            rPr=r.find(f"{{{_W}}}rPr"); bold=False; ital=False; strike=False; code=False
            if rPr is not None:
                if rPr.find(f"{{{_W}}}b") is not None: bold=True
                if rPr.find(f"{{{_W}}}i") is not None: ital=True
                if rPr.find(f"{{{_W}}}strike") is not None: strike=True
                rf=rPr.find(f"{{{_W}}}rFonts")
                if rf is not None:
                    af=rf.get(f"{{{_W}}}ascii") or ""
                    if "Consolas" in af or "Courier" in af or "Mono" in af: code=True
            rt="".join((te.text or "") for te in r.findall(f"{{{_W}}}t"))
            if not rt:
                if r.find(f"{{{_W}}}tab") is not None: rt=" "
                elif r.find(f"{{{_W}}}br") is not None: rt="\n"
            if not rt: continue
            if code: rt=f"`{rt}`"
            else:
                if bold and ital: rt=f"***{rt}***"
                elif bold: rt=f"**{rt}**"
                elif ital: rt=f"*{rt}*"
                if strike: rt=f"~~{rt}~~"
            parts.append(rt)
        txt="".join(parts).strip()
        return txt,{"heading":head,"style":style,"is_list":is_list,"numId":numId,"ordered":ordered}
    for child in list(body):
        local=child.tag.split("}")[-1]
        if local=="p":
            txt,info=render_p(child)
            if not txt: continue
            if info["heading"]:
                flush()
                plain=re.sub(r'\*\*\*|\*\*|\*|~~|`','',txt).strip() or txt
                blocks.append({"type":"heading","level":info["heading"],"text":plain,"id":_slug(plain),"raw":txt})
            elif info["is_list"]:
                if cur_nid is not None and info["numId"]!=cur_nid: flush()
                if not cur_items: cur_ord=info["ordered"]; cur_nid=info["numId"]
                cur_items.append(txt)
            else:
                flush()
                if info["style"] and "Quote" in info["style"]: blocks.append({"type":"quote","text":txt})
                elif info["style"] and "Code" in info["style"]: blocks.append({"type":"code","lang":"","text":re.sub(r'`','',txt)})
                else: blocks.append({"type":"paragraph","text":txt})
        elif local=="tbl":
            flush(); rows=[]
            for tr in child.findall(f".//{{{_W}}}tr"):
                cells=[]
                for tc in tr.findall(f"{{{_W}}}tc"):
                    cells.append(_clean("".join((n.text or "") for n in tc.findall(f".//{{{_W}}}t"))))
                if cells: rows.append(cells)
            if rows: blocks.append({"type":"table","headers":rows[0],"rows":rows[1:] if len(rows)>1 else []})
    flush()
    meta=_meta_base("docx",source=filename,extra={"title":"","pages":1})
    try:
        if "docProps/core.xml" in z.namelist():
            core=ET.fromstring(z.read("docProps/core.xml"))
            for el in core.iter():
                if el.tag.endswith("}title") and el.text: meta["title"]=el.text.strip()
                if el.tag.endswith("}creator") and el.text: meta["author"]=el.text.strip()
    except: pass
    if not blocks: blocks.append({"type":"paragraph","text":""})
    return Document(meta=meta,blocks=blocks,assets=[])

def _parse_pptx(data:bytes,filename:str|None=None)->Document:
    try: z=zipfile.ZipFile(io.BytesIO(data))
    except Exception as e: raise AnyDocError(503,f"BAD_ZIP_PPTX {e}","pptx")
    blocks=[]
    sns=sorted([n for n in z.namelist() if re.match(r"ppt/slides/slide\d+\.xml",n)], key=lambda x: int(re.search(r"slide(\d+)",x).group(1) if re.search(r"slide(\d+)",x) else 0))
    for idx,sname in enumerate(sns,1):
        try:
            root=ET.fromstring(z.read(sname))
            txts=[el.text.strip() for el in root.iter() if el.tag.endswith("}t") and el.text and el.text.strip()]
            if txts:
                blocks.append({"type":"heading","level":2,"text":f"Slide {idx}: {txts[0][:80]}","id":_slug(f"slide-{idx}-{txts[0][:20]}")})
                for t in txts[1:]:
                    if t: blocks.append({"type":"paragraph","text":t})
            nn=sname.replace("slides/slide","notesSlides/notesSlide")
            if nn in z.namelist():
                try:
                    nr=ET.fromstring(z.read(nn))
                    nts=[el.text.strip() for el in nr.iter() if el.tag.endswith("}t") and el.text and el.text.strip()]
                    if nts: blocks.append({"type":"quote","text":"Notes: "+" ".join(nts[:5])})
                except: pass
        except: continue
    if not blocks: blocks.append({"type":"paragraph","text":""})
    return Document(meta=_meta_base("pptx",source=filename,extra={"pages":len(sns)}),blocks=blocks,assets=[])

def _parse_xlsx(data:bytes,filename:str|None=None)->Document:
    try: z=zipfile.ZipFile(io.BytesIO(data))
    except Exception as e: raise AnyDocError(503,f"BAD_ZIP_XLSX {e}","xlsx")
    shared=[]
    try:
        if "xl/sharedStrings.xml" in z.namelist():
            sr=ET.fromstring(z.read("xl/sharedStrings.xml"))
            for si in sr.findall(f".//{{http://schemas.openxmlformats.org/spreadsheetml/2006/main}}t"):
                shared.append(si.text or "")
            if not shared:
                for si in sr.findall(f".//{{http://schemas.openxmlformats.org/spreadsheetml/2006/main}}si"):
                    shared.append("".join((n.text or "") for n in si.findall(f".//{{http://schemas.openxmlformats.org/spreadsheetml/2006/main}}t")))
    except: pass
    blocks=[]; sheets=sorted([n for n in z.namelist() if n.startswith("xl/worksheets/sheet") and n.endswith(".xml")])
    for sname in sheets:
        try:
            sr=ET.fromstring(z.read(sname)); ns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"
            rows_dict={}; maxc=0; maxr=0
            for re_el in sr.findall(f".//{{{ns}}}row"):
                ra=re_el.get("r"); ri=int(ra) if ra and ra.isdigit() else (maxr+1); maxr=max(maxr,ri)
                for ce in re_el.findall(f"{{{ns}}}c"):
                    ref=ce.get("r") or ""; col=0
                    for ch in "".join(ch for ch in ref if ch.isalpha()): col=col*26+(ord(ch)-64)
                    col=col or 1; maxc=max(maxc,col)
                    ta=ce.get("t"); ve=ce.find(f"{{{ns}}}v"); v=ve.text if ve is not None else ""; ct=""
                    if ta=="s" and v and v.isdigit():
                        idx=int(v); ct=shared[idx] if idx<len(shared) else v
                    else:
                        ise=ce.find(f"{{{ns}}}is")
                        if ise is not None: ct="".join((n.text or "") for n in ise.findall(f".//{{{ns}}}t"))
                        else: ct=v or ""
                    if ri not in rows_dict: rows_dict[ri]={}
                    rows_dict[ri][col]=ct
            if rows_dict:
                sid=re.search(r"sheet(\d+)",sname); sid=sid.group(1) if sid else "1"
                blocks.append({"type":"heading","level":2,"text":f"Sheet {sid}","id":_slug(f"sheet-{sid}")})
                srows=sorted(rows_dict.items()); trs=[]
                for _,cols in srows:
                    rv=[cols.get(ci,"") for ci in range(1,maxc+1)]
                    while rv and rv[-1]=="": rv.pop()
                    if any(v.strip() for v in rv): trs.append(rv)
                if trs: blocks.append({"type":"table","headers":trs[0],"rows":trs[1:] if len(trs)>1 else []})
        except: continue
    if not blocks: blocks.append({"type":"paragraph","text":""})
    return Document(meta=_meta_base("xlsx",source=filename,extra={"pages":len(sheets)}),blocks=blocks,assets=[])

def _parse_odt(data:bytes,fmt:str="odt",filename:str|None=None)->Document:
    try: z=zipfile.ZipFile(io.BytesIO(data)); cx=z.read("content.xml")
    except Exception as e: raise AnyDocError(503,f"BAD_ZIP_{fmt.upper()} {e}",fmt)
    try: root=ET.fromstring(cx)
    except Exception as e: raise AnyDocError(503,f"BAD_XML_{fmt.upper()} {e}",fmt)
    blocks=[]; NT="urn:oasis:names:tc:opendocument:xmlns:text:1.0"; TB="urn:oasis:names:tc:opendocument:xmlns:table:1.0"
    for el in root.iter():
        tag=el.tag
        if tag==f"{{{NT}}}h":
            lvl=el.get(f"{{{NT}}}outline-level") or "1"
            try: li=int(lvl)
            except: li=1
            txt="".join(el.itertext()).strip()
            if txt: blocks.append({"type":"heading","level":min(li,6),"text":txt,"id":_slug(txt)})
        elif tag==f"{{{NT}}}p" and fmt=="odt":
            txt="".join(el.itertext()).strip()
            if txt: blocks.append({"type":"paragraph","text":txt})
        elif tag==f"{{{TB}}}table" and fmt in ("ods","odt"):
            rows=[]
            for tr in el.findall(f".//{{{TB}}}table-row"):
                cells=[]
                for tc in tr.findall(f"{{{TB}}}table-cell"):
                    rep=tc.get(f"{{{TB}}}number-columns-repeated") or "1"
                    try: rp=int(rep)
                    except: rp=1
                    ct="".join(tc.itertext()).strip()
                    cells.append(ct)
                    for _ in range(rp-1): cells.append("")
                if any(c.strip() for c in cells): rows.append(cells)
            if rows:
                if fmt=="ods": blocks.append({"type":"table","headers":rows[0],"rows":rows[1:]})
                else: blocks.append({"type":"table","headers":rows[0],"rows":rows[1:]})
    if not blocks:
        txt=re.sub(r"<[^>]+>"," ",cx.decode("utf-8",errors="ignore")); txt=_clean(txt)[:5000]
        blocks.append({"type":"paragraph","text":txt or ""})
    return Document(meta=_meta_base(fmt,source=filename),blocks=blocks,assets=[])

def _parse_epub(data:bytes,filename:str|None=None)->Document:
    try: z=zipfile.ZipFile(io.BytesIO(data))
    except Exception as e: raise AnyDocError(503,f"BAD_ZIP_EPUB {e}","epub")
    opf=None
    try:
        if "META-INF/container.xml" in z.namelist():
            cont=ET.fromstring(z.read("META-INF/container.xml"))
            for el in cont.iter():
                if el.tag.endswith("}rootfile"):
                    fp=el.get("full-path")
                    if fp: opf=fp; break
    except: pass
    html_files=[]
    if opf:
        try:
            od="/".join(opf.split("/")[:-1]); oroot=ET.fromstring(z.read(opf))
            idh={}
            for it in oroot.iter():
                if it.tag.endswith("}item"):
                    iid=it.get("id"); href=it.get("href")
                    if iid and href: idh[iid]=href
            sids=[]
            for it in oroot.iter():
                if it.tag.endswith("}itemref"): sids.append(it.get("idref"))
            for sid in sids:
                href=idh.get(sid)
                if href:
                    full=f"{od}/{href}" if od else href
                    full=full.replace("./","")
                    if full in z.namelist(): html_files.append(full)
        except: pass
    if not html_files: html_files=[n for n in z.namelist() if n.lower().endswith((".html",".xhtml",".htm"))]
    blocks=[]
    for hf in html_files[:30]:
        try:
            hb=z.read(hf); doc=_parse_html(hb,filename=hf); blocks.extend(doc.blocks)
        except: continue
    if not blocks: blocks.append({"type":"paragraph","text":""})
    return Document(meta=_meta_base("epub",source=filename,extra={"pages":len(html_files)}),blocks=blocks,assets=[])

class _HTMLParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.blocks=[]; self._stack=[]; self._buf=[]; self._list=[]; self._in_code=False; self._in_pre=False; self._hl=0; self._in_quote=False; self._in_table=False; self._th=[]; self._rows=[]; self._cur=[]; self._cell=[]; self._in_cell=False; self._in_title=False; self._title=""; self._skip=False
    def handle_starttag(self,tag,attrs):
        tag=tag.lower()
        if tag in ("script","style","noscript"): self._skip=True; return
        self._stack.append(tag)
        if tag in ("h1","h2","h3","h4","h5","h6"):
            self._flush(); self._hl=int(tag[1]); self._buf=[]
        elif tag=="p": self._flush(); self._buf=[]
        elif tag in ("ul","ol"):
            self._flush(); self._list.append({"ordered":tag=="ol","items":[],"buf":[],"in_item":False})
        elif tag=="li":
            if self._list:
                ls=self._list[-1]
                if ls.get("in_item") and ls["buf"]:
                    it="".join(ls["buf"]).strip()
                    if it: ls["items"].append(it)
                    ls["buf"]=[]
                ls["in_item"]=True; ls["buf"]=[]
            else: self._buf=[]
        elif tag=="blockquote": self._flush(); self._in_quote=True; self._buf=[]
        elif tag in ("pre","code"):
            if tag=="pre": self._in_pre=True; self._flush(); self._buf=[]
            self._in_code=True
        elif tag=="table": self._flush(); self._in_table=True; self._th=[]; self._rows=[]; self._cur=[]
        elif tag=="tr": self._cur=[]
        elif tag in ("td","th"): self._in_cell=True; self._cell=[]
        elif tag=="title": self._in_title=True
        elif tag=="br":
            if self._in_table and self._in_cell: self._cell.append("\n")
            elif self._list and self._list[-1].get("in_item"): self._list[-1]["buf"].append("\n")
            else: self._buf.append("\n")
    def handle_endtag(self,tag):
        tag=tag.lower()
        if tag in ("script","style","noscript"): self._skip=False; return
        if self._stack and self._stack[-1]==tag: self._stack.pop()
        if tag in ("h1","h2","h3","h4","h5","h6"):
            txt="".join(self._buf).strip()
            if txt: self.blocks.append({"type":"heading","level":self._hl,"text":_clean(txt),"id":_slug(txt)})
            self._buf=[]; self._hl=0
        elif tag=="p":
            txt="".join(self._buf).strip()
            if txt:
                if self._in_quote: self.blocks.append({"type":"quote","text":_clean(txt)})
                else: self.blocks.append({"type":"paragraph","text":_clean(txt)})
            self._buf=[]
            if self._in_quote and not any(t=="blockquote" for t in self._stack): self._in_quote=False
        elif tag=="li":
            if self._list:
                ls=self._list[-1]; txt="".join(ls["buf"]).strip()
                if txt: ls["items"].append(_clean(txt))
                ls["buf"]=[]; ls["in_item"]=False
        elif tag in ("ul","ol"):
            if self._list:
                ls=self._list.pop()
                if ls.get("in_item") and ls["buf"]:
                    it="".join(ls["buf"]).strip()
                    if it: ls["items"].append(it)
                if ls["items"]: self.blocks.append({"type":"list","ordered":ls["ordered"],"items":ls["items"]})
        elif tag=="blockquote":
            txt="".join(self._buf).strip()
            if txt: self.blocks.append({"type":"quote","text":_clean(txt)})
            self._buf=[]; self._in_quote=False
        elif tag in ("pre","code"):
            if tag=="pre":
                txt="".join(self._buf)
                if txt.strip(): self.blocks.append({"type":"code","lang":"","text":txt.strip("\n")})
                self._buf=[]; self._in_pre=False
            self._in_code=False
        elif tag in ("td","th"):
            txt="".join(self._cell).strip(); self._cur.append(_clean(txt)); self._cell=[]; self._in_cell=False
        elif tag=="tr":
            if self._cur:
                if not self._th: self._th=self._cur
                else: self._rows.append(self._cur)
                self._cur=[]
        elif tag=="table":
            if self._th or self._rows:
                hdrs=self._th or (self._rows[0] if self._rows else [])
                rows=self._rows
                self.blocks.append({"type":"table","headers":hdrs,"rows":rows if hdrs!=rows else []})
            self._in_table=False; self._th=[]; self._rows=[]
        elif tag=="title":
            self._title="".join(self._buf).strip() if not self._title else self._title
            self._in_title=False; self._buf=[]
    def handle_data(self,data):
        if self._skip: return
        if self._in_table and self._in_cell: self._cell.append(data)
        elif self._list and self._list[-1].get("in_item"): self._list[-1]["buf"].append(data)
        elif self._in_title: self._title+=data
        else: self._buf.append(data)
    def _flush(self):
        if self._buf:
            txt="".join(self._buf).strip()
            if txt and not self._in_table: self.blocks.append({"type":"paragraph","text":_clean(txt)})
            self._buf=[]
    def close(self):
        super().close(); self._flush()
        while self._list:
            ls=self._list.pop()
            if ls["buf"]:
                it="".join(ls["buf"]).strip()
                if it and it not in ls["items"]: ls["items"].append(it)
            if ls["items"]: self.blocks.append({"type":"list","ordered":ls["ordered"],"items":ls["items"]})

def _parse_html(data:bytes|str,filename:str|None=None)->Document:
    if isinstance(data,bytes):
        try: text=data.decode("utf-8")
        except: text=data.decode("latin-1",errors="ignore")
    else: text=data
    p=_HTMLParser()
    try: p.feed(text); p.close()
    except:
        stripped=re.sub(r"<[^>]+>"," ",text); p.blocks=[{"type":"paragraph","text":_clean(stripped)[:5000]}]
    if not p.blocks:
        stripped=re.sub(r"<[^>]+>"," ",text); stripped=_clean(stripped)
        if stripped: p.blocks=[{"type":"paragraph","text":stripped[:8000]}]
        else: p.blocks=[{"type":"paragraph","text":""}]
    meta=_meta_base("html",source=filename,extra={"title":_clean(p._title)[:200]})
    if p._title: meta["title"]=p._title[:200]
    return Document(meta=meta,blocks=p.blocks,assets=[])

def _parse_csv(data:bytes,filename:str|None=None)->Document:
    try: text=data.decode("utf-8")
    except: text=data.decode("latin-1",errors="ignore")
    try:
        dialect=csv.Sniffer().sniff(text[:2048])
    except: dialect=csv.excel
    f=io.StringIO(text)
    try: rows=list(csv.reader(f,dialect))
    except: rows=[l.split(",") for l in text.splitlines() if l.strip()]
    if not rows: return Document(meta=_meta_base("csv",source=filename),blocks=[{"type":"paragraph","text":""}],assets=[])
    return Document(meta=_meta_base("csv",source=filename,extra={"rows":len(rows)}),blocks=[{"type":"table","headers":rows[0],"rows":rows[1:]}],assets=[])

def _parse_txt(data:bytes,filename:str|None=None,fmt:str="txt")->Document:
    try: text=data.decode("utf-8")
    except: text=data.decode("latin-1",errors="ignore")
    blocks=[]
    if fmt=="json":
        try:
            obj=json.loads(text); blocks.append({"type":"code","lang":"json","text":json.dumps(obj,indent=2)[:8000]})
            def walk(o,d=0):
                if d>3: return
                if isinstance(o,dict):
                    for k,v in o.items():
                        if isinstance(v,str) and len(v)>20: blocks.append({"type":"paragraph","text":f"{k}: {v[:500]}"})
                        elif isinstance(v,(dict,list)): walk(v,d+1)
                elif isinstance(o,list):
                    for it in o[:10]:
                        if isinstance(it,str) and len(it)>20: blocks.append({"type":"paragraph","text":it[:500]})
                        elif isinstance(it,(dict,list)): walk(it,d+1)
            walk(obj)
        except: blocks.append({"type":"paragraph","text":text[:8000]})
        return Document(meta=_meta_base("json",source=filename),blocks=blocks,assets=[])
    if fmt=="md":
        lines=text.splitlines(); i=0
        while i < len(lines):
            line=lines[i]
            if not line.strip(): i+=1; continue
            if line.strip().startswith("```"):
                lang=line.strip()[3:].strip(); j=i+1; cl=[]
                while j < len(lines) and not lines[j].strip().startswith("```"): cl.append(lines[j]); j+=1
                blocks.append({"type":"code","lang":lang,"text":"\n".join(cl)}); i=j+1; continue
            m=re.match(r"^(#{1,6})\s+(.+)$",line)
            if m: lvl=len(m.group(1)); txt=m.group(2).strip(); blocks.append({"type":"heading","level":lvl,"text":txt,"id":_slug(txt)}); i+=1; continue
            if line.lstrip().startswith(">"):
                q=[]
                while i < len(lines) and lines[i].lstrip().startswith(">"): q.append(lines[i].lstrip()[1:].strip()); i+=1
                blocks.append({"type":"quote","text":" ".join(q)}); continue
            if re.match(r"^\s*[-*+]\s+",line) or re.match(r"^\s*\d+\.\s+",line):
                items=[]; ordered=bool(re.match(r"^\s*\d+\.\s+",line))
                while i < len(lines) and (re.match(r"^\s*[-*+]\s+",lines[i]) or re.match(r"^\s*\d+\.\s+",lines[i])):
                    items.append(re.sub(r"^\s*([-*+]|\d+\.)\s+","",lines[i]).strip()); i+=1
                blocks.append({"type":"list","ordered":ordered,"items":items}); continue
            para=[]
            while i < len(lines) and lines[i].strip() and not re.match(r"^(#{1,6})\s+",lines[i]) and not lines[i].strip().startswith("```") and not re.match(r"^\s*[-*+]\s+",lines[i]) and not re.match(r"^\s*\d+\.\s+",lines[i]) and not lines[i].lstrip().startswith(">"):
                para.append(lines[i].strip()); i+=1
            if para: blocks.append({"type":"paragraph","text":" ".join(para)})
            else: i+=1
        if not blocks: blocks.append({"type":"paragraph","text":text[:8000]})
        return Document(meta=_meta_base("md",source=filename),blocks=blocks,assets=[])
    paras=[p.strip() for p in re.split(r"\n\s*\n",text) if p.strip()]
    for p in paras[:200]:
        if len(p)<80 and p.isupper(): blocks.append({"type":"heading","level":2,"text":p.title(),"id":_slug(p)})
        else: blocks.append({"type":"paragraph","text":p[:2000]})
    if not blocks: blocks.append({"type":"paragraph","text":text[:5000]})
    return Document(meta=_meta_base("txt",source=filename),blocks=blocks,assets=[])

def _parse_rtf(data:bytes,filename:str|None=None)->Document:
    try: text=data.decode("utf-8",errors="ignore")
    except: text=data.decode("latin-1",errors="ignore")
    t=re.sub(r"\\par\b","\n",text); t=re.sub(r"\\line\b","\n",t); t=re.sub(r"\\tab\b"," ",t)
    t=re.sub(r"\\[a-zA-Z]+\d*\s?"," ",t); t=t.replace("{"," ").replace("}"," "); t=re.sub(r"\s+"," ",t).strip()
    words=t.split(); cleaned=" ".join(w for w in words if len(w)>=2 or w.lower() in ("a","i"))[:8000]
    return Document(meta=_meta_base("rtf",source=filename),blocks=[{"type":"paragraph","text":cleaned}] if cleaned else [{"type":"paragraph","text":""}],assets=[])

def _parse_pdf(data:bytes,filename:str|None=None)->Document:
    head=data[:8192]
    if b"/Encrypt" in head or b"/Encrypt" in data[:8192]: raise EncryptedPDFError()
    texts=[]
    sre=re.compile(rb"stream\r?\n(.*?)\r?\nendstream",re.S)
    try:
        for m in sre.finditer(data):
            sd=m.group(1); st=max(0,m.start()-300); hdr=data[st:m.start()]
            if b"/FlateDecode" in hdr or b"/Fl" in hdr:
                try: dec=zlib.decompress(sd)
                except: dec=sd
            else: dec=sd
            for tj in re.finditer(rb"\(([^()]*(?:\.[^()]*)*)\)\s*Tj",dec):
                try:
                    raw=tj.group(1).decode("utf-8",errors="ignore")
                    raw=raw.replace("\\(","(").replace("\\)",")").replace("\\\\","\\")
                    if raw.strip(): texts.append(raw.strip())
                except: continue
            for tja in re.finditer(rb"\[(.*?)\]\s*TJ",dec,re.S):
                arr=tja.group(1)
                for part in re.finditer(rb"\(([^()]*)\)",arr):
                    try:
                        raw=part.group(1).decode("utf-8",errors="ignore")
                        if raw.strip(): texts.append(raw.strip())
                    except: continue
    except: pass
    if not texts:
        for tj in re.finditer(rb"\(([^()]*)\)\s*Tj",data):
            try:
                raw=tj.group(1).decode("utf-8",errors="ignore").strip()
                if len(raw)>2 and raw.isprintable(): texts.append(raw)
            except: continue
    if not texts: raise ScannedPDFError()
    full=_clean(" ".join(texts)); blocks=[]
    paras=re.split(r"\s{2,}|\n\s*\n",full)
    for p in paras[:100]:
        p=p.strip()
        if not p: continue
        if len(p)<80 and (p.isupper() or p.istitle()) and len(p.split())<=6:
            blocks.append({"type":"heading","level":2,"text":p,"id":_slug(p)})
        else: blocks.append({"type":"paragraph","text":p[:2000]})
    if not blocks: blocks=[{"type":"paragraph","text":full[:5000]}]
    return Document(meta=_meta_base("pdf",source=filename,extra={"pages":data.count(b"/Type /Page") or 1}),blocks=blocks,assets=[])

def parse(data:bytes,filename:str|None=None)->Document:
    fmt=detect(data,filename)
    if fmt in ("doc","xls","ppt","ole"): raise OleUnsupportedError(fmt)
    if fmt=="docx": return _parse_docx(data,filename)
    if fmt=="pptx": return _parse_pptx(data,filename)
    if fmt=="xlsx": return _parse_xlsx(data,filename)
    if fmt in ("odt","ods","odp"): return _parse_odt(data,fmt,filename)
    if fmt=="epub": return _parse_epub(data,filename)
    if fmt=="pdf": return _parse_pdf(data,filename)
    if fmt=="rtf": return _parse_rtf(data,filename)
    if fmt=="html": return _parse_html(data,filename)
    if fmt=="csv": return _parse_csv(data,filename)
    if fmt in ("txt","md","json"): return _parse_txt(data,filename,fmt)
    return _parse_txt(data,filename,"txt")

def to_markdown(doc:Union[Document,dict],*,include_meta:bool=False)->str:
    if isinstance(doc,dict):
        d=Document(meta=doc.get("meta",{}),blocks=doc.get("blocks",[]),assets=doc.get("assets",[])); doc=d
    out=[]
    if include_meta and doc.meta.get("title"): out.append(f"---\ntitle: {doc.meta.get('title')}\n---\n")
    for b in doc.blocks:
        t=b.get("type")
        if t=="heading":
            lvl=max(1,min(6,int(b.get("level",1)))); txt=b.get("text","").strip()
            out.append(f"{'#'*lvl} {txt}"); out.append("")
        elif t=="paragraph":
            txt=b.get("text","").strip()
            if txt: out.append(txt); out.append("")
        elif t=="list":
            ordered=b.get("ordered",False); items=b.get("items",[])
            for i,it in enumerate(items,1):
                it=it.strip()
                if ordered: out.append(f"{i}. {it}")
                else: out.append(f"- {it}")
            out.append("")
        elif t=="table":
            hdr=b.get("headers",[]); rows=b.get("rows",[])
            if hdr:
                out.append("| "+" | ".join(str(h) for h in hdr)+" |")
                out.append("| "+" | ".join("---" for _ in hdr)+" |")
                for r in rows:
                    pad=list(r)+[""]*(len(hdr)-len(r)); out.append("| "+" | ".join(str(c) for c in pad[:len(hdr)])+" |")
                out.append("")
            else:
                if rows:
                    mc=max(len(r) for r in rows)
                    out.append("| "+" | ".join(f"col{i+1}" for i in range(mc))+" |")
                    out.append("| "+" | ".join("---" for _ in range(mc))+" |")
                    for r in rows:
                        pad=list(r)+[""]*(mc-len(r)); out.append("| "+" | ".join(str(c) for c in pad)+" |")
                    out.append("")
        elif t=="code":
            lang=b.get("lang",""); txt=b.get("text",""); out.append(f"```{lang}"); out.append(txt); out.append("```"); out.append("")
        elif t=="quote":
            txt=b.get("text","").strip()
            for line in txt.splitlines(): out.append(f"> {line}")
            out.append("")
        elif t=="footnote":
            fid=b.get("id","1"); txt=b.get("text",""); out.append(f"[^{fid}]: {txt}"); out.append("")
        else:
            txt=b.get("text","").strip()
            if txt: out.append(txt); out.append("")
    while out and out[-1]=="": out.pop()
    return "\n".join(out)

to_gfm=to_markdown

def read(path_or_bytes:Union[str,bytes,Path],filename:str|None=None)->str:
    if isinstance(path_or_bytes,(bytes,bytearray)):
        doc=parse(bytes(path_or_bytes),filename=filename); return to_markdown(doc)
    else:
        p=Path(path_or_bytes)
        if not p.exists():
            s=str(path_or_bytes)
            if "\n" in s or len(s)<1024 and not p.suffix:
                doc=parse(s.encode("utf-8"),filename=filename); return to_markdown(doc)
            raise FileNotFoundError(f"{p} not found")
        doc=parse(p.read_bytes(),filename=str(p)); return to_markdown(doc)

def batch(sources:List[Union[str,bytes,Path]],jobs:int=4)->List[Document]:
    if jobs<1: jobs=1
    items=[]
    for src in sources:
        if isinstance(src,(bytes,bytearray)): items.append((bytes(src),None))
        else:
            p=Path(src)
            if p.exists() and p.is_file(): items.append((p.read_bytes(),str(p)))
            else: items.append((str(src).encode("utf-8"),None))
    results=[None]*len(items)
    def _work(idx,data,fn):
        try: return idx,parse(data,fn)
        except AnyDocError as e:
            ed=Document(meta={"format":e.format,"error":e.reason,"code":e.code,"source":fn},blocks=[{"type":"paragraph","text":f"Error {e.code}: {e.reason}"}],assets=[]); return idx,ed
        except Exception as ex:
            ed=Document(meta={"format":"unknown","error":str(ex),"code":503,"source":fn},blocks=[{"type":"paragraph","text":f"Error 503: {ex}"}],assets=[]); return idx,ed
    if jobs==1 or len(items)<=1:
        for i,(d,fn) in enumerate(items): _,doc=_work(i,d,fn); results[i]=doc
    else:
        with ThreadPoolExecutor(max_workers=jobs) as ex:
            futs=[ex.submit(_work,i,d,fn) for i,(d,fn) in enumerate(items)]
            for f in futs:
                idx,doc=f.result(); results[idx]=doc
    return [r for r in results if r is not None]

__all__=["Document","detect","parse","to_markdown","to_gfm","read","batch","SUPPORTED_FORMATS","VERSION","tier","AnyDocError","ScannedPDFError","EncryptedPDFError","OleUnsupportedError","UnsupportedFormatError"]
