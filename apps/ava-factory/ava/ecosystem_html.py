"""Shim: ava.ecosystem_html -> dottie.ecosystem_html (renamed to Dottie)"""

import sys

import dottie.ecosystem_html as _m
from dottie.ecosystem_html import *  # noqa: F403

sys.modules[__name__] = _m
