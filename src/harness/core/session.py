"""Session persistence ~/.dottie/sessions/<id>/session.jsonl — mandatory 7-field even no-change."""
from pathlib import Path
import json, os, time
def session_path(session_id:str)->Path:
    root=Path(os.environ.get("DOTTIE_ROOT", Path.home()/".dottie"))/"sessions"/session_id
    root.mkdir(parents=True, exist_ok=True)
    return root/"session.jsonl"
def log(session_id:str, **fields):
    p=session_path(session_id)
    rec={"ts":time.time(), **fields}
    with p.open("a") as f: f.write(json.dumps(rec)+"\n")
