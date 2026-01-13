from flask import Flask, request, jsonify
import sqlite3
import os
from datetime import datetime, timedelta

app = Flask(__name__)

DB_PATH = '/tmp/activation_codes.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute('''CREATE TABLE IF NOT EXISTS codes
                 (id INTEGER PRIMARY KEY,
                  code TEXT UNIQUE NOT NULL,
                  used INTEGER DEFAULT 0,
                  code_type TEXT NOT NULL,
                  created_at TIMESTAMP,
                  activated_at TIMESTAMP,
                  expires_at TIMESTAMP)''')
    
    conn.commit()
    conn.close()

def calculate_expiry(code_type):
    if code_type == "forever":
        return None
    elif code_type == "month":
        return datetime.now() + timedelta(days=30)
    elif code_type == "week":
        return datetime.now() + timedelta(days=7)
    elif code_type == "day":
        return datetime.now() + timedelta(days=1)
    else:
        return datetime.now() + timedelta(days=30)

def check_and_activate_code(code):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    c.execute("SELECT id, used, code_type, expires_at FROM codes WHERE code = ?", (code,))
    result = c.fetchone()
    
    if not result:
        conn.close()
        return {"status": "error", "message": "Invalid code"}
    
    code_id, used, code_type, expires_at = result
    
    if used:
        conn.close()
        return {"status": "error", "message": "Code already used"}
    
    if expires_at:
        try:
            expires_date = datetime.strptime(expires_at, '%Y-%m-%d %H:%M:%S.%f')
        except:
            expires_date = datetime.strptime(expires_at, '%Y-%m-%d %H:%M:%S')
        
        if datetime.now() > expires_date:
            conn.close()
            return {"status": "error", "message": "Code expired"}
    
    c.execute("UPDATE codes SET used = 1, activated_at = ? WHERE id = ?", 
             (datetime.now(), code_id))
    conn.commit()
    conn.close()
    
    expiry_info = ""
    if expires_at:
        expiry_info = f" Code expires at {expires_at}"
    
    return {
        "status": "success", 
        "message": f"Activation successful. Type: {code_type}.{expiry_info}",
        "code_type": code_type,
        "expires_at": expires_at
    }

def add_code_with_type(code, code_type):
    expires_at = calculate_expiry(code_type)
    
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    try:
        c.execute("""INSERT INTO codes (code, code_type, created_at, expires_at) 
                     VALUES (?, ?, ?, ?)""", 
                 (code, code_type, datetime.now(), expires_at))
        conn.commit()
        return True
    except sqlite3.IntegrityError:
        return False
    finally:
        conn.close()

def add_test_codes():
    test_codes = [
        ("fG956kGo9", "forever"),
        ("MONTH12345", "month"),
        ("WEEK67890", "week"),
        ("DAY54321", "day"),
        ("TESTFOREVER", "forever")
    ]
    
    for code, code_type in test_codes:
        add_code_with_type(code, code_type)

@app.route('/api/check_code', methods=['POST'])
def check_code():
    try:
        data = request.get_json()
        if not data or 'activation_code' not in data:
            return jsonify({"status": "error", "message": "No code provided"}), 400
        
        code = data['activation_code'].strip()
        
        if len(code) < 5:
            return jsonify({"status": "error", "message": "Code too short"}), 400
        
        result = check_and_activate_code(code)
        return jsonify(result)
    
    except Exception as e:
        return jsonify({"status": "error", "message": f"Server error: {str(e)}"}), 500

@app.route('/api/admin/add_code', methods=['POST'])
def add_code():
    try:
        data = request.get_json()
        if not data or 'code' not in data:
            return jsonify({"status": "error", "message": "No code provided"}), 400
        
        new_code = data['code'].strip()
        code_type = data.get('code_type', 'forever')
        
        if code_type not in ['forever', 'month', 'week', 'day']:
            return jsonify({"status": "error", "message": "Invalid code type"}), 400
        
        success = add_code_with_type(new_code, code_type)
        
        if success:
            return jsonify({
                "status": "success", 
                "message": f"Code {new_code} added (Type: {code_type})"
            })
        else:
            return jsonify({"status": "error", "message": "Code already exists"}), 400
    
    except Exception as e:
        return jsonify({"status": "error", "message": f"Error: {str(e)}"}), 500

@app.route('/api/admin/list_codes', methods=['GET'])
def list_codes():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT code, code_type, created_at, expires_at, used FROM codes ORDER BY created_at DESC")
        codes = c.fetchall()
        conn.close()
        
        result = []
        for row in codes:
            result.append({
                "code": row[0],
                "type": row[1],
                "created": row[2],
                "expires": row[3],
                "used": bool(row[4])
            })
        
        return jsonify({"status": "success", "codes": result})
    
    except Exception as e:
        return jsonify({"status": "error", "message": f"Error: {str(e)}"}), 500

@app.route('/api/status', methods=['GET'])
def status():
    return jsonify({
        "status": "active", 
        "service": "Activation API",
        "code_types": ["forever", "month", "week", "day"]
    })

# 👇 ДОБАВЛЯЕМ АДМИН-ПАНЕЛЬ С ФОРМОЙ
@app.route('/admin', methods=['GET'])
def admin_panel():
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Admin Panel - Activation Codes</title>
        <style>
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                max-width: 1000px;
                margin: 0 auto;
                padding: 20px;
                background: #f5f5f5;
            }
            .container {
                background: white;
                padding: 30px;
                border-radius: 10px;
                box-shadow: 0 2px 10px rgba(0,0,0,0.1);
            }
            h1 {
                color: #333;
                border-bottom: 2px solid #4CAF50;
                padding-bottom: 10px;
            }
            .section {
                margin: 30px 0;
                padding: 20px;
                background: #f9f9f9;
                border-radius: 8px;
            }
            input, select, button {
                padding: 12px;
                margin: 8px 0;
                border: 1px solid #ddd;
                border-radius: 5px;
                font-size: 16px;
            }
            input {
                width: 300px;
            }
            select {
                width: 150px;
            }
            button {
                background: #4CAF50;
                color: white;
                border: none;
                cursor: pointer;
                padding: 12px 24px;
                font-weight: bold;
            }
            button:hover {
                background: #45a049;
            }
            .result {
                padding: 15px;
                margin: 15px 0;
                border-radius: 5px;
                display: none;
            }
            .success {
                background: #d4edda;
                color: #155724;
                border: 1px solid #c3e6cb;
            }
            .error {
                background: #f8d7da;
                color: #721c24;
                border: 1px solid #f5c6cb;
            }
            .code-list {
                background: white;
                padding: 15px;
                border-radius: 5px;
                max-height: 400px;
                overflow-y: auto;
            }
            .code-item {
                padding: 10px;
                margin: 5px 0;
                border-left: 4px solid #4CAF50;
                background: #f9f9f9;
            }
            .used {
                border-left-color: #dc3545;
                opacity: 0.7;
            }
            .expired {
                border-left-color: #ffc107;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🔧 Панель управления кодами</h1>
            
            <div class="section">
                <h2>➕ Добавить новый код</h2>
                <input type="text" id="newCode" placeholder="Введите код (например: ABC123DEF)">
                <select id="codeType">
                    <option value="forever">Навсегда</option>
                    <option value="month">На месяц</option>
                    <option value="week">На неделю</option>
                    <option value="day">На день</option>
                </select>
                <button onclick="addCode()">Добавить код</button>
                <div id="addResult" class="result"></div>
            </div>
            
            <div class="section">
                <h2>✅ Проверить код</h2>
                <input type="text" id="checkCode" placeholder="Введите код для проверки">
                <button onclick="checkCode()">Проверить код</button>
                <div id="checkResult" class="result"></div>
            </div>
            
            <div class="section">
                <h2>📋 Все коды в системе</h2>
                <button onclick="loadCodes()">Обновить список</button>
                <div id="codesList" class="code-list">
                    <!-- Коды появятся здесь -->
                </div>
            </div>
            
            <div class="section">
                <h2>📊 Статистика</h2>
                <div id="stats">
                    <p>Всего кодов: <span id="totalCodes">0</span></p>
                    <p>Использовано: <span id="usedCodes">0</span></p>
                    <p>Активных: <span id="activeCodes">0</span></p>
                </div>
            </div>
        </div>
        
        <script>
            const API_BASE = window.location.origin;
            
            async function addCode() {
                const code = document.getElementById('newCode').value.trim();
                const type = document.getElementById('codeType').value;
                const resultDiv = document.getElementById('addResult');
                
                if (!code) {
                    showResult(resultDiv, 'Введите код!', 'error');
                    return;
                }
                
                try {
                    const response = await fetch(API_BASE + '/api/admin/add_code', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({code: code, code_type: type})
                    });
                    
                    const data = await response.json();
                    
                    if (data.status === 'success') {
                        showResult(resultDiv, `✅ ${data.message}`, 'success');
                        document.getElementById('newCode').value = '';
                        loadCodes();
                    } else {
                        showResult(resultDiv, `❌ ${data.message}`, 'error');
                    }
                } catch (error) {
                    showResult(resultDiv, '❌ Ошибка подключения к серверу', 'error');
                }
            }
            
            async function checkCode() {
                const code = document.getElementById('checkCode').value.trim();
                const resultDiv = document.getElementById('checkResult');
                
                if (!code) {
                    showResult(resultDiv, 'Введите код для проверки!', 'error');
                    return;
                }
                
                try {
                    const response = await fetch(API_BASE + '/api/check_code', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        body: JSON.stringify({activation_code: code})
                    });
                    
                    const data = await response.json();
                    
                    if (data.status === 'success') {
                        let message = `✅ ${data.message}`;
                        if (data.expires_at) {
                            message += `<br>⏰ Истекает: ${new Date(data.expires_at).toLocaleString()}`;
                        }
                        showResult(resultDiv, message, 'success');
                    } else {
                        showResult(resultDiv, `❌ ${data.message}`, 'error');
                    }
                } catch (error) {
                    showResult(resultDiv, '❌ Ошибка подключения к серверу', 'error');
                }
            }
            
            async function loadCodes() {
                try {
                    const response = await fetch(API_BASE + '/api/admin/list_codes');
                    const data = await response.json();
                    
                    if (data.status === 'success') {
                        const codesList = document.getElementById('codesList');
                        const stats = calculateStats(data.codes);
                        
                        codesList.innerHTML = data.codes.map(code => `
                            <div class="code-item ${code.used ? 'used' : ''}">
                                <strong>${code.code}</strong><br>
                                Тип: ${getTypeName(code.type)} | 
                                Создан: ${new Date(code.created).toLocaleDateString()} |
                                ${code.expires ? `Истекает: ${new Date(code.expires).toLocaleDateString()}` : 'Бессрочный'} |
                                Статус: ${code.used ? '🟥 Использован' : '🟢 Активен'}
                            </div>
                        `).join('');
                        
                        updateStats(stats);
                    }
                } catch (error) {
                    console.error('Ошибка загрузки кодов:', error);
                }
            }
            
            function calculateStats(codes) {
                const total = codes.length;
                const used = codes.filter(c => c.used).length;
                const active = total - used;
                
                return { total, used, active };
            }
            
            function updateStats(stats) {
                document.getElementById('totalCodes').textContent = stats.total;
                document.getElementById('usedCodes').textContent = stats.used;
                document.getElementById('activeCodes').textContent = stats.active;
            }
            
            function getTypeName(type) {
                const types = {
                    'forever': 'Навсегда',
                    'month': 'Месяц',
                    'week': 'Неделя',
                    'day': 'День'
                };
                return types[type] || type;
            }
            
            function showResult(element, message, type) {
                element.innerHTML = message;
                element.className = `result ${type}`;
                element.style.display = 'block';
                
                setTimeout(() => {
                    element.style.display = 'none';
                }, 5000);
            }
            
            // Загружаем коды при открытии страницы
            loadCodes();
        </script>
    </body>
    </html>
    '''

@app.route('/')
def home():
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Activation API</title>
        <style>
            body { font-family: Arial; margin: 40px; }
            .container { max-width: 800px; margin: 0 auto; }
            .endpoint { background: #f5f5f5; padding: 15px; margin: 10px 0; border-radius: 5px; }
            code { background: #e0e0e0; padding: 2px 5px; }
            .btn { background: #4CAF50; color: white; padding: 10px 20px; text-decoration: none; border-radius: 5px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🔑 Activation API</h1>
            <p>API для активации кодов с разными сроками действия</p>
            
            <a href="/admin" class="btn">📊 Панель управления кодами</a>
            
            <div class="endpoint">
                <h3>📡 Проверить статус API</h3>
                <code>GET /api/status</code>
            </div>
            
            <div class="endpoint">
                <h3>✅ Проверить код активации</h3>
                <code>POST /api/check_code</code><br>
                Body: <code>{"activation_code": "YOUR_CODE"}</code>
            </div>
            
            <div class="endpoint">
                <h3>➕ Добавить новый код</h3>
                <code>POST /api/admin/add_code</code><br>
                Body: <code>{"code": "NEW_CODE", "code_type": "forever|month|week|day"}</code>
            </div>
            
            <div class="endpoint">
                <h3>📋 Список всех кодов</h3>
                <code>GET /api/admin/list_codes</code>
            </div>
        </div>
    </body>
    </html>
    '''

init_db()
add_test_codes()

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)
