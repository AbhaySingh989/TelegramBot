import sqlite3
import os
from datetime import datetime, timezone

# Define the path to the database file within the bot_data directory
# This ensures the database is stored in a persistent location relative to the script.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "bot_data")
DATABASE_PATH = os.path.join(DATA_DIR, "multimode_bot.db")

# Ensure the DATA_DIR exists
os.makedirs(DATA_DIR, exist_ok=True)

def get_db_connection():
    """Establishes a connection to the SQLite database."""
    try:
        conn = sqlite3.connect(DATABASE_PATH)
        conn.row_factory = sqlite3.Row # Access columns by name
        return conn
    except sqlite3.Error as e:
        print(f"Database connection error: {e}")
        return None

def create_tables(conn: sqlite3.Connection | None = None) -> None:
    """Creates all necessary tables in the database if they don't exist."""
    if conn is None:
        conn = get_db_connection()
    
    if conn is None:
        print("Failed to create tables: No database connection.")
        return

    try:
        cursor = conn.cursor()
        
        # Users Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            telegram_username TEXT,
            display_name TEXT,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_interaction TIMESTAMP,
            preferences TEXT  -- JSON for storing various user preferences
        )
        """)
        
        # Journal Entries Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS journal_entries (
            entry_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            raw_text TEXT NOT NULL,
            input_type TEXT, -- 'text', 'audio', 'image'
            word_count INTEGER,
            sentiment TEXT,
            topics TEXT, -- Comma-separated
            categories TEXT, -- Comma-separated
            ai_analysis_text TEXT,
            dot_code TEXT, -- For Graphviz mind map
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
        """)

        # Feedback Table
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS feedback (
            feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            feedback_text TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
        """)

        # Daily Prompts Table (NEW)
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS daily_prompts (
            prompt_id INTEGER PRIMARY KEY AUTOINCREMENT,
            prompt_text TEXT NOT NULL UNIQUE,
            date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP 
        )
        """)
        
        conn.commit()
        print("Tables checked/created successfully.")
    except sqlite3.Error as e:
        print(f"Error creating tables: {e}")
    finally:
        if conn:
            conn.close()

# --- User Management ---
def add_user(user_id: int, telegram_username: str | None = None, display_name: str | None = None) -> bool:
    conn = get_db_connection()
    if not conn: return False
    try:
        cursor = conn.cursor()
        current_ts = datetime.now(timezone.utc)
        cursor.execute("""
            INSERT INTO users (user_id, telegram_username, display_name, first_seen, last_interaction)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                telegram_username = excluded.telegram_username,
                display_name = COALESCE(excluded.display_name, users.display_name), -- Only update if new display_name is provided
                last_interaction = excluded.last_interaction
        """, (user_id, telegram_username, display_name, current_ts, current_ts))
        conn.commit()
        return True
    except sqlite3.Error as e:
        print(f"Error adding/updating user {user_id}: {e}")
        return False
    finally:
        if conn: conn.close()

def get_user(user_id: int) -> dict | None:
    conn = get_db_connection()
    if not conn: return None
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
        user_row = cursor.fetchone()
        if user_row:
            # Update last_interaction timestamp
            current_ts = datetime.now(timezone.utc)
            cursor.execute("UPDATE users SET last_interaction = ? WHERE user_id = ?", (current_ts, user_id))
            conn.commit()
            return dict(user_row)
        return None
    except sqlite3.Error as e:
        print(f"Error getting user {user_id}: {e}")
        return None
    finally:
        if conn: conn.close()

def update_user_preferences(user_id: int, display_name: str | None = None, other_prefs: dict | None = None) -> bool:
    conn = get_db_connection()
    if not conn: return False
    try:
        cursor = conn.cursor()
        current_prefs_json = cursor.execute("SELECT preferences FROM users WHERE user_id = ?", (user_id,)).fetchone()
        
        current_prefs = {}
        if current_prefs_json and current_prefs_json[0]:
            current_prefs = json.loads(current_prefs_json[0])
        
        if display_name is not None:
            cursor.execute("UPDATE users SET display_name = ?, last_interaction = ? WHERE user_id = ?", 
                           (display_name, datetime.now(timezone.utc), user_id))
        
        if other_prefs is not None:
            current_prefs.update(other_prefs)
            cursor.execute("UPDATE users SET preferences = ?, last_interaction = ? WHERE user_id = ?", 
                           (json.dumps(current_prefs), datetime.now(timezone.utc), user_id))
        
        conn.commit()
        return True
    except sqlite3.Error as e:
        print(f"Error updating preferences for user {user_id}: {e}")
        return False
    finally:
        if conn: conn.close()

# --- Journaling ---
def add_journal_entry(user_id: int, raw_text: str, input_type: str, word_count: int, 
                      sentiment: str | None = None, topics: str | None = None, 
                      categories: str | None = None, ai_analysis_text: str | None = None, 
                      dot_code: str | None = None) -> int | None:
    conn = get_db_connection()
    if not conn: return None
    try:
        cursor = conn.cursor()
        ts = datetime.now(timezone.utc)
        cursor.execute("""
            INSERT INTO journal_entries 
            (user_id, timestamp, raw_text, input_type, word_count, sentiment, topics, categories, ai_analysis_text, dot_code)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (user_id, ts, raw_text, input_type, word_count, sentiment, topics, categories, ai_analysis_text, dot_code))
        conn.commit()
        return cursor.lastrowid
    except sqlite3.Error as e:
        print(f"Error adding journal entry for user {user_id}: {e}")
        return None
    finally:
        if conn: conn.close()

def update_journal_entry_analysis(entry_id: int, sentiment: str | None = None, topics: str | None = None, 
                                  categories: str | None = None, ai_analysis_text: str | None = None, 
                                  dot_code: str | None = None) -> bool:
    conn = get_db_connection()
    if not conn: return False
    try:
        cursor = conn.cursor()
        fields_to_update = []
        params = []

        if sentiment is not None: fields_to_update.append("sentiment = ?"); params.append(sentiment)
        if topics is not None: fields_to_update.append("topics = ?"); params.append(topics)
        if categories is not None: fields_to_update.append("categories = ?"); params.append(categories)
        if ai_analysis_text is not None: fields_to_update.append("ai_analysis_text = ?"); params.append(ai_analysis_text)
        if dot_code is not None: fields_to_update.append("dot_code = ?"); params.append(dot_code)

        if not fields_to_update: return True # Nothing to update

        sql = f"UPDATE journal_entries SET {', '.join(fields_to_update)} WHERE entry_id = ?"
        params.append(entry_id)
        
        cursor.execute(sql, tuple(params))
        conn.commit()
        return True
    except sqlite3.Error as e:
        print(f"Error updating journal entry {entry_id}: {e}")
        return False
    finally:
        if conn: conn.close()

def get_journal_entries_by_user(user_id: int, limit: int = 10) -> list[dict]:
    conn = get_db_connection()
    if not conn: return []
    try:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT * FROM journal_entries 
            WHERE user_id = ? 
            ORDER BY timestamp DESC 
            LIMIT ?
        """, (user_id, limit))
        return [dict(row) for row in cursor.fetchall()]
    except sqlite3.Error as e:
        print(f"Error fetching journal entries for user {user_id}: {e}")
        return []
    finally:
        if conn: conn.close()

# --- Feedback ---
def add_feedback(user_id: int, feedback_text: str) -> bool:
    conn = get_db_connection()
    if not conn: return False
    try:
        cursor = conn.cursor()
        ts = datetime.now(timezone.utc)
        cursor.execute("""
            INSERT INTO feedback (user_id, timestamp, feedback_text)
            VALUES (?, ?, ?)
        """, (user_id, ts, feedback_text))
        conn.commit()
        return True
    except sqlite3.Error as e:
        print(f"Error adding feedback for user {user_id}: {e}")
        return False
    finally:
        if conn: conn.close()

# --- Daily Prompts ---
def add_daily_prompt(prompt_text: str) -> int | None:
    conn = get_db_connection()
    if not conn: return None
    try:
        cursor = conn.cursor()
        ts = datetime.now(timezone.utc)
        cursor.execute("INSERT INTO daily_prompts (prompt_text, date_added) VALUES (?, ?)", (prompt_text, ts))
        conn.commit()
        return cursor.lastrowid
    except sqlite3.IntegrityError: # Handles UNIQUE constraint violation
        print(f"Prompt already exists: {prompt_text}")
        return None
    except sqlite3.Error as e:
        print(f"Error adding daily prompt: {e}")
        return None
    finally:
        if conn: conn.close()

def get_random_daily_prompt() -> dict | None:
    conn = get_db_connection()
    if not conn: return None
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT prompt_id, prompt_text FROM daily_prompts ORDER BY RANDOM() LIMIT 1")
        row = cursor.fetchone()
        return dict(row) if row else None
    except sqlite3.Error as e:
        print(f"Error fetching random daily prompt: {e}")
        return None
    finally:
        if conn: conn.close()

def get_all_daily_prompts() -> list[dict]:
    conn = get_db_connection()
    if not conn: return []
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT prompt_id, prompt_text, date_added FROM daily_prompts ORDER BY date_added DESC")
        return [dict(row) for row in cursor.fetchall()]
    except sqlite3.Error as e:
        print(f"Error fetching all daily prompts: {e}")
        return []
    finally:
        if conn: conn.close()

if __name__ == '__main__':
    # This is for direct execution to set up the database and add initial prompts
    print(f"Running db_utils.py directly. Database will be at: {DATABASE_PATH}")
    # Ensure DATA_DIR exists (redundant if get_db_connection creates it, but good practice)
    os.makedirs(DATA_DIR, exist_ok=True)
    
    # Create tables
    create_tables() # This will open and close its own connection
    print("Database tables checked/created.")

    # Example of adding some initial daily prompts
    initial_prompts = [
        "What are you grateful for today?",
        "Describe a small act of kindness you witnessed or performed.",
        "What is one thing you learned recently?",
        "How are you feeling right now, and why?",
        "What is a challenge you're currently facing?",
        "Describe something beautiful you saw today.",
        "What are you looking forward to this week?",
        "What's a simple pleasure you enjoyed recently?",
        "If you could tell your younger self one thing, what would it be?",
        "What does 'success' mean to you at this moment in your life?"
    ]
    
    print("\nAdding initial daily prompts (if they don't exist already):")
    for prompt in initial_prompts:
        prompt_id = add_daily_prompt(prompt) # This will open and close its own connection
        if prompt_id:
            print(f"  Added prompt ID {prompt_id}: {prompt}")
        else:
            print(f"  Prompt likely already exists or error occurred: {prompt}")
    
    print("\nFetching a random prompt as a test:")
    random_prompt = get_random_daily_prompt() # This will open and close its own connection
    if random_prompt:
        print(f"  Random prompt: {random_prompt['prompt_text']} (ID: {random_prompt['prompt_id']})")
    else:
        print("  Could not fetch a random prompt (perhaps none were added).")

    print("\nFetching all prompts as a test:")
    all_prompts = get_all_daily_prompts()
    if all_prompts:
        print(f"  Found {len(all_prompts)} prompts:")
        for p in all_prompts[:3]: # Print first 3
             print(f"    - ID: {p['prompt_id']}, Text: {p['prompt_text']}, Added: {p['date_added']}")
        if len(all_prompts) > 3:
            print(f"    ... and {len(all_prompts) - 3} more.")
    else:
        print("  No prompts found in the database.")

    print("\nDB Utils script finished.")
