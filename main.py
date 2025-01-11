from os import environ

from database import Bot as Database, add_watched_account, SessionLocal
from twitter import should_check_batch, get_tweets, get_user_from_handle, get_handle, get_baseline, get_tweet
from dotenv import load_dotenv
from sched import scheduler
from time import sleep, time
from telebot import TeleBot
from threading import Thread
from sqlalchemy import func

s = scheduler(time, sleep)
load_dotenv()
bot = TeleBot(environ.get("TELEGRAM_TOKEN", ""))

def check_accounts():
    session = SessionLocal()
    accounts = session.query(Database).filter(Database.active == True).all()
    
    # Grab DB data
    uids = [str(a.uid) for a in accounts]
    last_counts = [int(a.last_count) for a in accounts]

    # Query the “should_check_batch” in one go
    check_info = list(should_check_batch(uids, last_counts))

    for i, (account_uid, difference) in enumerate(check_info):
        if difference < 0:
            difference = 0

        if difference > 0:
            # Fetch new tweets
            tweets, ignored = get_tweets(account_uid, difference)

            # Post the tweets we want
            for tw in tweets:
                # If pinned or old, skip. Or if you want pinned, handle accordingly.
                # Right now, we just send them all:
                send_tweet(tw.full_text, tw.media, tw.author, tw.tweet_id)

            # NEW CODE: increment last_count by 1 for each skipped tweet
            # (i.e., for each item in `ignored`).
            if ignored:
                user_info = session.query(Database).filter(Database.uid == account_uid).first()
                if user_info:
                    skip_count = range(ignored)
                    session.query(Database).filter(Database.uid == account_uid).update(
                        {"last_count": user_info.last_count + skip_count}
                    )
                    session.commit()

            # Update the last_count by the difference in status counts
            user_info = session.query(Database).filter(Database.uid == account_uid).first()
            if user_info:
                old = user_info.last_count
                session.query(Database).filter(Database.uid == account_uid).update(
                    {"last_count": old + difference}
                )

    session.commit()
    session.close()

    # Reschedule
    s.enter(90, 1, check_accounts)
    
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
            .update({"last_count": baseline})
        session.commit()
    print("Updated all accounts' baseline statuses_count.")
    session.close()

def send_tweet(content: str, media: list[str], author: str, tid: str):
    try:
        bot.send_message(
            environ.get("CHAT_ID", ""), 
            (f"[{author}](https://x.com/{author}/status/{tid}): {content}" + '\n' + '\n'.join(media)) \
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
            f"{author}: {content}" + '\n' + '\n'.join(media),
        )
    
@bot.message_handler(commands=["subscribe"])
def subscribe(message):
    try:
        link = message.text.split(" ")[1]
        handle = get_handle(link)
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