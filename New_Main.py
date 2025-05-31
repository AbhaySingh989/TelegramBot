# -*- coding: utf-8 -*-

# --- IMPORTS ---
import logging
import os
import re
import json
from datetime import datetime, timezone, time as datetime_time
import asyncio
import random # For selecting random prompts

# Telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    filters,
    ContextTypes,
    ConversationHandler,
    CallbackQueryHandler,
    ApplicationBuilder
)
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown

# Google Gemini
import google.generativeai as genai
from google.generativeai.types import GenerationConfig, SafetySettingDict, HarmCategory, HarmBlockThreshold
from google.generativeai import types as genai_types

# File / Environment
from dotenv import load_dotenv
import PIL.Image # Pillow for image handling

# Visualization
import graphviz

# Custom modules
import db_utils # For database operations
from utils import reverse_alphabet # For chat response modification
import database_setup # For initial table creation

# --- BASIC SETUP ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logging.getLogger("httpx").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# --- LOAD ENVIRONMENT VARIABLES ---
load_dotenv()
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not TELEGRAM_TOKEN or not GEMINI_API_KEY:
    logger.critical("FATAL: Telegram Token or Gemini API Key missing!")
    exit("API Key Error: Check .env file.")

# --- CONFIGURE GEMINI AI ---
GEMINI_MODEL_NAME = 'gemini-1.5-flash-latest'
genai_model = None
try:
    genai.configure(api_key=GEMINI_API_KEY)
    generation_config = GenerationConfig()
    safety_settings: list[SafetySettingDict] = [
        {"category": HarmCategory.HARM_CATEGORY_HARASSMENT, "threshold": HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE},
        {"category": HarmCategory.HARM_CATEGORY_HATE_SPEECH, "threshold": HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE},
        {"category": HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT, "threshold": HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE},
        {"category": HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT, "threshold": HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE},
    ]
    genai_model = genai.GenerativeModel(
        GEMINI_MODEL_NAME,
        generation_config=generation_config,
        safety_settings=safety_settings
    )
    logger.info(f"Gemini Model '{GEMINI_MODEL_NAME}' configured.")
except Exception as e:
    logger.critical(f"Failed to configure Gemini: {e}", exc_info=True)
    exit("Gemini Configuration Error.")

# --- CONSTANTS AND FILE PATHS ---
SELECTING_MODE, CHATBOT_MODE, JOURNAL_MODE, OCR_MODE, SETTING_USERNAME, FEEDBACK_MODE = (
    "SELECTING_MODE", "CHATBOT_MODE", "JOURNAL_MODE", "OCR_MODE", "SETTING_USERNAME", "FEEDBACK_MODE"
)
END = ConversationHandler.END
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "bot_data")
TEMP_DIR = os.path.join(DATA_DIR, "temp")
TOKEN_USAGE_FILE = os.path.join(DATA_DIR, "token_usage.json")
VISUALIZATIONS_DIR = os.path.join(DATA_DIR, "visualizations")
JOURNAL_CATEGORIES_LIST = ["Emotional", "Family", "Grief", "Workplace", "Technology", "AI", "Spouse", "Kid", "Personal Reflection", "Health", "Finance", "Social", "Hobby", "Other"]

# --- ENSURE DIRECTORIES EXIST ---
for dir_path in [DATA_DIR, TEMP_DIR, VISUALIZATIONS_DIR]:
    os.makedirs(dir_path, exist_ok=True)

# --- FILE ACCESS LOCK (for token_usage.json only) ---
token_file_lock = asyncio.Lock()

# --- HELPER FUNCTIONS ---

async def load_token_data() -> dict:
    async with token_file_lock:
        default_data = {"total": 0, "daily": {"date": "", "count": 0}, "session": 0}
        try:
            if os.path.exists(TOKEN_USAGE_FILE):
                with open(TOKEN_USAGE_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    data.setdefault("total", 0)
                    data.setdefault("daily", {}).setdefault("date","")
                    data["daily"].setdefault("count",0)
                    data.setdefault("session",0)
                    return data
        except Exception as e:
            logger.error(f"Error loading token data: {e}")
        return default_data

async def save_token_data(data: dict) -> bool:
    async with token_file_lock:
        try:
            with open(TOKEN_USAGE_FILE, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=4)
            return True
        except Exception as e:
            logger.error(f"Error saving token data: {e}")
            return False

token_data_cache = {"session": 0}

async def initialize_token_data():
    global token_data_cache
    loaded_data = await load_token_data()
    token_data_cache = loaded_data
    token_data_cache['session'] = 0
    await save_token_data(token_data_cache)
    logger.info("Token data initialized.")

async def increment_token_usage(prompt_tokens: int = 0, candidate_tokens: int = 0, context: ContextTypes.DEFAULT_TYPE = None):
    global token_data_cache
    today = datetime.now().strftime("%Y-%m-%d")
    total_increment = prompt_tokens + candidate_tokens
    current_data = await load_token_data()
    if current_data.get("daily", {}).get("date") != today:
        current_data["daily"] = {"date": today, "count": 0}
    current_data["total"] = current_data.get("total", 0) + total_increment
    current_data["daily"]["count"] = current_data["daily"].get("count", 0) + total_increment
    token_data_cache["session"] = token_data_cache.get("session", 0) + total_increment
    current_data["session"] = token_data_cache["session"]
    if not await save_token_data(current_data):
        logger.error("Failed to save updated token data!")
    logger.info(f"Tokens Used - Prompt: {prompt_tokens}, Candidate: {candidate_tokens}, Session: {token_data_cache['session']}")

async def generate_gemini_response(prompt_parts: list, safety_settings_override=None, context: ContextTypes.DEFAULT_TYPE = None) -> tuple[str | None, dict | None]:
    if not genai_model:
        logger.error("Gemini model not initialized.")
        return None, None
    usage_metadata = None
    text_response = None
    try:
        logger.info(f"Sending request to Gemini ({len(prompt_parts)} parts)...")
        response = await genai_model.generate_content_async(prompt_parts, safety_settings=safety_settings_override if safety_settings_override else safety_settings)
        if hasattr(response, 'usage_metadata'):
            usage_metadata = response.usage_metadata
            await increment_token_usage(usage_metadata.prompt_token_count, usage_metadata.candidates_token_count, context)
        if response.prompt_feedback and response.prompt_feedback.block_reason:
            block_reason = response.prompt_feedback.block_reason
            logger.warning(f"Gemini request blocked: {block_reason}")
            return f"[BLOCKED: {block_reason}]", usage_metadata
        if hasattr(response, 'text'):
            text_response = response.text
            logger.info(f"Received response from Gemini ({len(text_response) if text_response else 0} chars).")
        elif not (response.prompt_feedback and response.prompt_feedback.block_reason):
            logger.warning("Gemini returned no text content.")
            text_response = "[No text content received]"
        return text_response, usage_metadata
    except (genai_types.BlockedPromptException, genai_types.StopCandidateException) as safety_exception:
        logger.warning(f"Gemini Safety Exception ({type(safety_exception).__name__}): {safety_exception}")
        response_obj = getattr(safety_exception, 'response', None)
        text_response = "[BLOCKED/STOPPED]"
        if response_obj:
             if hasattr(response_obj, 'text'):
                 text_response = response_obj.text + f" [{type(safety_exception).__name__}]"
             if hasattr(response_obj, 'usage_metadata'):
                 usage_metadata = response_obj.usage_metadata
                 await increment_token_usage(usage_metadata.prompt_token_count, usage_metadata.candidates_token_count, context)
        return text_response, usage_metadata
    except Exception as e:
        logger.error(f"Error calling Gemini API: {e}", exc_info=True)
        return f"[API ERROR: {type(e).__name__}]", None

async def add_punctuation_with_gemini(raw_text: str, context: ContextTypes.DEFAULT_TYPE = None) -> str:
    if not raw_text or raw_text.strip() == "": return raw_text
    if not genai_model: logger.warning("Gemini unavailable for punctuation."); return raw_text
    prompt = f'''Add appropriate punctuation, capitalization, and sentence breaks to the following raw text. Make it read naturally. Preserve original words/meaning.

    Raw Text: "{raw_text}"

    Formatted Text:'''
    logger.info("Sending raw transcript to Gemini for punctuation...")
    formatted_text, _ = await generate_gemini_response([prompt], context=context)
    if formatted_text and "[BLOCKED:" not in formatted_text and "[API ERROR:" not in formatted_text and "[No text content received]" not in formatted_text:
        logger.info("Punctuation added successfully."); return formatted_text.strip()
    else: logger.warning(f"Failed to punctuate: {formatted_text}. Returning raw."); return raw_text

async def transcribe_audio_with_gemini(audio_path: str, context: ContextTypes.DEFAULT_TYPE = None) -> str | None:
    if not os.path.exists(audio_path): logger.error(f"Audio file not found: {audio_path}"); return "[File Not Found Error]"
    if not genai_model: logger.error("Gemini model not available for audio transcription."); return "[AI Service Unavailable]"
    try:
        logger.info(f"Uploading audio file {os.path.basename(audio_path)} to Gemini...")
        audio_file_obj = genai.upload_file(path=audio_path)
        logger.info(f"Completed uploading '{audio_file_obj.display_name}'.")
        response = await genai_model.generate_content_async(["Transcribe accurately.", audio_file_obj])
        if response.prompt_feedback and response.prompt_feedback.block_reason:
            logger.warning(f"Gemini audio transcription blocked: {response.prompt_feedback.block_reason}")
            return f"[BLOCKED: {response.prompt_feedback.block_reason}]"
        if hasattr(response, 'text'):
            raw_text = response.text.strip()
            logger.info(f"Gemini raw transcription successful ({len(raw_text)} chars).")
            try: await genai.delete_file_async(audio_file_obj.name); logger.info(f"Deleted uploaded file '{audio_file_obj.name}' from Gemini.")
            except Exception as del_e: logger.warning(f"Could not delete uploaded audio file {audio_file_obj.name} from Gemini: {del_e}")
            return raw_text
        else: logger.warning("Gemini audio transcription returned no text content."); return "[No transcription content]"
    except Exception as e: logger.error(f"Error during Gemini audio transcription: {e}", exc_info=True); return f"[AI Transcription Error: {type(e).__name__}]"

async def generate_mind_map_image(dot_string: str, user_id: int) -> str | None:
    if not dot_string or "digraph" not in dot_string.lower(): logger.warning(f"Invalid DOT for user {user_id}."); return None
    output_base_path = os.path.join(VISUALIZATIONS_DIR, f"{user_id}_jmap_{datetime.now().strftime('%Y%m%d%H%M%S')}")
    output_png_path = output_base_path + ".png"
    try:
        logger.info(f"Generating mind map for user {user_id}")
        s = graphviz.Source(dot_string, filename=output_base_path, format="png")
        loop = asyncio.get_running_loop()
        rendered_path = await loop.run_in_executor(None, s.render, None, VISUALIZATIONS_DIR, False, True) # Ensure no_exec=True
        if os.path.exists(output_png_path): logger.info(f"Mind map PNG generated: {output_png_path}"); return output_png_path
        elif rendered_path and os.path.exists(rendered_path): logger.warning(f"Graphviz path mismatch. Using: {rendered_path}"); return rendered_path
        else: logger.error(f"Graphviz render failed or output file missing: {output_png_path}. Rendered path: {rendered_path}"); return None
    except graphviz.backend.execute.ExecutableNotFound: logger.error("Graphviz executable not found. Please ensure it's installed and in PATH."); return None
    except Exception as e: logger.error(f"Error generating mind map image: {e}", exc_info=True); return None
# --- TELEGRAM COMMAND HANDLERS ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    user = update.effective_user
    user_id = user.id
    telegram_username = user.username if user.username else str(user_id)

    # Ensure user exists in the database, or add them
    db_user_info = await asyncio.to_thread(db_utils.get_user, user_id)
    if not db_user_info:
        await asyncio.to_thread(db_utils.add_user, user_id, telegram_username, display_name=user.first_name or telegram_username)
        db_user_info = await asyncio.to_thread(db_utils.get_user, user_id) # Re-fetch to get the data

    display_name = db_user_info.get('display_name', telegram_username) if db_user_info and db_user_info.get('display_name') else telegram_username

    logger.info(f"User {user_id} ({telegram_username}) /start. Name: {display_name}")
    context.user_data.pop('current_mode', None)
    keyboard = [
        [InlineKeyboardButton(f"💬 Chatbot Mode", callback_data=CHATBOT_MODE)],
        [InlineKeyboardButton(f"📓 Journal Mode", callback_data=JOURNAL_MODE)],
        [InlineKeyboardButton(f"📄 OCR Mode", callback_data=OCR_MODE)]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(f"Hi {display_name}! Please choose a mode:", reply_markup=reply_markup)
    return SELECTING_MODE

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    help_text = escape_markdown("""*Multi-Mode Bot Help*

Use /start or /mode to select a mode:
• *Chatbot:* General conversation.
• *Journal:* Personal notes with AI analysis & mind maps.
• *OCR:* Extract text directly from images.

*Other Commands:*
/setusername <name> - Set display name
/tokens - Check AI token usage
/feedback <your message> - Send feedback to the developers
/enableprompts - Enable daily journal prompts
/disableprompts - Disable daily journal prompts
/end - End current session/mode
/cancel - Cancel current action & return to mode select
/help - Show this message

Send text, voice, or image after selecting a mode. Commands like /end or /cancel should work anytime.
""", version=2)
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN_V2)

async def set_username_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    telegram_username = user.username or str(user_id)

    if not context.args:
        await update.message.reply_text("Usage: `/setusername Your Name Here`", parse_mode=ParseMode.MARKDOWN_V2)
        return

    new_display_name = " ".join(context.args).strip()
    if not new_display_name or len(new_display_name) > 50:
        await update.message.reply_text("Invalid username (1-50 chars).")
        return

    db_user_info = await asyncio.to_thread(db_utils.get_user, user_id)
    if not db_user_info:
        await asyncio.to_thread(db_utils.add_user, user_id, telegram_username, display_name=new_display_name)
        logger.info(f"New user {user_id} created with display name '{new_display_name}' via setusername.")
        await update.message.reply_text(f"Username set to: {new_display_name}")
    else:
        if await asyncio.to_thread(db_utils.update_user_preferences, user_id, display_name=new_display_name):
            logger.info(f"User {user_id} updated display name to '{new_display_name}'")
            await update.message.reply_text(f"Username set to: {new_display_name}")
        else:
            await update.message.reply_text("Error saving username. Please try again.")

async def tokens_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    current_data = await load_token_data()
    today = datetime.now().strftime("%Y-%m-%d")
    if current_data.get("daily", {}).get("date") != today:
        current_data["daily"] = {"date": today, "count": 0}
        await save_token_data(current_data)
    total = current_data.get("total", 0)
    daily_count = current_data.get("daily", {}).get("count", 0)
    session_count = token_data_cache.get("session", 0)
    message = f"""*Token Usage:*
• Session \\(since start\\): {session_count:,}
• Today \\({today}\\): {daily_count:,}
• Total \\(all time\\): {total:,}"""
    await update.message.reply_text(escape_markdown(message, version=2), parse_mode=ParseMode.MARKDOWN_V2)

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    user = update.effective_user
    current_mode = context.user_data.get('current_mode')
    logger.info(f"User {user.id} issued /cancel (mode: {current_mode}). Returning to mode selection.")
    context.user_data.pop('current_mode', None)
    await update.message.reply_text("Operation cancelled.")
    return await start_command(update, context)

async def end_session_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    user = update.effective_user
    current_mode = context.user_data.get('current_mode')
    logger.info(f"User {user.id} issued /end (mode: {current_mode}). Ending session.")
    context.user_data.pop('current_mode', None)
    await update.message.reply_text("✅ Session ended. Use /start to begin a new one.")
    return END

async def feedback_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    if not context.args:
        await update.message.reply_text("Please provide your feedback after the /feedback command. For example: `/feedback I love this bot!`")
        return
    feedback_message = " ".join(context.args)

    telegram_username = user.username or str(user_id)
    db_user_info = await asyncio.to_thread(db_utils.get_user, user_id)
    if not db_user_info:
        await asyncio.to_thread(db_utils.add_user, user_id, telegram_username)

    success = await asyncio.to_thread(db_utils.add_feedback, user_id, feedback_message)
    if success:
        await update.message.reply_text("Thank you for your feedback! It has been recorded.")
        logger.info(f"Feedback received from user {user_id}: {feedback_message}")
    else:
        await update.message.reply_text("Sorry, there was an issue saving your feedback. Please try again later.")

async def enable_prompts_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    telegram_username = user.username or str(user_id)

    db_user_info = await asyncio.to_thread(db_utils.get_user, user_id)
    if not db_user_info:
        await asyncio.to_thread(db_utils.add_user, user_id, telegram_username)

    current_preferences = await asyncio.to_thread(db_utils.get_user_preferences, user_id)
    if current_preferences is None:
        current_preferences = {}

    new_prefs = current_preferences.copy()
    new_prefs['daily_prompt_enabled'] = True
    new_prefs['last_prompt_sent_date'] = None
    if 'preferred_prompt_time' not in new_prefs:
        new_prefs['preferred_prompt_time'] = '09:00'

    success = await asyncio.to_thread(db_utils.update_user_preferences, user_id, other_prefs=new_prefs)
    if success:
        await update.message.reply_text("Daily journal prompts have been enabled! You'll receive a prompt around 09:00 UTC (or your set time). The first prompt might arrive tomorrow.")
        logger.info(f"User {user_id} enabled daily prompts.")
    else:
        await update.message.reply_text("Sorry, there was an issue enabling daily prompts. Please try again.")

async def disable_prompts_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id
    success = await asyncio.to_thread(db_utils.update_user_preferences, user_id, other_prefs={'daily_prompt_enabled': False})
    if success:
        await update.message.reply_text("Daily journal prompts have been disabled.")
        logger.info(f"User {user_id} disabled daily prompts.")
    else:
        await update.message.reply_text("Sorry, there was an issue disabling daily prompts. Please try again.")

# --- DAILY PROMPT SCHEDULER ---
async def daily_prompt_scheduler(application: Application):
    """Periodically checks and sends daily prompts to users who opted in."""
    logger.info("Daily prompt scheduler started. Will check for users to prompt every hour.")
    while True:
        await asyncio.sleep(3600) # Check every hour (3600 seconds)
        logger.info("Running daily prompt scheduler check...")
        try:
            users_to_prompt = await asyncio.to_thread(db_utils.get_users_for_daily_prompt_check)
            if not users_to_prompt:
                logger.info("Daily prompt: No users to prompt at this time.")
                continue

            now_utc = datetime.now(timezone.utc)
            today_str = now_utc.strftime('%Y-%m-%d')

            for user_data in users_to_prompt:
                user_id = user_data['user_id']
                preferences_str = user_data.get('preferences')
                preferences = {}
                if preferences_str:
                    try:
                        preferences = json.loads(preferences_str)
                    except json.JSONDecodeError:
                        logger.error(f"Could not parse preferences JSON for user {user_id}: {preferences_str}")
                        continue

                if preferences.get('daily_prompt_enabled') and preferences.get('last_prompt_sent_date') != today_str:
                    preferred_time_str = preferences.get('preferred_prompt_time', '09:00') # Default to 09:00 UTC
                    try:
                        preferred_time_obj = datetime.strptime(preferred_time_str, '%H:%M').time()
                    except ValueError:
                        logger.warning(f"Invalid preferred_prompt_time format for user {user_id}: {preferred_time_str}. Using default 09:00 UTC.")
                        preferred_time_obj = datetime_time(9, 0) # Default to 09:00 UTC

                    # Check if current time is past preferred time for today
                    if now_utc.time() >= preferred_time_obj:
                        prompt_obj = await asyncio.to_thread(db_utils.get_random_daily_prompt)
                        if prompt_obj:
                            prompt_text = prompt_obj['prompt_text']
                            try:
                                await application.bot.send_message(chat_id=user_id, text=f"✨ Daily Journal Prompt ✨\n\n{prompt_text}")
                                preferences['last_prompt_sent_date'] = today_str
                                await asyncio.to_thread(db_utils.update_user_preferences, user_id, other_prefs=preferences)
                                logger.info(f"Sent daily prompt to user {user_id}.")
                            except Exception as e:
                                logger.error(f"Failed to send daily prompt to user {user_id}: {e}")
                        else:
                            logger.warning("No daily prompts available in the database to send.")
                    # else: # Optional: Log if it's not time yet
                        # logger.debug(f"User {user_id} has daily prompts enabled, but preferred time {preferred_time_str} has not passed yet today ({now_utc.time()}).")
                # else: # Optional: Log if already sent or disabled
                    # logger.debug(f"User {user_id} either has prompts disabled or already received one today.")

        except Exception as e:
            logger.error(f"Error in daily_prompt_scheduler: {e}", exc_info=True)


# --- CALLBACK QUERY HANDLER ---
async def mode_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    query = update.callback_query
    user = query.from_user
    await query.answer()
    chosen_mode = query.data
    context.user_data['current_mode'] = chosen_mode

    mode_texts = {CHATBOT_MODE: "Chatbot 💬", JOURNAL_MODE: "Journal 📓", OCR_MODE: "OCR 📄"}
    mode_text = mode_texts.get(chosen_mode, "Unknown")
    next_state = END

    try:
        message_text = f"Mode set to: *{escape_markdown(mode_text, version=2)}*\n"
        if chosen_mode == CHATBOT_MODE:
            next_state = CHATBOT_MODE
            message_text += escape_markdown("Send text, audio, or image.", version=2)
        elif chosen_mode == JOURNAL_MODE:
            next_state = JOURNAL_MODE
            message_text += escape_markdown("Send text, audio, or image for your entry.", version=2)
        elif chosen_mode == OCR_MODE:
            next_state = OCR_MODE
            message_text += escape_markdown("Send an image to extract text.", version=2)
        else:
            await query.edit_message_text(text="Invalid mode selected. Use /start again.")
            context.user_data.pop('current_mode', None)
            return END

        await query.edit_message_text(text=message_text, parse_mode=ParseMode.MARKDOWN_V2)
        logger.info(f"User {user.id} entered {mode_text} mode.")
        return next_state

    except telegram.error.BadRequest as e:
        logger.error(f"BadRequest editing mode message with MarkdownV2: {e}. Falling back to plain text.")
        try:
            await query.edit_message_text(text=f"Mode set to: {mode_text}. Please send input.")
            logger.info(f"User {user.id} entered {mode_text} mode (fallback message).")
        except Exception as fallback_e:
            logger.error(f"Failed plain text fallback edit: {fallback_e}")
        if chosen_mode in [CHATBOT_MODE, JOURNAL_MODE, OCR_MODE]:
            return chosen_mode
        else:
            context.user_data.pop('current_mode', None)
            return END
    except Exception as e:
        logger.error(f"Unexpected error in mode_button_callback: {e}", exc_info=True)
        try:
            await query.edit_message_text(text="An error occurred while selecting the mode. Please try again.")
        except Exception:
            pass
        context.user_data.pop('current_mode', None)
        return END

# --- INPUT PROCESSING & MODE-SPECIFIC LOGIC ---
async def get_text_from_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> tuple[str | None, str | None, str | None]:
    message = update.effective_message
    user_id = update.effective_user.id
    text_input, voice_input, photo_input = message.text, message.voice, message.photo
    temp_file_path, status_msg = None, None
    final_text = None
    input_type = None

    try:
        if text_input:
            return text_input, "text", None

        elif voice_input:
            input_type = "audio"
            status_msg = await message.reply_text("⬇️ Downloading audio...")
            temp_file_path = os.path.join(TEMP_DIR, f"{user_id}_{voice_input.file_unique_id}.ogg")
            audio_file = await voice_input.get_file()
            await audio_file.download_to_drive(temp_file_path)
            logger.info(f"Audio downloaded: {temp_file_path}")
            await status_msg.edit_text("🧠 Transcribing audio with AI...")
            raw_text = await transcribe_audio_with_gemini(temp_file_path, context)
            if raw_text is None or "[" in raw_text: # Check for None or error messages like "[BLOCKED...]"
                error_msg_to_return = raw_text or "❌ Transcription failed (Unknown error)."
                if status_msg: try: await status_msg.delete(); except Exception: pass
                return None, input_type, error_msg_to_return
            await status_msg.edit_text("✍️ Enhancing transcript...")
            punctuated_text = await add_punctuation_with_gemini(raw_text, context)
            if status_msg: await status_msg.delete()
            display_transcript = punctuated_text
            logger.info(f"Displaying transcript (len: {len(display_transcript)}) user {user_id}")
            header_text = escape_markdown(f"*Audio Transcript* (AI Enhanced):", version=2)
            try: await message.reply_text(header_text, parse_mode=ParseMode.MARKDOWN_V2)
            except Exception as e: logger.error(f"Error sending transcript header: {e}"); await message.reply_text("Audio Transcript (AI Enhanced):", parse_mode=None)
            safe_display_transcript = escape_markdown(display_transcript, version=2)
            max_len = 4000; chunks = [safe_display_transcript[i:i+max_len] for i in range(0, len(safe_display_transcript), max_len)]
            for i, chunk in enumerate(chunks):
                message_text = f"```\n{chunk}\n```"
                try: await message.reply_text(message_text, parse_mode=ParseMode.MARKDOWN_V2)
                except telegram.error.BadRequest as e: logger.error(f"BadRequest transcript chunk {i+1}: {e}. Plain."); await message.reply_text(display_transcript[i*max_len:(i+1)*max_len], parse_mode=None)
                except Exception as e: logger.error(f"Error sending transcript chunk {i+1}: {e}"); await message.reply_text(f"[Error display part {i+1}]")
            final_text = punctuated_text

        elif photo_input:
            input_type = "image"; status_msg = await message.reply_text("⬇️ Downloading image...")
            photo = photo_input[-1]; temp_file_path = os.path.join(TEMP_DIR, f"{user_id}_{photo.file_unique_id}.jpg")
            img_file = await photo.get_file(); await img_file.download_to_drive(temp_file_path)
            logger.info(f"Image downloaded: {temp_file_path}"); await status_msg.edit_text("📄 Processing image with AI Vision (OCR)...")
            extracted_text_result = None
            try:
                with PIL.Image.open(temp_file_path) as img:
                    ocr_prompt = "Extract text accurately from this image, preserving line breaks if possible."
                    extracted_text_result, _ = await generate_gemini_response([ocr_prompt, img], context=context)
            except FileNotFoundError: logger.error(f"Image gone before processing? {temp_file_path}"); return None, input_type, "Error finding image."
            except Exception as img_err: logger.error(f"Error opening/processing image {temp_file_path}: {img_err}"); return None, input_type, "Error processing image file."
            if status_msg: await status_msg.delete()
            if extracted_text_result is None or "[API ERROR:" in extracted_text_result: return None, input_type, extracted_text_result or "❌ AI Vision OCR failed."
            if "[BLOCKED:" in extracted_text_result: return None, input_type, f"❌ AI Vision OCR failed ({extracted_text_result})."
            if not extracted_text_result or "[No text content received]" in extracted_text_result: return None, input_type, "AI Vision found no text in the image."
            final_text = extracted_text_result
        else:
            return None, None, "Unsupported message type."
        return final_text, input_type, None
    except Exception as e:
        logger.error(f"Error in get_text_from_input main try block: {e}", exc_info=True)
        if status_msg: try: await status_msg.delete(); except Exception: pass
        return None, input_type, "An unexpected error occurred processing your input."
    finally:
        if temp_file_path and os.path.exists(temp_file_path):
            try: os.remove(temp_file_path); logger.info(f"Temp file deleted: {temp_file_path}")
            except OSError as e_del_file: logger.error(f"Error deleting temp file {temp_file_path}: {e_del_file}")
        if status_msg: try: await status_msg.delete(); except Exception as e_del_msg: logger.warning(f"Could not delete status message: {e_del_msg}")

async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user = update.effective_user
    user_id = user.id
    mode = context.user_data.get('current_mode')
    if not mode:
        await update.message.reply_text("Please select a mode first using /start.")
        return

    # Ensure user exists for all interactions
    telegram_username = user.username or str(user_id)
    # Using asyncio.to_thread for potentially blocking DB calls
    db_user_info = await asyncio.to_thread(db_utils.get_user, user_id)
    if not db_user_info:
        await asyncio.to_thread(db_utils.add_user, user_id, telegram_username, display_name=user.first_name or telegram_username)

    extracted_text, input_type, error_message = await get_text_from_input(update, context)

    if error_message:
        await update.message.reply_text(error_message)
        return
    if extracted_text is None:
        await update.message.reply_text("Could not process your input. Please try again.")
        return

    if mode == CHATBOT_MODE:
        await handle_chatbot_logic(update, context, extracted_text)
    elif mode == JOURNAL_MODE:
        await handle_journal_logic(update, context, extracted_text, input_type)
    elif mode == OCR_MODE:
        await handle_ocr_logic(update, context, extracted_text, input_type)
    else:
        logger.error(f"Invalid mode '{mode}' in handle_input for user {user_id}")
        await update.message.reply_text("Internal error: Invalid mode selected. Please try /start again.")

# Mode-Specific Logic Functions
async def handle_chatbot_logic(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str):
    user_id = update.effective_user.id
    logger.info(f"Chatbot logic: User {user_id} sent text (length: {len(text)})")
    status_msg = await update.message.reply_text("🤔 Thinking...")
    response_text, _ = await generate_gemini_response([text], context=context)
    if response_text is None or "[API ERROR:" in response_text:
        await status_msg.edit_text(f"Sorry, there was an error communicating with the AI. {response_text or ''}")
    elif "[BLOCKED:" in response_text:
        await status_msg.edit_text(f"My response was blocked: {response_text}")
    else:
        reversed_text = reverse_alphabet(response_text) # Apply reverse_alphabet
        await status_msg.edit_text(reversed_text, parse_mode=None)

async def handle_journal_logic(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, input_type: str):
    user = update.effective_user
    user_id = user.id
    telegram_username = user.username or str(user_id)

    db_user_info = await asyncio.to_thread(db_utils.get_user, user_id)
    display_name = telegram_username
    if db_user_info:
        display_name = db_user_info.get('display_name') if db_user_info.get('display_name') else telegram_username
    else:
        initial_display_name = user.first_name or telegram_username
        await asyncio.to_thread(db_utils.add_user, user_id, telegram_username, display_name=initial_display_name)
        db_user_info = await asyncio.to_thread(db_utils.get_user, user_id) # Re-fetch
        if db_user_info and db_user_info.get('display_name'): display_name = db_user_info['display_name']
        elif user.first_name: display_name = user.first_name


    now = datetime.now(timezone.utc)
    logger.info(f"Journal logic for user {user_id} ('{display_name}'). Input type: {input_type}, Text length: {len(text)}")

    status_msg = await update.message.reply_text("💾 Saving your thoughts...")

    word_count = len(text.split())
    entry_id = await asyncio.to_thread(db_utils.add_journal_entry,
                                     user_id=user_id,
                                     raw_text=text,
                                     input_type=input_type,
                                     word_count=word_count)

    if not entry_id:
        await status_msg.edit_text("❌ Oops! There was an error saving your journal entry. Please try again.")
        logger.error(f"Failed to save journal entry for user {user_id}")
        return

    await status_msg.edit_text("📊 Analyzing your entry...")
    categorization_prompt_template = f"""Analyze the following journal entry for user {display_name}:
---
{{text}}
---
Provide:
1. Sentiment: (e.g., Positive, Negative, Neutral, Mixed, Anxious, Hopeful, etc. - be specific if possible)
2. Topics: (e.g., Work, Family, Personal Growth, Hobbies, Current Events - list up to 3 comma-separated topics, or 'None' if not applicable)
3. Categories: (Choose up to 3 relevant categories from this list: {', '.join(JOURNAL_CATEGORIES_LIST)}. If none seem to fit well, suggest 'Other' or a more specific category if evident from the text. List as comma-separated.)

Format your response *exactly* as follows, with each item on a new line, and do not add any extra text or explanations:
Sentiment: [Identified Sentiment]
Topics: [Identified Topics]
Categories: [Chosen Categories]"""
    categorization_prompt = categorization_prompt_template.format(text=text)

    categorization_response, _ = await generate_gemini_response([categorization_prompt], context=context)

    sentiment, topics, categories = "N/A", "N/A", "N/A"
    if categorization_response and not any(err_tag in categorization_response for err_tag in ["[BLOCKED:", "[API ERROR:", "[No text content received]"]):
        sentiment_match = re.search(r"Sentiment:\s*(.*)", categorization_response, re.IGNORECASE)
        topics_match = re.search(r"Topics:\s*(.*)", categorization_response, re.IGNORECASE)
        categories_match = re.search(r"Categories:\s*(.*)", categorization_response, re.IGNORECASE)

        if sentiment_match: sentiment = sentiment_match.group(1).strip()
        if topics_match: topics = topics_match.group(1).strip()
        if categories_match: categories = categories_match.group(1).strip()

        logger.info(f"Categorization for entry ID {entry_id}: Sentiment={sentiment}, Topics={topics}, Categories={categories}")
        await asyncio.to_thread(db_utils.update_journal_entry_analysis, entry_id, sentiment=sentiment, topics=topics, categories=categories)
    else:
        logger.warning(f"Categorization failed or was blocked for entry ID {entry_id}. Response: {categorization_response}")
        await update.message.reply_text(f"⚠️ AI categorization of your entry encountered an issue. It's saved, but some insights might be missing. Details: {categorization_response or 'No response'}")

    await status_msg.edit_text("🧠 Thinking about your entry...")

    recent_entries_from_db = await asyncio.to_thread(db_utils.get_journal_entries_by_user, user_id, limit=5)
    history_context_parts = []
    if recent_entries_from_db:
        history_context_parts.append(f"\n\nHere are summaries of some of your recent entries, {escape_markdown(display_name, version=2)}:")
        for entry in reversed(recent_entries_from_db):
            if entry['entry_id'] == entry_id:
                continue
            entry_ts_str = entry.get('timestamp')
            entry_ts_formatted = "earlier"
            if entry_ts_str:
                try:
                    entry_dt = datetime.fromisoformat(str(entry_ts_str).replace('Z', '+00:00')) if 'Z' in str(entry_ts_str) else datetime.fromisoformat(str(entry_ts_str))
                    entry_ts_formatted = entry_dt.strftime('%Y-%m-%d %H:%M')
                except (ValueError, TypeError) as e_ts:
                    logger.error(f"Error parsing timestamp '{entry_ts_str}' for entry {entry.get('entry_id')}: {e_ts}")
            history_context_parts.append(f"- On {entry_ts_formatted}: {escape_markdown(entry['raw_text'][:100], version=2)}... (Sentiment: {escape_markdown(entry.get('sentiment', 'N/A'),version=2)}, Topics: {escape_markdown(entry.get('topics', 'N/A'),version=2)})")

    history_context = "".join(history_context_parts) if history_context_parts else "\n\nThis seems to be one of your first entries, or I couldn't retrieve recent history."

    current_entry_summary = f"User's name: {escape_markdown(display_name, version=2)}\nThe user's latest journal entry (submitted on {now.strftime('%Y-%m-%d %H:%M:%S %Z')} with input type '{input_type}', AI-detected sentiment '{escape_markdown(sentiment,version=2)}', AI-detected topics '{escape_markdown(topics,version=2)}', and AI-detected categories '{escape_markdown(categories,version=2)}') is:\n---\n{escape_markdown(text,version=2)}\n---"

    therapist_analysis_prompt_template = f"""Act as a thoughtful and empathetic journaling assistant. The user, {{display_name}}, has provided the following journal entry:

{{current_entry_summary}}

{{history_context}}

Considering the current entry and any available history, please provide a concise (2-3 paragraphs), empathetic, and insightful analysis. Focus on potential patterns, underlying feelings, or themes. Offer 1-2 gentle, actionable suggestions or reflective questions that might help {{display_name}}. Avoid giving direct medical advice. Address the user as {{display_name}}.

Also, generate a DOT language representation for a mind map visualizing the key themes and connections in the *current* entry. The mind map should be simple and clear. Format this DOT code *exactly* between '--- DOT START ---' and '--- DOT END ---' markers. Ensure the DOT code is valid and self-contained.

**Analysis for {{display_name}}:**
[Your insightful analysis here]

--- DOT START ---
digraph JournalMap {{
    rankdir=LR;
    bgcolor="transparent";
    node [shape=box, style="rounded,filled", fillcolor=lightblue, fontname="Arial", fontsize=10];
    edge [arrowhead=none, color="#555555"];
    main [label="{{text_summary}}..."];
    senti [label="Sentiment: {{sentiment}}"];
    main -> senti;
    {{topics_dot}}
    {{categories_dot}}
}}
--- DOT END ---
"""
    # Sanitize inputs for DOT label (simple replacement)
    clean_text_summary = text[:30].replace('"', '').replace('\n', ' ').replace('{', '(').replace('}', ')')
    clean_sentiment = sentiment.replace('"', '').replace('{', '(').replace('}', ')')

    topics_dot_str = ' '.join([f'topic{i} [label="Topic: {topic.strip().replace("-", "_").replace(" ", "_").replace("'", "").replace("`", "").replace("""\"""", "")}", fillcolor="lightgreen"]; main -> topic{i};' for i, topic in enumerate(str(topics).split(',')) if topic.strip() and topic != 'N/A'])
    categories_dot_str = ' '.join([f'cat{i} [label="Category: {category.strip().replace("-", "_").replace(" ", "_").replace("'", "").replace("`", "").replace("""\"""", "")}", fillcolor="lightcoral"]; main -> cat{i};' for i, category in enumerate(str(categories).split(',')) if category.strip() and category != 'N/A'])

    therapist_analysis_prompt = therapist_analysis_prompt_template.format(
        display_name=display_name,
        current_entry_summary=current_entry_summary,
        history_context=history_context,
        text_summary=clean_text_summary,
        sentiment=clean_sentiment,
        topics_dot=topics_dot_str,
        categories_dot=categories_dot_str
    )

    analysis_response_text, _ = await generate_gemini_response([therapist_analysis_prompt], context=context)
    ai_analysis_output_for_user = "Sorry, I couldn't generate an analysis for this entry."
    dot_code_for_db = None
    ai_analysis_text_for_db = None

    if analysis_response_text and not any(err_tag in analysis_response_text for err_tag in ["[BLOCKED:", "[API ERROR:", "[No text content received]"]):
        dot_match = re.search(r"--- DOT START ---([\s\S]*?)--- DOT END ---", analysis_response_text, re.DOTALL)
        analysis_text_part = analysis_response_text
        if dot_match:
            dot_code_for_db = dot_match.group(1).strip()
            analysis_output_candidate = analysis_response_text.split("--- DOT START ---")[0]
            # Use a more generic marker if display_name can have markdown characters
            reflection_marker_generic = "**Analysis for "
            if reflection_marker_generic in analysis_output_candidate:
                 # Find the end of the display name in the marker for splitting
                marker_end_index = analysis_output_candidate.find(":**") + 3 # Length of ":**"
                ai_analysis_output_for_user = analysis_output_candidate[marker_end_index:].strip()

            else:
                ai_analysis_output_for_user = analysis_output_candidate.strip()
            logger.info(f"Extracted AI analysis (len: {len(ai_analysis_output_for_user)}) and DOT code (len: {len(dot_code_for_db)}) for entry {entry_id}")
        else:
            ai_analysis_output_for_user = analysis_response_text # No DOT code found, use the whole response as analysis
            logger.warning(f"DOT markers not found in AI analysis for entry {entry_id}")

        ai_analysis_text_for_db = ai_analysis_output_for_user # Store the user-facing analysis
        await asyncio.to_thread(db_utils.update_journal_entry_analysis, entry_id, ai_analysis_text=ai_analysis_text_for_db, dot_code=dot_code_for_db)
    elif analysis_response_text: # It was blocked or API error
        ai_analysis_output_for_user = f"AI analysis was blocked or encountered an error: {analysis_response_text}"
        logger.warning(f"AI analysis failed/blocked for entry {entry_id}: {analysis_response_text}")
        await asyncio.to_thread(db_utils.update_journal_entry_analysis, entry_id, ai_analysis_text=ai_analysis_output_for_user, dot_code=None)

    safe_ai_analysis_output = escape_markdown(ai_analysis_output_for_user, version=2)
    try:
        await status_msg.edit_text(safe_ai_analysis_output, parse_mode=ParseMode.MARKDOWN_V2)
    except telegram.error.BadRequest:
        logger.warning("Markdown error in AI analysis output, sending as plain text.")
        await status_msg.edit_text(ai_analysis_output_for_user, parse_mode=None)


    if dot_code_for_db:
        map_status_msg = await update.message.reply_text("🗺️ Generating mind map...")
        mind_map_image_path = await generate_mind_map_image(dot_code_for_db, user_id)
        if mind_map_image_path:
            try:
                with open(mind_map_image_path, 'rb') as photo_file:
                    await update.message.reply_photo(photo=photo_file, caption="Mind map of your entry.")
                await map_status_msg.delete()
            except Exception as e:
                logger.error(f"Error sending mind map for entry {entry_id}: {e}")
                await map_status_msg.edit_text("⚠️ Error sending the mind map image.")
            finally:
                if os.path.exists(mind_map_image_path):
                    try: os.remove(mind_map_image_path)
                    except OSError as e_del: logger.error(f"Error deleting mind map image file {mind_map_image_path}: {e_del}")
        else:
            await map_status_msg.edit_text("⚠️ Could not generate the mind map from the provided data.")
    else:
        await update.message.reply_text("(Mind map could not be generated for this entry.)")

    await update.message.reply_text("✅ Your journal entry has been fully processed!")


async def handle_ocr_logic(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, input_type: str):
    if input_type != "image":
         await update.message.reply_text("OCR mode requires an image input.")
         return

    logger.info(f"OCR mode sending extracted text (len: {len(text)}) to user {update.effective_user.id}")

    header_text = escape_markdown("*Extracted Text (AI Vision OCR):*", version=2)
    try:
        await update.message.reply_text(header_text, parse_mode=ParseMode.MARKDOWN_V2)
    except telegram.error.BadRequest as e:
         logger.error(f"BadRequest sending OCR header: {e}. Sending plain.")
         await update.message.reply_text("Extracted Text (AI Vision OCR):", parse_mode=None)
    except Exception as e:
         logger.error(f"Error sending OCR header: {e}")

    safe_extracted_text = escape_markdown(text, version=2)
    max_len = 4000
    chunks = [safe_extracted_text[i:i+max_len] for i in range(0, len(safe_extracted_text), max_len)]
    for i, chunk in enumerate(chunks):
        message_text = f"```\n{chunk}\n```"
        try:
            await update.message.reply_text(message_text, parse_mode=ParseMode.MARKDOWN_V2)
        except telegram.error.BadRequest as e:
            logger.error(f"BadRequest sending OCR chunk {i+1}: {e}. Sending plain."); plain_text_chunk = text[i*max_len:(i+1)*max_len]; await update.message.reply_text(plain_text_chunk, parse_mode=None)
        except Exception as e:
             logger.error(f"Error sending OCR chunk {i+1}: {e}"); await update.message.reply_text(f"[Error display part {i+1}]")

# --- POST INIT FUNCTION ---
async def post_init_tasks(application: Application) -> None:
    # Ensure database and tables are created before starting the scheduler
    try:
        db_path = db_utils.DATABASE_PATH # Get DB path from db_utils
        os.makedirs(os.path.dirname(db_path), exist_ok=True) # Ensure directory for DB exists

        # Use database_setup to create tables initially if it's preferred for setup logic
        conn_setup = database_setup.create_connection(db_path)
        if conn_setup:
            database_setup.create_tables(conn_setup) # This uses the setup script's table defs
            conn_setup.close()
            logger.info(f"Database tables ensured by database_setup.py at {db_path} from post_init_tasks.")
        else:
            logger.error(f"Failed to establish database connection via database_setup.py in post_init_tasks at {db_path}.")

    except Exception as e:
        logger.error(f"Error during database_setup in post_init_tasks: {e}", exc_info=True)

    await post_set_commands(application)
    await initialize_token_data()
    asyncio.create_task(daily_prompt_scheduler(application))
    logger.info("Daily prompt scheduler task created.")

async def post_set_commands(application: Application) -> None:
    commands = [
        BotCommand("start", "Start / Select Mode"),
        BotCommand("mode", "Re-select Mode"),
        BotCommand("changemode", "Re-select Mode"),
        BotCommand("setusername", "Set display name"),
        BotCommand("tokens", "Check AI token usage"),
        BotCommand("feedback", "Provide feedback about the bot"),
        BotCommand("enableprompts", "Enable daily journal prompts"),
        BotCommand("disableprompts", "Disable daily journal prompts"),
        BotCommand("end", "End current session"),
        BotCommand("help", "Show help"),
        BotCommand("cancel", "Cancel action / New Mode")
    ]
    try:
        await application.bot.set_my_commands(commands)
        logger.info("Bot commands menu set.")
    except Exception as e:
        logger.error(f"Failed to set bot commands: {e}")

# --- GLOBAL ERROR HANDLER ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Exception while handling an update: {context.error}", exc_info=context.error)
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("Sorry, an unexpected error occurred. Please try again later, or use /start.")
        except Exception as e:
            logger.error(f"Failed to send error message to user: {e}")

# --- MAIN FUNCTION ---
def main() -> None:
    logger.info("Starting bot setup...")

    # Initial database setup using database_setup.py
    # This ensures tables are created before any bot operations that might need them.
    try:
        db_path = db_utils.DATABASE_PATH # Centralized DB path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        conn = database_setup.create_connection(db_path)
        if conn:
            database_setup.create_tables(conn) # Creates all tables from database_setup.py
            conn.close()
            logger.info(f"Initial database tables ensured by database_setup.py at {db_path} from main.")
        else:
            logger.error(f"Failed to establish initial database connection via database_setup.py at {db_path} from main.")
    except Exception as e:
        logger.error(f"Error during initial database_setup in main: {e}", exc_info=True)


    application = (
        ApplicationBuilder()
        .token(TELEGRAM_TOKEN)
        .post_init(post_init_tasks)
        .build()
    )

    application.add_error_handler(error_handler)

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler('start', start_command),
            CommandHandler('mode', start_command),
            CommandHandler('changemode', start_command)
        ],
        states={
            SELECTING_MODE: [CallbackQueryHandler(mode_button_callback)],
            CHATBOT_MODE: [MessageHandler(filters.ChatType.PRIVATE & (filters.TEXT | filters.VOICE | filters.PHOTO | filters.Document.IMAGE) & ~filters.COMMAND, handle_input)],
            JOURNAL_MODE: [MessageHandler(filters.ChatType.PRIVATE & (filters.TEXT | filters.VOICE | filters.PHOTO | filters.Document.IMAGE) & ~filters.COMMAND, handle_input)],
            OCR_MODE: [
                MessageHandler(filters.ChatType.PRIVATE & (filters.PHOTO | filters.Document.IMAGE) & ~filters.COMMAND, handle_input),
                MessageHandler(filters.ChatType.PRIVATE & (filters.TEXT | filters.VOICE) & ~filters.COMMAND, lambda u,c: u.message.reply_text("OCR mode requires an image."))
            ],
        },
        fallbacks=[
            CommandHandler('cancel', cancel_command),
            CommandHandler('end', end_session_command),
            CommandHandler('start', start_command),
            CommandHandler('mode', start_command),
            CommandHandler('changemode', start_command),
            CommandHandler('help', help_command),
            CommandHandler('setusername', set_username_command),
            CommandHandler('tokens', tokens_command),
            CommandHandler('feedback', feedback_command),
            CommandHandler('enableprompts', enable_prompts_command),
            CommandHandler('disableprompts', disable_prompts_command),
        ],
        allow_reentry=True
    )
    application.add_handler(conv_handler)

    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("setusername", set_username_command))
    application.add_handler(CommandHandler("tokens", tokens_command))
    application.add_handler(CommandHandler("feedback", feedback_command))
    application.add_handler(CommandHandler("enableprompts", enable_prompts_command))
    application.add_handler(CommandHandler("disableprompts", disable_prompts_command))

    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND & filters.ChatType.PRIVATE,
        lambda u, c: u.message.reply_text("Please use /start or /mode to begin, or /help for more options.")
    ))

    logger.info("Bot setup complete. Starting polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
    logger.info("Bot polling stopped.")

if __name__ == "__main__":
    main()

[end of New_Main.py]
