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
                media=[m["media_url_https"] for m in data["entities"].get("media", [])],
                sort_index=data.get("sort_index")
            )
            
        return Tweet(
            tweet_id,
            created_at=data.get("created_at"),
            full_text=data["full_text"],
            favorite_count=data.get("favorite_count"),
            retweet_count=data.get("retweet_count"),
            author=data.get("user_id_str"),
            media=[m["media_url_https"] for m in data["entities"].get("media", [])],
            sort_index=data.get("sort_index")
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
        
def parse_tweets(api_response: Dict[str, Any]) -> (List[Tweet], int):
    """
    Parses the API response to return the newest tweets from a user, ignoring older pinned tweets.
    
    Args:
        api_response (Dict[str, Any]): The JSON/dictionary response from Twitter’s API.
    
    Returns:
        (tweets, skipped_count):
            tweets (List[Tweet]): The list of parsed Tweet objects, newest first.
            skipped_count (int): How many tweets were skipped (e.g., invalid entries or older pinned).
    """
    # The main timeline instructions
    instructions = api_response["result"]["timeline"]["instructions"]

    timeline_tweets: List[Tweet] = []
    pinned_tweet: Optional[Tweet] = None
    pinned_sort_index: Optional[str] = None

    # Track how many entries we skip
    skipped_count = 0

    # 1) For “TimelineAddEntries,” parse tweets from each entry
    for instruction in instructions:
        if instruction.get("type") == "TimelineAddEntries":
            for entry in instruction.get("entries", []):
                maybe_tweet = _extract_tweet_from_entry(entry)
                if maybe_tweet is not None:
                    timeline_tweets.append(maybe_tweet)
                else:
                    skipped_count += 1
        # 2) For “TimelinePinEntry,” handle pinned tweet (if we recognize it as the newest)
        elif instruction.get("type") == "TimelinePinEntry":
            pinned_entry = instruction.get("entry")
            if pinned_entry:
                pinned_sort_index = pinned_entry.get("sortIndex", "")
                maybe_tweet = _extract_tweet_from_entry(pinned_entry)
                if maybe_tweet is not None:
                    pinned_tweet = maybe_tweet
                else:
                    skipped_count += 1

    # 3) If we found no normal timeline tweets at all, we can just return now
    if not timeline_tweets and not pinned_tweet:
        return ([], skipped_count)

    # Determine the max sort_index among normal timeline tweets
    max_sort_index = max((t.sort_index for t in timeline_tweets), default="")

    # 4) Only add pinned_tweet if its sortIndex is >= the highest sortIndex of normal tweets
    if pinned_tweet and pinned_sort_index and pinned_sort_index >= max_sort_index:
        timeline_tweets.append(pinned_tweet)
    elif pinned_tweet:
        # We skip pinned tweet if it’s not the newest
        skipped_count += 1

    # 5) Sort tweets by sort_index descending so the newest tweets come first
    timeline_tweets.sort(key=lambda t: t.sort_index, reverse=True)

    return (timeline_tweets, skipped_count)

def _extract_tweet_from_entry(entry: Dict[str, Any]) -> Optional[Tweet]:
    """
    Helper function to parse a single entry into a Tweet. Returns None if invalid or not a tweet.
    """
    sort_index = entry.get("sortIndex", "")

    content = entry.get("content", {})
    entry_type = content.get("entryType")

    # Some entries are “TimelineTimelineModule” (like a conversation), containing multiple “items.”
    if entry_type == "TimelineTimelineModule":
        module_items = content.get("items", [])
        # Return first valid tweet from the module. If you expect multiple tweets, adapt accordingly.
        for mod_item in module_items:
            mod_tweet = _extract_tweet_from_entry(mod_item)
            if mod_tweet is not None:
                # Inherit sort_index if the module itself had one
                if sort_index and not mod_tweet.sort_index:
                    mod_tweet.sort_index = sort_index
                return mod_tweet
        return None

    # If it’s a single tweet entry
    if entry_type == "TimelineTimelineItem":
        item_content = content.get("itemContent", {})
        tweet_data = item_content.get("tweet_results", {}).get("result")
        if not tweet_data:
            return None

        legacy = tweet_data.get("legacy")
        if not legacy:
            return None

        tweet_id = legacy.get("id_str", "")
        created_at = legacy.get("created_at", "")
        full_text = legacy.get("full_text", "")
        favorite_count = legacy.get("favorite_count", 0)
        retweet_count = legacy.get("retweet_count", 0)

        # Extract user info
        core_user_data = tweet_data.get("core", {}).get("user_results", {}).get("result", {})
        user_legacy = core_user_data.get("legacy", {})
        user_id = user_legacy.get("id_str", "")
        screen_name = user_legacy.get("screen_name", "")
        name = user_legacy.get("name", "")
        description = user_legacy.get("description", "")
        statuses_count = user_legacy.get("statuses_count", 0)

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
            sort_index=sort_index,
            media=media_urls
        )

    return None