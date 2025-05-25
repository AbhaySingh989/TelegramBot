import json
import csv
import os
from datetime import datetime, timezone
import db_utils # Assumes db_utils.py is in the same directory or accessible via PYTHONPATH

# Define paths to the old data files
USER_PROFILES_JSON = os.path.join('bot_data', 'user_profiles.json')
JOURNAL_CSV = os.path.join('bot_data', 'journal.csv')

def migrate_users():
    """Migrates users from the old user_profiles.json to the SQLite database."""
    print("Starting user migration...")
    if not os.path.exists(USER_PROFILES_JSON):
        print(f"User profiles file not found: {USER_PROFILES_JSON}")
        return

    migrated_count = 0
    failed_count = 0
    try:
        with open(USER_PROFILES_JSON, 'r', encoding='utf-8') as f:
            profiles_data = json.load(f)
        
        if not isinstance(profiles_data, dict):
            print(f"Error: Expected a dictionary in {USER_PROFILES_JSON}, but got {type(profiles_data)}. Aborting user migration.")
            return

        for user_id_str, profile_info in profiles_data.items():
            try:
                user_id = int(user_id_str)
                # The old JSON file stores the display name under the 'username' key.
                display_name = profile_info.get('username') 
                # telegram_username is not available in the old file.
                telegram_username = profile_info.get('telegram_username') # Will likely be None

                if display_name is None:
                    logger.warning(f"User ID {user_id} has no 'username' (display_name) in JSON. Skipping.")
                    failed_count +=1
                    continue

                # Use db_utils to add the user. The add_user function has UPSERT logic.
                # It also sets first_seen and last_interaction.
                # We don't have historical last_interaction, so it will be set to now.
                if db_utils.add_user(user_id, telegram_username=telegram_username, display_name=display_name):
                    migrated_count += 1
                    print(f"Migrated user ID: {user_id}, Display Name: {display_name}")
                else:
                    failed_count += 1
                    print(f"Failed to migrate user ID: {user_id}")
            except ValueError:
                print(f"Invalid user ID format: {user_id_str}. Skipping.")
                failed_count +=1
            except Exception as e:
                print(f"An error occurred processing user {user_id_str}: {e}")
                failed_count +=1
        
        print(f"\nUser migration summary:")
        print(f"  Successfully migrated: {migrated_count} users.")
        print(f"  Failed/skipped: {failed_count} users.")

    except FileNotFoundError:
        print(f"User profiles file not found: {USER_PROFILES_JSON}")
    except json.JSONDecodeError:
        print(f"Error decoding JSON from {USER_PROFILES_JSON}. Ensure it's a valid JSON file.")
    except Exception as e:
        print(f"An unexpected error occurred during user migration: {e}")

def migrate_journal_entries():
    """Migrates journal entries from the old journal.csv to the SQLite database."""
    print("\nStarting journal entry migration...")
    if not os.path.exists(JOURNAL_CSV):
        print(f"Journal CSV file not found: {JOURNAL_CSV}")
        return

    migrated_count = 0
    failed_count = 0
    try:
        with open(JOURNAL_CSV, 'r', newline='', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames or "UserID" not in reader.fieldnames:
                print(f"Journal CSV {JOURNAL_CSV} is empty or missing required headers (e.g., UserID).")
                return
            
            for row_num, row in enumerate(reader, 1):
                try:
                    user_id = int(row.get("UserID", "").strip())
                    raw_text = row.get("Raw Text", "").strip()
                    input_type = row.get("Input Type", "text").strip() # Default to 'text' if missing
                    word_count_str = row.get("Word Count", "0").strip()
                    word_count = int(word_count_str) if word_count_str else 0
                    
                    sentiment = row.get("Sentiment", "N/A").strip()
                    topics = row.get("Topics", "N/A").strip()
                    categories = row.get("Categories", "N/A").strip()
                    
                    date_str = row.get("Date", "").strip()
                    time_str = row.get("Time", "").strip()
                    
                    timestamp_obj = None
                    if date_str and time_str:
                        try:
                            # Assuming date is YYYY-MM-DD and time is HH:MM:SS or HH:MM
                            dt_str = f"{date_str} {time_str}"
                            if ":" in time_str and len(time_str.split(':')) == 2: # HH:MM format
                                timestamp_obj = datetime.strptime(dt_str, '%Y-%m-%d %H:%M').replace(tzinfo=timezone.utc)
                            else: # Assuming HH:MM:SS
                                timestamp_obj = datetime.strptime(dt_str, '%Y-%m-%d %H:%M:%S').replace(tzinfo=timezone.utc)
                        except ValueError as ve:
                            print(f"Row {row_num}: Error parsing date/time '{date_str} {time_str}': {ve}. Storing as current time.")
                            timestamp_obj = datetime.now(timezone.utc) # Fallback
                    else:
                        timestamp_obj = datetime.now(timezone.utc) # Fallback if date/time missing

                    # db_utils.add_journal_entry expects all these fields.
                    # The old CSV might not have ai_analysis_text or dot_code.
                    entry_id = db_utils.add_journal_entry(
                        user_id=user_id,
                        raw_text=raw_text,
                        input_type=input_type,
                        word_count=word_count,
                        sentiment=sentiment if sentiment and sentiment != "N/A" else None,
                        topics=topics if topics and topics != "N/A" else None,
                        categories=categories if categories and categories != "N/A" else None,
                        ai_analysis_text=None, # Not in old CSV
                        dot_code=None,         # Not in old CSV
                        timestamp_override=timestamp_obj # Pass the parsed timestamp
                    )
                    if entry_id:
                        migrated_count += 1
                        if migrated_count % 50 == 0: # Print progress every 50 entries
                            print(f"  Migrated {migrated_count} journal entries...")
                    else:
                        failed_count += 1
                        print(f"Row {row_num}: Failed to migrate journal entry for UserID {user_id}.")
                
                except ValueError as ve:
                    print(f"Row {row_num}: Invalid data format in row: {row}. Error: {ve}. Skipping.")
                    failed_count += 1
                except Exception as e:
                    print(f"Row {row_num}: An error occurred processing row {row}: {e}")
                    failed_count +=1
        
        print(f"\nJournal entry migration summary:")
        print(f"  Successfully migrated: {migrated_count} entries.")
        print(f"  Failed/skipped: {failed_count} entries.")

    except FileNotFoundError:
        print(f"Journal CSV file not found: {JOURNAL_CSV}")
    except Exception as e:
        print(f"An unexpected error occurred during journal migration: {e}")


if __name__ == '__main__':
    print("Starting data migration process...")
    
    # Ensure database and tables exist before migration
    print("Ensuring database and tables are created...")
    conn = None
    try:
        # Ensure data directory exists for the database file
        os.makedirs(os.path.dirname(db_utils.DATABASE_PATH), exist_ok=True)
        conn = db_utils.get_db_connection()
        if conn:
            db_utils.create_tables(conn) # This function now closes the connection
            print(f"Database tables checked/created at {db_utils.DATABASE_PATH}")
        else:
            print(f"FATAL: Could not establish database connection at {db_utils.DATABASE_PATH}. Migration aborted.")
            exit(1)
    except Exception as e:
        print(f"FATAL: Error setting up database: {e}. Migration aborted.")
        if conn:
            conn.close()
        exit(1)
    finally:
        if conn and not conn.closed: # Ensure connection is closed if create_tables didn't
             conn.close()


    migrate_users()
    migrate_journal_entries()
    
    print("\nData migration process finished.")
    print(f"Please verify the data in the SQLite database: {db_utils.DATABASE_PATH}")
