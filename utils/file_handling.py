import csv
import os
from datetime import datetime
from database.db_connection import get_db_connection


def import_materials_from_csv(file_path):
    imported = 0
    errors = 0
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    with open(file_path, mode='r', encoding='utf-8') as csv_file:
        csv_reader = csv.DictReader(csv_file, delimiter=';')

        for row in csv_reader:
            try:
                # Get category ID if exists
                category_id = None
                if 'Категория' in row and row['Категория']:
                    cursor.execute("SELECT id FROM categories WHERE name = %s", (row['Категория'],))
                    category = cursor.fetchone()
                    if category:
                        category_id = category['id']

                # Insert material
                cursor.execute("""
                    INSERT INTO materials 
                    (name, quantity, unit, min_quantity, category_id)
                    VALUES (%s, %s, %s, %s, %s)
                """, (
                    row['Название'],
                    float(row['Количество']),
                    row['Единица измерения'],
                    float(row['Минимальное количество']),
                    category_id
                ))
                imported += 1
            except Exception as e:
                errors += 1
                print(f"Error importing row {row}: {str(e)}")

    conn.commit()
    cursor.close()
    conn.close()

    return imported, errors


def export_materials_to_csv():
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    cursor.execute("""
        SELECT m.name, m.quantity, m.unit, m.min_quantity, c.name as category_name
        FROM materials m
        LEFT JOIN categories c ON m.category_id = c.id
    """)
    materials = cursor.fetchall()

    cursor.close()
    conn.close()

    # Generate filename with timestamp
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = f"materials_export_{timestamp}.csv"
    filepath = os.path.join('exports', filename)

    os.makedirs('exports', exist_ok=True)

    with open(filepath, mode='w', encoding='utf-8', newline='') as csv_file:
        fieldnames = ['Название', 'Количество', 'Единица измерения',
                      'Минимальное количество', 'Категория']
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames, delimiter=';')

        writer.writeheader()
        for material in materials:
            writer.writerow({
                'Название': material['name'],
                'Количество': material['quantity'],
                'Единица измерения': material['unit'],
                'Минимальное количество': material['min_quantity'],
                'Категория': material['category_name'] or ''
            })

    return filepath