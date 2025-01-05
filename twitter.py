import re
import requests
from os import environ
from type import parse_tweets
from urllib.parse import urlparse
from dotenv import load_dotenv

load_dotenv()
HOST = "twitter241.p.rapidapi.com"
KEY = environ.get("TWTTR_API_KEY")
HEADERS = {
    "x-rapidapi-key": KEY,
    "x-rapidapi-host": HOST
}
URL = "https://"+HOST

def get_user_from_handle(handle: str):
    req = requests.get(URL + "/user", params={"username": handle}, headers=HEADERS)
    try:
        return req.json()["result"]["data"]["user"]["result"]
    except KeyError:
        print(req.json())
        return

def get_handle(link: str) -> str:
    """
    Validate if a passed link came from Twitter/X, and if it did, 
    extract the Twitter handle. If the link did not come from Twitter/X, 
    raise a ValueError.
    """
    parsed_url = urlparse(link)
    domain = parsed_url.netloc.lower()

    # Domains that are valid for Twitter/X
    valid_domains = {
        "twitter.com", "www.twitter.com",
        "x.com", "www.x.com"
    }

    if domain not in valid_domains:
        raise ValueError("The provided link is not from Twitter/X.")

    # Example of a typical Twitter/X profile link: https://twitter.com/ElonMusk
    # The first path segment is the handle.
    path_segments = parsed_url.path.strip("/").split("/")
    if not path_segments or not path_segments[0]:
        raise ValueError("No Twitter handle could be extracted from the provided link.")
    
    handle = path_segments[0]

    # A very basic check to ensure the handle has valid characters 
    # (alphanumeric and underscores).
    if not re.match(r"^[A-Za-z0-9_]+$", handle):
        print("The extracted handle contains invalid characters.")
        return link
    
    return handle    

def get_tweets(uid: str, count: int = 20):
    req = requests.get(URL + "/user-tweets", params={"user":uid,"count":count}, headers=HEADERS)
    try:
        return parse_tweets(req.json())
    except KeyError:
        print(req.json())
        return []
    
def get_most_recent_tweet(uid: str):
    req = requests.get(URL + "/user-tweets", params={"user":uid,"count":1}, headers=HEADERS)
    return parse_tweets(req.json())[0]
    
def should_check(uid: str, last: int) -> int:
    q = {"users": uid}
    req = requests.get(URL + "/get-users", params=q, headers=HEADERS)
    user = req.json()["result"]["data"]["users"][0]["result"]
    return user["legacy"]["statuses_count"] - last
    
def should_check_batch(uids: list[str], counts: list[int]):
    if len(uids) != len(counts):
        raise ValueError("uids and counts must be the same length")
    if not uids:
        return []
    q = {"users": ",".join(uids)}
    req = requests.get(URL + "/get-users", params=q, headers=HEADERS)
    for user in req.json()["result"]["data"]["users"]:
        yield (user["result"]["rest_id"], user["result"]["legacy"]["statuses_count"] - counts[uids.index(user["result"]["rest_id"])])
        
def get_user_info(uid: str):
    q = {"users": uid}
    req = requests.get(URL + "/get-users", params=q, headers=HEADERS)
    try:
        user = req.json()["result"]["data"]["users"][0]["result"]
        return user
    except:
        print(req.json())