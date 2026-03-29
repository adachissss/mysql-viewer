// localStorage cache key
const STORAGE_KEY = 'mysql_viewer_conn';

let conn = { host: '', port: '', user: '', password: '', database: '' };
let currentTables = {};
let contextActions = [];
let activeCellEditor = null;

// Load cached connection on start
(function loadCached() {
    const cached = localStorage.getItem(STORAGE_KEY);
    if (cached) {
        try {
            const c = JSON.parse(cached);
            document.getElementById('host').value = c.host || 'localhost';
            document.getElementById('port').value = c.port || '3306';
            document.getElementById('user').value = c.user || '';
            document.getElementById('password').value = c.password || '';
        } catch(e) {}
    }
})();

function getFormData() {
    conn.host = document.getElementById('host').value;
    conn.port = document.getElementById('port').value;
    conn.user = document.getElementById('user').value;
    conn.password = document.getElementById('password').value;
}

function saveConn() {
    localStorage.setItem(STORAGE_KEY, JSON.stringify({
        host: conn.host,
        port: conn.port,
        user: conn.user,
        password: conn.password
    }));
}

function formatValue(v) {
    if (v === null || v === undefined) return '<span class="cell-null">NULL</span>';
    if (typeof v === 'object') return JSON.stringify(v);
    return String(v);
}

function hideContextMenu() {
    const menu = document.getElementById('context-menu');
    menu.style.display = 'none';
    contextActions = [];
}

function showContextMenu(x, y, actions) {
    const menu = document.getElementById('context-menu');
    contextActions = actions;
    menu.innerHTML = actions.map((a, i) =>
        `<button class="context-item ${a.danger ? 'danger' : ''}" data-index="${i}" ${a.disabled ? 'disabled' : ''}>${a.label}</button>`
    ).join('');
    menu.style.display = 'block';

    const maxX = window.innerWidth - menu.offsetWidth - 8;
    const maxY = window.innerHeight - menu.offsetHeight - 8;
    menu.style.left = `${Math.max(8, Math.min(x, maxX))}px`;
    menu.style.top = `${Math.max(8, Math.min(y, maxY))}px`;
}

function getRowPrimaryKey(name, rowIndex) {
    const tableData = currentTables[name] && currentTables[name].data;
    if (!tableData || !tableData.primary_keys || tableData.primary_keys.length === 0) return null;
    const row = tableData.rows[rowIndex];
    if (!row) return null;

    const pk = {};
    for (const key of tableData.primary_keys) {
        const idx = tableData.columns.indexOf(key);
        if (idx < 0) return null;
        pk[key] = row[idx];
    }
    return pk;
}

async function reloadCurrentDatabase() {
    const activeLi = document.querySelector('#db-list li.active');
    if (!activeLi) return;
    await loadTables(activeLi.textContent, activeLi);
}

async function dropDatabase(dbName) {
    if (!confirm(`Delete database ${dbName}? This action cannot be undone.`)) return;
    const res = await fetch('/api/drop_database', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...conn, database: dbName })
    });
    const json = await res.json();
    if (!json.success) {
        alert('Delete database failed: ' + json.error);
        return;
    }

    if (conn.database === dbName) {
        conn.database = '';
        currentTables = {};
        document.getElementById('current-db').textContent = 'No database selected';
        document.getElementById('content').innerHTML = '<div class="loading">Database deleted. Please select another database.</div>';
    }
    await refreshDatabases();
}

async function dropTable(name) {
    if (!confirm(`Delete table ${name}? This action cannot be undone.`)) return;
    const res = await fetch('/api/drop_table', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...conn, table: name })
    });
    const json = await res.json();
    if (!json.success) {
        alert('Delete table failed: ' + json.error);
        return;
    }
    await reloadCurrentDatabase();
}

async function renameTable(name) {
    const newName = prompt('New table name:', name);
    if (!newName || newName === name) return;
    const res = await fetch('/api/rename_table', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...conn, old_name: name, new_name: newName })
    });
    const json = await res.json();
    if (!json.success) {
        alert('Rename table failed: ' + json.error);
        return;
    }
    await reloadCurrentDatabase();
}

async function truncateTable(name) {
    if (!confirm(`Clear all rows in table ${name}?`)) return;
    const res = await fetch('/api/truncate_table', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...conn, table: name })
    });
    const json = await res.json();
    if (!json.success) {
        alert('Truncate table failed: ' + json.error);
        return;
    }
    const card = document.querySelector(`.table-card[data-table="${name}"]`);
    if (card) {
        await loadTableDataOffset(name, card, 0);
        card.classList.add('open');
    }
}

function showDatabaseContextMenu(event, dbName) {
    event.preventDefault();
    showContextMenu(event.clientX, event.clientY, [
        { label: `Delete database: ${dbName}`, danger: true, action: () => dropDatabase(dbName) }
    ]);
}

function showTableContextMenu(event, name) {
    event.preventDefault();
    showContextMenu(event.clientX, event.clientY, [
        { label: `Rename table: ${name}`, action: () => renameTable(name) },
        { label: `Clear table data: ${name}`, action: () => truncateTable(name), danger: true },
        { label: `Delete table: ${name}`, action: () => dropTable(name), danger: true }
    ]);
}

function showRowContextMenu(event, name, rowIndex) {
    event.preventDefault();
    const pk = getRowPrimaryKey(name, rowIndex);
    showContextMenu(event.clientX, event.clientY, [
        {
            label: pk ? 'Delete this row' : 'Delete row (requires primary key)',
            danger: true,
            disabled: !pk,
            action: () => deleteRow(name, rowIndex)
        }
    ]);
}

async function deleteRow(name, rowIndex) {
    const pk = getRowPrimaryKey(name, rowIndex);
    if (!pk) {
        alert('This table has no primary key, cannot safely delete a specific row.');
        return;
    }
    if (!confirm('Delete this row?')) return;

    const res = await fetch('/api/delete_row', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...conn, table: name, pk: pk })
    });
    const json = await res.json();
    if (!json.success) {
        alert('Delete row failed: ' + json.error);
        return;
    }

    const card = document.querySelector(`.table-card[data-table="${name}"]`);
    if (!card) return;
    const offset = (currentTables[name] && currentTables[name].data && currentTables[name].data.offset) || 0;
    await loadTableDataOffset(name, card, offset);
    card.classList.add('open');
}

async function editCell(cell, name, rowIndex, colIndex) {
    const tableData = currentTables[name] && currentTables[name].data;
    if (!tableData || !cell) return;

    if (activeCellEditor && activeCellEditor.cell !== cell) {
        activeCellEditor.cancel();
    }
    if (cell.dataset.editing === '1') return;

    const pk = getRowPrimaryKey(name, rowIndex);
    if (!pk) {
        alert('This table has no primary key, cannot safely update a specific row.');
        return;
    }

    const column = tableData.columns[colIndex];
    const oldValue = tableData.rows[rowIndex][colIndex];
    const oldText = oldValue === null ? 'NULL' : String(oldValue);

    cell.dataset.editing = '1';
    cell.innerHTML = '';

    const input = document.createElement('input');
    input.type = 'text';
    input.className = 'cell-edit-input';
    input.value = oldText;
    cell.appendChild(input);
    input.focus();
    input.select();

    const cleanup = () => {
        delete cell.dataset.editing;
        if (activeCellEditor && activeCellEditor.cell === cell) {
            activeCellEditor = null;
        }
    };

    const cancel = () => {
        cleanup();
        cell.innerHTML = formatValue(oldValue);
    };

    const commit = async () => {
        const rawInput = input.value;
        const newValue = rawInput.trim().toUpperCase() === 'NULL' ? null : rawInput;

        if (newValue === oldValue) {
            cleanup();
            cell.innerHTML = formatValue(oldValue);
            return;
        }

        const res = await fetch('/api/update_cell', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ ...conn, table: name, column: column, value: newValue, pk: pk })
        });
        const json = await res.json();
        if (!json.success) {
            alert('Update cell failed: ' + json.error);
            input.focus();
            input.select();
            return;
        }

        tableData.rows[rowIndex][colIndex] = newValue;
        cleanup();
        cell.innerHTML = formatValue(newValue);
    };

    activeCellEditor = { cell, cancel };

    input.addEventListener('keydown', async (e) => {
        if (e.key === 'Enter') {
            e.preventDefault();
            await commit();
        } else if (e.key === 'Escape') {
            e.preventDefault();
            cancel();
        }
    });

    input.addEventListener('blur', () => {
        if (cell.dataset.editing === '1') {
            cancel();
        }
    });
}

document.addEventListener('click', hideContextMenu);
window.addEventListener('resize', hideContextMenu);
window.addEventListener('scroll', hideContextMenu, true);
document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') hideContextMenu();
});
document.getElementById('context-menu').addEventListener('click', async (e) => {
    const btn = e.target.closest('button[data-index]');
    if (!btn) return;
    const action = contextActions[Number(btn.dataset.index)];
    hideContextMenu();
    if (action && !action.disabled && typeof action.action === 'function') {
        await action.action();
    }
});

function toggleTable(name) {
    const card = document.querySelector(`.table-card[data-table="${name}"]`);
    if (!card) return;
    const isOpen = card.classList.contains('open');

    if (isOpen) {
        card.classList.remove('open');
        return;
    }

    if (!currentTables[name] || !currentTables[name].schema) {
        loadTableSchema(name, card);
    } else {
        card.classList.add('open');
    }
}

async function loadTableSchema(name, card) {
    card.querySelector('.table-body').innerHTML = '<div class="loading">Loading schema...</div>';
    const res = await fetch('/api/table_schema', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...conn, table: name })
    });
    const json = await res.json();
    if (!json.success) {
        card.querySelector('.table-body').innerHTML = `<div class="error">${json.error}</div>`;
        return;
    }
    currentTables[name].schema = json.schema;
    renderTableSchema(card, name, 'schema');
    card.classList.add('open');
}

async function loadTableDataOffset(name, card, offset) {
    card.querySelector('.tab-content[data-tab="data"]').innerHTML = '<div class="loading">Loading...</div>';
    const res = await fetch('/api/table_data', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...conn, table: name, limit: 100, offset: offset })
    });
    const json = await res.json();
    if (!json.success) {
        card.querySelector('.tab-content[data-tab="data"]').innerHTML = `<div class="error">${json.error}</div>`;
        return;
    }
    currentTables[name].data = json;
    renderTableSchema(card, name, 'data');
}

async function loadTableData(name, card, page = 1) {
    const limit = 100;
    const offset = (page - 1) * limit;
    card.querySelector('.table-body').innerHTML = '<div class="loading">Loading data...</div>';
    const res = await fetch('/api/table_data', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...conn, table: name, limit: limit, offset: offset })
    });
    const json = await res.json();
    if (!json.success) {
        card.querySelector('.table-body').innerHTML = `<div class="error">${json.error}</div>`;
        return;
    }
    currentTables[name].data = json;
    currentTables[name].page = page;
    renderTableSchema(card, name, 'data', page);
    card.classList.add('open');
}

function switchTab(card, name, tab) {
    card.querySelectorAll('.tab-btn').forEach(t => t.classList.remove('active'));
    card.querySelectorAll('.tab-content').forEach(c => c.classList.remove('active'));
    card.querySelector(`.tab-btn[data-tab="${tab}"]`).classList.add('active');
    card.querySelector(`.tab-content[data-tab="${tab}"]`).classList.add('active');

    if (tab === 'data' && (!currentTables[name].data)) {
        loadTableData(name, card, 1);
    }
}

function renderTableSchema(card, name, mode, page = 1) {
    const schema = currentTables[name].schema;
    const data = currentTables[name].data;
    const limit = 100;
    const activeTab = mode === 'data' ? 'data' : 'schema';

    let schemaHtml = '';
    if (schema && schema.length > 0) {
        const rows = schema.map(col => `
            <tr>
                <td>${col.Field || ''}</td>
                <td>${col.Type || ''}</td>
                <td>${col.Null || ''}</td>
                <td>${col.Key || ''}</td>
                <td>${col.Default || ''}</td>
                <td>${col.Extra || ''}</td>
            </tr>
        `).join('');
        schemaHtml = `
            <table>
                <thead><tr><th>Field</th><th>Type</th><th>Null</th><th>Key</th><th>Default</th><th>Extra</th></tr></thead>
                <tbody>${rows}</tbody>
            </table>`;
    } else {
        schemaHtml = '<div class="empty">No schema</div>';
    }

    let dataHtml = '<div class="loading">Click Data tab to load</div>';
    if (data) {
        const total = data.total;
        const offset = data.offset || 0;
        const currentPage = data.current_page || 1;
        const showing = data.rows.length;
        const rows2 = data.rows.map((r, rowIndex) =>
            `<tr data-row-index="${rowIndex}" oncontextmenu="showRowContextMenu(event, '${name}', ${rowIndex})">` +
            r.map((v, colIndex) => `<td ondblclick="editCell(this, '${name}', ${rowIndex}, ${colIndex})">${formatValue(v)}</td>`).join('') +
            '</tr>'
        ).join('');
        dataHtml = `
            <div class="data-summary">${total} rows total, showing ${showing > 0 ? `${offset + 1}-${offset + showing}` : '0'}</div>
            <table>
                <thead><tr>${data.columns.map(c => `<th>${c}</th>`).join('')}</tr></thead>
                <tbody>${rows2}</tbody>
            </table>
            <div class="pagination">
                <button onclick="loadTableDataOffset('${name}', document.querySelector('.table-card[data-table=&quot;${name}&quot;]'), ${offset - limit})" ${offset <= 0 ? 'disabled' : ''}>Prev</button>
                <span>Page ${currentPage}</span>
                <button onclick="loadTableDataOffset('${name}', document.querySelector('.table-card[data-table=&quot;${name}&quot;]'), ${offset + limit})" ${offset + limit >= total ? 'disabled' : ''}>Next</button>
            </div>`;
    }

    card.querySelector('.table-body').innerHTML = `
        <div class="tabs">
            <div class="tab-btn ${activeTab === 'schema' ? 'active' : ''}" data-tab="schema" onclick="switchTab(this.closest('.table-card'), '${name}', 'schema')">Structure</div>
            <div class="tab-btn ${activeTab === 'data' ? 'active' : ''}" data-tab="data" onclick="switchTab(this.closest('.table-card'), '${name}', 'data')">Data</div>
        </div>
        <div class="tab-content ${activeTab === 'schema' ? 'active' : ''}" data-tab="schema">${schemaHtml}</div>
        <div class="tab-content ${activeTab === 'data' ? 'active' : ''}" data-tab="data">${dataHtml}</div>`;

}

async function loadDatabases() {
    getFormData();
    saveConn();
    document.getElementById('conn-status').textContent = 'Connecting...';
    document.getElementById('conn-status').className = 'conn-status';

    const res = await fetch('/api/connect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(conn)
    });
    const json = await res.json();
    if (!json.success) {
        document.getElementById('conn-status').textContent = 'Failed: ' + json.error;
        document.getElementById('conn-status').className = 'conn-status error';
        alert('Connection failed: ' + json.error);
        return;
    }
    document.getElementById('conn-status').textContent = 'Connected';
    document.getElementById('conn-status').className = 'conn-status connected';

    const dbRes = await fetch('/api/databases', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(conn)
    });
    const dbJson = await dbRes.json();
    if (!dbJson.success) { alert('Failed to get databases: ' + dbJson.error); return; }

    const list = document.getElementById('db-list');
    list.innerHTML = '';
    dbJson.databases.forEach(db => {
        const li = document.createElement('li');
        li.textContent = db;
        li.onclick = () => loadTables(db, li);
        li.oncontextmenu = (e) => showDatabaseContextMenu(e, db);
        list.appendChild(li);
    });
}

async function refreshDatabases() {
    getFormData();
    saveConn();
    const btn = document.getElementById('refresh-btn');
    btn.disabled = true;
    btn.classList.add('loading');
    document.getElementById('conn-status').textContent = 'Refreshing...';
    document.getElementById('conn-status').className = 'conn-status';

    const res = await fetch('/api/connect', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(conn)
    });
    const json = await res.json();
    if (!json.success) {
        document.getElementById('conn-status').textContent = 'Failed';
        document.getElementById('conn-status').className = 'conn-status error';
        btn.disabled = false;
        btn.classList.remove('loading');
        return;
    }
    document.getElementById('conn-status').textContent = 'Connected';
    document.getElementById('conn-status').className = 'conn-status connected';

    const dbRes = await fetch('/api/databases', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(conn)
    });
    const dbJson = await dbRes.json();
    btn.disabled = false;
    btn.classList.remove('loading');

    if (!dbJson.success) { return; }

    // Update cached connection
    saveConn();

    // Re-render list, keep active if exists
    const list = document.getElementById('db-list');
    const activeDb = list.querySelector('li.active');
    const activeName = activeDb ? activeDb.textContent : null;
    list.innerHTML = '';
    dbJson.databases.forEach(db => {
        const li = document.createElement('li');
        li.textContent = db;
        li.onclick = () => loadTables(db, li);
        li.oncontextmenu = (e) => showDatabaseContextMenu(e, db);
        if (db === activeName) {
            li.classList.add('active');
        }
        list.appendChild(li);
    });
}

async function loadTables(db, li) {
    document.querySelectorAll('#db-list li').forEach(l => l.classList.remove('active'));
    li.classList.add('active');
    conn.database = db;
    currentTables = {};
    document.getElementById('current-db').textContent = db;
    document.getElementById('content').innerHTML = '<div class="loading">Loading...</div>';

    const res = await fetch('/api/tables', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(conn)
    });
    const json = await res.json();
    if (!json.success) {
        document.getElementById('content').innerHTML = `<div class="error">${json.error}</div>`;
        return;
    }

    json.tables.forEach(t => { currentTables[t] = {}; });

    if (json.tables.length === 0) {
        document.getElementById('content').innerHTML = `
            <div class="db-summary">
                <div class="summary-item"><span class="summary-label">Database</span><span class="summary-value">${db}</span></div>
                <span class="summary-divider"></span>
                <div class="summary-item"><span class="summary-label">Tables</span><span class="summary-value">0</span></div>
            </div>
            <div class="empty">No tables</div>`;
        return;
    }

    let html = `
        <div class="db-summary">
            <div class="summary-item"><span class="summary-label">Database</span><span class="summary-value">${db}</span></div>
            <span class="summary-divider"></span>
            <div class="summary-item"><span class="summary-label">Tables</span><span class="summary-value">${json.tables.length}</span></div>
        </div>`;
    json.tables.forEach(name => {
        html += `
        <div class="table-card" data-table="${name}">
            <div class="table-header" onclick="toggleTable('${name}')">
                <span>${name}</span>
                <span class="table-toggle">▶</span>
            </div>
            <div class="table-body"><div class="empty">Click to expand</div></div>
        </div>`;
    });
    document.getElementById('content').innerHTML = html;

    json.tables.forEach(name => {
        const header = document.querySelector(`.table-card[data-table="${name}"] .table-header`);
        if (header) {
            header.oncontextmenu = (e) => showTableContextMenu(e, name);
        }
    });

}
