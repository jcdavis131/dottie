"""Shim: ava.evals_html -> dottie.evals_html (renamed to Dottie)"""
from dottie.evals_html import *  # noqa: F401,F403
import dottie.evals_html as _m
import sys
sys.modules[__name__] = _m
