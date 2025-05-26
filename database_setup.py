import sqlite3
import os

# Import DATABASE_PATH from db_utils to ensure consistency
# Assuming db_utils.py is in the same directory or accessible in PYTHONPATH
try:
    from db_utils import DATABASE_PATH, DATA_DIR
except ImportError:
    # Fallback if db_utils is not directly importable here (e.g. during initial setup by some tools)
    # This path construction should match the one in db_utils.py
    print("Warning: Could not import DATABASE_PATH from db_utils. Using fallback path for database_setup.")
    BASE_DIR_SETUP = os.path.dirname(os.path.abspath(__file__))
    DATA_DIR_SETUP = os.path.join(BASE_DIR_SETUP, "bot_data")
    DATABASE_PATH_SETUP = os.path.join(DATA_DIR_SETUP, "multimode_bot.db")
    
    DATA_DIR = DATA_DIR_SETUP
    DATABASE_PATH = DATABASE_PATH_SETUP

def create_connection(db_file_path: str | None = None) -> sqlite3.Connection | None:
    """Creates a database connection to the SQLite database specified by db_file_path.
       If no path is provided, it uses the DATABASE_PATH from db_utils.
    """
    if db_file_path is None:
        db_file_path = DATABASE_PATH

    # Ensure the data directory exists
    os.makedirs(DATA_DIR, exist_ok=True)
    
    conn = None
    try:
        conn = sqlite3.connect(db_file_path)
        conn.row_factory = sqlite3.Row # Optional: Access columns by name
        return conn
    except sqlite3.Error as e:
        print(f"Error connecting to database '{db_file_path}': {e}")
        return None

def create_tables(conn: sqlite3.Connection) -> None:
    """Creates all necessary tables in the database if they don't exist.
       The table definitions mirror those in db_utils.py.
    """
    if conn is None:
        print("Failed to create tables: No database connection provided.")
        return

    try:
        cursor = conn.cursor()
        
        # Users Table
        cursor.execute(\"\"\"
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            telegram_username TEXT,
            display_name TEXT,
            first_seen TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_interaction TIMESTAMP,
            preferences TEXT  -- JSON for storing various user preferences (e.g., daily_prompt_enabled, preferred_prompt_time, last_prompt_sent_date)
        )
        \"\"\")
        
        # Journal Entries Table
        cursor.execute(\"\"\"
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
        \"\"\")

        # Feedback Table
        cursor.execute(\"\"\"
        CREATE TABLE IF NOT EXISTS feedback (
            feedback_id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            feedback_text TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users (user_id)
        )
        \"\"\")

        # Daily Prompts Table
        cursor.execute(\"\"\"
        CREATE TABLE IF NOT EXISTS daily_prompts (
            prompt_id INTEGER PRIMARY KEY AUTOINCREMENT,
            prompt_text TEXT NOT NULL UNIQUE,
            category TEXT, -- Optional: category for the prompt
            date_added TIMESTAMP DEFAULT CURRENT_TIMESTAMP 
        )
        \"\"\")
        
        conn.commit()
        # print("Tables checked/created successfully by database_setup.py.") # Optional: for debugging
    except sqlite3.Error as e:
        print(f"Error creating tables in database_setup.py: {e}")

if __name__ == '__main__':
    # This section can be used for direct setup if needed,
    # similar to how New_Main.py uses these functions.
    print(f"Running database_setup.py directly...")
    print(f"Database path is configured to: {DATABASE_PATH}")
    
    # Ensure the data directory exists
    os.makedirs(DATA_DIR, exist_ok=True)
    print(f"Data directory '{DATA_DIR}' ensured.")

    connection = create_connection() # Uses DATABASE_PATH by default
    if connection:
        print("Database connection successful.")
        create_tables(connection)
        print("Tables creation process completed.")
        
        # Example: Add a few default prompts if the table is empty
        try:
            cursor = connection.cursor()
            cursor.execute("SELECT COUNT(*) FROM daily_prompts")
            if cursor.fetchone()[0] == 0:
                print("Adding initial daily prompts via database_setup.py...")
                initial_prompts = [
                    ("What are you grateful for today?", "Reflection"),
                    ("Describe a small act of kindness you witnessed or performed.", "Kindness"),
                    ("What is one thing you learned recently?", "Learning"),
                    ("How are you feeling right now, and why?", "Emotion"),
                    ("What is a challenge you're currently facing?", "Challenge")
                ]
                for prompt_text, category in initial_prompts:
                    try:
                        cursor.execute("INSERT INTO daily_prompts (prompt_text, category) VALUES (?, ?)", (prompt_text, category))
                    except sqlite3.IntegrityError:
                        print(f"Prompt '{prompt_text}' already exists.")
                connection.commit()
                print("Initial daily prompts added.")
            else:
                print("Daily prompts table already has data.")
        except sqlite3.Error as e:
            print(f"Error adding initial prompts in database_setup.py: {e}")
        finally:
            connection.close()
            print("Database connection closed.")
    else:
        print("Failed to connect to the database.")
    print("database_setup.py finished.")
