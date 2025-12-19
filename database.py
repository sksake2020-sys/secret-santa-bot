# database.py - УПРОЩЕННАЯ ВЕРСИЯ ДЛЯ RAILWAY
from sqlalchemy import create_engine, Column, Integer, String, Boolean, ForeignKey, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import os

Base = declarative_base()

# ============== МОДЕЛИ БАЗЫ ДАННЫХ ==============
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

# ============== НАСТРОЙКА ПОДКЛЮЧЕНИЯ ==============
# Получаем URL базы данных
DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL or DATABASE_URL.strip() == '':
    # Режим тестирования: используем SQLite в памяти
    DATABASE_URL = 'sqlite:///:memory:'
    print("⚠️ DATABASE_URL не установлен, использую SQLite in-memory")
elif DATABASE_URL.startswith('postgres://'):
    # Исправляем для SQLAlchemy 2.x
    DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)

# Создаем engine с безопасными параметрами
try:
    if DATABASE_URL.startswith('sqlite'):
        engine = create_engine(
            DATABASE_URL, 
            connect_args={"check_same_thread": False}
        )
    else:
        engine = create_engine(DATABASE_URL)
    
    # Создаем таблицы
    Base.metadata.create_all(bind=engine)
    print(f"✅ База данных подключена: {DATABASE_URL[:50]}...")
    
except Exception as e:
    print(f"❌ Ошибка подключения к базе данных: {e}")
    # Аварийный режим: SQLite в памяти
    DATABASE_URL = 'sqlite:///:memory:'
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    print("✅ Использую аварийный режим (SQLite in-memory)")

# Создаем сессию
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    """Функция для получения сессии базы данных."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
