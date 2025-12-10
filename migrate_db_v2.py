from backend.database import engine
from sqlalchemy import text

def migrate():
    print("Migrating schema...")
    with engine.connect() as conn:
        try:
            conn.execute(text("ALTER TABLE voiceconfig ADD COLUMN system_prompt VARCHAR"))
            conn.commit()
            print("Added system_prompt column.")
        except Exception as e:
            if "duplicate column" in str(e) or "no such table" in str(e):
                print("Column already exists or table missing (will be created).")
            else:
                print(f"Migration error (might be okay if column exists): {e}")

if __name__ == "__main__":
    migrate()
