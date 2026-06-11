#!/usr/bin/env python3
"""
CIN Telegram Agent — ThinkCentre Edition
Conversation · Command · Shell Ghost integration
"""

import logging
import os
import json
import httpx
from pathlib import Path

from telegram import Update
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from telegram.constants import ParseMode

import command_parser
import shell_ghost
import memory

# ── Config ─────────────────────────────────────────────────────────────────

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
ALLOWED_USERS = set(
    int(x) for x in os.environ.get("ALLOWED_USER_IDS", "").split(",") if x.strip()
)
# This bot executes natural-language shell commands, so an unset allowlist must
# fail CLOSED, not open. Set ALLOW_ALL_USERS=1 to intentionally run without an
# allowlist (e.g. a throwaway sandbox); otherwise an empty allowlist denies all.
ALLOW_ALL = os.environ.get("ALLOW_ALL_USERS", "") == "1"
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3")
USE_CLOUD_FALLBACK = os.environ.get("ANTHROPIC_API_KEY", "") != ""
ANTHROPIC_KEY = os.environ.get("ANTHROPIC_API_KEY", "")
DATA_DIR = Path(os.environ.get("CIN_DATA_DIR", "~/.cin_agent")).expanduser()
# Ensure the data directory exists before the FileHandler opens bot.log,
# otherwise configuring logging at import time raises FileNotFoundError.
DATA_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(DATA_DIR / "bot.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("cin_agent")

# Phosphor green status line
STATUS_LINE = "⚡️ <i>ThinkCentre · $0.00</i>"
CLOUD_STATUS = "⚡️ <i>ThinkCentre → Cloud · $0.01</i>"

# ── Auth Guard ──────────────────────────────────────────────────────────────

def is_allowed(user_id: int) -> bool:
    if not ALLOWED_USERS:
        # Fail closed: no allowlist => deny everyone unless ALLOW_ALL_USERS=1.
        return ALLOW_ALL
    return user_id in ALLOWED_USERS


# ── LLM Backends ──────────────────────────────────────────────────────────

async def ask_ollama(prompt: str, history: list[dict]) -> tuple[str, str]:
    """Query local Ollama. Returns (response, status_line)."""
    messages = [
        {
            "role": "system",
            "content": (
                "You are CIN, a sharp, concise AI agent running on a ThinkCentre. "
                "You have personality — direct, a little dry, but genuinely helpful. "
                "Never say you can't do something without trying. "
                "When confused, say so clearly and ask for clarification. "
                "Keep responses brief unless depth is needed."
            ),
        }
    ] + history + [{"role": "user", "content": prompt}]

    try:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{OLLAMA_URL}/api/chat",
                json={"model": OLLAMA_MODEL, "messages": messages, "stream": False},
            )
            resp.raise_for_status()
            return resp.json()["message"]["content"], STATUS_LINE
    except Exception as e:
        logger.warning(f"Ollama failed: {e}")
        return None, None


async def ask_cloud(prompt: str, history: list[dict]) -> tuple[str, str]:
    """Fallback to Anthropic Claude API."""
    if not ANTHROPIC_KEY:
        return "Local model unavailable and no cloud fallback configured.", CLOUD_STATUS

    messages = history + [{"role": "user", "content": prompt}]
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 1024,
                    "system": (
                        "You are CIN, a sharp concise AI agent. Direct, a little dry, genuinely helpful. "
                        "Keep responses brief."
                    ),
                    "messages": messages,
                },
            )
            resp.raise_for_status()
            return resp.json()["content"][0]["text"], CLOUD_STATUS
    except Exception as e:
        logger.error(f"Cloud fallback failed: {e}")
        return f"Both local and cloud unavailable. Error: {e}", CLOUD_STATUS


async def get_response(user_id: int, prompt: str) -> tuple[str, str]:
    """Try Ollama, fall back to cloud if needed."""
    history = memory.get_history(user_id, n=8)
    response, status = await ask_ollama(prompt, history)
    if response is None and USE_CLOUD_FALLBACK:
        response, status = await ask_cloud(prompt, history)
    if response is None:
        response = "Local AI is offline and no fallback is set. Type /status to check."
    return response, status


# ── Command Handlers ───────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    if not is_allowed(user.id):
        await update.message.reply_text("🔒 Not authorized.")
        return

    memory.remember(user.id, "name", user.first_name)
    name = user.first_name or "human"
    await update.message.reply_html(
        f"<b>CIN Agent online.</b>\n\n"
        f"Hey {name}. I run on the ThinkCentre.\n\n"
        f"<b>What I can do:</b>\n"
        f"• Chat normally — just talk\n"
        f"• Execute commands — <i>show me disk space</i>, <i>list files in ~/Downloads</i>\n"
        f"• Create files — <i>create file notes.txt with content Hello world</i>\n"
        f"• System status — <i>check status</i>\n\n"
        f"/help — full command list\n"
        f"/clear — reset conversation\n\n"
        f"{STATUS_LINE}"
    )


async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_html(
        "<b>CIN Agent — Commands</b>\n\n"
        "<b>System</b>\n"
        "• <i>show disk space</i> / <i>check memory</i>\n"
        "• <i>check status</i> / <i>show processes</i>\n"
        "• <i>check uptime</i> / <i>show network</i>\n\n"
        "<b>Files</b>\n"
        "• <i>list files in ~/Documents</i>\n"
        "• <i>read file config.txt</i>\n"
        "• <i>create file todo.txt with content buy milk</i>\n"
        "• <i>find notes in ~/</i>\n\n"
        "<b>Git</b>\n"
        "• <i>git status</i> / <i>git log</i>\n\n"
        "<b>Bot Commands</b>\n"
        "/start — reintroduce\n"
        "/status — agent health check\n"
        "/clear — clear conversation history\n"
        "/audit — show last 10 executed commands\n"
        "/help — this message\n\n"
        f"{STATUS_LINE}"
    )


async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("🔒 Not authorized.")
        return
    result = shell_ghost.execute("uptime && free -h && df -h /")
    ollama_ok = False
    try:
        async with httpx.AsyncClient(timeout=3) as client:
            r = await client.get(f"{OLLAMA_URL}/api/tags")
            ollama_ok = r.status_code == 200
    except Exception:
        pass

    status_block = (
        f"<b>CIN Agent Status</b>\n"
        f"🟢 Bot: Online\n"
        f"{'🟢' if ollama_ok else '🔴'} Ollama ({OLLAMA_MODEL}): {'up' if ollama_ok else 'down'}\n"
        f"{'🟢' if USE_CLOUD_FALLBACK else '⚪'} Cloud fallback: {'ready' if USE_CLOUD_FALLBACK else 'not configured'}\n\n"
        f"<pre>{result['output'][:1000]}</pre>\n\n"
        f"{STATUS_LINE}"
    )
    await update.message.reply_html(status_block)


async def cmd_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        await update.message.reply_text("🔒 Not authorized.")
        return
    memory.clear_user_history(update.effective_user.id)
    await update.message.reply_text("🗑 Conversation history cleared.")


async def cmd_audit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_allowed(update.effective_user.id):
        return

    audit_file = DATA_DIR / "audit.log"
    if not audit_file.exists():
        await update.message.reply_text("No audit log yet.")
        return

    lines = audit_file.read_text().strip().split("\n")[-10:]
    entries = []
    for line in lines:
        try:
            e = json.loads(line)
            entries.append(f"[{e['ts'][:19]}] {e['status']} → {e['cmd'][:60]}")
        except Exception:
            pass

    text = "\n".join(entries) or "No entries."
    await update.message.reply_html(f"<b>Last 10 commands</b>\n<pre>{text}</pre>")


# ── Pending Confirmations ──────────────────────────────────────────────────

PENDING: dict[int, dict] = {}  # user_id → {type, data}


async def handle_confirmation(update: Update, user_id: int, text: str):
    pending = PENDING.get(user_id)
    if not pending:
        return False

    affirmative = text.lower().strip() in {"yes", "y", "yeah", "yep", "confirm", "ok", "do it"}
    negative = text.lower().strip() in {"no", "n", "nope", "cancel", "abort"}

    if not affirmative and not negative:
        return False  # Not a confirmation response

    if negative:
        del PENDING[user_id]
        await update.message.reply_text("❌ Cancelled.")
        return True

    if affirmative:
        ptype = pending["type"]
        if ptype == "command":
            result = shell_ghost.execute(pending["cmd"])
            await send_command_result(update, pending["cmd"], result)
        elif ptype == "create_file":
            result = shell_ghost.create_file(
                pending["path"], pending["content"], overwrite=True
            )
            if result["success"]:
                await update.message.reply_html(
                    f"✅ File created: <code>{result['path']}</code>"
                )
            else:
                await update.message.reply_text(f"❌ {result['error']}")
        del PENDING[user_id]
        return True

    return False


# ── Core Message Router ────────────────────────────────────────────────────

async def send_command_result(update: Update, cmd: str, result: dict):
    if result.get("blocked"):
        await update.message.reply_html(
            f"🚫 <b>Blocked:</b> {result['reason']}\n\n{STATUS_LINE}"
        )
        return

    icon = "✅" if result["success"] else "⚠️"
    output = result.get("output", "").strip() or "(no output)"

    # Truncate long output
    if len(output) > 3000:
        output = output[:3000] + "\n... (truncated)"

    await update.message.reply_html(
        f"{icon} <code>{cmd}</code>\n\n"
        f"<pre>{output}</pre>\n\n"
        f"{STATUS_LINE}"
    )


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    text = update.message.text.strip()

    if not is_allowed(user.id):
        await update.message.reply_text("🔒 Not authorized.")
        return

    logger.info(f"[{user.id}] {user.first_name}: {text[:100]}")

    # ── Check pending confirmations first ────────────────────────────────
    if user.id in PENDING:
        handled = await handle_confirmation(update, user.id, text)
        if handled:
            return

    # ── Parse intent ──────────────────────────────────────────────────────
    intent = command_parser.parse(text)
    logger.info(f"Intent: {intent.intent} ({intent.confidence:.2f}) action={intent.action}")

    # ── COMMAND MODE ──────────────────────────────────────────────────────
    if intent.intent == "command":

        # File creation is special — needs content extraction
        if intent.action == "create_file":
            params = command_parser.extract_file_create_params(text)
            if not params or not params.get("path"):
                await update.message.reply_text(
                    "I can create a file, but I need a name.\n"
                    "Try: <i>create file notes.txt with content hello world</i>",
                    parse_mode=ParseMode.HTML,
                )
                return

            path = params["path"]
            content = params.get("content", "")
            target = Path(path).expanduser()

            if target.exists():
                PENDING[user.id] = {"type": "create_file", "path": path, "content": content}
                await update.message.reply_html(
                    f"⚠️ <code>{path}</code> already exists. Overwrite? (yes/no)"
                )
                return

            result = shell_ghost.create_file(path, content)
            if result["success"]:
                await update.message.reply_html(
                    f"✅ Created <code>{result['path']}</code>\n\n{STATUS_LINE}"
                )
            else:
                await update.message.reply_text(f"❌ {result['error']}")
            return

        # Shell commands
        if intent.command:
            # Check if needs confirmation
            if shell_ghost.needs_confirmation(intent.command):
                PENDING[user.id] = {"type": "command", "cmd": intent.command}
                await update.message.reply_html(
                    f"⚠️ Confirm: <code>{intent.command}</code> (yes/no)"
                )
                return

            # Typing indicator
            await context.bot.send_chat_action(update.effective_chat.id, "typing")
            result = shell_ghost.execute(intent.command)
            await send_command_result(update, intent.command, result)
            return
        else:
            # Couldn't build a command
            await update.message.reply_html(
                "🤔 I understood you want to do something, but couldn't figure out the exact command.\n"
                "Can you be more specific?\n\n"
                "<i>Example: show disk space, list files in ~/Downloads</i>"
            )
            return

    # ── CONFUSED MODE ─────────────────────────────────────────────────────
    if intent.intent == "confused":
        # Still try LLM — maybe it can handle it
        pass  # Fall through to chat mode with a note

    # ── CHAT MODE ─────────────────────────────────────────────────────────
    await context.bot.send_chat_action(update.effective_chat.id, "typing")

    # Store user message
    memory.add_history(user.id, "user", text)

    response, status = await get_response(user.id, text)

    # Store response
    memory.add_history(user.id, "assistant", response)

    # Escape for HTML (basic)
    safe_response = response.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    await update.message.reply_html(
        f"{safe_response}\n\n{status}"
    )


# ── Entry Point ────────────────────────────────────────────────────────────

def main():
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN environment variable not set")

    DATA_DIR.mkdir(parents=True, exist_ok=True)

    logger.info("⚡ CIN Agent starting up")
    logger.info(f"Ollama: {OLLAMA_URL} / model: {OLLAMA_MODEL}")
    logger.info(f"Cloud fallback: {'enabled' if USE_CLOUD_FALLBACK else 'disabled'}")
    logger.info(
        f"Allowed users: {ALLOWED_USERS or ('ALL (ALLOW_ALL_USERS=1)' if ALLOW_ALL else 'NONE — denying all; set ALLOWED_USER_IDS')}"
    )

    app = Application.builder().token(TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("clear", cmd_clear))
    app.add_handler(CommandHandler("audit", cmd_audit))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Polling started.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
