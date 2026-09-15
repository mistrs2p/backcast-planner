"""Domain layer — pure, framework-independent (AGENTS.md §4).

This package must not import FastAPI, SQLAlchemy, Redis, vendor LLM SDKs,
or UI libraries; ``scripts/check_rules.py`` enforces this in CI.
"""
