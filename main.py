import os
import re
import logging
import uuid
from typing import Dict, Optional, Any
from dotenv import load_dotenv
from requests_oauthlib import OAuth2Session
from fastapi import FastAPI, Request, Form, File, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from requests import Response
from starlette.templating import _TemplateResponse

from x_twitter_api_v2_demo.auth import (
    generate_code_verifier,
    generate_code_challenge,
    create_oauth2_session,
)
from x_twitter_api_v2_demo.tweet import post_tweet
from x_twitter_api_v2_demo.utils import get_temp_dir

# Configure logging
logger = logging.getLogger("uvicorn.error")
logger.setLevel(logging.INFO)

# Load environment variables
load_dotenv()

# FastAPI application
app = FastAPI()
templates = Jinja2Templates(directory="templates")

# Global state
oauth_states: Dict[str, Dict[str, Any]] = {}
code_verifier: str = generate_code_verifier()
code_challenge: str = generate_code_challenge(code_verifier)

@app.get("/", response_class=HTMLResponse)
def show_form(request: Request) -> _TemplateResponse:
    """
    Serve a basic form (index.html) for posting tweets.
    """
    return templates.TemplateResponse("index.html", {"request": request})


@app.post("/", response_class=HTMLResponse)
async def start_oauth(
    request: Request,
    text: str = Form(...),
    image: Optional[UploadFile] = File(None)
) -> RedirectResponse:
    """
    Handle the form submission:
      - Save text and image.
      - Begin OAuth flow with Twitter.
    """
    # Save the text and optional image in a newly generated state
    state = str(uuid.uuid4())
    data_to_store: Dict[str, Optional[str]] = {"text": text, "image_path": None}

    if image and image.filename:
        temp_dir = get_temp_dir()
        image_path = os.path.join(temp_dir, image.filename)
        with open(image_path, "wb") as buffer:
            buffer.write(await image.read())
        data_to_store["image_path"] = image_path

    # Create an OAuth2Session and store relevant data
    twitter_session: OAuth2Session = create_oauth2_session()
    logger.info("Starting OAuth2 flow with Twitter")
    assert code_challenge is not None, "Code challenge is not set"
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
def callback(request: Request, code: str, state: str) -> _TemplateResponse:
    """
    Callback route after user authenticates with Twitter.
      - Exchange code for token.
      - Post the tweet.
    """
    # Retrieve stored info for this state
    if state not in oauth_states:
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "message": "Invalid state or session has expired."
            }
        )

    stored_data = oauth_states[state]
    text: str = stored_data["text"]
    image_path: Optional[str] = stored_data["image_path"]
    twitter_session: OAuth2Session = stored_data["twitter_session"]

    # Exchange code for token
    assert code_verifier is not None, "Code verifier is not set"
    token: Dict[str, Any] = twitter_session.fetch_token(
        token_url="https://api.x.com/2/oauth2/token",
        client_id=os.environ.get("X_CLIENT_ID"),
        client_secret=os.environ.get("X_CLIENT_SECRET"),
        code_verifier=code_verifier,
        code=code
    )

    # Post the tweet
    response: Response = post_tweet(text=text, media_path=image_path, new_token=token)
    
    message: Optional[str] = None
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
    tweet_link: Optional[str] = tweet_link_match.group(0) if tweet_link_match else None

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