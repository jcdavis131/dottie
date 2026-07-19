"""Shim: ava.dashboard_html -> dottie.dashboard_html (renamed to Dottie)"""
from dottie.dashboard_html import *  # noqa: F401,F403
import dottie.dashboard_html as _m
import sys
sys.modules[__name__] = _m
