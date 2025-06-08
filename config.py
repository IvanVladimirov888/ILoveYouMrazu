#sdffsdfsdfsdfsfd

import os
from dotenv import load_dotenv
#БД
load_dotenv()

class Config:
    SECRET_KEY = os.getenv('SECRET_KEY') or '123456789'

DB_CONFIG = {
    'host': os.getenv('DB_HOST') or 'localhost',
    'database': os.getenv('DB_NAME') or 'Alik',
    'user': os.getenv('DB_USER') or 'root',
    'password': os.getenv('DB_PASSWORD') or 'Ivan_Vladimirov_888',
    'port': os.getenv('DB_PORT') or 3306,
    'auth_plugin': 'mysql_native_password'
}

