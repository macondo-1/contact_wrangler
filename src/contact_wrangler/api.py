import os

from fastapi import FastAPI
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

load_dotenv('.env')
DATABASE_URL = os.environ.get('DATABASE_URL')

app = FastAPI()

@app.get("/health")
def health():
    engine = create_engine(DATABASE_URL)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
    return {"status": "ok"}
