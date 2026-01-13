from flask import Flask, request, jsonify, Response
import sqlite3
import os
from datetime import datetime, timedelta
from functools import wraps

app = Flask(__name__)

ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'CHANGE_THIS_IN_PRODUCTION')

if ADMIN_PASSWORD == 'CHANGE_THIS_IN_PRODUCTION':
    print("ВНИМАНИЕ: Используется дефолтный пароль! Добавьте ADMIN_PASSWORD в переменные окружения.")

def check_admin_auth(username, password):
    return password == ADMIN_PASSWORD

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_admin_auth(auth.username, auth.password):
            return Response(
                'Требуется авторизация для доступа к панели администратора',
                401,
                {'WWW-Authenticate': 'Basic realm="Login Required"'}
            )
        return f(*args, **kwargs)
    return decorated

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

@app.route('/api/status', methods=['GET'])
def status():
    return jsonify({
        "status": "active", 
        "service": "Activation API",
        "code_types": ["forever", "month", "week", "day"]
    })

@app.route('/api/admin/add_code', methods=['POST'])
@requires_auth
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
@requires_auth
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

@app.route('/admin')
@requires_auth
def admin_panel():
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Admin Panel - Activation Codes</title>
        <meta charset="UTF-8">
        <style>
            body { font-family: Arial; margin: 40px; }
            .container { max-width: 1000px; margin: 0 auto; }
            .section { margin: 30px 0; padding: 20px; background: #f5f5f5; border-radius: 8px; }
            input, select, button { padding: 10px; margin: 5px; }
            input { width: 250px; }
            button { background: #4CAF50; color: white; border: none; cursor: pointer; }
            .result { padding: 10px; margin: 10px 0; border-radius: 5px; }
            .success { background: #d4edda; color: #155724; }
            .error { background: #f8d7da; color: #721c24; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🔧 Панель управления кодами</h1>
            <p><strong>⚠️ Доступ только для администратора</strong></p>
            
            <div class="section">
                <h2>➕ Добавить новый код</h2>
                <input type="text" id="newCode" placeholder="Введите код">
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
                <h2>📋 Все коды в системе</h2>
                <button onclick="loadCodes()">Обновить список</button>
                <div id="codesList"></div>
            </div>
        </div>
        
        <script>
            async function addCode() {
                const code = document.getElementById('newCode').value.trim();
                const type = document.getElementById('codeType').value;
                
                if (!code) {
                    showResult('Введите код!', 'error');
                    return;
                }
                
                try {
                    const response = await fetch('/api/admin/add_code', {
                        method: 'POST',
                        headers: {'Content-Type': 'application/json'},
                        credentials: 'include',
                        body: JSON.stringify({code: code, code_type: type})
                    });
                    
                    const data = await response.json();
                    showResult(data.message, data.status);
                    
                    if (data.status === 'success') {
                        document.getElementById('newCode').value = '';
                        loadCodes();
                    }
                } catch (error) {
                    showResult('Ошибка подключения', 'error');
                }
            }
            
            async function loadCodes() {
                try {
                    const response = await fetch('/api/admin/list_codes', {
                        credentials: 'include'
                    });
                    const data = await response.json();
                    
                    if (data.status === 'success') {
                        const codesList = document.getElementById('codesList');
                        codesList.innerHTML = '<h3>Всего кодов: ' + data.codes.length + '</h3>';
                        
                        data.codes.forEach(code => {
                            const div = document.createElement('div');
                            div.style.padding = '10px';
                            div.style.margin = '5px';
                            div.style.background = code.used ? '#ffe6e6' : '#e6ffe6';
                            div.style.border = '1px solid #ddd';
                            
                            div.innerHTML = `
                                <strong>${code.code}</strong> | 
                                Тип: ${code.type} | 
                                Создан: ${new Date(code.created).toLocaleDateString()} |
                                ${code.expires ? 'Истекает: ' + new Date(code.expires).toLocaleDateString() : 'Бессрочный'} |
                                Статус: ${code.used ? 'Использован ❌' : 'Активен ✅'}
                            `;
                            
                            codesList.appendChild(div);
                        });
                    }
                } catch (error) {
                    console.error(error);
                }
            }
            
            function showResult(message, type) {
                const resultDiv = document.getElementById('addResult');
                resultDiv.textContent = message;
                resultDiv.className = `result ${type}`;
                resultDiv.style.display = 'block';
                
                setTimeout(() => {
                    resultDiv.style.display = 'none';
                }, 3000);
            }
            
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
        <meta charset="UTF-8">
        <style>
            body { font-family: Arial; margin: 40px; }
            .container { max-width: 800px; margin: 0 auto; }
            .endpoint { background: #f5f5f5; padding: 15px; margin: 10px 0; border-radius: 5px; }
            code { background: #e0e0e0; padding: 2px 5px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🔑 Activation API</h1>
            <p>API для активации кодов с разными сроками действия</p>
            <p><strong>⚠️ Админ-панель защищена паролем</strong></p>
            
            <div class="endpoint">
                <h3>📡 Проверить статус API</h3>
                <code>GET /api/status</code>
            </div>
            
            <div class="endpoint">
                <h3>✅ Проверить код активации (для вашего C++ мода)</h3>
                <code>POST /api/check_code</code><br>
                Body: <code>{"activation_code": "YOUR_CODE"}</code>
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
