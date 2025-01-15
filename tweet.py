import base64
import hashlib
import os
import re
import requests
from dotenv import load_dotenv
from requests_oauthlib import OAuth2Session
from fastapi import FastAPI, Request, Form, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
import tempfile
import atexit
import logging
import shutil
import uuid
from requests_oauthlib import OAuth1

# Configure logging
logger = logging.getLogger("uvicorn.error")
logger.setLevel(logging.INFO)

# Load environment variables from a .env file
load_dotenv()

# FastAPI application
app = FastAPI()

# Use Jinja2 templates (ensure you have a folder named "templates" with your .html files)
templates = Jinja2Templates(directory="templates")

# Define the scopes needed for the OAuth2 flow
scopes = ["tweet.read", "users.read", "tweet.write", "media.write"]

# Generate a code verifier and its corresponding challenge for the OAuth2 flow
code_verifier: bytes = base64.urlsafe_b64encode(s=os.urandom(30))
code_verifier_str: str = code_verifier.decode(encoding="utf-8")
code_verifier_str = re.sub(pattern="[^a-zA-Z0-9]+", repl="", string=code_verifier_str)
code_challenge: bytes = hashlib.sha256(string=code_verifier_str.encode(encoding="utf-8")).digest()
code_challenge_str: str = base64.urlsafe_b64encode(s=code_challenge).decode(encoding="utf-8")
code_challenge_str = code_challenge_str.replace("=", "")

# Global dictionary to map an OAuth 'state' to the data needed in callback
oauth_states = {}

# In-memory path for the temp directory
temp_dir_path = None

def get_temp_dir():
    global temp_dir_path
    if not temp_dir_path:
        temp_dir_path = tempfile.mkdtemp()
    return temp_dir_path

def cleanup_temp_dir():
    global temp_dir_path
    if temp_dir_path and os.path.exists(temp_dir_path):
        shutil.rmtree(temp_dir_path)
        temp_dir_path = None

atexit.register(cleanup_temp_dir)

def create_media_payload(path) -> dict[str, dict[str, list[str]]]:
    """
    Upload media using OAuth1 authentication and return a payload containing the media ID.
    """
    auth = OAuth1(
        os.environ.get("X_API_KEY"),
        os.environ.get("X_API_SECRET"),
        os.environ.get("X_ACCESS_TOKEN"),
        os.environ.get("X_ACCESS_TOKEN_SECRET")
    )
    
    upload_url = "https://upload.twitter.com/1.1/media/upload.json"
    try:
        with open(path, "rb") as file:
            files = {"media": file}
            response = requests.post(upload_url, auth=auth, files=files)
            response.raise_for_status()
            media_id = response.json().get("media_id_string")
            if media_id:
                return {"media": {"media_ids": [media_id]}}
    except Exception as e:
        logging.error(f"Error uploading media: {e}")
    
    return {"media": {"media_ids": []}}

def create_text_payload(text) -> dict[str, str]:
    return {"text": text}

def create_tweet_payload(text, media_path=None) -> dict:
    text_payload = create_text_payload(text=text)
    if media_path is None:
        return text_payload
    media_payload = create_media_payload(path=media_path)
    return {**text_payload, **media_payload}


# Function to post a tweet using the provided text and media
def post_tweet(text, media_path=None, new_token=None) -> requests.Response:
    tweet_payload = create_tweet_payload(text=text, media_path=media_path)
    # Send a POST request to Twitter's API to post the tweet
    return requests.request(
        method="POST",
        url="https://api.x.com/2/tweets",
        json=tweet_payload,
        headers={
            "Authorization": f"Bearer {new_token['access_token']}",
            "Content-Type": "application/json",
        },
    )

@app.get("/", response_class=HTMLResponse)
def show_form(request: Request):
    """
    Serve a basic form (index.html) for posting tweets.
    """
    return templates.TemplateResponse("index.html", {"request": request})

@app.post("/", response_class=HTMLResponse)
async def start_oauth(
    request: Request,
    text: str = Form(...),
    image: UploadFile = File(None)
):
    """
    Handle the form submission:
      - Save text and image.
      - Begin OAuth flow with Twitter.
    """
    # Save the text and optional image in a newly generated state
    state = str(uuid.uuid4())
    data_to_store = {"text": text, "image_path": None}

    if image and image.filename:
        temp_dir = get_temp_dir()
        image_path = os.path.join(temp_dir, image.filename)
        with open(image_path, "wb") as buffer:
            buffer.write(await image.read())
        data_to_store["image_path"] = image_path

    # Create an OAuth2Session and store relevant data
    twitter_session = OAuth2Session(
        client_id=os.environ.get("X_CLIENT_ID"),
        redirect_uri=os.environ.get("X_REDIRECT_URI"),
        scope=scopes
    )
    authorization_url, oauth_state = twitter_session.authorization_url(
        "https://twitter.com/i/oauth2/authorize",
        code_challenge=code_challenge,
        code_challenge_method="S256"
    )

    # Store everything in our global map keyed by the state from the library
    oauth_states[oauth_state] = {
        "text": data_to_store["text"],
        "image_path": data_to_store["image_path"],
        "twitter_session": twitter_session
    }

    # Redirect to Twitter's OAuth page
    return RedirectResponse(authorization_url)

@app.get("/oauth/callback", response_class=HTMLResponse)
def callback(request: Request, code: str, state: str):
    """
    Callback route after user authenticates with Twitter.
      - Exchange code for token.
      - Post the tweet.
    """
    # Retrieve stored info for this state
    if state not in oauth_states:
        return HTMLResponse(content="Invalid state or session has expired.", status_code=400)

    stored_data = oauth_states[state]
    text = stored_data["text"]
    image_path = stored_data["image_path"]
    twitter_session = stored_data["twitter_session"]

    # Exchange code for token
    token = twitter_session.fetch_token(
        token_url="https://api.x.com/2/oauth2/token",
        client_secret=os.environ.get("X_CLIENT_SECRET"),
        code_verifier=code_verifier,
        code=code
    )

    # Post the tweet
    response = post_tweet(text=text, media_path=image_path, new_token=token)
    
    message = None
    if response.ok:
        message = "Tweet posted successfully!"
    else:
        try:
            error_details = response.json()
            if 'errors' in error_details:
                # Handle Twitter API specific error format
                error_messages = [error['message'] for error in error_details['errors']]
                message = f"Twitter API Error: {'; '.join(error_messages)}"
            else:
                # Handle general API errors
                status_code = response.status_code
                if status_code == 429:
                    message = "Rate limit exceeded. Please wait a few minutes and try again."
                else:
                    # Get the most meaningful error detail
                    detail = error_details.get('detail') or error_details.get('title') or response.reason
                    message = f"Error ({status_code}): {detail}"
        except ValueError:
            message = f"Error ({response.status_code}): {response.reason}"
        
        logger.error(f"Failed to post tweet: {response.status_code} {response.reason} - {response.text}")

    # Attempt to extract the short t.co or x.com link from the returned tweet text
    tweet_text = response.json().get("data", {}).get("text", "")
    tweet_link_match = re.search(r"https://(?:t\.co|x\.com)/\w+", tweet_text)
    tweet_link = tweet_link_match.group(0) if tweet_link_match else None

    # Remove state data to avoid re-use or memory leaks
    del oauth_states[state]

    return templates.TemplateResponse(
        "index.html",
        {
            "request": request,
            "tweet_link": tweet_link,
            "message": message
        }
    )

# To run this app:
#   uvicorn tweet:app --host 0.0.0.0 --port 5000
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=5000)