from typing_extensions import TypedDict
from typing import Optional

class RuntimeState(TypedDict):
    last_status: str
    stories_found: int
    last_run: Optional[str]
    last_email_html: Optional[str]
    run_history: list[dict]

runtime_state: RuntimeState = {
    "last_status": "Never run",
    "stories_found": 0,
    "last_run": None,
    "last_email_html": None,
    "run_history": [],
}