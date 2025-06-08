import mysql.connector
from mysql.connector import Error
from config import DB_CONFIG
#qweeqweqe
def get_db_connection():
    """Возвращает соединение с базой данных"""
    try:
        connection = mysql.connector.connect(**DB_CONFIG)
        return connection
    except Error as e:
        print(f"Error connecting to MySQL: {e}")
        return None

def get_db_cursor(connection):
    """Возвращает курсор с dictionary=True"""
    return connection.cursor(dictionary=True)


def execute_query(query, params=None, fetch_one=False):
    try:
        with get_db_connection() as conn:
            with conn.cursor(dictionary=True) as cursor:
                cursor.execute(query, params or ())
                if fetch_one:
                    return cursor.fetchone()
                return cursor.fetchall()
    except Error as e:
        #app.logger.error(f"Query failed: {query} | Error: {str(e)}")
        raise

def test_db_connection():
    """Тестирует подключение к базе данных и выводит сообщение в консоль."""
    try:
        # Пытаемся подключиться к базе данных
        connection = mysql.connector.connect(**DB_CONFIG)

        if connection.is_connected():
            print("Успешно подключено к базе данных!")
            connection.close()  # Закрываем соединение после проверки
    except Error as e:
        print(f"Ошибка при подключении к базе данных: {e}")