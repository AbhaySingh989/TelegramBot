# -*- coding: utf-8 -*-

# --- IMPORTS ---
import logging
import os
import re
import json
import csv
from datetime import datetime
import io
import asyncio

# Telegram
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import (
    Application, CommandHandler, MessageHandler, filters,
    ContextTypes, ConversationHandler, CallbackQueryHandler,
    ApplicationBuilder # Added for error handler setup
)
from telegram.constants import ParseMode
from telegram.helpers import escape_markdown # Important for MarkdownV2

# Google Gemini
import google.generativeai as genai
from google.generativeai.types import GenerationConfig, SafetySettingDict, HarmCategory, HarmBlockThreshold
from google.generativeai import types as genai_types

# File / Environment
from dotenv import load_dotenv
import PIL.Image # Pillow for image handling

# Audio Processing
# import speech_recognition as sr
# from pydub import AudioSegment
# Ensure FFmpeg is installed and in PATH

# Visualization
import graphviz

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
SELECTING_MODE, CHATBOT_MODE, JOURNAL_MODE, OCR_MODE, SETTING_USERNAME = ("SELECTING_MODE", "CHATBOT_MODE", "JOURNAL_MODE", "OCR_MODE", "SETTING_USERNAME")
END = ConversationHandler.END
BASE_DIR = os.path.dirname(os.path.abspath(__file__)); DATA_DIR = os.path.join(BASE_DIR, "bot_data"); TEMP_DIR = os.path.join(DATA_DIR, "temp")
JOURNAL_FILE = os.path.join(DATA_DIR, "journal.csv"); PROFILES_FILE = os.path.join(DATA_DIR, "user_profiles.json"); TOKEN_USAGE_FILE = os.path.join(DATA_DIR, "token_usage.json")
VISUALIZATIONS_DIR = os.path.join(DATA_DIR, "visualizations")
JOURNAL_HEADERS = ["Username", "UserID", "Date", "Time", "Raw Text", "Sentiment", "Topics", "Categories", "Word Count", "Input Type", "Entry ID"]
JOURNAL_CATEGORIES_LIST = ["Emotional", "Family", "Grief", "Workplace", "Technology", "AI", "Spouse", "Kid", "Personal Reflection", "Health", "Finance", "Social", "Hobby", "Other"]

# --- ENSURE DIRECTORIES EXIST ---
for dir_path in [DATA_DIR, TEMP_DIR, VISUALIZATIONS_DIR]: os.makedirs(dir_path, exist_ok=True)

# --- FILE ACCESS LOCK ---
file_lock = asyncio.Lock()

# --- HELPER FUNCTIONS ---

# Profile Management (No changes)
async def load_profiles() -> dict:
    async with file_lock:
        try:
            if os.path.exists(PROFILES_FILE):
                with open(PROFILES_FILE, 'r', encoding='utf-8') as f: return json.load(f)
        except Exception as e: logger.error(f"Error loading profiles: {e}")
        return {}
async def save_profiles(profiles: dict) -> bool:
    async with file_lock:
        try:
            with open(PROFILES_FILE, 'w', encoding='utf-8') as f: json.dump(profiles, f, indent=4)
            return True
        except Exception as e: logger.error(f"Error saving profiles: {e}"); return False

# Token Tracking (No changes)
async def load_token_data() -> dict:
    async with file_lock:
        default_data = {"total": 0, "daily": {"date": "", "count": 0}, "session": 0}
        try:
            if os.path.exists(TOKEN_USAGE_FILE):
                with open(TOKEN_USAGE_FILE, 'r', encoding='utf-8') as f: data = json.load(f); data.setdefault("total", 0); data.setdefault("daily", {}).setdefault("date",""); data["daily"].setdefault("count",0); data.setdefault("session",0); return data
        except Exception as e: logger.error(f"Error loading token data: {e}")
        return default_data
async def save_token_data(data: dict) -> bool:
    async with file_lock:
        try:
            with open(TOKEN_USAGE_FILE, 'w', encoding='utf-8') as f: json.dump(data, f, indent=4)
            return True
        except Exception as e: logger.error(f"Error saving token data: {e}"); return False
token_data_cache = {"session": 0}
async def initialize_token_data():
    global token_data_cache; loaded_data = await load_token_data(); token_data_cache = loaded_data; token_data_cache['session'] = 0; await save_token_data(token_data_cache); logger.info("Token data initialized.")
async def increment_token_usage(prompt_tokens: int = 0, candidate_tokens: int = 0, context: ContextTypes.DEFAULT_TYPE = None):
    global token_data_cache; today = datetime.now().strftime("%Y-%m-%d"); total_increment = prompt_tokens + candidate_tokens; current_data = await load_token_data()
    if current_data.get("daily", {}).get("date") != today: current_data["daily"] = {"date": today, "count": 0}
    current_data["total"] = current_data.get("total", 0) + total_increment; current_data["daily"]["count"] = current_data["daily"].get("count", 0) + total_increment
    token_data_cache["session"] = token_data_cache.get("session", 0) + total_increment; current_data["session"] = token_data_cache["session"]
    if not await save_token_data(current_data): logger.error("Failed to save updated token data!")
    logger.info(f"Tokens Used - Prompt: {prompt_tokens}, Candidate: {candidate_tokens}, Session: {token_data_cache['session']}")

# Gemini API Call Wrapper (No changes)
async def generate_gemini_response(prompt_parts: list, safety_settings_override=None, context: ContextTypes.DEFAULT_TYPE = None) -> tuple[str | None, dict | None]:
    if not genai_model: logger.error("Gemini model not initialized."); return None, None
    usage_metadata = None; text_response = None
    try:
        logger.info(f"Sending request to Gemini ({len(prompt_parts)} parts)...")
        response = await genai_model.generate_content_async(prompt_parts, safety_settings=safety_settings_override if safety_settings_override else safety_settings)
        if hasattr(response, 'usage_metadata'):
            usage_metadata = response.usage_metadata; await increment_token_usage(usage_metadata.prompt_token_count, usage_metadata.candidates_token_count, context)
        if response.prompt_feedback and response.prompt_feedback.block_reason:
            block_reason = response.prompt_feedback.block_reason; logger.warning(f"Gemini request blocked: {block_reason}"); return f"[BLOCKED: {block_reason}]", usage_metadata
        if hasattr(response, 'text'): text_response = response.text; logger.info(f"Received response from Gemini ({len(text_response) if text_response else 0} chars).")
        elif not (response.prompt_feedback and response.prompt_feedback.block_reason): logger.warning("Gemini returned no text content."); text_response = "[No text content received]"
        return text_response, usage_metadata
    except (genai_types.BlockedPromptException, genai_types.StopCandidateException) as safety_exception:
        logger.warning(f"Gemini Safety Exception ({type(safety_exception).__name__}): {safety_exception}"); response_obj = getattr(safety_exception, 'response', None); text_response = "[BLOCKED/STOPPED]"
        if response_obj:
             if hasattr(response_obj, 'text'): text_response = response_obj.text + f" [{type(safety_exception).__name__}]"
             if hasattr(response_obj, 'usage_metadata'):
                 usage_metadata = response_obj.usage_metadata; await increment_token_usage(usage_metadata.prompt_token_count, usage_metadata.candidates_token_count, context)
        return text_response, usage_metadata
    except Exception as e: logger.error(f"Error calling Gemini API: {e}", exc_info=True); return f"[API ERROR: {type(e).__name__}]", None

# Gemini Punctuation Helper (No changes)
async def add_punctuation_with_gemini(raw_text: str, context: ContextTypes.DEFAULT_TYPE = None) -> str:
    if not raw_text or raw_text.strip() == "": return raw_text
    if not genai_model: logger.warning("Gemini unavailable for punctuation."); return raw_text
    prompt = f"""Add appropriate punctuation, capitalization, and sentence breaks to the following raw text. Make it read naturally. Preserve original words/meaning.

    Raw Text: "{raw_text}"

    Formatted Text:"""
    logger.info("Sending raw transcript to Gemini for punctuation...")
    formatted_text, _ = await generate_gemini_response([prompt], context=context)
    if formatted_text and "[BLOCKED:" not in formatted_text and "[API ERROR:" not in formatted_text and "[No text content received]" not in formatted_text:
        logger.info("Punctuation added successfully."); return formatted_text.strip()
    else: logger.warning(f"Failed to punctuate: {formatted_text}. Returning raw."); return raw_text

# --- MODIFIED: Audio Transcription using Gemini ---
async def transcribe_audio_with_gemini(audio_path: str, context: ContextTypes.DEFAULT_TYPE = None) -> str | None:
    """
    Transcribes audio file directly using Gemini.
    Returns raw transcribed text or an error message string starting with [].
    """
    if not os.path.exists(audio_path):
        logger.error(f"Audio file not found for Gemini transcription: {audio_path}")
        return "[File Not Found Error]"
    if not genai_model: # Check if Gemini model is available
        logger.error("Gemini model not available for audio transcription.")
        return "[AI Service Unavailable]"

    try:
        logger.info(f"Uploading audio file {os.path.basename(audio_path)} to Gemini...")
        # Upload the file first (recommended for larger files)
        audio_file_obj = genai.upload_file(path=audio_path)
        logger.info(f"Completed uploading '{audio_file_obj.display_name}'.")

        # Prompt Gemini to transcribe
        prompt = "Transcribe the following audio file accurately."
        logger.info("Sending audio transcription request to Gemini...")

        # Make the LLM call including the uploaded file
        response = await genai_model.generate_content_async(
            [prompt, audio_file_obj],
            # Request JSON output if needed for more structure, but text is fine for transcription
            # generation_config=genai.types.GenerationConfig(response_mime_type="application/json")
        )

        # Process response and count tokens (metadata might be different for file inputs)
        # Note: Token counting for direct file inputs might be less precise via simple metadata.
        # For simplicity, we are not incrementing tokens accurately here for audio files.
        # Proper counting might require analyzing the response object structure further.
        # if hasattr(response, 'usage_metadata'):
        #     await increment_token_usage(response.usage_metadata.prompt_token_count, response.usage_metadata.candidates_token_count, context)

        # Check for blocks
        if response.prompt_feedback and response.prompt_feedback.block_reason:
            block_reason = response.prompt_feedback.block_reason
            logger.warning(f"Gemini audio transcription blocked: {block_reason}")
            return f"[BLOCKED: {block_reason}]"

        # Extract text
        if hasattr(response, 'text'):
            raw_text = response.text.strip()
            logger.info(f"Gemini raw transcription successful ({len(raw_text)} chars).")
            # Clean up the uploaded file on Gemini side AFTER getting response
            try:
                await genai.delete_file_async(audio_file_obj.name)
                logger.info(f"Deleted uploaded file '{audio_file_obj.name}' from Gemini.")
            except Exception as del_e:
                logger.warning(f"Could not delete uploaded audio file {audio_file_obj.name} from Gemini: {del_e}")
            return raw_text
        else:
            logger.warning("Gemini audio transcription returned no text content.")
            return "[No transcription content]" # Return specific message

    except Exception as e:
        logger.error(f"Error during Gemini audio transcription: {e}", exc_info=True)
        # Provide a more specific error if possible
        return f"[AI Transcription Error: {type(e).__name__}]"
    # No need for finally block to delete local WAV as we don't create one



# Journal CSV Handling (No changes)
async def initialize_journal_csv():
    async with file_lock:
        if not os.path.exists(JOURNAL_FILE):
            try:
                with open(JOURNAL_FILE, 'w', newline='', encoding='utf-8') as f: csv.writer(f).writerow(JOURNAL_HEADERS)
                logger.info(f"Journal CSV created: {JOURNAL_FILE}")
            except IOError as e: logger.error(f"Failed to create journal CSV: {e}")
async def append_journal_entry(entry_data: dict) -> str | None:
    for header in JOURNAL_HEADERS: entry_data.setdefault(header, "")
    entry_data["Entry ID"] = f"{entry_data['UserID']}_{datetime.now().strftime('%Y%m%d%H%M%S%f')}"
    async with file_lock:
        try:
            file_exists = os.path.exists(JOURNAL_FILE); write_header = not file_exists or os.path.getsize(JOURNAL_FILE) == 0
            with open(JOURNAL_FILE, 'a', newline='', encoding='utf-8') as f:
                writer = csv.DictWriter(f, fieldnames=JOURNAL_HEADERS)
                if write_header: writer.writeheader()
                writer.writerow(entry_data)
            logger.info(f"Appended journal entry ID: {entry_data['Entry ID']}")
            return entry_data["Entry ID"]
        except Exception as e: logger.error(f"Error appending journal entry: {e}", exc_info=True); return None
async def update_journal_entry(entry_id: str, update_data: dict):
    if not entry_id: return False; updated = False
    async with file_lock:
        rows = []; reader_ok = False
        try:
            with open(JOURNAL_FILE, 'r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f); reader_ok = reader.fieldnames and all(h in reader.fieldnames for h in ["Entry ID"])
                if not reader_ok: logger.error("Journal CSV missing headers! Update aborted."); return False
                rows = list(reader)
            for row in rows:
                if row.get("Entry ID") == entry_id:
                    for key, value in update_data.items():
                        if key in JOURNAL_HEADERS: row[key] = value
                    updated = True; break
            if updated:
                with open(JOURNAL_FILE, 'w', newline='', encoding='utf-8') as f:
                    writer = csv.DictWriter(f, fieldnames=rows[0].keys()); writer.writeheader(); writer.writerows(rows)
                logger.info(f"Updated journal entry ID: {entry_id}"); return True
            else: logger.warning(f"Journal entry ID {entry_id} not found for update."); return False
        except Exception as e: logger.error(f"Error updating journal CSV for {entry_id}: {e}", exc_info=True); return False
async def read_journal_entries(user_id: int | None = None) -> list[dict]:
    entries = []
    async with file_lock:
        try:
            if not os.path.exists(JOURNAL_FILE): return []
            with open(JOURNAL_FILE, 'r', newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f);
                if not reader.fieldnames: return []
                for row in reader:
                    try:
                        row_user_id = row.get("UserID")
                        if user_id is None or (row_user_id and int(row_user_id) == user_id): entries.append(row)
                    except (ValueError, TypeError): logger.warning(f"Skipping row with invalid UserID: {row}"); continue
            entries.sort(key=lambda x: (x.get("Date", ""), x.get("Time", ""))); return entries
        except Exception as e: logger.error(f"Error reading journal CSV: {e}", exc_info=True); return []

# Mind Map Generation (No changes)
async def generate_mind_map_image(dot_string: str, user_id: int) -> str | None:
    if not dot_string or "digraph" not in dot_string.lower(): logger.warning(f"Invalid DOT user {user_id}."); return None
    output_base_path = os.path.join(VISUALIZATIONS_DIR, f"{user_id}_jmap_{datetime.now().strftime('%Y%m%d%H%M%S')}"); output_png_path = output_base_path + ".png"
    try:
        logger.info(f"Generating mind map user {user_id}"); s = graphviz.Source(dot_string, filename=output_base_path, format="png")
        loop = asyncio.get_running_loop(); rendered_path = await loop.run_in_executor(None, s.render, None, VISUALIZATIONS_DIR, False, True)
        if os.path.exists(output_png_path): logger.info(f"Mind map PNG generated: {output_png_path}"); return output_png_path
        elif rendered_path and os.path.exists(rendered_path): logger.warning(f"Graphviz path mismatch. Using: {rendered_path}"); return rendered_path
        else: logger.error(f"Graphviz render failed/missing {output_png_path}."); return None
    except graphviz.backend.execute.ExecutableNotFound: logger.error("Graphviz executable not found."); return None
    except Exception as e: logger.error(f"Error generating mind map image: {e}", exc_info=True); return None

# --- TELEGRAM COMMAND HANDLERS ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str: # ... (no changes)
    user = update.effective_user; user_id = str(user.id); profiles = await load_profiles(); username = profiles.get(user_id, {}).get("username", "there"); logger.info(f"User {user_id} ({user.username or 'NoUsername'}) /start. Name: {username}")
    context.user_data.pop('current_mode', None)
    keyboard = [[InlineKeyboardButton(f"💬 {CHATBOT_MODE}", callback_data=CHATBOT_MODE)],[InlineKeyboardButton(f"📓 {JOURNAL_MODE}", callback_data=JOURNAL_MODE)],[InlineKeyboardButton(f"📄 {OCR_MODE}", callback_data=OCR_MODE)]]
    reply_markup = InlineKeyboardMarkup(keyboard); await update.message.reply_text(f"Hi {username}! Please choose a mode:", reply_markup=reply_markup)
    return SELECTING_MODE

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: # ... (no changes)
    help_text = escape_markdown("""*Multi-Mode Bot Help*

Use /start or /mode to select a mode:
• *Chatbot:* General conversation.
• *Journal:* Personal notes with AI analysis & mind maps.
• *OCR:* Extract text directly from images.

*Other Commands:*
/setusername <name> - Set display name
/tokens - Check AI token usage
/end - End current session/mode
/cancel - Cancel current action & return to mode select
/help - Show this message

Send text, voice, or image after selecting a mode. Commands like /end or /cancel should work anytime.
""", version=2)
    await update.message.reply_text(help_text, parse_mode=ParseMode.MARKDOWN_V2)

async def set_username_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: # ... (no changes)
    user = update.effective_user; user_id = str(user.id)
    if not context.args: await update.message.reply_text("Usage: `/setusername Your Name Here`", parse_mode=ParseMode.MARKDOWN_V2); return
    new_username = " ".join(context.args).strip()
    if not new_username or len(new_username) > 50: await update.message.reply_text("Invalid username (1-50 chars)."); return
    profiles = await load_profiles(); profiles.setdefault(user_id, {})["username"] = new_username
    if await save_profiles(profiles): logger.info(f"User {user_id} set username to '{new_username}'"); await update.message.reply_text(f"Username set to: {new_username}")
    else: await update.message.reply_text("Error saving username.")

async def tokens_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None: # ... (no changes)
    current_data = await load_token_data(); today = datetime.now().strftime("%Y-%m-%d")
    if current_data.get("daily", {}).get("date") != today: current_data["daily"] = {"date": today, "count": 0}; await save_token_data(current_data)
    total = current_data.get("total", 0); daily_count = current_data.get("daily", {}).get("count", 0); session_count = token_data_cache.get("session", 0)
    message = f"""*Token Usage:*
• Session \(since start\): {session_count:,}
• Today \({today}\): {daily_count:,}
• Total \(all time\): {total:,}"""
    await update.message.reply_text(escape_markdown(message, version=2), parse_mode=ParseMode.MARKDOWN_V2)

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str: # ... (no changes)
    user = update.effective_user; current_mode = context.user_data.get('current_mode')
    logger.info(f"User {user.id} issued /cancel (mode: {current_mode}). Returning to mode selection.")
    context.user_data.pop('current_mode', None)
    await update.message.reply_text("Operation cancelled.")
    return await start_command(update, context) # Explicitly re-run start

async def end_session_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str: # ... (no changes)
    user = update.effective_user; current_mode = context.user_data.get('current_mode')
    logger.info(f"User {user.id} issued /end (mode: {current_mode}). Ending session.")
    context.user_data.pop('current_mode', None)
    await update.message.reply_text("✅ Session ended. Use /start to begin a new one.")
    return END


# --- ACCESS CONTROL ---
# Approve Command (Admin Only)
async def approve_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Admin command to approve a user ID."""
    user_id = update.effective_user.id

    if user_id != ADMIN_USER_ID:
        logger.warning(f"User {user_id} attempted to use /approve command.")
        await update.message.reply_text("Sorry, this command is only for the bot administrator.")
        return

    if not context.args:
        await update.message.reply_text("Please provide the User ID to approve. Usage: `/approve <UserID>`")
        return

    try:
        user_id_to_approve = int(context.args[0])
    except ValueError:
        await update.message.reply_text("Invalid User ID format. Please provide a number.")
        return

    approved_users = await load_approved_users()
    if user_id_to_approve in approved_users:
        await update.message.reply_text(f"User ID {user_id_to_approve} is already approved.")
    else:
        approved_users.append(user_id_to_approve)
        if await save_approved_users(approved_users):
            logger.info(f"Admin {ADMIN_USER_ID} approved User ID {user_id_to_approve}")
            await update.message.reply_text(f"User ID {user_id_to_approve} has been approved.")
            # Optionally notify the approved user
            try:
                await context.bot.send_message(
                    chat_id=user_id_to_approve,
                    text="Your access request has been approved! You can now use /start to interact with the bot."
                )
            except Exception as e:
                logger.warning(f"Could not notify newly approved user {user_id_to_approve}: {e}")
        else:
            await update.message.reply_text("Failed to save the updated approved users list.")

# --- END ACCESS CONTROL ---



# --- CALLBACK QUERY HANDLER ---
async def mode_button_callback(update: Update, context: ContextTypes.DEFAULT_TYPE) -> str:
    """Handles the mode selection button presses. Sets mode and next state."""
    query = update.callback_query
    user = query.from_user
    await query.answer()
    chosen_mode = query.data
    context.user_data['current_mode'] = chosen_mode

    mode_texts = {CHATBOT_MODE: "Chatbot 💬", JOURNAL_MODE: "Journal 📓", OCR_MODE: "OCR 📄"}
    mode_text = mode_texts.get(chosen_mode, "Unknown")
    next_state = END # Default state

    try:
        message_text = f"Mode set to: *{escape_markdown(mode_text, version=2)}*\n" # Escape mode name
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
            # Handle invalid mode selection gracefully
            await query.edit_message_text(text="Invalid mode selected. Use /start again.")
            context.user_data.pop('current_mode', None)
            return END

        # Attempt to edit the message with MarkdownV2
        await query.edit_message_text(text=message_text, parse_mode=ParseMode.MARKDOWN_V2)
        logger.info(f"User {user.id} entered {mode_text} mode.")
        return next_state # Transition to the chosen mode's state

    except telegram.error.BadRequest as e:
        # --- CORRECTED INDENTATION BELOW ---
        # This block executes if the MarkdownV2 edit fails
        logger.error(f"BadRequest editing mode message with MarkdownV2: {e}. Falling back to plain text.")
        try:
            # Fallback to plain text
            await query.edit_message_text(text=f"Mode set to: {mode_text}. Please send input.")
            logger.info(f"User {user.id} entered {mode_text} mode (fallback message).")
        except Exception as fallback_e:
            # Log if even the fallback fails
            logger.error(f"Failed plain text fallback edit: {fallback_e}")
        # --- END OF CORRECTED INDENTATION ---

        # Still transition state even if message edit fails, if the mode was valid
        if chosen_mode in [CHATBOT_MODE, JOURNAL_MODE, OCR_MODE]:
            return chosen_mode
        else:
            context.user_data.pop('current_mode', None) # Clear invalid mode state
            return END

    except Exception as e:
        # Catch any other unexpected errors during callback handling
        logger.error(f"Unexpected error in mode_button_callback: {e}", exc_info=True)
        try:
            # Inform the user about the error
            await query.edit_message_text(text="An error occurred while selecting the mode. Please try again.")
        except Exception:
            pass # Ignore if editing fails here too
        context.user_data.pop('current_mode', None) # Clear mode state on error
        return END

# --- INPUT PROCESSING & MODE-SPECIFIC LOGIC ---

# Helper to get text from various inputs (Corrected transcribe_audio call)
async def get_text_from_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> tuple[str | None, str | None, str | None]:
    """
    Determines input type, extracts/enhances text, handles errors, cleans up.
    Uses Gemini for both audio transcription and punctuation.
    Shows enhanced audio transcript to user.
    Returns (final_text, input_type, error_message).
    """
    message = update.effective_message
    user_id = update.effective_user.id
    text_input, voice_input, photo_input = message.text, message.voice, message.photo
    temp_file_path, status_msg = None, None
    final_text = None # Initialize final_text
    input_type = None # Initialize input_type

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

            # --- CORRECTED FUNCTION CALL BELOW ---
            # Call the Gemini transcription function first to get raw text
            raw_text = await transcribe_audio_with_gemini(temp_file_path, context)
            # --- END OF CORRECTION ---

            # Handle transcription errors FIRST
            if raw_text is None or "[" in raw_text: # Check for None or error messages like "[BLOCKED...]"
                error_msg_to_return = raw_text or "❌ Transcription failed (Unknown error)."
                if status_msg:
                    try: await status_msg.delete()
                    except Exception: pass
                return None, input_type, error_msg_to_return

            # --- Now call Gemini for Punctuation ---
            await status_msg.edit_text("✍️ Enhancing transcript...")
            punctuated_text = await add_punctuation_with_gemini(raw_text, context)
            if status_msg: await status_msg.delete() # Delete status early

            # Display punctuated transcript (Header escaped)
            display_transcript = punctuated_text
            logger.info(f"Displaying transcript (len: {len(display_transcript)}) user {user_id}")
            header_text = escape_markdown(f"*Audio Transcript* (AI Enhanced):", version=2)
            try:
                await message.reply_text(header_text, parse_mode=ParseMode.MARKDOWN_V2)
            except Exception as e:
                logger.error(f"Error sending transcript header: {e}")
                await message.reply_text("Audio Transcript (AI Enhanced):", parse_mode=None) # Plain fallback

            safe_display_transcript = escape_markdown(display_transcript, version=2)
            max_len = 4000; chunks = [safe_display_transcript[i:i+max_len] for i in range(0, len(safe_display_transcript), max_len)]
            for i, chunk in enumerate(chunks):
                message_text = f"```\n{chunk}\n```"
                try: await message.reply_text(message_text, parse_mode=ParseMode.MARKDOWN_V2)
                except telegram.error.BadRequest as e: logger.error(f"BadRequest transcript chunk {i+1}: {e}. Plain."); await message.reply_text(display_transcript[i*max_len:(i+1)*max_len], parse_mode=None)
                except Exception as e: logger.error(f"Error sending transcript chunk {i+1}: {e}"); await message.reply_text(f"[Error display part {i+1}]")

            # Return the ENHANCED text for mode processing
            final_text = punctuated_text # Assign to final_text

        elif photo_input: # Image processing... (No changes needed here)
            # ... (Existing logic using Pillow and Gemini Vision) ...
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
            final_text = extracted_text_result # Assign to final_text

        else:
            return None, None, "Unsupported message type."

        # If we reached here successfully, return the result
        return final_text, input_type, None

    except Exception as e:
        logger.error(f"Error in get_text_from_input main try block: {e}", exc_info=True)
        # Ensure status message is deleted on unexpected error
        if status_msg:
            try: await status_msg.delete()
            except Exception: pass
        return None, input_type, "An unexpected error occurred processing your input."

    finally: # Cleanup TEMP file (OGG or JPG) and status message
        if temp_file_path and os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
                logger.info(f"Temp file deleted: {temp_file_path}")
            except OSError as e_del_file:
                logger.error(f"Error deleting temp file {temp_file_path}: {e_del_file}")

        if status_msg:
            try:
                await status_msg.delete()
            except Exception as e_del_msg:
                logger.warning(f"Could not delete status message: {e_del_msg}")
        # --- END OF CORRECTLY INDENTED FINALLY BLOCK ---


# Generic Input Handler (No changes)
async def handle_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = update.effective_user.id; mode = context.user_data.get('current_mode')
    if not mode: await update.message.reply_text("Please select a mode first using /start."); return
    extracted_text, input_type, error_message = await get_text_from_input(update, context)
    if error_message: await update.message.reply_text(error_message); return
    if extracted_text is None: await update.message.reply_text("Input could not be processed into text."); return
    if mode == CHATBOT_MODE: await handle_chatbot_logic(update, context, extracted_text)
    elif mode == JOURNAL_MODE: await handle_journal_logic(update, context, extracted_text, input_type)
    elif mode == OCR_MODE: await handle_ocr_logic(update, context, extracted_text, input_type)
    else: logger.error(f"Invalid mode '{mode}' in handle_input"); await update.message.reply_text("Internal error: Invalid mode.")

# Mode-Specific Logic Functions
async def handle_chatbot_logic(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str): # ... (no changes)
    user_id = update.effective_user.id; logger.info(f"Chatbot logic text (len: {len(text)}) user {user_id}"); status_msg = await update.message.reply_text("🤔 Thinking...")
    response_text, _ = await generate_gemini_response([text], context=context)
    if response_text is None or "[API ERROR:" in response_text: await status_msg.edit_text(f"Sorry, error contacting AI. {response_text or ''}")
    elif "[BLOCKED:" in response_text: await status_msg.edit_text(f"My response was blocked: {response_text}")
    else: await status_msg.edit_text(response_text, parse_mode=None)

async def handle_journal_logic(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, input_type: str): # ... (no changes)
    # Step 1-7: Save, Categorize, Update, Analyze, Output Analysis, Generate/Output Map
    user = update.effective_user; user_id = user.id; profiles = await load_profiles(); username = profiles.get(str(user_id), {}).get("username", f"User_{user_id}"); now = datetime.now(); date_str, time_str = now.strftime("%Y-%m-%d"), now.strftime("%H:%M:%S"); logger.info(f"Journal logic '{input_type}' (len: {len(text)}) user {user_id}")
    status_msg = await update.message.reply_text("💾 Saving..."); entry_data = {"Username": username, "UserID": user_id, "Date": date_str, "Time": time_str, "Raw Text": text, "Word Count": len(text.split()), "Input Type": input_type}; entry_id = await append_journal_entry(entry_data)
    if not entry_id: await status_msg.edit_text("❌ Error saving."); return
    await status_msg.edit_text("📊 Categorizing..."); categorization_prompt = f"""Analyze entry:\n---\n{text}\n---\nProvide:\n1. Sentiment: (Positive/Negative/Neutral)\n2. Topics: (1-3 brief topics)\n3. Categories: (Choose from: [{', '.join(JOURNAL_CATEGORIES_LIST)}])\nFormat ONLY:\nSentiment: [S]\nTopics: [T]\nCategories: [C]"""; categorization_response, _ = await generate_gemini_response([categorization_prompt], context=context)
    sentiment, topics, categories = "N/A", "N/A", "N/A"
    if categorization_response and "[BLOCKED:" not in categorization_response and "[API ERROR:" not in categorization_response:
        sentiment = (re.search(r"Sentiment:\s*(.*)", categorization_response, re.I) or ['','N/A'])[1].strip(); topics = (re.search(r"Topics:\s*(.*)", categorization_response, re.I) or ['','N/A'])[1].strip(); categories = (re.search(r"Categories:\s*(.*)", categorization_response, re.I) or ['','N/A'])[1].strip(); logger.info(f"Categorization {entry_id}: S={sentiment}, T={topics}, C={categories}")
        update_data = {"Sentiment": sentiment, "Topics": topics, "Categories": categories}
        if not await update_journal_entry(entry_id, update_data): logger.warning(f"Failed CSV update {entry_id}")
    else: logger.warning(f"Categorization failed/blocked {entry_id}: {categorization_response}"); await update.message.reply_text(f"⚠️ Categorization failed. {categorization_response or ''}")
    await status_msg.edit_text("🧠 Analyzing..."); all_entries = await read_journal_entries(user_id=user_id); history_context = "\n\nPrev Entries (Max 5):\n" if len(all_entries) > 1 else "\n\nFirst entry.";
    if len(all_entries) > 1: history_context += "".join([f"- {e.get('Date')}: S={e.get('Sentiment')}, T={e.get('Topics')}, C={e.get('Categories')}\n" for e in all_entries[-6:-1]])
    current_entry_summary = f"Recent ({date_str} {time_str}):\nS:{sentiment}, T:{topics}, C:{categories}\nText:\n---\n{text}\n---"; therapist_analysis_prompt = f"""Act as therapist. Analyze recent entry vs history. Note patterns/changes. Give structured insights. NO medical advice.\n\n{current_entry_summary}\n{history_context}\n\n**Analysis:**\n[Your analysis]\n\n--- DOT START ---\ndigraph JournalMap {{ rankdir=LR; node [shape=box, style=rounded]; /* Add DOT code */ }}\n--- DOT END ---"""
    analysis_response_text, _ = await generate_gemini_response([therapist_analysis_prompt], context=context); analysis_output = "Analysis failed."; dot_code = None
    if analysis_response_text and "[BLOCKED:" not in analysis_response_text and "[API ERROR:" not in analysis_response_text:
        dot_match = re.search(r"---\s*DOT START\s*---(.*)---\s*DOT END\s*---", analysis_response_text, re.DOTALL | re.I)
        if dot_match: dot_code = dot_match.group(1).strip(); analysis_output = re.sub(r"---\s*DOT START\s*---.*---\s*DOT END\s*---", "", analysis_response_text, flags=re.DOTALL | re.I).strip(); logger.info(f"Extracted DOT (len: {len(dot_code)}) for {entry_id}")
        else: analysis_output = analysis_response_text; logger.warning(f"DOT markers missing {entry_id}")
    elif analysis_response_text: analysis_output = f"Analysis failed/blocked: {analysis_response_text}"; logger.warning(f"Analysis failed/blocked {entry_id}: {analysis_response_text}")
    await status_msg.edit_text(analysis_output, parse_mode=None)
    if dot_code:
        map_status = await update.message.reply_text("🗺️ Generating map..."); mind_map_image_path = await generate_mind_map_image(dot_code, user_id)
        if mind_map_image_path:
            try: await update.message.reply_photo(photo=open(mind_map_image_path, 'rb'), caption="Mind map."); await map_status.delete()
            except Exception as e: logger.error(f"Error sending map: {e}"); await map_status.edit_text("⚠️ Error sending map.")
            finally:
                 if os.path.exists(mind_map_image_path):
                     try: os.remove(mind_map_image_path)
                     except OSError as e_del: logger.error(f"Error deleting map: {e_del}")
        else: await map_status.edit_text("⚠️ Could not generate map.")
    else: await update.message.reply_text("(Mind map not generated)")
    await update.message.reply_text("✅ Journal entry processed.")

# MODIFIED OCR Logic handler
async def handle_ocr_logic(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, input_type: str):
    """Handles OCR mode output (text already extracted). Fixes header markdown."""
    if input_type != "image":
         await update.message.reply_text("OCR mode requires an image input.")
         return

    logger.info(f"OCR mode sending extracted text (len: {len(text)}) to user {update.effective_user.id}")

    # --- FIX: Escape header text ---
    header_text = escape_markdown("*Extracted Text (AI Vision OCR):*", version=2)
    try:
        await update.message.reply_text(header_text, parse_mode=ParseMode.MARKDOWN_V2)
    except telegram.error.BadRequest as e:
         logger.error(f"BadRequest sending OCR header: {e}. Sending plain.")
         await update.message.reply_text("Extracted Text (AI Vision OCR):", parse_mode=None)
    except Exception as e:
         logger.error(f"Error sending OCR header: {e}")
         # Proceed to send content even if header fails

    # Send content in code block
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
             logger.error(f"Error sending OCR chunk {i+1}: {e}"); await update.message.reply_text(f"[Error displaying part {i+1}]")

    # No final "complete" message needed here.

# --- POST INIT FUNCTION ---
async def post_set_commands(application: Application) -> None: # ... (no changes)
    commands = [BotCommand("start", "Start / Select Mode"), BotCommand("mode", "Re-select Mode"), BotCommand("changemode", "Re-select Mode"), BotCommand("setusername", "Set display name"), BotCommand("tokens", "Check AI token usage"), BotCommand("end", "End current session"), BotCommand("help", "Show help"), BotCommand("cancel", "Cancel action / New Mode")]
    try: await application.bot.set_my_commands(commands); logger.info("Bot commands menu set.")
    except Exception as e: logger.error(f"Failed to set bot commands: {e}")

# --- NEW: Global Error Handler ---
async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log Errors caused by Updates and notify user."""
    logger.error(f"Exception while handling an update: {context.error}", exc_info=context.error)

    # Inform user (optional, can be noisy)
    # Avoid sending error message if it's a known handled exception type if needed
    if isinstance(update, Update) and update.effective_message:
        try:
            await update.effective_message.reply_text("Sorry, an unexpected error occurred. Please try again later, or use /start.")
        except Exception as e:
            logger.error(f"Failed to send error message to user: {e}")

# --- MAIN FUNCTION (MODIFIED to add error handler) ---
def main() -> None:
    """Sets up and runs the bot."""
    logger.info("Starting bot setup...")
    # Use ApplicationBuilder to easily add error handler
    application = (
        ApplicationBuilder()
        .token(TELEGRAM_TOKEN)
        .post_init(post_set_commands)
        .build()
    )

    # Add the global error handler
    application.add_error_handler(error_handler)

    # --- Conversation Handler (Filters already fixed in previous version) ---
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler('start', start_command),
                      CommandHandler('mode', start_command),
                      CommandHandler('changemode', start_command)],
        states={
            SELECTING_MODE: [CallbackQueryHandler(mode_button_callback)],
            # Ensure ~filters.COMMAND is present to allow fallbacks to handle commands
            CHATBOT_MODE: [MessageHandler(filters.ChatType.PRIVATE & (filters.TEXT | filters.VOICE | filters.PHOTO | filters.Document.IMAGE) & ~filters.COMMAND, handle_input)],
            JOURNAL_MODE: [MessageHandler(filters.ChatType.PRIVATE & (filters.TEXT | filters.VOICE | filters.PHOTO | filters.Document.IMAGE) & ~filters.COMMAND, handle_input)],
            OCR_MODE: [MessageHandler(filters.ChatType.PRIVATE & (filters.PHOTO | filters.Document.IMAGE) & ~filters.COMMAND, handle_input),
                       MessageHandler(filters.ChatType.PRIVATE & (filters.TEXT | filters.VOICE) & ~filters.COMMAND, lambda u,c: u.message.reply_text("OCR mode requires an image."))],
        },
        fallbacks=[ # Commands here should correctly interrupt states now
            CommandHandler('cancel', cancel_command),
            CommandHandler('end', end_session_command),
            CommandHandler('start', start_command),
            CommandHandler('mode', start_command),
            CommandHandler('changemode', start_command),
            CommandHandler('help', help_command),
            CommandHandler('setusername', set_username_command),
            CommandHandler('tokens', tokens_command),
        ],
        allow_reentry=False
    )
    application.add_handler(conv_handler)

    # Standalone handlers (mostly covered by fallbacks, but good redundancy)
    application.add_handler(CommandHandler("help", help_command))
    application.add_handler(CommandHandler("setusername", set_username_command))
    application.add_handler(CommandHandler("tokens", tokens_command))
    # Commands like start, mode, cancel, end are handled by ConversationHandler

    # Generic message handler (lowest priority)
    application.add_handler(MessageHandler(
        filters.UpdateType.MESSAGE & ~filters.COMMAND & filters.ChatType.PRIVATE,
        lambda u, c: u.message.reply_text("Please use /start or /mode to begin.")
    ))

    # Initialize token data via post_init
    logger.info("Bot setup complete. Starting polling...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
    logger.info("Bot polling stopped.")

if __name__ == "__main__":
    main()