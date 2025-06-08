# file app.py
from locale import Error

from flask import Flask, render_template, request, redirect, url_for, flash, session, send_file
from werkzeug.security import generate_password_hash, check_password_hash
import os
from datetime import datetime, timedelta
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


# Декоратор для проверки прав администратора
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or session.get('role') != 'admin':
            flash('Доступ запрещен', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)

    return decorated_function


@app.route('/')
def home():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    return redirect(url_for('dashboard'))


@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        flash('Пожалуйста, войдите в систему', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Данные для всех пользователей
    cursor.execute("""
        SELECT * FROM requests 
        WHERE user_id = %s 
        ORDER BY created_at DESC
        LIMIT 5
    """, (session['user_id'],))
    user_requests = cursor.fetchall()

    # Данные только для администратора
    admin_stats = None
    if session.get('role') == 'admin':
        admin_stats = {}

        cursor.execute("SELECT COUNT(*) as count FROM users")
        admin_stats['total_users'] = cursor.fetchone()['count']

        cursor.execute("SELECT COUNT(*) as count FROM requests WHERE status = 'pending'")
        admin_stats['pending_requests'] = cursor.fetchone()['count']

        # ИСПРАВЛЕННЫЙ ЗАПРОС - считаем только материалы с недостатком
        cursor.execute("SELECT COUNT(*) as count FROM materials WHERE quantity < min_quantity")
        admin_stats['low_materials'] = cursor.fetchone()['count']

        cursor.execute("SELECT COUNT(*) as count FROM equipment WHERE is_active = 1")
        admin_stats['active_equipment'] = cursor.fetchone()['count']

        # Последние заявки от всех пользователей для админа
        cursor.execute("""
            SELECT r.*, u.full_name as user_name 
            FROM requests r
            JOIN users u ON r.user_id = u.id
            ORDER BY r.created_at DESC
            LIMIT 10
        """)
        admin_stats['recent_requests'] = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('dashboard.html',
                           user_requests=user_requests,
                           admin_stats=admin_stats)


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
                # Проверяем, активен ли пользователь
                if not user.get('is_active', True):
                    flash('Ваша учетная запись заблокирована. Обратитесь к администратору.', 'danger')
                    return redirect(url_for('login'))

                session['user_id'] = user['id']
                session['username'] = user['username']
                session['full_name'] = user['full_name']
                session['role'] = get_user_role(conn, user['id'])
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


# === ADMIN ROUTES ===

@app.route('/admin/users')
def admin_users():
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("""
        SELECT u.*, r.name as role_name 
        FROM users u
        JOIN roles r ON u.role_id = r.id
    """)
    users = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template('admin/users.html', users=users)


@app.route('/admin/materials')
def admin_materials():
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('login'))

    # Перенаправляем на общий список материалов
    return redirect(url_for('materials_list'))

@app.route('/admin/users/add', methods=['POST'])
def add_user():
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('login'))

    full_name = request.form['full_name']
    phone = request.form['phone']
    username = request.form['username']
    password = generate_password_hash(request.form['password'])
    role_id = request.form['role_id']

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO users (full_name, phone, username, password, role_id)
            VALUES (%s, %s, %s, %s, %s)
        """, (full_name, phone, username, password, role_id))
        conn.commit()
        flash('Пользователь успешно добавлен', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Ошибка при добавлении пользователя: {str(e)}', 'danger')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('admin_users'))


@app.route('/admin/users/<int:id>/edit', methods=['POST'])
def edit_user(id):
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('login'))

    full_name = request.form['full_name']
    phone = request.form['phone']
    username = request.form['username']
    password = request.form.get('password')
    role_id = request.form['role_id']

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        if password:
            # Если указан новый пароль
            hashed_password = generate_password_hash(password)
            cursor.execute("""
                UPDATE users 
                SET full_name = %s, phone = %s, username = %s, password = %s, role_id = %s
                WHERE id = %s
            """, (full_name, phone, username, hashed_password, role_id, id))
        else:
            # Если пароль не меняется
            cursor.execute("""
                UPDATE users 
                SET full_name = %s, phone = %s, username = %s, role_id = %s
                WHERE id = %s
            """, (full_name, phone, username, role_id, id))

        conn.commit()
        flash('Пользователь успешно обновлен', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Ошибка при обновлении пользователя: {str(e)}', 'danger')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('admin_users'))


@app.route('/admin/users/<int:id>/toggle-status', methods=['POST'])
def toggle_user_status(id):
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('login'))

    if id == session['user_id']:
        flash('Вы не можете изменить свой собственный статус', 'danger')
        return redirect(url_for('admin_users'))

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE users 
            SET is_active = NOT is_active
            WHERE id = %s
        """, (id,))
        conn.commit()
        flash('Статус пользователя изменен', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Ошибка при изменении статуса: {str(e)}', 'danger')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('admin_users'))



@app.route('/admin/users/<int:id>/delete', methods=['POST'])
def delete_user(id):
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('login'))

    if id == session['user_id']:
        flash('Вы не можете удалить свой собственный аккаунт', 'danger')
        return redirect(url_for('admin_users'))

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("DELETE FROM users WHERE id = %s", (id,))
        conn.commit()
        flash('Пользователь успешно удален', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Ошибка при удалении пользователя: {str(e)}', 'danger')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('admin_users'))
@app.route('/admin/requests')
def admin_requests():
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('login'))

    # Используем существующую функцию с дополнительными правами админа
    return requests_list()


@app.route('/admin/reports')
def admin_reports():
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('login'))

    return reports()


@app.route('/admin/equipment')
def admin_equipment():
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('login'))

    return equipment_list()


@app.route('/admin/suppliers')
def admin_suppliers():
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM suppliers ORDER BY name")
    suppliers = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template('admin/suppliers.html', suppliers=suppliers)


@app.route('/admin/suppliers/add', methods=['POST'])
def add_supplier():
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('login'))

    name = request.form['name']
    contact_info = request.form.get('contact_info', '')

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            INSERT INTO suppliers (name, contact_info)
            VALUES (%s, %s)
        """, (name, contact_info))
        conn.commit()
        flash('Поставщик успешно добавлен', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Ошибка при добавлении поставщика: {str(e)}', 'danger')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('admin_suppliers'))


@app.route('/admin/suppliers/<int:id>/edit', methods=['POST'])
def edit_supplier(id):
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('login'))

    name = request.form['name']
    contact_info = request.form.get('contact_info', '')

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE suppliers 
            SET name = %s, contact_info = %s
            WHERE id = %s
        """, (name, contact_info, id))
        conn.commit()
        flash('Поставщик успешно обновлен', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Ошибка при обновлении поставщика: {str(e)}', 'danger')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('admin_suppliers'))


@app.route('/admin/suppliers/<int:id>/delete', methods=['POST'])
def delete_supplier(id):
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("DELETE FROM suppliers WHERE id = %s", (id,))
        conn.commit()
        flash('Поставщик успешно удален', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Ошибка при удалении поставщика: {str(e)}', 'danger')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('admin_suppliers'))




# === MATERIALS ROUTES ===

@app.route('/materials')
def materials_list():
    if 'user_id' not in session:
        flash('Пожалуйста, войдите в систему', 'danger')
        return redirect(url_for('login'))

    search_query = request.args.get('search', '')
    selected_category = request.args.get('category', 'all')

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Получаем категории для фильтра
    cursor.execute("SELECT * FROM categories")
    categories = cursor.fetchall()

    # Получаем материалы
    query = """
        SELECT m.*, c.name as category_name 
        FROM materials m
        LEFT JOIN categories c ON m.category_id = c.id
        WHERE 1=1
    """
    params = []

    if search_query:
        query += " AND m.name LIKE %s"
        params.append(f'%{search_query}%')

    if selected_category != 'all':
        query += " AND m.category_id = %s"
        params.append(selected_category)

    query += " ORDER BY m.name"

    cursor.execute(query, params)
    materials = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('materials/list.html',
                           materials=materials,
                           categories=categories,
                           search_query=search_query,
                           selected_category=selected_category)


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


@app.route('/materials/edit/<int:id>', methods=['GET', 'POST'])
def edit_material(id):
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
                UPDATE materials 
                SET name = %s, quantity = %s, unit = %s, min_quantity = %s, 
                    category_id = %s, price_per_unit = %s, supplier_id = %s, 
                    expiration_date = %s, auto_add_to_request = %s
                WHERE id = %s
            """, (name, quantity, unit, min_quantity, category_id, price_per_unit,
                  supplier_id, expiration_date, auto_add, id))
            conn.commit()
            flash('Материал успешно обновлен', 'success')
            return redirect(url_for('materials_list'))
        except Exception as e:
            conn.rollback()
            flash(f'Ошибка при обновлении материала: {str(e)}', 'danger')

    # Получаем данные материала
    cursor.execute("SELECT * FROM materials WHERE id = %s", (id,))
    material = cursor.fetchone()

    if not material:
        flash('Материал не найден', 'danger')
        return redirect(url_for('materials_list'))

    # Получаем категории и поставщиков
    cursor.execute("SELECT * FROM categories")
    categories = cursor.fetchall()

    cursor.execute("SELECT * FROM suppliers")
    suppliers = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('materials/edit.html',
                           material=material,
                           categories=categories,
                           suppliers=suppliers)

@app.route('/admin/materials/delete/<int:id>')
def delete_material(id):
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("DELETE FROM materials WHERE id = %s", (id,))
        conn.commit()
        flash('Материал успешно удален', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Ошибка при удалении материала: {str(e)}', 'danger')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('materials_list'))


# === IMPORT/EXPORT ROUTES ===

@app.route('/materials/import', methods=['GET', 'POST'])
def import_materials():
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('login'))

    if request.method == 'POST':
        if 'csv_file' not in request.files:
            flash('Файл не выбран', 'danger')
            return redirect(url_for('import_materials'))

        file = request.files['csv_file']
        if file.filename == '':
            flash('Файл не выбран', 'danger')
            return redirect(url_for('import_materials'))

        if file and file.filename.endswith('.csv'):
            filename = os.path.join(app.config['UPLOAD_FOLDER'], 'import_temp.csv')
            file.save(filename)

            try:
                imported, errors = import_materials_from_csv(filename)
                flash(f'Импортировано: {imported} материалов. Ошибок: {errors}', 'success')
            except Exception as e:
                flash(f'Ошибка при импорте: {str(e)}', 'danger')
            finally:
                os.remove(filename)
        else:
            flash('Неверный формат файла. Требуется CSV', 'danger')

    return render_template('materials/import_export.html')


@app.route('/materials/export')
def export_materials():
    if 'user_id' not in session:
        flash('Пожалуйста, войдите в систему', 'danger')
        return redirect(url_for('login'))

    try:
        filepath = export_materials_to_csv()
        return send_file(filepath, as_attachment=True, download_name='materials_export.csv')
    except Exception as e:
        flash(f'Ошибка при экспорте: {str(e)}', 'danger')
        return redirect(url_for('materials_list'))


# === CATEGORIES ROUTES ===

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


# === EQUIPMENT ROUTES ===

@app.route('/equipment')
def equipment_list():
    if 'user_id' not in session:
        flash('Пожалуйста, войдите в систему', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM equipment ORDER BY name")
    equipment = cursor.fetchall()
    cursor.close()
    conn.close()

    return render_template('equipment/list.html', equipment=equipment, timedelta=timedelta)


@app.route('/equipment/add', methods=['GET', 'POST'])
def add_equipment():
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('login'))

    if request.method == 'POST':
        name = request.form['name']
        maintenance_interval = request.form.get('maintenance_interval')
        is_active = 1 if 'is_active' in request.form else 0

        conn = get_db_connection()
        cursor = conn.cursor()

        try:
            cursor.execute("""
                INSERT INTO equipment (name, maintenance_interval, is_active)
                VALUES (%s, %s, %s)
            """, (name, maintenance_interval, is_active))
            conn.commit()
            flash('Техника успешно добавлена', 'success')
            return redirect(url_for('equipment_list'))
        except Exception as e:
            conn.rollback()
            flash(f'Ошибка при добавлении техники: {str(e)}', 'danger')
        finally:
            cursor.close()
            conn.close()

    return render_template('equipment/add.html')


@app.route('/equipment/edit/<int:id>', methods=['GET', 'POST'])
def edit_equipment(id):
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        name = request.form['name']
        maintenance_interval = request.form.get('maintenance_interval')
        is_active = 1 if 'is_active' in request.form else 0

        try:
            cursor.execute("""
                UPDATE equipment 
                SET name = %s, maintenance_interval = %s, is_active = %s
                WHERE id = %s
            """, (name, maintenance_interval, is_active, id))
            conn.commit()
            flash('Техника успешно обновлена', 'success')
            return redirect(url_for('equipment_list'))
        except Exception as e:
            conn.rollback()
            flash(f'Ошибка при обновлении техники: {str(e)}', 'danger')

    # Получаем данные техники
    cursor.execute("SELECT * FROM equipment WHERE id = %s", (id,))
    equipment = cursor.fetchone()

    if not equipment:
        flash('Техника не найдена', 'danger')
        return redirect(url_for('equipment_list'))

    cursor.close()
    conn.close()

    return render_template('equipment/edit.html', equipment=equipment)
@app.route('/equipment/delete/<int:id>', methods=['POST'])
def delete_equipment(id):
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("DELETE FROM equipment WHERE id = %s", (id,))
        conn.commit()
        flash('Техника успешно удалена', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Ошибка при удалении техники: {str(e)}', 'danger')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('equipment_list'))


@app.route('/equipment/maintenance/<int:id>')
def equipment_maintenance(id):
    if 'user_id' not in session:
        flash('Пожалуйста, войдите в систему', 'danger')
        return redirect(url_for('login'))

    # Добавить логику технического обслуживания
    flash('Функция в разработке', 'info')
    return redirect(url_for('equipment_list'))


# === REPORTS ROUTES ===

@app.route('/reports')
def reports():
    if 'user_id' not in session:
        flash('Пожалуйста, войдите в систему', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Получаем категории для фильтра
    cursor.execute("SELECT * FROM categories")
    categories = cursor.fetchall()

    # Базовая статистика
    stats = {
        'total_requests': 0,
        'completed_requests': 0,
        'total_materials': 0,
        'total_equipment': 0
    }

    # Получаем статистику
    cursor.execute("SELECT COUNT(*) as count FROM requests")
    stats['total_requests'] = cursor.fetchone()['count']

    cursor.execute("SELECT COUNT(*) as count FROM requests WHERE status = 'completed'")
    stats['completed_requests'] = cursor.fetchone()['count']

    cursor.execute("SELECT COUNT(*) as count FROM materials")
    stats['total_materials'] = cursor.fetchone()['count']

    cursor.execute("SELECT COUNT(*) as count FROM equipment")
    stats['total_equipment'] = cursor.fetchone()['count']

    # Данные для графика (пример)
    chart_labels = ['Январь', 'Февраль', 'Март', 'Апрель', 'Май', 'Июнь']
    chart_values = [10, 15, 8, 22, 18, 25]
    chart_title = 'Количество заявок по месяцам'
    chart_type = 'bar'

    cursor.close()
    conn.close()

    return render_template('reports/charts.html',
                           categories=categories,
                           stats=stats,
                           chart_labels=chart_labels,
                           chart_values=chart_values,
                           chart_title=chart_title,
                           chart_type=chart_type)


@app.route('/reports/export/<report_type>')
def export_report(report_type):
    if 'user_id' not in session:
        flash('Пожалуйста, войдите в систему', 'danger')
        return redirect(url_for('login'))

    # Временная заглушка
    flash(f'Экспорт в {report_type.upper()} в разработке', 'info')
    return redirect(url_for('reports'))


# === REQUESTS ROUTES ===

@app.route('/requests')
def requests_list():
    if 'user_id' not in session:
        flash('Пожалуйста, войдите в систему', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Базовый запрос
    query = """
        SELECT r.*, u.full_name as user_name 
        FROM requests r
        JOIN users u ON r.user_id = u.id
    """
    params = []
    conditions = []

    # Фильтры для админа
    if session.get('role') == 'admin':
        status_filter = request.args.get('status')
        user_filter = request.args.get('user_id')

        if status_filter:
            conditions.append("r.status = %s")
            params.append(status_filter)
        if user_filter:
            conditions.append("r.user_id = %s")
            params.append(user_filter)

        # Получаем всех пользователей для фильтра
        cursor.execute("SELECT id, full_name FROM users ORDER BY full_name")
        users = cursor.fetchall()
    else:
        # Для обычных пользователей - только их заявки
        conditions.append("r.user_id = %s")
        params.append(session['user_id'])
        users = []

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY r.created_at DESC"

    cursor.execute(query, params)
    requests_data = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('requests/list.html',
                           requests=requests_data,
                           users=users)


@app.route('/user/requests/create', methods=['GET', 'POST'])
def create_request():
    if 'user_id' not in session:
        flash('Пожалуйста, войдите в систему', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST':
        title = request.form['title']
        description = request.form['description']
        area = float(request.form['area']) if request.form['area'] else None

        # Если админ создает заявку для другого пользователя
        if session.get('role') == 'admin' and 'user_id' in request.form:
            user_id = request.form['user_id']
        else:
            user_id = session['user_id']

        try:
            cursor.execute("""
                INSERT INTO requests (user_id, title, description, area, status)
                VALUES (%s, %s, %s, %s, 'pending')
            """, (user_id, title, description, area))
            request_id = cursor.lastrowid

            # Добавляем материалы в заявку
            material_ids = request.form.getlist('material_id')
            quantities = request.form.getlist('quantity')

            for i in range(len(material_ids)):
                if material_ids[i] and quantities[i]:
                    cursor.execute("""
                        INSERT INTO request_materials (request_id, material_id, quantity)
                        VALUES (%s, %s, %s)
                    """, (request_id, material_ids[i], quantities[i]))

            # Добавляем технику в заявку
            equipment_ids = request.form.getlist('equipment_id')
            minutes_used = request.form.getlist('minutes_used')

            for i in range(len(equipment_ids)):
                if equipment_ids[i] and minutes_used[i]:
                    cursor.execute("""
                        INSERT INTO request_equipment (request_id, equipment_id, minutes_used)
                        VALUES (%s, %s, %s)
                    """, (request_id, equipment_ids[i], minutes_used[i]))

            conn.commit()
            flash('Заявка успешно создана', 'success')
            return redirect(url_for('view_request', request_id=request_id))
        except Exception as e:
            conn.rollback()
            flash(f'Ошибка при создании заявки: {str(e)}', 'danger')

    # Получаем материалы с автодобавлением
    cursor.execute("SELECT * FROM materials WHERE auto_add_to_request = 1")
    auto_materials = cursor.fetchall()

    # Получаем все материалы для выбора
    cursor.execute("SELECT * FROM materials ORDER BY name")
    available_materials = cursor.fetchall()

    # Получаем доступную технику
    cursor.execute("SELECT * FROM equipment WHERE is_active = 1 ORDER BY name")
    available_equipment = cursor.fetchall()

    # Получаем пользователей для админа
    users = []
    if session.get('role') == 'admin':
        cursor.execute("SELECT id, full_name FROM users WHERE is_active = 1 ORDER BY full_name")
        users = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('requests/create.html',
                           auto_materials=auto_materials,
                           available_materials=available_materials,
                           available_equipment=available_equipment,
                           users=users)

@app.route('/requests/<int:request_id>')
def view_request(request_id):
    if 'user_id' not in session:
        flash('Пожалуйста, войдите в систему', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    # Получаем заявку
    cursor.execute("""
        SELECT r.*, u.full_name as user_name 
        FROM requests r
        JOIN users u ON r.user_id = u.id
        WHERE r.id = %s
    """, (request_id,))
    request_data = cursor.fetchone()

    if not request_data:
        flash('Заявка не найдена', 'danger')
        return redirect(url_for('requests_list'))

    # Проверяем права доступа
    if session.get('role') != 'admin' and request_data['user_id'] != session['user_id']:
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('requests_list'))

    # Получаем материалы
    cursor.execute("""
        SELECT m.name, m.unit, rm.quantity
        FROM request_materials rm
        JOIN materials m ON rm.material_id = m.id
        WHERE rm.request_id = %s
    """, (request_id,))
    materials = cursor.fetchall()

    # Получаем технику
    cursor.execute("""
        SELECT e.name, re.minutes_used
        FROM request_equipment re
        JOIN equipment e ON re.equipment_id = e.id
        WHERE re.request_id = %s
    """, (request_id,))
    equipment = cursor.fetchall()

    cursor.close()
    conn.close()

    return render_template('requests/view.html',
                           request=request_data,
                           materials=materials,
                           equipment=equipment)


@app.route('/requests/<int:request_id>/approve')
def approve_request(request_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE requests 
            SET status = 'approved', approved_by = %s, updated_at = NOW()
            WHERE id = %s AND status = 'pending'
        """, (session['user_id'], request_id))
        conn.commit()

        if cursor.rowcount > 0:
            flash('Заявка одобрена', 'success')
        else:
            flash('Заявка не найдена или уже обработана', 'warning')
    except Exception as e:
        conn.rollback()
        flash(f'Ошибка при одобрении заявки: {str(e)}', 'danger')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('view_request', request_id=request_id))


@app.route('/requests/<int:request_id>/reject')
def reject_request(request_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE requests 
            SET status = 'rejected', approved_by = %s, updated_at = NOW()
            WHERE id = %s AND status = 'pending'
        """, (session['user_id'], request_id))
        conn.commit()

        if cursor.rowcount > 0:
            flash('Заявка отклонена', 'success')
        else:
            flash('Заявка не найдена или уже обработана', 'warning')
    except Exception as e:
        conn.rollback()
        flash(f'Ошибка при отклонении заявки: {str(e)}', 'danger')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('view_request', request_id=request_id))


@app.route('/requests/<int:request_id>/complete', methods=['POST'])
def complete_request(request_id):
    if 'user_id' not in session:
        flash('Пожалуйста, войдите в систему', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        cursor.execute("""
            UPDATE requests 
            SET status = 'completed', completed_at = NOW()
            WHERE id = %s AND status = 'approved' AND user_id = %s
        """, (request_id, session['user_id']))
        conn.commit()

        if cursor.rowcount > 0:
            flash('Заявка завершена', 'success')
        else:
            flash('Заявка не найдена или недоступна для завершения', 'warning')
    except Exception as e:
        conn.rollback()
        flash(f'Ошибка при завершении заявки: {str(e)}', 'danger')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('view_request', request_id=request_id))


@app.route('/requests/<int:request_id>/delete', methods=['POST'])
def delete_request(request_id):
    if 'user_id' not in session or session.get('role') != 'admin':
        flash('Доступ запрещен', 'danger')
        return redirect(url_for('login'))

    conn = get_db_connection()
    cursor = conn.cursor()

    try:
        # Удаляем заявку (связанные материалы и техника удалятся автоматически через CASCADE)
        cursor.execute("DELETE FROM requests WHERE id = %s", (request_id,))
        conn.commit()
        flash('Заявка успешно удалена', 'success')
    except Exception as e:
        conn.rollback()
        flash(f'Ошибка при удалении заявки: {str(e)}', 'danger')
    finally:
        cursor.close()
        conn.close()

    return redirect(url_for('requests_list'))
@app.route('/requests/<int:request_id>/export')
def export_request(request_id):
    if 'user_id' not in session:
        flash('Пожалуйста, войдите в систему', 'danger')
        return redirect(url_for('login'))

    try:
        filename = generate_word_report(request_id)
        return send_file(filename, as_attachment=True, download_name=f'request_{request_id}.docx')
    except Exception as e:
        flash(f'Ошибка при экспорте: {str(e)}', 'danger')
        return redirect(url_for('view_request', request_id=request_id))


# === ERROR HANDLERS ===

# === ERROR HANDLERS ===

@app.errorhandler(404)
def page_not_found(e):
    if 'user_id' in session:
        return render_template('errors/404.html'), 404
    else:
        return redirect(url_for('login'))


@app.errorhandler(500)
def internal_error(e):
    return render_template('errors/500.html', error=str(e)), 500

if __name__ == '__main__':
    test_db_connection()
    app.run(debug=True)