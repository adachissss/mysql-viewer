from flask import Flask, render_template, request, jsonify
import hashlib
import os
from threading import Lock
import mysql.connector
from mysql.connector import Error
from mysql.connector import pooling

app = Flask(__name__)

DB_POOL_SIZE = int(os.getenv('DB_POOL_SIZE', '5'))
DB_MAX_POOLS = int(os.getenv('DB_MAX_POOLS', '32'))
DB_CONNECTION_TIMEOUT = int(os.getenv('DB_CONNECTION_TIMEOUT', '10'))

_POOLS = {}
_POOL_LOCK = Lock()


def _pool_key(host, port, user, password):
    normalized_port = int(port) if port else 3306
    return (str(host or 'localhost'), normalized_port, str(user or ''), str(password or ''))


def _pool_name_for_key(key):
    raw = '|'.join([str(v) for v in key])
    digest = hashlib.sha1(raw.encode('utf-8')).hexdigest()[:16]
    return f"mysql_viewer_{digest}"


def _get_or_create_pool(host, port, user, password):
    key = _pool_key(host, port, user, password)

    with _POOL_LOCK:
        pool = _POOLS.get(key)
        if pool is not None:
            return pool

        if len(_POOLS) >= DB_MAX_POOLS:
            oldest_key = next(iter(_POOLS))
            del _POOLS[oldest_key]

        pool = pooling.MySQLConnectionPool(
            pool_name=_pool_name_for_key(key),
            pool_size=DB_POOL_SIZE,
            pool_reset_session=True,
            host=key[0],
            port=key[1],
            user=key[2],
            password=key[3],
            connection_timeout=DB_CONNECTION_TIMEOUT
        )
        _POOLS[key] = pool
        return pool


def quote_identifier(name):
    if not isinstance(name, str) or not name.strip():
        raise ValueError('Invalid identifier')
    return f"`{name.replace('`', '``')}`"


def get_db_connection(host, port, user, password, database=None):
    try:
        pool = _get_or_create_pool(host, port, user, password)
        conn = pool.get_connection()
        if isinstance(database, str) and database.strip():
            cursor = conn.cursor()
            cursor.execute(f"USE {quote_identifier(database.strip())}")
            cursor.close()
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

    cursor = None
    try:
        cursor = conn.cursor()
        cursor.execute("SHOW TABLES")
        tables = [row[0] for row in cursor.fetchall()]
    except Error as e:
        return jsonify({'success': False, 'error': str(e)})
    finally:
        if cursor is not None:
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

    def parse_int(value, default, minimum=None, maximum=None):
        try:
            num = int(value)
        except (TypeError, ValueError):
            num = default
        if minimum is not None:
            num = max(minimum, num)
        if maximum is not None:
            num = min(maximum, num)
        return num

    def parse_bool(value, default=False):
        if isinstance(value, bool):
            return value
        if value is None:
            return default
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in ('1', 'true', 'yes', 'on')
        return default

    cursor = conn.cursor()
    table_name = data.get('table', '')
    limit = parse_int(data.get('limit', 50), 50, minimum=1, maximum=500)
    offset = parse_int(data.get('offset', 0), 0, minimum=0)
    include_total = parse_bool(data.get('include_total'), default=(offset == 0))

    try:
        qt = quote_identifier(table_name)

        # Primary key metadata is used by row edit/delete operations on frontend.
        key_cursor = conn.cursor(dictionary=True)
        key_cursor.execute(f"SHOW KEYS FROM {qt} WHERE Key_name = 'PRIMARY'")
        primary_keys = [row['Column_name'] for row in key_cursor.fetchall()]
        key_cursor.close()

        # Use limit + 1 rows to determine whether a next page exists.
        cursor.execute(f"SELECT * FROM {qt} LIMIT {limit + 1} OFFSET {offset}")
        columns = [desc[0] for desc in cursor.description]
        rows = cursor.fetchall()
        has_next = len(rows) > limit
        rows = rows[:limit]

        total = None
        total_mode = 'none'
        if include_total:
            count_cursor = conn.cursor()
            count_cursor.execute(f"SELECT COUNT(*) FROM {qt}")
            total = count_cursor.fetchone()[0]
            count_cursor.close()
            total_mode = 'exact'

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
        'total_mode': total_mode,
        'has_next': has_next,
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

    cursor = None
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
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    finally:
        if cursor is not None:
            cursor.close()
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

    cursor = None
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
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})
    finally:
        if cursor is not None:
            cursor.close()
        conn.close()

    if affected == 0:
        return jsonify({'success': False, 'error': 'No row deleted'})
    return jsonify({'success': True})


if __name__ == '__main__':
    app.run(debug=True, port=5050)
