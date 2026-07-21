"""Shim: ava.dashboard_html -> dottie.dashboard_html (renamed to Dottie)"""

import sys

import dottie.dashboard_html as _m
from dottie.dashboard_html import *  # noqa: F403

sys.modules[__name__] = _m
