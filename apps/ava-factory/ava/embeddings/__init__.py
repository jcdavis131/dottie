"""Shim: ava.embeddings -> dottie.embeddings"""
from dottie.embeddings import *  # noqa
import dottie.embeddings as _m
import sys
sys.modules[__name__] = _m
