import mysql.connector
import os

def get_db_connection():
    return mysql.connector.connect(
        host=os.getenv("MEDIAI_DB_HOST", "127.0.0.1"),
        user=os.getenv("MEDIAI_DB_USER", "root"),
        password=os.getenv("MEDIAI_DB_PASSWORD", "admin123"),
        database=os.getenv("MEDIAI_DB_NAME", "mediai")
    )
