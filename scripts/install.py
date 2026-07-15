#!/usr/bin/env python3
"""Dev install script"""
import subprocess, sys
subprocess.check_call([sys.executable, "-m", "pip", "install", "-e", ".[all]"])
print("bb installed — try: bb doctor")
