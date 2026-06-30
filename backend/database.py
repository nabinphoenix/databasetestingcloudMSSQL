import os
from pathlib import Path

import pyodbc
from dotenv import load_dotenv


load_dotenv(Path(__file__).with_name(".env"), override=True)


class DatabaseConfigError(RuntimeError):
    pass


def get_required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise DatabaseConfigError(f"Missing required environment variable: {name}")
    return value


def get_connection():
    host = get_required_env("DB_HOST")
    database = get_required_env("DB_NAME")
    user = get_required_env("DB_USER")
    password = get_required_env("DB_PASSWORD")

    connection_string = (
        "DRIVER={ODBC Driver 18 for SQL Server};"
        f"SERVER={host};"
        f"DATABASE={database};"
        f"UID={user};"
        f"PWD={password};"
        "Encrypt=yes;"
        "TrustServerCertificate=yes;"
    )

    return pyodbc.connect(connection_string)
