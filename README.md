# Journal
How the Multimodal Bot Works
This Telegram bot is designed as a versatile assistant, leveraging Google's Gemini AI for its core intelligence across different operational modes. It uses the python-telegram-bot library for interacting with the Telegram API and asyncio for efficient handling of asynchronous operations.
Here's a breakdown of its main components and interactions:
Core Setup & Initialization:
Environment: Loads essential API keys (Telegram, Gemini) from a .env file.
Gemini AI: Configures and initializes the gemini-1.5-flash-latest model with specific safety settings. This model is the backbone for text generation, understanding, audio transcription, and image analysis (OCR).
Data Storage:
user_profiles.json: Stores user-defined display names.
token_usage.json: Tracks Gemini API token consumption (session, daily, total).
journal.csv: Stores journal entries with metadata like sentiment, topics, categories, etc.
bot_data/temp/: Temporary storage for downloaded audio/image files before processing.
bot_data/visualizations/: Stores generated mind map images.
File Lock: An asyncio.Lock is used to prevent race conditions when multiple operations might try to access shared files (profiles, token data, journal) concurrently.
User Interaction & Conversation Flow:
Entry Points: Users typically start interacting via /start, /mode, or /changemode.
Mode Selection: The bot presents inline buttons for CHATBOT_MODE, JOURNAL_MODE, and OCR_MODE. User selection is handled by mode_button_callback.
State Management: A ConversationHandler manages the bot's state, directing user input to the appropriate logic based on the current_mode stored in context.user_data.
Input Handling (get_text_from_input): This crucial function processes various user inputs:
Text: Used directly.
Voice: Audio is downloaded, then sent to transcribe_audio_with_gemini. This function uploads the audio file to Gemini, which performs the transcription. The raw transcript is then passed to add_punctuation_with_gemini for enhancement (capitalization, punctuation) also using Gemini. The enhanced transcript is shown to the user.
Image: The image is downloaded. For OCR mode (or image input in other modes), it's opened with PIL (Pillow) and then sent to Gemini along with a prompt to extract text.
Generic Input Router (handle_input): After get_text_from_input provides the processed text and input type, this function routes the data to the mode-specific handler.
Mode-Specific Logic:
Chatbot Mode (handle_chatbot_logic):
The extracted text (from user's text, voice, or image description if implemented) is sent to Gemini for a conversational response.
The AI's response is then sent back to the user.
OCR Mode (handle_ocr_logic):
Requires an image input.
The text extracted from the image by Gemini (via get_text_from_input) is formatted and sent back to the user.
Journal Mode (handle_journal_logic): This is the most complex mode:
Save Initial Entry: The raw text (from user's text, voice, or image OCR) is saved to journal.csv with basic metadata (user ID, timestamp, input type).
AI Categorization: The text is sent to Gemini with a prompt to determine sentiment, topics, and predefined categories.
Update Entry: The journal entry in the CSV is updated with this AI-generated analysis.
AI Analysis & Mind Map Prep: The current entry, along with a summary of recent previous entries for context, is sent to Gemini. The prompt asks Gemini to act like a therapist, provide insights, and generate a mind map in DOT language format.
Display Analysis: The textual analysis from Gemini is sent to the user.
Generate Mind Map: If DOT code was successfully extracted, graphviz is used to render it into a PNG image.
Send Mind Map: The generated image is sent to the user.
Supporting Commands & Functions:
/help, /setusername, /tokens, /cancel, /end: Standard utility commands.
Profile, token, and journal CSV helper functions manage data persistence.
generate_gemini_response: A wrapper for making calls to the Gemini API, including token incrementing and basic error/block handling.
Error Handling: A global error_handler is set up to log exceptions and optionally inform the user of unexpected issues.
