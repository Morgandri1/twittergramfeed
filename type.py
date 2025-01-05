from dataclasses import dataclass
from typing import List, Optional, Dict, Any
from datetime import datetime

@dataclass
class User:
    uid: str
    username: str
    added_by: str
    last_count: str
    last_checked: datetime
    added: datetime
    active: bool

@dataclass
class Tweet:
    tweet_id: str
    created_at: str
    full_text: str
    favorite_count: int
    retweet_count: int
    author: str
    media: List[str]

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

    return Tweet(
        tweet_id=tweet_id,
        created_at=created_at,
        full_text=full_text,
        favorite_count=favorite_count,
        retweet_count=retweet_count,
        author=screen_name,
        media=media_urls
    )