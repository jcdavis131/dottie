"""Real evaluation harness.

Replaces eval_branch_harness.py, whose every score is a hardcoded literal and
whose "RealInterventionEngine" edits a torch.randn verbalizer indexed by
sha256(concept) % vocab -- it never touches the model. Nothing in this package
may return a constant: every number comes from a forward pass of the loaded
checkpoint. tests/test_no_mock.py enforces that.
"""
