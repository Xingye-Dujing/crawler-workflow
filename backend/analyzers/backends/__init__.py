"""Runtime adapters, one file per model family.

A family answers "how are weights turned into columns". Shared nodes and services never branch on a
model id; they ask the catalogue for the family and call the matching adapter. Importing this package
loads nothing heavy -- every adapter imports its runtime inside the function that uses it.
"""
