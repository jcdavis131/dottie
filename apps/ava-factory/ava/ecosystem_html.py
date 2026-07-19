"""Shim: ava.ecosystem_html -> dottie.ecosystem_html (renamed to Dottie)"""
from dottie.ecosystem_html import *  # noqa: F401,F403
import dottie.ecosystem_html as _m
import sys
sys.modules[__name__] = _m
