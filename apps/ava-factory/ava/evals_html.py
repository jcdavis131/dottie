"""Shim: ava.evals_html -> dottie.evals_html (renamed to Dottie)"""

import sys

import dottie.evals_html as _m
from dottie.evals_html import *  # noqa: F403

sys.modules[__name__] = _m
