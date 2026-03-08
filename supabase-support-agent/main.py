"""
Supabase Support Agent - Main Application
FastAPI server handling Telegram webhook + Gemini AI + Supabase

GitHub: https://github.com/YOUR_USERNAME/supabase-support-agent
"""

import os
import time
import logging
import asyncio

from contextlib import asynccontextmanager
from dotenv import load_dotenv
from fastapi import FastAPI, Request, Response
import httpx

from database import DatabaseService
from gemini_service import GeminiService

load_dotenv()

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger(__name__)

# =========================================================
# CONFIG
# =========================================================

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_ESCALATION_CHAT_ID = os.getenv("TELEGRAM_ESCALATION_CHAT_ID")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_SERVICE_KEY = os.getenv("SUPABASE_SERVICE_KEY")

TELEGRAM_API = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# =========================================================
# SERVICES
# =========================================================

db = DatabaseService(SUPABASE_URL, SUPABASE_SERVICE_KEY)
gemini = GeminiService(GEMINI_API_KEY, db)

# =========================================================
# TELEGRAM HELPERS
# =========================================================


async def send_telegram_message(chat_id: int, text: str, parse_mode: str = "Markdown"):
    """Send a message via Telegram Bot API with auto-chunking and markdown fallback."""
    chunks = _split_message(text, 4000)
    async with httpx.AsyncClient() as client:
        for chunk in chunks:
            resp = await client.post(
                f"{TELEGRAM_API}/sendMessage",
                json={"chat_id": chat_id, "text": chunk, "parse_mode": parse_mode},
                timeout=10,
            )
            if resp.status_code != 200:
                # Markdown failed, retry as plain text
                resp2 = await client.post(
                    f"{TELEGRAM_API}/sendMessage",
                    json={"chat_id": chat_id, "text": chunk},
                    timeout=10,
                )
                if resp2.status_code != 200:
                    logger.error(f"Telegram send failed: {resp2.text}")


def _split_message(text: str, max_length: int = 4000) -> list[str]:
    """Split a long message into chunks at newline boundaries."""
    if len(text) <= max_length:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_length:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, max_length)
        if split_at == -1:
            split_at = max_length
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


async def send_escalation(user_name: str, question: str, agent_answer: str, reason: str):
    """Forward an escalation to the designated Telegram channel."""
    if not TELEGRAM_ESCALATION_CHAT_ID:
        logger.warning("No escalation chat ID configured, skipping")
        return
    text = (
        f"🚨 *ESCALATION*\n\n"
        f"*From:* {user_name}\n"
        f"*Question:* {question}\n\n"
        f"*Agent analysis:*\n{agent_answer[:1500]}\n\n"
        f"*Reason:* {reason}"
    )
    await send_telegram_message(int(TELEGRAM_ESCALATION_CHAT_ID), text)


async def download_telegram_file(file_id: str) -> bytes:
    """Download a file from Telegram by file_id."""
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{TELEGRAM_API}/getFile", params={"file_id": file_id}, timeout=10)
        file_path = resp.json()["result"]["file_path"]
        resp = await client.get(
            f"https://api.telegram.org/file/bot{TELEGRAM_BOT_TOKEN}/{file_path}", timeout=30
        )
        return resp.content


# =========================================================
# FASTAPI APP
# =========================================================


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Support Agent starting up...")
    cleanup_task = asyncio.create_task(_periodic_cleanup())
    yield
    cleanup_task.cancel()
    logger.info("Support Agent shutting down...")


async def _periodic_cleanup():
    """Clean up expired chat history every 10 minutes."""
    while True:
        try:
            await db.cleanup_old_chat_history()
        except Exception as e:
            logger.error(f"Cleanup failed: {e}")
        await asyncio.sleep(600)


app = FastAPI(title="Supabase Support Agent", lifespan=lifespan)


@app.get("/health")
async def health():
    return {"status": "ok", "service": "supabase-support-agent"}


@app.post("/webhook")
async def telegram_webhook(request: Request):
    """Handle incoming Telegram messages (text + images)."""
    try:
        data = await request.json()
    except Exception:
        return Response(status_code=400)

    message = data.get("message")
    if not message:
        return Response(status_code=200)

    chat_id = message["chat"]["id"]
    user_id = message["from"]["id"]
    user_name = message["from"].get("first_name", "Unknown")

    # Extract text from message or caption
    text = message.get("text", "").strip()
    caption = message.get("caption", "").strip()

    # Handle /start command
    if text.startswith("/start"):
        await send_telegram_message(
            chat_id,
            "👋 *Support Agent ready.*\n\n"
            "Ask me anything about a customer, error, or stats.\n"
            "You can also send screenshots with a question.\n\n"
            "Examples:\n"
            "• `What's the status of Acme Corp?`\n"
            "• `ERR_AUTH_001 - what does this mean?`\n"
            "• `How many active subscribers?`",
        )
        return Response(status_code=200)

    if text.startswith("/"):
        return Response(status_code=200)

    # Handle images
    image_bytes = None
    image_mime = "image/jpeg"

    if message.get("photo"):
        photo = message["photo"][-1]  # largest size
        try:
            image_bytes = await download_telegram_file(photo["file_id"])
        except Exception as e:
            logger.error(f"Failed to download photo: {e}")
    elif message.get("document") and message["document"].get("mime_type", "").startswith("image/"):
        try:
            image_bytes = await download_telegram_file(message["document"]["file_id"])
            image_mime = message["document"]["mime_type"]
        except Exception as e:
            logger.error(f"Failed to download document image: {e}")

    # Build query text
    query_text = text or caption
    if not query_text and image_bytes:
        query_text = "What does this screenshot show? What error or issue is visible?"
    if not query_text and not image_bytes:
        return Response(status_code=200)

    logger.info(f"Message from {user_name} ({user_id}): {query_text[:100]} [image={'yes' if image_bytes else 'no'}]")

    # Send typing indicator
    async with httpx.AsyncClient() as client:
        await client.post(
            f"{TELEGRAM_API}/sendChatAction",
            json={"chat_id": chat_id, "action": "typing"},
            timeout=5,
        )

    start_time = time.time()

    try:
        # Get conversation history
        history = await db.get_chat_history(user_id)
        await db.save_chat_message(user_id, "user", query_text + (" [+image]" if image_bytes else ""))

        # Call Gemini
        response_text, queries_run, tools_used, confidence = await gemini.chat(
            message=query_text,
            history=history,
            image_bytes=image_bytes,
            image_mime=image_mime,
        )

        response_time_ms = int((time.time() - start_time) * 1000)
        await db.save_chat_message(user_id, "assistant", response_text)

        # Detect escalation signals
        escalated = False
        escalation_reason = None
        escalation_keywords = ["escalat", "code change", "bug", "can't determine"]
        for keyword in escalation_keywords:
            if keyword.lower() in response_text.lower():
                escalated = True
                escalation_reason = f"Agent flagged: {keyword}"
                break
        if confidence == "low":
            escalated = True
            escalation_reason = "Low confidence response"

        # Log interaction
        await db.log_interaction(
            telegram_user_id=user_id,
            user_name=user_name,
            question=query_text,
            answer=response_text,
            queries_run=queries_run,
            tools_used=tools_used,
            escalated=escalated,
            escalation_reason=escalation_reason,
            confidence=confidence,
            response_time_ms=response_time_ms,
        )

        # Send response
        await send_telegram_message(chat_id, response_text)

        # Escalate if needed
        if escalated:
            await send_escalation(user_name, query_text, response_text, escalation_reason)

        logger.info(
            f"Response to {user_name} in {response_time_ms}ms "
            f"[confidence={confidence}, escalated={escalated}, tools={len(tools_used)}, "
            f"image={'yes' if image_bytes else 'no'}]"
        )

    except Exception as e:
        logger.error(f"Error: {e}", exc_info=True)
        await send_telegram_message(chat_id, "⚠️ Error processing your request. Please try again.")

    return Response(status_code=200)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
