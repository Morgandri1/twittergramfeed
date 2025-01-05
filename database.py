from sqlalchemy import create_engine, Column, String, DateTime, Boolean, Numeric
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import SQLAlchemyError
from datetime import datetime
from os import environ
from dotenv import load_dotenv
from twitter import get_user_info  # Assumes you have this file/function

# Load environment variables
load_dotenv()

DATABASE_URL = environ.get('DATABASE_URL', '')

# Create the engine
engine = create_engine(
    DATABASE_URL,
    echo=False,          # Turn this off in production
    pool_size=5,
    max_overflow=10
)

# Create a session factory
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

# Declare the base
Base = declarative_base()

class Bot(Base):
    __tablename__ = "bot"

    uid = Column(String, primary_key=True)
    username = Column(String)
    added_by = Column(String)
    last_count = Column(Numeric)
    last_checked = Column(DateTime, default=datetime.now, onupdate=datetime.now)
    added = Column(DateTime, default=datetime.now)
    active = Column(Boolean, default=True)

# Create tables if they do not already exist
Base.metadata.create_all(bind=engine)

def add_watched_account(uid: str, executor: str, user: dict | None = None):
    """
    Add a watched account to the database.
    
    :param uid: The user's unique identifier (as a string).
    :param executor: The user or system that triggered the addition.
    :param user: A dictionary of user data (optional). If not provided, get_user_info(uid) is called.
    :raises ValueError: If unable to retrieve user info or add the record.
    """
    if user is None:
        user = get_user_info(uid)
    if not user:
        raise ValueError("Failed to get user info.")

    session = SessionLocal()
    try:
        new_bot = Bot(
            uid=uid,
            username=user["legacy"]["screen_name"],
            added_by=executor,
            last_count=user["legacy"]["statuses_count"],
            last_checked=datetime.now(),
            added=datetime.now(),
            active=True
        )
        session.add(new_bot)
        session.commit()
    except SQLAlchemyError as e:
        session.rollback()
        # You can log the exception here or handle it further
        raise ValueError(f"Failed to add account: {e}") from e
    finally:
        session.close()