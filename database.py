# database.py
from sqlalchemy import create_engine, Column, Integer, String, Boolean, ForeignKey, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import os

Base = declarative_base()

class Game(Base):
    __tablename__ = 'games'
    
    id = Column(Integer, primary_key=True)
    name = Column(String(100), nullable=False)
    admin_id = Column(Integer, nullable=False)
    admin_username = Column(String(100), nullable=True)
    chat_id = Column(String(50), nullable=False)
    is_active = Column(Boolean, default=True)
    is_started = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.now)
    gift_price = Column(String(100), nullable=True)
    wishlist = Column(Text, nullable=True)
    
    participants = relationship("Participant", back_populates="game", cascade="all, delete-orphan")

class Participant(Base):
    __tablename__ = 'participants'
    
    id = Column(Integer, primary_key=True)
    game_id = Column(Integer, ForeignKey('games.id'), nullable=False)
    user_id = Column(Integer, nullable=False)
    username = Column(String(100), nullable=True)
    full_name = Column(String(200), nullable=False)
    wishlist = Column(Text, nullable=True)
    target_id = Column(Integer, nullable=True)
    
    game = relationship("Game", back_populates="participants")

# Используем SQLite. Файл базы будет создан в той же директории.
DATABASE_URL = os.environ.get('DATABASE_URL', 'sqlite:///secret_santa.db')
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False} if DATABASE_URL.startswith('sqlite') else {})
Base.metadata.create_all(bind=engine)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    """Функция для получения сессии базы данных."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
