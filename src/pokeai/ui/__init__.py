"""Diagnostic dashboard and run control (fail-safe) for pokeai.

`RunControl` is the pure state machine (no UI deps) the training loop
checks each step. `Dashboard` (pygame) drives it from user input.
"""
