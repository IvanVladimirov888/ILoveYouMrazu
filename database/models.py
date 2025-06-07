from datetime import datetime

from app import app
from database.db_connection import get_db_connection, execute_query  # Исправленный импорт

class BaseModel:
    @classmethod
    def safe_get(cls, query, params=None):
        try:
            return execute_query(query, params, fetch_one=True)
        except Exception as e:
            app.logger.error(f"Safe get failed: {str(e)}")
            return None

    @classmethod
    def safe_get_all(cls, query, params=None):
        try:
            return execute_query(query, params)
        except Exception as e:
            app.logger.error(f"Safe get all failed: {str(e)}")
            return []

class User(BaseModel):
    @classmethod
    def get_by_username(cls, username):
        return cls.safe_get("SELECT * FROM users WHERE username = %s", (username,))

class User:
    def __init__(self, id, full_name, phone, username, password, role_id, is_active=True):
        self.id = id
        self.full_name = full_name
        self.phone = phone
        self.username = username
        self.password = password
        self.role_id = role_id
        self.is_active = is_active
        self.created_at = datetime.now()
        self.updated_at = None

    @classmethod
    def get_by_username(cls, username):
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        user_data = cursor.fetchone()
        cursor.close()
        conn.close()
        return cls(**user_data) if user_data else None


class Material:
    def __init__(self, id, name, quantity, unit, min_quantity, category_id=None,
                 price_per_unit=0, supplier_id=None, expiration_date=None,
                 auto_add_to_request=False):
        self.id = id
        self.name = name
        self.quantity = quantity
        self.unit = unit
        self.min_quantity = min_quantity
        self.category_id = category_id
        self.price_per_unit = price_per_unit
        self.supplier_id = supplier_id
        self.expiration_date = expiration_date
        self.auto_add_to_request = auto_add_to_request

    @classmethod
    def get_all(cls, search_query='', category_id=None):
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)

        query = """
        SELECT m.*, c.name as category_name 
        FROM materials m
        LEFT JOIN categories c ON m.category_id = c.id
        WHERE m.name LIKE %s
        """
        params = [f'%{search_query}%']

        if category_id:
            query += " AND c.id = %s"
            params.append(category_id)

        cursor.execute(query, params)
        materials = [cls(**row) for row in cursor.fetchall()]

        cursor.close()
        conn.close()
        return materials


class Category:
    def __init__(self, id, name, is_chemical=False):
        self.id = id
        self.name = name
        self.is_chemical = is_chemical

    @classmethod
    def get_all(cls):
        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM categories")
        categories = [cls(**row) for row in cursor.fetchall()]
        cursor.close()
        conn.close()
        return categories