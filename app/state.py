# Simple in-memory state shared across the app.
# For production, replace with Redis or a DB table.

agent_state: dict = {
    "last_run": None,
    "last_status": "Not yet run",
    "stories_found": 0,
    "last_email_html": None,
    "run_history": [],  # List of {"timestamp", "stories", "status"} — enables trend tracking
}