import os
import json
import requests
from dotenv import load_dotenv
import secrets
import base64
import hashlib
from urllib.parse import urlencode, parse_qs
from http.server import BaseHTTPRequestHandler, HTTPServer
import threading

load_dotenv()

# --- Configuration ---
CLIENT_ID = os.environ.get("X_CLIENT_ID")
CLIENT_SECRET = os.environ.get("X_CLIENT_SECRET")
REDIRECT_URI = "http://127.0.0.1:5000/oauth/callback"  # Replace with your actual redirect URI
SCOPES = "tweet.read tweet.write users.read offline.access media.write" # Add other scopes as needed
AUTHORIZATION_URL = "https://twitter.com/i/oauth2/authorize"
TOKEN_URL = "https://api.x.com/2/oauth2/token"
TWEET_URL = "https://api.x.com/2/tweets"
MEDIA_URL = "https://api.twitter.com/2/media/upload"

# --- Helper Functions ---
def generate_code_verifier():
    """Generates a random code verifier string."""
    return secrets.token_urlsafe(100)

def generate_code_challenge(code_verifier):
    """Generates the code challenge from the code verifier."""
    code_challenge = hashlib.sha256(code_verifier.encode()).digest()
    code_challenge = base64.urlsafe_b64encode(code_challenge).decode().rstrip("=")
    return code_challenge

def create_authorization_url(code_challenge, state):
    """Constructs the authorization URL."""
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{AUTHORIZATION_URL}?{urlencode(params)}"

def get_access_token(auth_code, code_verifier):
    """Exchanges the authorization code for an access token."""
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "code": auth_code,
        "grant_type": "authorization_code",
        "client_id": CLIENT_ID,
        "redirect_uri": REDIRECT_URI,
        "code_verifier": code_verifier,
    }
    if CLIENT_SECRET:
        # If it's a confidential client, use basic auth
        auth_str = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
        headers["Authorization"] = f"Basic {auth_str}"
        del data["client_id"] # client_id is not needed in the body for confidential clients
    response = requests.post(TOKEN_URL, headers=headers, data=data)
    response.raise_for_status()  # Raise an exception for bad status codes
    return response.json()

def refresh_access_token(refresh_token):
    """Refreshes the access token using the refresh token."""
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    data = {
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
        "client_id": CLIENT_ID,
    }
    if CLIENT_SECRET:
        # If it's a confidential client, use basic auth
        auth_str = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
        headers["Authorization"] = f"Basic {auth_str}"
        del data["client_id"] # client_id is not needed in the body for confidential clients
    response = requests.post(TOKEN_URL, headers=headers, data=data)
    response.raise_for_status()
    return response.json()

def post_tweet(access_token, text):
    """Posts a tweet using the provided access token."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    payload = {"text": text}
    response = requests.post(TWEET_URL, headers=headers, json=payload)
    response.raise_for_status()
    return response.json()

def upload_media(access_token, file_path, media_category="tweet_image"):
    """Uploads media using the provided access token."""
    total_bytes = os.path.getsize(file_path)
    file_extension = file_path.split(".")[-1]
    mime_type = f"image/{file_extension}"
    headers = {
        "Authorization": f"Bearer {access_token}",
    }
    # INIT
    params = {
        "media_category": media_category,
        "total_bytes": total_bytes,
        "media_type": mime_type,
        "command": "INIT"
    }
    response = requests.post(MEDIA_URL, headers=headers, params=params)
    response.raise_for_status()
    media_id = response.json()["media_id"]

    # APPEND in chunks
    with open(file_path, "rb") as f:
        chunk_size = 1024 * 1024  # 1MB chunks
        segment_index = 0
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            params = {
                "command": "APPEND",
                "media_id": media_id,
                "segment_index": segment_index
            }
            files = {"media": chunk}
            response = requests.post(MEDIA_URL, headers=headers, params=params, files=files)
            response.raise_for_status()
            segment_index += 1

    # FINALIZE
    params = {
        "command": "FINALIZE",
        "media_id": media_id
    }
    response = requests.post(MEDIA_URL, headers=headers, params=params)
    response.raise_for_status()
    return media_id

def post_tweet_with_media(access_token, text, media_ids):
    """Posts a tweet with media using the provided access token."""
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    payload = {"text": text, "media": {"media_ids": media_ids}}
    response = requests.post(TWEET_URL, headers=headers, json=payload)
    response.raise_for_status()
    return response.json()

# --- HTTP Server Handler ---
class OAuthCallbackHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/oauth/callback'):
            query_params = parse_qs(self.path[self.path.find('?') + 1:])
            auth_code = query_params.get('code', [None])[0]
            returned_state = query_params.get('state', [None])[0]
            
            if auth_code and returned_state:
                self.server.auth_code = auth_code
                self.server.returned_state = returned_state
                self.send_response(200)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(b"<html><head><title>Authorization Successful</title></head><body><h1>Authorization Successful</h1><p>You can close this window.</p></body></html>")
            else:
                self.send_response(400)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                self.wfile.write(b"<html><head><title>Authorization Failed</title></head><body><h1>Authorization Failed</h1><p>Invalid parameters.</p></body></html>")
        else:
            self.send_response(404)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(b"<html><head><title>Not Found</title></head><body><h1>Not Found</h1></body></html>")

# --- Main Flow ---
if __name__ == "__main__":
    # 1. Generate PKCE parameters
    code_verifier = generate_code_verifier()
    code_challenge = generate_code_challenge(code_verifier)
    state = secrets.token_urlsafe(16)

    # 2. Construct the authorization URL
    auth_url = create_authorization_url(code_challenge, state)
    print(f"Please visit this URL to authorize the app:\n{auth_url}")

    # 3. Start the HTTP server in a separate thread
    server_address = ('127.0.0.1', 5000)
    httpd = HTTPServer(server_address, OAuthCallbackHandler)
    httpd.auth_code = None
    httpd.returned_state = None
    server_thread = threading.Thread(target=httpd.serve_forever)
    server_thread.daemon = True
    server_thread.start()

    # 4. Wait for the authorization code
    while httpd.auth_code is None:
        pass
    auth_code = httpd.auth_code
    returned_state = httpd.returned_state
    httpd.shutdown()
    print("Authorization code received.")

    if returned_state != state:
        raise Exception("State does not match")

    # 5. Exchange the authorization code for an access token
    try:
        token_response = get_access_token(auth_code, code_verifier)
        access_token = token_response["access_token"]
        refresh_token = token_response.get("refresh_token")
        print("Successfully obtained access token.")
    except requests.exceptions.RequestException as e:
        print(f"Error obtaining access token: {e}")
        exit()

    # 6. (Optional) Refresh the access token if needed
    if refresh_token:
        try:
            refreshed_token_response = refresh_access_token(refresh_token)
            access_token = refreshed_token_response["access_token"]
            refresh_token = refreshed_token_response.get("refresh_token")
            print("Successfully refreshed access token.")
        except requests.exceptions.RequestException as e:
            print(f"Error refreshing access token: {e}")
            exit()

    # 7. Post a tweet
    # try:
    #     tweet_text = "Hello world! This is a test tweet using OAuth 2.0."
    #     tweet_response = post_tweet(access_token, tweet_text)
    #     print(f"Tweet posted successfully: {tweet_response}")
    # except requests.exceptions.RequestException as e:
    #     print(f"Error posting tweet: {e}")

    # 8. Upload media
    try:
        media_id = upload_media(access_token, "test.png") # Replace with your actual file path
        print(f"Media uploaded successfully: {media_id}")
    except requests.exceptions.RequestException as e:
        print(f"Error uploading media: {e}")
        exit()

    # 9. Post a tweet with media
    try:
        tweet_text = "Hello world! This is a test tweet with media using OAuth 2.0."
        tweet_response = post_tweet_with_media(access_token, tweet_text, [media_id])
        print(f"Tweet with media posted successfully: {tweet_response}")
    except requests.exceptions.RequestException as e:
        print(f"Error posting tweet with media: {e}")