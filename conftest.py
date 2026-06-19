"""
Present so that `pytest tests/` can import the top-level modules (tools, agent,
utils) from the project root. pytest adds the directory containing this file to
sys.path, which makes `from tools import ...` work from inside tests/.
"""
