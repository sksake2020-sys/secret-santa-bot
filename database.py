# database.py - ВЕРСИЯ ДЛЯ POSTGRESQL НА RAILWAY
from sqlalchemy import create_engine, Column, Integer, String, Boolean, ForeignKey, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import os
import urllib.parse

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

# ============== НАСТРОЙКА ПОДКЛЮЧЕНИЯ К POSTGRESQL ==============
# Получаем URL базы данных от Railway
DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL or DATABASE_URL.strip() == '':
    # Режим тестирования: SQLite в памяти
    DATABASE_URL = 'sqlite:///:memory:'
    print("⚠️ DATABASE_URL не установлен, использую SQLite in-memory")
else:
    # Railway даёт URL в формате postgres://, а SQLAlchemy 1.4.x требует postgresql://
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
    print(f"✅ Использую PostgreSQL: {DATABASE_URL.split('@')[1] if '@' in DATABASE_URL else DATABASE_URL[:50]}...")

# Создаем engine
try:
    if DATABASE_URL.startswith('sqlite'):
        engine = create_engine(
            DATABASE_URL, 
            connect_args={"check_same_thread": False},
            echo=False  # Убрать SQL-логи для продакшена
        )
    else:
        # Для PostgreSQL
        engine = create_engine(
            DATABASE_URL,
            pool_size=10,           # Размер пула соединений
            max_overflow=20,        # Максимальное количество соединений
            pool_recycle=3600,      # Пересоздавать соединения каждый час
            echo=False              # Убрать SQL-логи
        )
    
    # Создаем таблицы (если их нет)
    Base.metadata.create_all(bind=engine)
    print("✅ Таблицы созданы/проверены успешно")
    
except Exception as e:
    print(f"❌ Ошибка подключения к базе данных: {e}")
    # Аварийный режим
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

# Функция для проверки подключения
def test_connection():
    """Тест подключения к базе данных"""
    try:
        db = SessionLocal()
        result = db.execute("SELECT version()").fetchone()
        db.close()
        print(f"✅ Подключение к БД: {result[0] if result else 'OK'}")
        return True
    except Exception as e:
        print(f"❌ Ошибка теста подключения: {e}")
        return False

# Автоматически тестируем подключение при импорте
if __name__ != "__main__":
    test_connection()
