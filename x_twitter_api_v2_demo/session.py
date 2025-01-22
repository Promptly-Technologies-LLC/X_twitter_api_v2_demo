import os
import json
import pickle
from typing import Optional, Dict, Any
from requests_oauthlib import OAuth2Session

def get_sessions_dir() -> str:
    """Get or create the sessions directory."""
    sessions_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "sessions")
    os.makedirs(sessions_dir, exist_ok=True)
    return sessions_dir

def save_session(session: OAuth2Session, token: Dict[str, Any]) -> None:
    """Save the OAuth2Session and token to a file."""
    sessions_dir = get_sessions_dir()
    
    # Save token as JSON
    token_path = os.path.join(sessions_dir, "token.json")
    with open(token_path, "w") as f:
        json.dump(token, f)
    
    # Save session as pickle
    session_path = os.path.join(sessions_dir, "session.pkl")
    with open(session_path, "wb") as f:
        pickle.dump(session, f)

def load_session() -> tuple[Optional[OAuth2Session], Optional[Dict[str, Any]]]:
    """Load the OAuth2Session and token from files if they exist."""
    sessions_dir = get_sessions_dir()
    token_path = os.path.join(sessions_dir, "token.json")
    session_path = os.path.join(sessions_dir, "session.pkl")
    
    token = None
    session = None
    
    # Load token if exists
    if os.path.exists(token_path):
        try:
            with open(token_path, "r") as f:
                token = json.load(f)
        except (json.JSONDecodeError, IOError):
            pass
    
    # Load session if exists
    if os.path.exists(session_path):
        try:
            with open(session_path, "rb") as f:
                session = pickle.load(f)
        except (pickle.UnpicklingError, IOError):
            pass
    
    return session, token 