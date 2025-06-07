from database.db_connection import get_db_connection, get_db_cursor


def get_user_role(conn, user_id):
    """Получает роль пользователя, используя существующее соединение"""
    cursor = None
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT r.name 
            FROM users u
            JOIN roles r ON u.role_id = r.id
            WHERE u.id = %s
        """, (user_id,))
        role = cursor.fetchone()
        return role['name'] if role else None
    except Exception as e:
        print(f"Error getting user role: {e}")
        return None
    finally:
        if cursor:
            cursor.close()

def get_auto_materials():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM materials WHERE auto_add_to_request = 1")
    materials = cursor.fetchall()
    cursor.close()
    conn.close()
    return materials

def get_chemical_materials():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT m.* 
        FROM materials m
        JOIN categories c ON m.category_id = c.id
        WHERE c.is_chemical = 1
    """)
    materials = cursor.fetchall()
    cursor.close()
    conn.close()
    return materials

def get_equipment_list():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM equipment WHERE is_active = 1")
    equipment = cursor.fetchall()
    cursor.close()
    conn.close()
    return equipment