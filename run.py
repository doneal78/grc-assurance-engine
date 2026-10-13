"""Local development entry point.

Run with: python run.py
Serves on http://127.0.0.1:5000 only. Do not expose this to the internet.
"""

from app import create_app

app = create_app()

if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False)
