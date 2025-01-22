import os
import re
import logging
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
from x_twitter_api_v2_demo.session import save_session, load_session

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
current_session: Optional[OAuth2Session] = None
current_token: Optional[Dict[str, Any]] = None

# Try to load existing session
current_session, current_token = load_session()
if current_session and current_token:
    logger.info("Loaded existing Twitter session with token expiry: %s", current_token.get("expires_at"))
else:
    logger.info("No existing Twitter session found")

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
) -> RedirectResponse | _TemplateResponse:
    """
    Handle the form submission:
      - Try to use saved session if available
      - Otherwise begin OAuth flow with Twitter
    """
    global current_session, current_token
    
    logger.info("Processing tweet request: text='%s', has_image=%s", text, bool(image))
    
    # Process image if provided
    image_path = None
    if image and image.filename:
        temp_dir = get_temp_dir()
        image_path = os.path.join(temp_dir, image.filename)
        with open(image_path, "wb") as buffer:
            buffer.write(await image.read())
        logger.info("Saved uploaded image to: %s", image_path)

    # If we have a saved session, try to use it
    if current_session and current_token:
        logger.info("Attempting to use saved session (token expires at: %s)", current_token.get("expires_at"))
        response = post_tweet(text=text, media_path=image_path, new_token=current_token)
        
        if response.ok:
            logger.info("Successfully posted tweet using saved session")
            # Extract tweet link on success
            tweet_text = response.json().get("data", {}).get("text", "")
            tweet_link_match = re.search(r"https://(?:t\.co|x\.com)/\w+", tweet_text)
            tweet_link = tweet_link_match.group(0) if tweet_link_match else None
            return templates.TemplateResponse(
                "index.html",
                {
                    "request": request,
                    "tweet_link": tweet_link,
                    "message": "Tweet posted successfully!"
                }
            )
        else:
            # Clear invalid session and proceed with new auth
            logger.warning(
                "Saved session failed with status %d: %s", 
                response.status_code, 
                response.text
            )
            current_session = None
            current_token = None

    # Start new OAuth flow
    code_verifier = generate_code_verifier()
    code_challenge = generate_code_challenge(code_verifier)
    twitter_session = create_oauth2_session()
    
    logger.info("Starting new OAuth2 flow with Twitter")
    authorization_url, oauth_state = twitter_session.authorization_url(
        "https://twitter.com/i/oauth2/authorize",
        code_challenge=code_challenge,
        code_challenge_method="S256"
    )

    # Store everything needed for the callback
    oauth_states[oauth_state] = {
        "text": text,
        "image_path": image_path,
        "twitter_session": twitter_session,
        "code_verifier": code_verifier
    }
    logger.info("Stored OAuth state: %s", oauth_state)

    # Redirect to Twitter's OAuth page
    logger.info("Redirecting to Twitter auth URL: %s", authorization_url)
    return RedirectResponse(authorization_url)

@app.get("/oauth/callback", response_class=HTMLResponse)
def callback(request: Request, code: str, state: str) -> _TemplateResponse:
    """
    Callback route after user authenticates with Twitter.
      - Exchange code for token.
      - Post the tweet.
    """
    global current_session, current_token
    
    logger.info("Received OAuth callback with state: %s", state)
    
    # Retrieve stored info for this state
    if state not in oauth_states:
        logger.error("Invalid OAuth state received: %s", state)
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
    code_verifier: str = stored_data["code_verifier"]

    # Exchange code for token
    logger.info("Exchanging OAuth code for token")
    try:
        token: Dict[str, Any] = twitter_session.fetch_token(
            token_url="https://api.x.com/2/oauth2/token",
            client_id=os.environ.get("X_CLIENT_ID"),
            client_secret=os.environ.get("X_CLIENT_SECRET"),
            code_verifier=code_verifier,
            code=code
        )
        logger.info("Successfully obtained token, expires at: %s", token.get("expires_at"))
    except Exception as e:
        logger.error("Failed to fetch token: %s", str(e))
        return templates.TemplateResponse(
            "index.html",
            {
                "request": request,
                "message": f"Failed to authenticate with Twitter: {str(e)}"
            }
        )

    # Update current session and save it
    current_session = twitter_session
    current_token = token
    save_session(twitter_session, token)
    logger.info("Saved new session to disk")

    # Post the tweet
    logger.info("Attempting to post tweet with new token")
    response: Response = post_tweet(text=text, media_path=image_path, new_token=token)
    
    message: Optional[str] = None
    if response.ok:
        logger.info("Successfully posted tweet")
        message = "Tweet posted successfully!"
    else:
        try:
            error_details = response.json()
            if 'errors' in error_details:
                # Handle Twitter API specific error format
                error_messages = [error['message'] for error in error_details['errors']]
                message = f"Twitter API Error: {'; '.join(error_messages)}"
                logger.error("Twitter API errors: %s", error_messages)
            else:
                # Handle general API errors
                status_code = response.status_code
                if status_code == 429:
                    message = "Rate limit exceeded. Please wait a few minutes and try again."
                    logger.error("Rate limit exceeded")
                else:
                    # Get the most meaningful error detail
                    detail = error_details.get('detail') or error_details.get('title') or response.reason
                    message = f"Error ({status_code}): {detail}"
                    logger.error("API error %d: %s", status_code, detail)
        except ValueError:
            message = f"Error ({response.status_code}): {response.reason}"
            logger.error("Failed to parse error response: %s", response.text)
        
        logger.error("Failed to post tweet: %s %s - %s", 
                    response.status_code, response.reason, response.text)

    # Attempt to extract the short t.co or x.com link from the returned tweet text
    tweet_text = response.json().get("data", {}).get("text", "")
    tweet_link_match = re.search(r"https://(?:t\.co|x\.com)/\w+", tweet_text)
    tweet_link: Optional[str] = tweet_link_match.group(0) if tweet_link_match else None
    if tweet_link:
        logger.info("Tweet URL: %s", tweet_link)

    # Remove state data to avoid re-use or memory leaks
    del oauth_states[state]
    logger.info("Cleaned up OAuth state")

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