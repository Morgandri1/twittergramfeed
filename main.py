from os import environ

from database import Bot as Database, add_watched_account, SessionLocal
from twitter import should_check_batch, get_tweets, get_user_from_handle, get_handle, get_baseline
from dotenv import load_dotenv
from sched import scheduler
from time import sleep, time
from telebot import TeleBot
from threading import Thread
from sqlalchemy import func
from dateutil.parser import parse as parse_date
from datetime import datetime, timezone, time as dTime, date

def ensure_datetime(d):
    """Convert a date (or datetime) into a datetime with time.min if needed."""
    if isinstance(d, datetime):
        return d
    elif isinstance(d, date):
        return datetime.combine(d, dTime.min)
    return None
    
def to_utc_aware(dt: date | datetime) -> datetime:
    """
    Convert a date or datetime into an aware datetime in UTC.
    - If dt is a date (with no time), combine it with the minimal time.
    - If dt is a naive datetime, replace tzinfo with UTC.
    - If dt is already offset-aware, convert it to UTC.
    """
    if isinstance(dt, date) and not isinstance(dt, datetime):
        # Convert bare date to a naive datetime (midnight)
        dt = datetime.combine(dt, dTime.min)
    # Now dt is definitely a datetime object
    if dt.tzinfo is None:
        # Naive -> treat as UTC
        return dt.replace(tzinfo=timezone.utc)
    else:
        # Aware -> convert to UTC
        return dt.astimezone(timezone.utc)

s = scheduler(time, sleep)
load_dotenv()
bot = TeleBot(environ.get("TELEGRAM_TOKEN", ""))

def check_accounts():
    try:
        session = SessionLocal()
        accounts = session.query(Database).filter(Database.active == True).all()
    
        for acc in accounts:
            # Decide how many new tweets we might fetch
            (account_uid, difference) = next(
                should_check_batch([acc.uid], [float(acc.last_count)]),
                (None, 0)
            )
            if not account_uid or difference <= 0:
                continue  # Nothing new; skip
    
            # Fetch tweets (cap difference in case it is huge)
            tweets, ignored = get_tweets(account_uid, min(difference, 20))
            if not tweets:
                continue
    
            # For each fetched tweet, compare creation time to acc.last_checked:
            new_tweets_to_send = []
            acc_last_checked_dt = ensure_datetime(acc.last_checked)  # Also a datetime
            for tweet in tweets:
                tweet_created = parse_date(tweet.created_at)   # Usually an offset-aware dt
                acc_last_checked_dt = acc.last_checked            # Possibly naive
                if not acc_last_checked_dt:
                    acc_last_checked_dt = datetime.utcnow()       # or a default
        
                # Convert BOTH to UTC-aware
                tweet_created_utc = to_utc_aware(tweet_created)
                acc_last_checked_utc = to_utc_aware(acc_last_checked_dt)
        
                if tweet_created_utc <= acc_last_checked_utc:
                    continue
                if acc.last_id and float(acc.last_id) >= float(tweet.tweet_id):
                    continue
        
                # Otherwise, send the tweet
                session.query(Database).filter(Database.uid == acc.uid).update({"last_count": acc.last_count + 1, "last_checked": datetime.utcnow(), "last_id": tweet.tweet_id})
                send_tweet(tweet.full_text, tweet.media, tweet.author, tweet.tweet_id, tweet.created_at)
            
            # Optionally, move last_checked to now (or to max tweet_created if you prefer).
            # Using the newest tweet’s DateTime can help avoid edge cases.
            if new_tweets_to_send:
                # Pick the largest creation time among tweets you actually sent
                newest_tweet_time = max(parse_date(t.created_at) for t in new_tweets_to_send)
                acc.last_checked = max(acc.last_checked, newest_tweet_time)
            else:
                # If no tweets were sent, just update last_checked to now
                acc.last_checked = datetime.utcnow()
    
        session.commit()
        session.close()
    except Exception as e:
        print(e)
    s.enter(180, 1, check_accounts)
    
def set_baseline():
    """
    Just in case, set the baseline statuses_count for all active accounts and update it when the bot starts up. only fetching new tweets.
    """
    session = SessionLocal()
    accounts = session.query(Database).filter(Database.active == True).all()
    baselines = get_baseline([str(a.uid) for a in accounts])
    for (account, baseline) in baselines:
        session.query(Database) \
            .filter(Database.uid == account) \
            .update({"last_count": baseline, "last_checked": datetime.utcnow()})
    session.commit()
    print("Updated all accounts' baseline statuses_count.")
    session.close()

def send_tweet(content: str, media: list[str], author: str, tid: str, timestamp: str):
    try:
        bot.send_message(
            environ.get("CHAT_ID", ""), 
            f"[{author}](https://x.com/{author}/status/{tid})" + (f": {content}" + '\n' + '\n'.join(media)) \
                .replace(".", r"\.") \
                .replace("-", r"\-") \
                .replace("(", r"\(") \
                .replace(")", r"\)") \
                .replace("#", r"\#") \
                .replace("!", r"\!") \
                .replace(">", r"\>") \
                .replace("~", r"\~") \
                .replace("`", r"\`") \
                .replace(":", r"\:") \
                .replace("*", r"\*") \
                .replace("_", r"\_") \
                .replace("[", r"\[") \
                .replace("]", r"\]") \
                .replace("|", r"\|") \
                .replace("{", r"\{") \
                .replace("}", r"\}") \
                .replace("+", r"\+"),
            parse_mode="MarkdownV2",
        )
    except Exception as e:
        print(f"Failed to send tweet: {e}")
        bot.send_message(
            environ.get("CHAT_ID", ""), 
            f"{author}: {content}" + '\n' + '\n'.join(media) + "\n\n" + timestamp,
        )
    
@bot.message_handler(commands=["subscribe"])
def subscribe(message):
    try:
        session = SessionLocal()
        link = message.text.split(" ")[1]
        handle = get_handle(link)
        if session.query(Database).filter(func.lower(Database.username) == handle.lower()).first():
            session.query(Database).filter(func.lower(Database.username) == handle.lower()).update({"active": True})
            session.commit()
            session.close()
            return bot.reply_to(message, f"resubscribed to {handle}")
        user = get_user_from_handle(handle)
        if not user: raise ValueError("Failed to get user.")
        uid = user["rest_id"]
        if not uid:
            bot.reply_to(message, "Failed to find user.")
            return
        add_watched_account(uid, message.from_user.username, user)
        bot.reply_to(message, f"Subscribed to {handle}")
    except Exception as e:
        bot.reply_to(message, f"Failed to subscribe: {e}")
    
@bot.message_handler(commands=["unsubscribe"])
def unsubscribe(message):
    session = SessionLocal()
    try:
        link = message.text.split(" ")[1]
        handle = get_handle(link)
        # Case-insensitive update, if needed:
        session.query(Database).filter(func.lower(Database.username) == handle.lower()).update({"active": False})
        session.commit()
        bot.reply_to(message, f"Unsubscribed from {handle}")
    except Exception as e:
        session.rollback()
        bot.reply_to(message, f"Failed to unsubscribe: {e}")
    finally:
        session.close()

@bot.message_handler(commands=["list"])
def list_accounts(message):
    session = SessionLocal()
    try:
        accounts = session.query(Database).filter(Database.active == True).all()
        if not accounts:
            bot.reply_to(message, "No active subscriptions")
            return
        reply = "\n".join([f"{account.username} ({account.uid})" for account in accounts])
        bot.reply_to(message, reply)
    except Exception as e:
        bot.reply_to(message, f"Failed to list: {e}")
    finally:
        session.close()
        
@bot.message_handler(commands=["restart"])
def restart(message):
    try:
        bot.reply_to(message, "Restarting...")
        if not s.queue:
            s.enter(0, 5, check_accounts)
    except Exception as e:
        bot.reply_to(message, f"Failed to restart: {e}")
  
def verify_channel():
    try:
        if not bot.get_chat(environ.get("CHAT_ID", "")):
            raise ValueError("Failed to get chat.")
        print("Channel verified.")
    except Exception as e:
        print(f"Failed to verify channel: {e}")
        return False
  
s.enter(30, 1, check_accounts) 
s.enter(5, 2, verify_channel)
s.enter(5, 3, set_baseline)
Thread(target=bot.polling, kwargs={"non_stop":True}).start()
Thread(target=s.run).start()