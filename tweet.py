import base64
import hashlib
import os
import re
import requests
import tweepy
from dotenv import load_dotenv
from requests_oauthlib import OAuth2Session
from flask import Flask, request, redirect, session, render_template, flash

# Initialize the Flask application
app = Flask(import_name=__name__)
# Set a random secret key for the Flask session
app.secret_key = os.urandom(50)

# Load environment variables from a .env file
load_dotenv()
# Retrieve necessary credentials and settings from environment variables
client_id = os.environ.get("X_CLIENT_ID")
client_secret = os.environ.get("X_CLIENT_SECRET")
auth_url = "https://twitter.com/i/oauth2/authorize"
token_url = "https://api.twitter.com/2/oauth2/token"
redirect_uri = os.environ.get("X_REDIRECT_URI")
text_to_tweet = os.environ.get("TEXT_TO_TWEET")
media_path_to_tweet = os.environ.get("MEDIA_PATH_TO_TWEET")

# Define the scopes needed for the OAuth2 flow
scopes = ["tweet.read", "users.read", "tweet.write"]

# Generate a code verifier and its corresponding challenge for the OAuth2 flow
code_verifier = base64.urlsafe_b64encode(s=os.urandom(30)).decode(encoding="utf-8")
code_verifier = re.sub(pattern="[^a-zA-Z0-9]+", repl="", string=code_verifier)
code_challenge = hashlib.sha256(string=code_verifier.encode(encoding="utf-8")).digest()
code_challenge = base64.urlsafe_b64encode(s=code_challenge).decode(encoding="utf-8")
code_challenge = code_challenge.replace("=", "")


# Function to upload media and return its media ID
def create_media_payload(path) -> dict[str, dict[str, list[str]]]:
    # Authenticate with Twitter using Tweepy and OAuth1
    tweepy_auth = tweepy.OAuth1UserHandler(
        consumer_key="{}".format(os.environ.get("X_API_KEY")),
        consumer_secret="{}".format(os.environ.get("X_API_SECRET")),
        access_token="{}".format(os.environ.get("X_ACCESS_TOKEN")),
        access_token_secret="{}".format(os.environ.get("X_ACCESS_TOKEN_SECRET")),
    )
    tweepy_api = tweepy.API(auth=tweepy_auth)
    # Upload the image to Twitter
    post = tweepy_api.simple_upload(filename=path)
    # Extract the media ID from the response
    text = str(object=post)
    media_id = re.search(pattern="media_id=(.+?),", string=text).group(1)
    # Return the media ID in the required payload format
    media_payload = {"media": {"media_ids": ["{}".format(media_id)]}}
    return media_payload


# Function to create a text payload for our request
def create_text_payload(text) -> dict[str, str]:
    text_payload = {"text": text}
    return text_payload


# Function to create a combined payload with both text and media for the tweet
def create_tweet_payload(text, media_path=None) -> dict[str, dict[str, list[str]]]:
    text_payload = create_text_payload(text=text)
    if media_path is None:
        tweet_payload = text_payload
    else:
        media_payload = create_media_payload(path=media_path)
        tweet_payload = {**text_payload, **media_payload}
    return tweet_payload


# Function to post a tweet using the provided text and media
def post_tweet(text, media_path=None, new_token=None) -> requests.Response:
    tweet_payload = create_tweet_payload(text=text, media_path=media_path)
    # Send a POST request to Twitter's API to post the tweet
    return requests.request(
        method="POST",
        url="https://api.twitter.com/2/tweets",
        json=tweet_payload,
        headers={
            "Authorization": "Bearer {}".format(new_token["access_token"]),
            "Content-Type": "application/json",
        },
    )


# Route to handle the initial step of the OAuth2 flow and tweet posting form
@app.route(rule="/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        # Store the tweet's text and image path in the Flask session
        session["text"] = request.form.get(key="text")
        image = request.files["image"]
        image_path = os.path.join("temp", image.filename)
        image.save(dst=image_path)
        session["image_path"] = image_path

        # Start the OAuth2 flow to authenticate with Twitter
        global twitter
        twitter = OAuth2Session(client_id=client_id, redirect_uri=redirect_uri, scope=scopes)
        authorization_url, state = twitter.authorization_url(
            url=auth_url, code_challenge=code_challenge, code_challenge_method="S256"
        )
        session["oauth_state"] = state
        # Redirect the user to Twitter's authentication page
        return redirect(location=authorization_url)

    # If the request method is GET, render the index.html template
    return render_template(template_name_or_list="index.html")


# Route to handle the callback from Twitter after successful OAuth2 authentication
@app.route(rule="/oauth/callback", methods=["GET"])
def callback() -> requests.Response:
    text = session.get("text", default=text_to_tweet)
    image_path = session.get("image_path", default=media_path_to_tweet)

    # Retrieve the code from the callback URL's query parameters
    code = request.args.get(key="code")
    # Fetch the OAuth2 token using the provided code
    token = twitter.fetch_token(
        token_url=token_url,
        client_secret=client_secret,
        code_verifier=code_verifier,
        code=code,
    )
    
    # Post the tweet using the provided text and image
    response = post_tweet(text=text, media_path=image_path, new_token=token)
    
    # Delete any uploaded image from the server
    if os.path.exists(path=image_path):
        os.remove(path=image_path)

    # Extract the tweet's link from the response and display it to the user
    tweet_text = response.json().get("data", {}).get("text", "")
    tweet_link_match = re.search(pattern=r"https://t\.co/\w+", string=tweet_text)
    tweet_link = tweet_link_match.group(0) if tweet_link_match else None

    return render_template(template_name_or_list="index.html", tweet_link=tweet_link)


# Run the Flask application
if __name__ == "__main__":
    app.run()