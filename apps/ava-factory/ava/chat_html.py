"""Shim: ava.chat_html -> dottie.chat_html (renamed to Dottie)"""
from dottie.chat_html import *  # noqa: F401,F403
import dottie.chat_html as _m
import sys
sys.modules[__name__] = _m
