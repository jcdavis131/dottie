# MIT License — Copyright (c) 2026 JC Davis
#
# Clean-room implementation. Reimplemented from first principles and documented
# patterns. No vendor code referenced or copied.

"""Training pipeline for the homegrown state-model calibrator.

The neural net does NOT replace the heuristic's answer selection. It learns
one thing: P(heuristic answer is correct | state features, query kind).
That is calibration, and it is the highest-leverage upgrade — the heuristic
picks good answers but its confidence is uncalibrated.

Pipeline: data.py (synthetic) -> model.py (torch MLP) -> train.py (BCE +
calibration loss, ECE early stopping) -> export.py (weights as JSON).
Inference needs no torch: dottie_core/_nn.py does the forward pass in
stdlib/numpy.
"""
