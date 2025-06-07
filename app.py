from locale import Error

from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file
from werkzeug.security import generate_password_hash, check_password_hash
import os
from datetime import datetime
import secrets
import logging
from functools import wraps

# Инициализация Flask приложения
app = Flask(__name__)

# Секретный ключ для защиты сессий
app.secret_key = os.environ.get('SECRET_KEY') or secrets.token_hex(32)

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    filename='app.log'
)

app.config['UPLOAD_FOLDER'] = 'uploads'
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Импорт после создания app для избежания циклических импортов
from database.db_connection import get_db_connection, test_db_connection
from database.queries import *
from utils.file_handling import import_materials_from_csv, export_materials_to_csv
from utils.reporting import generate_word_report

@app.route('/')
def home():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    user_role = session.get('role')
    if user_role == 'admin':
        return redirect(url_for('admin_dashboard'))
    elif user_role == 'user':
        return redirect(url_for('manager_dashboard'))
    else:
        return redirect(url_for('user_dashboard'))


def create_password_hash(password):
    """Создает безопасный хеш пароля"""
    return generate_password_hash(password, method='pbkdf2:sha256')

# Authentication routes
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        conn = None
        cursor = None
        try:
            conn = get_db_connection()
            if not conn:
                flash('Ошибка подключения к базе данных', 'danger')
                return redirect(url_for('login'))

            cursor = conn.cursor(dictionary=True)
            cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
            user = cursor.fetchone()

            if user and check_password_hash(user['password'], password):
                session['user_id'] = user['id']
                session['username'] = user['username']
                session['full_name'] = user['full_name']
                session['role'] = get_user_role(conn, user['id'])  # Передаем соединение
                flash('Вы успешно вошли в систему', 'success')
                return redirect(url_for('home'))
            else:
                flash('Неверное имя пользователя или пароль', 'danger')

        except Exception as e:
            flash('Ошибка при входе в систему', 'danger')
            app.logger.error(f"Login error: {str(e)}")
        finally:
            if cursor:
                cursor.close()
            if conn:
                conn.close()

    return render_template('auth/login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        full_name = request.form['full_name']
        phone = request.form['phone']
        username = request.form['username']
        password = generate_password_hash(request.form['password'])

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            # Default role is 'cleaner' for new users
            cursor.execute("INSERT INTO users (full_name, phone, username, password, role_id) "
                           "VALUES (%s, %s, %s, %s, (SELECT id FROM roles WHERE name = 'cleaner'))",
                           (full_name, phone, username, password))
            conn.commit()
            flash('Регистрация успешна. Пожалуйста, войдите.', 'success')
            return redirect(url_for('login'))
        except Exception as e:
            conn.rollback()
            flash('Ошибка регистрации: ' + str(e), 'danger')
        finally:
            cursor.close()
            conn.close()

    return render_template('auth/register.html')


@app.route('/logout')
def logout():
    session.clear()
    flash('Вы вышли из системы', 'info')
    return redirect(url_for('login'))


# Admin routes
@app.route('/admin/dashboard')
def admin_dashboard():
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('login'))

    return render_template('admin/dashboard.html')


@app.route('/admin/materials', methods=['GET', 'POST'])
def admin_materials():
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Search functionality
    search_query = request.args.get('search', '')
    category_filter = request.args.get('category', '')

    query = """
    SELECT m.*, c.name as category_name 
    FROM materials m
    LEFT JOIN categories c ON m.category_id = c.id
    WHERE m.name LIKE %s
    """
    params = [f'%{search_query}%']

    if category_filter and category_filter != 'all':
        query += " AND c.id = %s"
        params.append(category_filter)

    cursor.execute(query, params)
    materials = cursor.fetchall()

    # Get categories for filter dropdown
    cursor.execute("SELECT * FROM categories")
    categories = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('materials/list.html',
                           materials=materials,
                           categories=categories,
                           search_query=search_query,
                           selected_category=category_filter)


@app.route('/admin/materials/add', methods=['GET', 'POST'])
def add_material():
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        name = request.form['name']
        quantity = float(request.form['quantity'])
        unit = request.form['unit']
        min_quantity = float(request.form['min_quantity'])
        category_id = request.form['category_id'] if request.form['category_id'] else None
        price_per_unit = float(request.form['price_per_unit'])
        supplier_id = request.form['supplier_id'] if request.form['supplier_id'] else None
        expiration_date = request.form['expiration_date'] if request.form['expiration_date'] else None
        auto_add = 1 if 'auto_add_to_request' in request.form else 0

        try:
            cursor.execute("""
                INSERT INTO materials 
                (name, quantity, unit, min_quantity, category_id, price_per_unit, 
                 supplier_id, expiration_date, auto_add_to_request)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (name, quantity, unit, min_quantity, category_id, price_per_unit,
                  supplier_id, expiration_date, auto_add))
            conn.commit()
            flash('Материал успешно добавлен', 'success')
            return redirect(url_for('admin_materials'))
        except Exception as e:
            conn.rollback()
            flash(f'Ошибка при добавлении материала: {str(e)}', 'danger')

    # Get categories and suppliers for dropdowns
    cursor.execute("SELECT * FROM categories")
    categories = cursor.fetchall()

    cursor.execute("SELECT * FROM suppliers")
    suppliers = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('materials/add.html', categories=categories, suppliers=suppliers)


# Add similar routes for other admin functionalities (categories, equipment, etc.)
# User routes
@app.route('/user/dashboard')
def user_dashboard():
    if 'user_id' not in session:
        flash('Пожалуйста, войдите в систему', 'danger')
        return redirect(url_for('login'))

    user_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Get user's requests
    cursor.execute("""
        SELECT r.*, u.full_name as user_name 
        FROM requests r
        JOIN users u ON r.user_id = u.id
        WHERE r.user_id = %s
        ORDER BY r.created_at DESC
    """, (user_id,))
    requests = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('user/dashboard.html', requests=requests)


@app.route('/user/requests/create', methods=['GET', 'POST'])
def create_request():
    if 'user_id' not in session:
        flash('Пожалуйста, войдите в систему', 'danger')
        return redirect(url_for('login'))

    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        area = float(request.form['area']) if request.form['area'] else None
        user_id = session['user_id']

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO requests (user_id, title, description, area, status)
                VALUES (%s, %s, %s, %s, 'draft')
            """, (user_id, title, description, area))
            request_id = cursor.lastrowid

            # Add auto materials if any
            cursor.execute("""
                SELECT id FROM materials WHERE auto_add_to_request = 1
            """)
            auto_materials = cursor.fetchall()

            for material in auto_materials:
                # Add default quantity (could be configurable)
                cursor.execute("""
                    INSERT INTO request_materials (request_id, material_id, quantity)
                    VALUES (%s, %s, 1)
                """, (request_id, material['id']))

            conn.commit()
            flash('Заявка успешно создана', 'success')
            return redirect(url_for('view_request', request_id=request_id))
        except Exception as e:
            conn.rollback()
            flash(f'Ошибка при создании заявки: {str(e)}', 'danger')
        finally:
            cursor.close()
            conn.close()

    return render_template('requests/create.html')


# Add other routes for request management, material adding, etc.
@app.route('/categories')
def categories_list():
    if 'user_id' not in session or session.get('role') not in ['admin', 'user']:
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Получаем категории с количеством материалов
    cursor.execute("""
        SELECT c.*, COUNT(m.id) as materials_count 
        FROM categories c
        LEFT JOIN materials m ON m.category_id = c.id
        GROUP BY c.id
    """)
    categories = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('categories/list.html', categories=categories)


@app.route('/categories/manage')
def manage_categories():
    if 'user_id' not in session or session.get('role') not in ['admin', 'user']:
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT c.*, COUNT(m.id) as materials_count 
        FROM categories c
        LEFT JOIN materials m ON m.category_id = c.id
        GROUP BY c.id
    """)
    categories = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('categories/manage.html', categories=categories)


@app.route('/categories/add', methods=['POST'])
def add_category():
    if 'user_id' not in session or session.get('role') not in ['admin', 'user']:
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('login'))

    name = request.form.get('name')
    is_chemical = 1 if 'is_chemical' in request.form else 0

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("INSERT INTO categories (name, is_chemical) VALUES (%s, %s)",
                       (name, is_chemical))
        conn.commit()
        flash('Категория успешно добавлена', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Ошибка при добавлении категории: {str(e)}', 'danger')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('manage_categories'))


@app.route('/categories/update/<int:id>', methods=['POST'])
def update_category(id):
    if 'user_id' not in session or session.get('role') not in ['admin', 'user']:
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('login'))

    name = request.form.get('name')
    is_chemical = int(request.form.get('is_chemical', 0))

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE categories 
            SET name = %s, is_chemical = %s 
            WHERE id = %s
        """, (name, is_chemical, id))
        conn.commit()
        flash('Категория успешно обновлена', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Ошибка при обновлении категории: {str(e)}', 'danger')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('manage_categories'))


@app.route('/categories/delete/<int:id>', methods=['POST'])
def delete_category(id):
    if 'user_id' not in session or session.get('role') not in ['admin', 'user']:
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Проверяем, есть ли материалы в этой категории
        cursor.execute("SELECT COUNT(*) FROM materials WHERE category_id = %s", (id,))
        count = cursor.fetchone()[0]

        if count > 0:
            flash('Нельзя удалить категорию, так как в ней есть материалы', 'danger')
        else:
            cursor.execute("DELETE FROM categories WHERE id = %s", (id,))
            conn.commit()
            flash('Категория успешно удалена', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Ошибка при удалении категории: {str(e)}', 'danger')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('manage_categories'))

if __name__ == '__main__':
    test_db_connection()
    app.run(debug=True)