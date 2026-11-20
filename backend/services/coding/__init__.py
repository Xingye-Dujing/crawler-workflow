"""Qualitative coding: codebooks and the three coding passes.

A codebook is authored work. It lives in the signed-in account's tree and is resolved at CALL time
through ``runtime.paths.active()``, never cached in a module constant. Models propose; the human
approves a codebook version before the next pass consumes it.
"""
