"""python -m app.main  (stdio)  |  python -m app.main --http  (MCP on :8000)"""

from app.main import _run_server

if __name__ == "__main__":
    _run_server()
