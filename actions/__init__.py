"""Action handlers — the things TONY can actually do.

apps (launch), web (URLs), control (keys/media/scroll), screen_record (ffmpeg capture).
`commands.py` composes these into the command registry; there is no LLM tool-schema
layer — TONY routes by fuzzy match, not by asking a model.
"""
