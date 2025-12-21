# app/webhook_app.py
# Flask-приложение: webhook, статус, дамп, запуск aiogram worker

import os
import logging
from flask import Flask, request, jsonify

from app.worker import start_worker
from app.database import init_db, SessionLocal
from app.models import Game, Participant

# ---------------------------------------------------------
# ЛОГИ
# ---------------------------------------------------------

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("santa")

# ---------------------------------------------------------
# НАСТРОЙКИ
# ---------------------------------------------------------

BOT_TOKEN = os.environ.get("BOT_TOKEN")
BOT_USERNAME = os.environ.get("BOT_USERNAME")
ADMIN_ID = os.environ.get("ADMIN_ID")  # для /dump_games

if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is not set")

if not BOT_USERNAME:
    raise RuntimeError("BOT_USERNAME is not set")

# Railway URL
WEBHOOK_HOST = os.environ.get("RAILWAY_STATIC_URL") or os.environ.get("WEBHOOK_HOST")
if not WEBHOOK_HOST:
    raise RuntimeError("WEBHOOK_HOST or RAILWAY_STATIC_URL must be set")

if not WEBHOOK_HOST.startswith("http"):
    WEBHOOK_HOST = "https://" + WEBHOOK_HOST

WEBHOOK_PATH = f"/webhook/{BOT_TOKEN}"
WEBHOOK_URL = f"{WEBHOOK_HOST}{WEBHOOK_PATH}"

# ---------------------------------------------------------
# FLASK
# ---------------------------------------------------------

app = Flask(__name__)

# Версия приложения
@app.route("/version")
def version():
    return "VERSION_1.0.0_PROFESSIONAL_BUILD"

# ---------------------------------------------------------
# ИНИЦИАЛИЗАЦИЯ БД
# ---------------------------------------------------------

init_db()

# ---------------------------------------------------------
# ЗАПУСК AIROGRAM WORKER
# ---------------------------------------------------------

update_queue = start_worker(BOT_TOKEN, BOT_USERNAME)

# ---------------------------------------------------------
# WEBHOOK
# ---------------------------------------------------------

@app.route(WEBHOOK_PATH, methods=["POST"])
def webhook():
    try:
        update_data = request.get_json()
        update_id = update_data.get("update_id", "unknown")

        update_queue.put(update_data)
        logger.info("📥 Update queued: %s", update_id)

        return jsonify({"status": "queued", "update_id": update_id})

    except Exception as e:
        logger.exception("Webhook error: %s", e)
        return jsonify({"status": "error"}), 500

# ---------------------------------------------------------
# СЕРВИСНЫЕ ЭНДПОЙНТЫ
# ---------------------------------------------------------

@app.route("/")
def index():
    return (
        f
