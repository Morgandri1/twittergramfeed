from dataclasses import dataclass
from datetime import datetime
from typing import List

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