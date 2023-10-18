# Twitter/X API v2 Connectivity Demo with Python Flask

X has officially launched version 2 of the Twitter API. And despite Elon Musk's threats to discontinue all free access to the API, there **is** a [free tier](https://developer.twitter.com/en/docs/twitter-api/getting-started/about-twitter-api) available. It is quite limited, however. Free users can only access the endpoints to upload media, create tweets (up to 1500 per month), and manage their own user data. They can't view tweets, like tweets, retweet tweets, or reply to tweets. They can't even view their own timeline. The free-tier endpoints also don't support application authentication, so you have to use user authentication, in which the user manually logs into their account and authorizes the app to use it.

(Note that it is still possible to create an automated bot. You will just have to manually authorize it when you first spin it up, and then the bot can continually generate refresh tokens to keep itself logged in. This is a bit of a pain, because it requires database storage of refresh tokens and regular workflow runs to generate new ones. That is, however, outside the scope of this demo.)

Currently, the documentation for API connectivity via the free tier is extremely limited. In the absence of good docs, I've created this demo to illustrate how to connect to the v2 API via a Python Flask application. It's a little complicated, especially if you want to tweet media, because the media upload endpoint still uses OAuth1, whereas the tweet endpoint uses OAuth2. So you have to use both authentication methods in the same app.

## Setup

This demo repo uses the the `poetry` package manager to manage dependencies. If you don't already have `poetry` installed, you can install it with the following curl command:

```bash
curl -sSL https://install.python-poetry.org | python3 -
```

To verify install, use:

```bash
poetry --version
```

Consult the [poetry installation docs](https://python-poetry.org/docs/#installing-with-the-official-installer) for more detailed instructions and troubleshooting, including Powershell installation and manually adding poetry to your system path.

Once poetry is installed on your system, clone this repo. Then navigate to the cloned directory via a command-line terminal. Then, install dependencies with `poetry install`. 

## Configuration

### Getting an API key and secret

Before you can run the app, you need to configure your Twitter API credentials. To do this, you need to [sign up for a Twitter/X developer account](https://developer.twitter.com/). Upon creating your account, you will receive an API key and an API secret. Save these in a secure place. 

### Getting a client token and secret

Next, create a new project and application from the developer dashboard. Then, from the application settings, do your user authentication setup. Give you application "Read and Write" permissions, classify it as a "Web App", and set the Callback URI to "http://127.0.0.1:5000/oauth/callback". Upon saving these settings, you will be provided a client token and secret, which you should save to a secure location.

### Getting an access token and secret

You will also need to generate an access token and secret from your application's "Keys and Tokens" section in the developer dashboard. Save these to a secure location.

### Setting environment variables

An `example.env` file is provided. Copy it to `.env` using the command `cp example.env .env`. Then, edit the `.env` file and add your API key, API secret, client token, client secret, access token, and access secret.

## Usage

To run the application, use `poetry run python tweet.py`. This will start a Flask server on port 5000. You can then navigate to `[http://127.0.0.1:5000](http://127.0.0.1:5000)` in a web browser to view the app.

The app consists of a simple form that allows you to input text and select an image to go with the text. Supply some text and then click "Post Tweet". You will be redirected to Twitter to authenticate with your account. Once you authenticate, you will be redirected back to the app, which will display a link to your posted tweet.

That's it. That's all this app does. It's just a simple demo to illustrate how to connect to the Twitter API v2 via Python Flask.
