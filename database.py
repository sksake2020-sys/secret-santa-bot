# database.py - PostgreSQL ready for Railway
from sqlalchemy import create_engine, Column, Integer, String, Boolean, ForeignKey, DateTime, Text
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship
from datetime import datetime
import os
import logging

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)

Base = declarative_base()

# ============== МОДЕЛИ БАЗЫ ДАННЫХ ==============
class Game(Base):
    __tablename__ = 'games'
    
    id = Column(String(50), primary_key=True)  # string id to support codes like ABC123XY
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
    game_id = Column(String(50), ForeignKey('games.id'), nullable=False)  # string FK
    user_id = Column(Integer, nullable=False, index=True)
    username = Column(String(100), nullable=True)
    full_name = Column(String(200), nullable=True)
    wishlist = Column(Text, nullable=True)
    target_id = Column(Integer, nullable=True, index=True)
    
    game = relationship("Game", back_populates="participants")

# ============== НАСТРОЙКА ПОДКЛЮЧЕНИЯ К POSTGRESQL ==============
DATABASE_URL = os.environ.get('DATABASE_URL')

if not DATABASE_URL or DATABASE_URL.strip() == '':
    # Режим тестирования: SQLite в памяти
    DATABASE_URL = 'sqlite:///:memory:'
    logger.warning("DATABASE_URL не установлен, использую SQLite in-memory")
else:
    # Railway может отдавать postgres:// — SQLAlchemy требует postgresql://
    if DATABASE_URL.startswith('postgres://'):
        DATABASE_URL = DATABASE_URL.replace('postgres://', 'postgresql://', 1)
    logger.info("Использую базу данных: %s", DATABASE_URL.split('@')[-1] if '@' in DATABASE_URL else DATABASE_URL[:60])

# Создаем engine с пулом и pre_ping
try:
    if DATABASE_URL.startswith('sqlite'):
        engine = create_engine(
            DATABASE_URL,
            connect_args={"check_same_thread": False},
            echo=False
        )
    else:
        engine = create_engine(
            DATABASE_URL,
            pool_size=10,
            max_overflow=20,
            pool_recycle=3600,
            pool_pre_ping=True,
            echo=False
        )
    # Создаем таблицы (первичный запуск). Для продакшена рекомендую Alembic.
    Base.metadata.create_all(bind=engine)
    logger.info("Таблицы созданы/проверены успешно")
except Exception as e:
    logger.exception("Ошибка подключения к базе данных: %s", e)
    # Аварийный режим: sqlite in-memory
    DATABASE_URL = 'sqlite:///:memory:'
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    logger.info("Использую аварийный режим (SQLite in-memory)")

# Создаем сессию
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

def get_db():
    """Функция-генератор для получения сессии базы данных."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

def test_connection():
    """Тест подключения к базе данных"""
    try:
        db = SessionLocal()
        # Для PostgreSQL вернёт версию, для SQLite - простой запрос
        res = db.execute("SELECT version()").fetchone() if not DATABASE_URL.startswith('sqlite') else db.execute("SELECT 1").fetchone()
        db.close()
        logger.info("Подключение к БД успешно: %s", res[0] if res else "OK")
        return True
    except Exception as e:
        logger.exception("Ошибка теста подключения: %s", e)
        return False

# Автоматическая проверка при импорте (не мешает при импорте в тестах)
if __name__ != "__main__":
    test_connection()
