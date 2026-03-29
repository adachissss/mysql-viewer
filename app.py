from flask import Flask, render_template, request, jsonify
import mysql.connector
from mysql.connector import Error

app = Flask(__name__)


def quote_identifier(name):
    if not isinstance(name, str) or not name.strip():
        raise ValueError('Invalid identifier')
    return f"`{name.replace('`', '``')}`"


def get_db_connection(host, port, user, password, database=None):
    try:
        conn = mysql.connector.connect(
            host=host,
            port=int(port) if port else 3306,
            user=user,
            password=password,
            database=database,
            connection_timeout=10
        )
        return conn
    except Error as e:
        return str(e)


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/connect', methods=['POST'])
def connect():
    data = request.json
    conn = get_db_connection(
        host=data.get('host', 'localhost'),
        port=data.get('port', 3306),
        user=data.get('user', 'root'),
        password=data.get('password', ''),
        database=data.get('database', None)
    )
    if isinstance(conn, str):
        return jsonify({'success': False, 'error': conn})
    conn.close()
    return jsonify({'success': True})


@app.route('/api/databases', methods=['POST'])
def list_databases():
    data = request.json
    conn = get_db_connection(
        host=data.get('host', 'localhost'),
        port=data.get('port', 3306),
        user=data.get('user', 'root'),
        password=data.get('password', '')
    )
    if isinstance(conn, str):
        return jsonify({'success': False, 'error': conn})
    cursor = conn.cursor()
    cursor.execute("SHOW DATABASES")
    dbs = [row[0] for row in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({'success': True, 'databases': dbs})


@app.route('/api/tables', methods=['POST'])
def list_tables():
    data = request.json
    conn = get_db_connection(
        host=data.get('host', 'localhost'),
        port=data.get('port', 3306),
        user=data.get('user', 'root'),
        password=data.get('password', ''),
        database=data.get('database', '')
    )
    if isinstance(conn, str):
        return jsonify({'success': False, 'error': conn})
    cursor = conn.cursor()
    cursor.execute("SHOW TABLES")
    tables = [row[0] for row in cursor.fetchall()]
    cursor.close()
    conn.close()
    return jsonify({'success': True, 'tables': tables})


@app.route('/api/table_schema', methods=['POST'])
def table_schema():
    data = request.json
    conn = get_db_connection(
        host=data.get('host', 'localhost'),
        port=data.get('port', 3306),
        user=data.get('user', 'root'),
        password=data.get('password', ''),
        database=data.get('database', '')
    )
    if isinstance(conn, str):
        return jsonify({'success': False, 'error': conn})
    cursor = conn.cursor()
    table_name = data.get('table', '')
    try:
        cursor.execute(f"DESCRIBE `{table_name}`")
        schema = [dict(zip(['Field', 'Type', 'Null', 'Key', 'Default', 'Extra'], row)) for row in cursor.fetchall()]
    except Error as e:
        schema = []
    cursor.close()
    conn.close()
    return jsonify({'success': True, 'schema': schema})


@app.route('/api/table_data', methods=['POST'])
def table_data():
    data = request.json
    conn = get_db_connection(
        host=data.get('host', 'localhost'),
        port=data.get('port', 3306),
        user=data.get('user', 'root'),
        password=data.get('password', ''),
        database=data.get('database', '')
    )
    if isinstance(conn, str):
        return jsonify({'success': False, 'error': conn})
    cursor = conn.cursor()
    table_name = data.get('table', '')
    limit = min(int(data.get('limit', 100)), 500)

    try:
        qt = quote_identifier(table_name)

        # Primary key metadata is used by row edit/delete operations on frontend.
        key_cursor = conn.cursor(dictionary=True)
        key_cursor.execute(f"SHOW KEYS FROM {qt} WHERE Key_name = 'PRIMARY'")
        primary_keys = [row['Column_name'] for row in key_cursor.fetchall()]
        key_cursor.close()

        # 先查总条数
        count_cursor = conn.cursor()
        count_cursor.execute(f"SELECT COUNT(*) FROM {qt}")
        total = count_cursor.fetchone()[0]
        count_cursor.close()

        # 再查数据
        offset = min(int(data.get('offset', 0)), total)
        cursor.execute(f"SELECT * FROM {qt} LIMIT {limit} OFFSET {offset}")
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        current_page = int(offset / limit) + 1
    except Error as e:
        cursor.close()
        conn.close()
        return jsonify({'success': False, 'error': str(e)})

    cursor.close()
    conn.close()
    return jsonify({
        'success': True,
        'columns': columns,
        'rows': [list(r) for r in rows],
        'primary_keys': primary_keys,
        'total': total,
        'limit': limit,
        'offset': offset,
        'current_page': current_page
    })


@app.route('/api/drop_database', methods=['POST'])
def drop_database():
    data = request.json
    conn = get_db_connection(
        host=data.get('host', 'localhost'),
        port=data.get('port', 3306),
        user=data.get('user', 'root'),
        password=data.get('password', '')
    )
    if isinstance(conn, str):
        return jsonify({'success': False, 'error': conn})

    db_name = data.get('database', '')
    try:
        qd = quote_identifier(db_name)
        cursor = conn.cursor()
        cursor.execute(f"DROP DATABASE {qd}")
        conn.commit()
        cursor.close()
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'error': str(e)})

    conn.close()
    return jsonify({'success': True})


@app.route('/api/drop_table', methods=['POST'])
def drop_table():
    data = request.json
    conn = get_db_connection(
        host=data.get('host', 'localhost'),
        port=data.get('port', 3306),
        user=data.get('user', 'root'),
        password=data.get('password', ''),
        database=data.get('database', '')
    )
    if isinstance(conn, str):
        return jsonify({'success': False, 'error': conn})

    table_name = data.get('table', '')
    try:
        qt = quote_identifier(table_name)
        cursor = conn.cursor()
        cursor.execute(f"DROP TABLE {qt}")
        conn.commit()
        cursor.close()
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'error': str(e)})

    conn.close()
    return jsonify({'success': True})


@app.route('/api/rename_table', methods=['POST'])
def rename_table():
    data = request.json
    conn = get_db_connection(
        host=data.get('host', 'localhost'),
        port=data.get('port', 3306),
        user=data.get('user', 'root'),
        password=data.get('password', ''),
        database=data.get('database', '')
    )
    if isinstance(conn, str):
        return jsonify({'success': False, 'error': conn})

    old_name = data.get('old_name', '')
    new_name = data.get('new_name', '')
    try:
        q_old = quote_identifier(old_name)
        q_new = quote_identifier(new_name)
        cursor = conn.cursor()
        cursor.execute(f"RENAME TABLE {q_old} TO {q_new}")
        conn.commit()
        cursor.close()
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'error': str(e)})

    conn.close()
    return jsonify({'success': True})


@app.route('/api/truncate_table', methods=['POST'])
def truncate_table():
    data = request.json
    conn = get_db_connection(
        host=data.get('host', 'localhost'),
        port=data.get('port', 3306),
        user=data.get('user', 'root'),
        password=data.get('password', ''),
        database=data.get('database', '')
    )
    if isinstance(conn, str):
        return jsonify({'success': False, 'error': conn})

    table_name = data.get('table', '')
    try:
        qt = quote_identifier(table_name)
        cursor = conn.cursor()
        cursor.execute(f"TRUNCATE TABLE {qt}")
        conn.commit()
        cursor.close()
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'error': str(e)})

    conn.close()
    return jsonify({'success': True})


@app.route('/api/update_cell', methods=['POST'])
def update_cell():
    data = request.json
    conn = get_db_connection(
        host=data.get('host', 'localhost'),
        port=data.get('port', 3306),
        user=data.get('user', 'root'),
        password=data.get('password', ''),
        database=data.get('database', '')
    )
    if isinstance(conn, str):
        return jsonify({'success': False, 'error': conn})

    table_name = data.get('table', '')
    column_name = data.get('column', '')
    pk = data.get('pk', {})
    value = data.get('value', None)

    if not isinstance(pk, dict) or not pk:
        conn.close()
        return jsonify({'success': False, 'error': 'Primary key required for update'})

    try:
        qt = quote_identifier(table_name)
        qc = quote_identifier(column_name)
        where_parts = []
        params = [value]
        for k, v in pk.items():
            where_parts.append(f"{quote_identifier(k)} <=> %s")
            params.append(v)

        sql = f"UPDATE {qt} SET {qc} = %s WHERE {' AND '.join(where_parts)} LIMIT 1"
        cursor = conn.cursor()
        cursor.execute(sql, params)
        conn.commit()
        affected = cursor.rowcount
        cursor.close()
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'error': str(e)})

    conn.close()
    if affected == 0:
        return jsonify({'success': False, 'error': 'No row updated'})
    return jsonify({'success': True})


@app.route('/api/delete_row', methods=['POST'])
def delete_row():
    data = request.json
    conn = get_db_connection(
        host=data.get('host', 'localhost'),
        port=data.get('port', 3306),
        user=data.get('user', 'root'),
        password=data.get('password', ''),
        database=data.get('database', '')
    )
    if isinstance(conn, str):
        return jsonify({'success': False, 'error': conn})

    table_name = data.get('table', '')
    pk = data.get('pk', {})
    if not isinstance(pk, dict) or not pk:
        conn.close()
        return jsonify({'success': False, 'error': 'Primary key required for delete'})

    try:
        qt = quote_identifier(table_name)
        where_parts = []
        params = []
        for k, v in pk.items():
            where_parts.append(f"{quote_identifier(k)} <=> %s")
            params.append(v)

        sql = f"DELETE FROM {qt} WHERE {' AND '.join(where_parts)} LIMIT 1"
        cursor = conn.cursor()
        cursor.execute(sql, params)
        conn.commit()
        affected = cursor.rowcount
        cursor.close()
    except Exception as e:
        conn.close()
        return jsonify({'success': False, 'error': str(e)})

    conn.close()
    if affected == 0:
        return jsonify({'success': False, 'error': 'No row deleted'})
    return jsonify({'success': True})


if __name__ == '__main__':
    app.run(debug=True, port=5050)
