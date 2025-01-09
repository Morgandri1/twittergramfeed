import re
import requests
from os import environ
from type import Tweet
from urllib.parse import urlparse
from typing import List, Optional, Dict, Any
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

def get_tweet(tweet_id: str):
    req = requests.get(URL + "/tweet", params={"pid": tweet_id}, headers=HEADERS)
    try:
        data = req.json().get("tweet")
        if data.get("note_tweet", False):
            return Tweet(
                tweet_id,
                created_at=data.get("created_at"),
                full_text=data["note_tweet"]["note_tweet_results"]["result"]["text"],
                favorite_count=data.get("favorite_count"),
                retweet_count=data.get("retweet_count"),
                author=data.get("user_id_str"),
                media=[m["media_url_https"] for m in data["entities"].get("media", [])]
            )
            
        return Tweet(
            tweet_id,
            created_at=data.get("created_at"),
            full_text=data["full_text"],
            favorite_count=data.get("favorite_count"),
            retweet_count=data.get("retweet_count"),
            author=data.get("user_id_str"),
            media=[m["media_url_https"] for m in data["entities"]["media"]]
        )
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
        # Why does the count turn fucking negative???
        c = user["result"]["legacy"]["statuses_count"] - counts[uids.index(user["result"]["rest_id"])]
        yield (user["result"]["rest_id"], c * -1 if c < 0 else c)
        
def get_baseline(uids: list[str]):
    if not uids:
        return []
    q = {"users": ",".join(uids)}
    req = requests.get(URL + "/get-users", params=q, headers=HEADERS)
    for user in req.json()["result"]["data"]["users"]:
        c = user["result"]["legacy"]["statuses_count"]
        yield (user["result"]["rest_id"], c)
        
def get_user_info(uid: str):
    q = {"users": uid}
    req = requests.get(URL + "/get-users", params=q, headers=HEADERS)
    try:
        user = req.json()["result"]["data"]["users"][0]["result"]
        return user
    except:
        print(req.json())
        
def parse_tweets(api_response: Dict[str, Any]) -> List[Tweet]:
    all_tweets: List[Tweet] = []

    # Navigate into the JSON where instructions are located
    instructions = api_response["result"]["timeline"]["instructions"]
    # Also handle the possibility of pinned tweets existing outside "instructions"
    pinned_entry = None

    # The instructions block often holds the main timeline entries.
    for instruction in instructions:
        # "TimelineAddEntries" contains the main tweet entries
        if instruction.get("type") == "TimelineAddEntries":
            entries = instruction.get("entries", [])
            for entry in entries:
                maybe_tweet = _extract_tweet_from_entry(entry)
                if maybe_tweet is not None:
                    all_tweets.append(maybe_tweet)

        # Some timelines have pinned tweets in "TimelinePinEntry"
        elif instruction.get("type") == "TimelinePinEntry":
            pinned_entry = instruction.get("entry", {})

    # If there's a pinned tweet entry, handle that as well
    if pinned_entry:
        maybe_tweet = _extract_tweet_from_entry(pinned_entry)
        if maybe_tweet is not None:
            all_tweets.append(maybe_tweet)

    return all_tweets

def _extract_tweet_from_entry(entry: Dict[str, Any]) -> Optional[Tweet]:
    content = entry.get("content")
    if not content:
        return None

    # "TimelineTimelineItem" or "TimelinePinEntry" with an item type of "TimelineTweet" 
    # is where the tweet data resides.
    if content.get("__typename") != "TimelineTimelineItem":
        # Or, if pinned: content.get("__typename") could be "TimelineTimelineItem"
        # but check item content. We'll unify logic below.
        pass

    item_content = content.get("itemContent")
    if not item_content:
        # Could be a module (like a conversation), so we check that too.
        # Some conversation items have "items" -> ... -> "tweet_results"
        if content.get("entryType") == "TimelineTimelineModule":
            module_items = content.get("items", [])
            for mod_item in module_items:
                mod_tweet = _extract_tweet_from_entry(mod_item)
                if mod_tweet is not None:
                    return mod_tweet
        return None

    tweet_data = item_content.get("tweet_results", {}).get("result")
    if not tweet_data:
        return None

    # The “legacy” portion usually has the tweet’s main details.
    legacy = tweet_data.get("legacy")
    if not legacy:
        return None
        
    # Skip replies
    if legacy.get("in_reply_to_user_id"):
        return None

    tweet_id = legacy.get("id_str")
    full_text = legacy.get("full_text", "")
    created_at = legacy.get("created_at", "")
    favorite_count = legacy.get("favorite_count", 0)
    retweet_count = legacy.get("retweet_count", 0)

    # Extract user info
    user_data = tweet_data.get("core", {}) \
                          .get("user_results", {}) \
                          .get("result", {})
    user_legacy = user_data.get("legacy", {})
    screen_name = user_legacy.get("screen_name", "")
    
    # Extract media URLs
    media = legacy.get("entities", {}) \
                  .get("media", [])
    media_urls = [m.get("media_url_https", "") for m in media]

    if legacy.get("is_quote_status"):
        quoted_status = get_tweet(legacy.get("quoted_status_id_str"))
        if not quoted_status:
            full_text = full_text + "\n[Failed to fetch original tweet]"
        else: 
            full_text = full_text + "\nOriginal Tweet:\n" + quoted_status.full_text

    return Tweet(
        tweet_id=tweet_id,
        created_at=created_at,
        full_text=full_text,
        favorite_count=favorite_count,
        retweet_count=retweet_count,
        author=screen_name,
        media=media_urls
    )