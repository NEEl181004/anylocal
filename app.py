"""
Root Entrypoint for Render / Railway / Heroku
Delegates directly to server/app.py
"""
import os
import sys

server_dir = os.path.join(os.path.dirname(__file__), "server")
if server_dir not in sys.path:
    sys.path.insert(0, server_dir)

from server.app import create_app, PORT, web

if __name__ == "__main__":
    print(f"[Render] Starting AnyLocal Cloud Relay on port {PORT}...")
    web.run_app(create_app(), port=PORT)
