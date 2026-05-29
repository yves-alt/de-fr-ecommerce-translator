"""
Auth stubs — delegates to app.py session-based authentication.
These are thin wrappers so other modules can import auth logic without
depending directly on app.py's Streamlit-coupled code.
"""


def get_current_user(session_state: dict) -> tuple[str, str]:
    """
    Return (user_email, user_role) from Streamlit session state.
    Returns ('', '') if not logged in.
    """
    email = session_state.get("user_email", "")
    role  = session_state.get("user_role", "")
    return email, role


def is_authenticated(session_state: dict) -> bool:
    """Return True if the user is logged in."""
    return bool(session_state.get("authenticated", False))


def is_admin(session_state: dict) -> bool:
    """Return True if the current user has admin role."""
    return session_state.get("user_role", "") == "admin"
