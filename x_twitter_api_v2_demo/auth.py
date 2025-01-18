import base64
import hashlib
import os
import secrets
from requests_oauthlib import OAuth1, OAuth2Session

# Define the scopes needed for the OAuth2 flow
SCOPES = ["tweet.read", "tweet.write", "users.read", "offline.access", "media.write"]

def generate_code_verifier() -> str:
    """Generates a random code verifier string."""
    return secrets.token_urlsafe(100)

def generate_code_challenge(code_verifier: str) -> str:
    """Generates the code challenge from the code verifier."""
    code_challenge: bytes = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge_b64: str = base64.urlsafe_b64encode(code_challenge).decode()
    return code_challenge_b64.rstrip("=")

def create_oauth1_auth() -> OAuth1:
    """Create OAuth1 authentication object for media uploads."""
    return OAuth1(
        os.environ.get("X_API_KEY"),
        os.environ.get("X_API_SECRET"),
        os.environ.get("X_ACCESS_TOKEN"),
        os.environ.get("X_ACCESS_TOKEN_SECRET")
    )

def create_oauth2_session() -> OAuth2Session:
    """Create OAuth2 session for tweet posting."""
    return OAuth2Session(
        client_id=os.environ.get("X_CLIENT_ID"),
        redirect_uri=os.environ.get("X_REDIRECT_URI"),
        scope=SCOPES
    )