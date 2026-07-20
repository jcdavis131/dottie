"""Shim: ava.chat_html -> dottie.chat_html (renamed to Dottie)"""

import sys

import dottie.chat_html as _m
from dottie.chat_html import *  # noqa: F403

sys.modules[__name__] = _m
