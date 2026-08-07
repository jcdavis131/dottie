"""Thin wrapper for ultra modules — keeps zero-deps contract"""
import subprocess, json, pathlib, sys
def capture_from_module(what, cause, lesson, fix, prevention, where="", conf=0.7):
    cmd=[sys.executable, str(pathlib.Path.home()/"workspace/skills/mistake-learning/bin/learn.py"), "capture", json.dumps({"what":what,"where":where}), "--lesson", json.dumps({"cause":cause,"lesson":lesson,"fix_now":fix,"prevention":prevention,"confidence":conf})]
    return subprocess.run(cmd, capture_output=True, text=True)
