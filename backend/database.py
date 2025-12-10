from sqlmodel import SQLModel, create_engine, Session

import os
sqlite_file_name = "database_v2.db"
sqlite_url = os.environ.get("DATABASE_URL", f"sqlite:///{sqlite_file_name}")

if "sqlite" in sqlite_url:
    # Extract path and ensure directory exists
    # split 'sqlite:///' or 'sqlite://'
    path = sqlite_url.replace("sqlite:///", "").replace("sqlite://", "")
    folder = os.path.dirname(path)
    if folder:
        os.makedirs(folder, exist_ok=True)

engine = create_engine(sqlite_url, connect_args={"check_same_thread": False} if "sqlite" in sqlite_url else {})

def create_db_and_tables():
    SQLModel.metadata.create_all(engine)

def get_session():
    with Session(engine) as session:
        yield session
