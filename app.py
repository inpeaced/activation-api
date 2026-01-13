from flask import Flask, request, jsonify, Response
import sqlite3
import os
import hashlib
import secrets
from datetime import datetime, timedelta
from functools import wraps

app = Flask(__name__)

ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'CHANGE_THIS_IN_PRODUCTION')

if ADMIN_PASSWORD == 'CHANGE_THIS_IN_PRODUCTION':
    print("ВНИМАНИЕ: Используется дефолтный пароль!")

def check_admin_auth(username, password):
    return password == ADMIN_PASSWORD

def requires_auth(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        auth = request.authorization
        if not auth or not check_admin_auth(auth.username, auth.password):
            return Response(
                'Требуется авторизация',
                401,
                {'WWW-Authenticate': 'Basic realm="Login Required"'}
            )
        return f(*args, **kwargs)
    return decorated

DB_PATH = '/tmp/activation_codes.db'

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # Таблица кодов активации
    c.execute('''CREATE TABLE IF NOT EXISTS codes
                 (id INTEGER PRIMARY KEY,
                  code TEXT UNIQUE NOT NULL,
                  used INTEGER DEFAULT 0,
                  code_type TEXT NOT NULL,
                  created_at TIMESTAMP,
                  expires_at TIMESTAMP)''')
    
    # Таблица пользователей
    c.execute('''CREATE TABLE IF NOT EXISTS users
                 (id INTEGER PRIMARY KEY,
                  username TEXT UNIQUE NOT NULL,
                  password_hash TEXT NOT NULL,
                  created_at TIMESTAMP,
                  last_login TIMESTAMP)''')
    
    # Таблица активаций (связь пользователь-код)
    c.execute('''CREATE TABLE IF NOT EXISTS activations
                 (id INTEGER PRIMARY KEY,
                  user_id INTEGER NOT NULL,
                  code_id INTEGER NOT NULL,
                  activated_at TIMESTAMP,
                  expires_at TIMESTAMP,
                  FOREIGN KEY(user_id) REFERENCES users(id),
                  FOREIGN KEY(code_id) REFERENCES codes(id))''')
    
    conn.commit()
    conn.close()

def hash_password(password):
    salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return salt + key

def verify_password(stored_hash, password):
    salt = stored_hash[:32]
    stored_key = stored_hash[32:]
    key = hashlib.pbkdf2_hmac('sha256', password.encode('utf-8'), salt, 100000)
    return key == stored_key

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

def register_user(username, password, activation_code):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    try:
        conn.execute("BEGIN")
        
        # 1. Проверяем код активации
        c.execute("SELECT id, used, code_type, expires_at FROM codes WHERE code = ?", (activation_code,))
        code_data = c.fetchone()
        
        if not code_data:
            return {"status": "error", "message": "Invalid activation code"}
        
        code_id, used, code_type, expires_at = code_data
        
        if used:
            return {"status": "error", "message": "Code already used"}
        
        if expires_at:
            try:
                expires_date = datetime.strptime(expires_at, '%Y-%m-%d %H:%M:%S.%f')
            except:
                expires_date = datetime.strptime(expires_at, '%Y-%m-%d %H:%M:%S')
            
            if datetime.now() > expires_date:
                return {"status": "error", "message": "Code expired"}
        
        # 2. Проверяем не занят ли username
        c.execute("SELECT id FROM users WHERE username = ?", (username,))
        if c.fetchone():
            return {"status": "error", "message": "Username already exists"}
        
        # 3. Создаем пользователя
        password_hash = hash_password(password)
        c.execute("INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)",
                 (username, password_hash, datetime.now()))
        user_id = c.lastrowid
        
        # 4. Помечаем код как использованный
        c.execute("UPDATE codes SET used = 1 WHERE id = ?", (code_id,))
        
        # 5. Записываем активацию
        activation_expiry = calculate_expiry(code_type)
        c.execute("""INSERT INTO activations (user_id, code_id, activated_at, expires_at) 
                     VALUES (?, ?, ?, ?)""",
                 (user_id, code_id, datetime.now(), activation_expiry))
        
        conn.commit()
        
        return {
            "status": "success",
            "message": "Registration successful",
            "user_id": user_id,
            "code_type": code_type,
            "expires_at": activation_expiry
        }
        
    except Exception as e:
        conn.rollback()
        return {"status": "error", "message": f"Registration failed: {str(e)}"}
    
    finally:
        conn.close()

def login_user(username, password):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    try:
        # Ищем пользователя
        c.execute("SELECT id, password_hash FROM users WHERE username = ?", (username,))
        user_data = c.fetchone()
        
        if not user_data:
            return {"status": "error", "message": "Invalid username or password"}
        
        user_id, stored_hash = user_data
        
        # Проверяем пароль
        if not verify_password(stored_hash, password):
            return {"status": "error", "message": "Invalid username or password"}
        
        # Обновляем время последнего входа
        c.execute("UPDATE users SET last_login = ? WHERE id = ?", (datetime.now(), user_id))
        
        # Получаем информацию об активации
        c.execute("""SELECT a.expires_at, c.code_type 
                     FROM activations a 
                     JOIN codes c ON a.code_id = c.id 
                     WHERE a.user_id = ? 
                     ORDER BY a.activated_at DESC LIMIT 1""", (user_id,))
        activation_data = c.fetchone()
        
        expires_at = None
        code_type = "forever"
        if activation_data:
            expires_at, code_type = activation_data
        
        # Проверяем не истекла ли активация
        is_active = True
        if expires_at:
            try:
                expires_date = datetime.strptime(expires_at, '%Y-%m-%d %H:%M:%S.%f')
            except:
                expires_date = datetime.strptime(expires_at, '%Y-%m-%d %H:%M:%S')
            
            if datetime.now() > expires_date:
                is_active = False
        
        conn.commit()
        
        return {
            "status": "success",
            "message": "Login successful",
            "user_id": user_id,
            "is_active": is_active,
            "code_type": code_type,
            "expires_at": expires_at
        }
        
    except Exception as e:
        return {"status": "error", "message": f"Login failed: {str(e)}"}
    
    finally:
        conn.close()

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

# ========== API ЭНДПОИНТЫ ==========

@app.route('/api/register', methods=['POST'])
def register():
    """Регистрация нового пользователя"""
    try:
        data = request.get_json()
        if not data or 'username' not in data or 'password' not in data or 'activation_code' not in data:
            return jsonify({"status": "error", "message": "Missing required fields"}), 400
        
        username = data['username'].strip()
        password = data['password'].strip()
        activation_code = data['activation_code'].strip()
        
        if len(username) < 3:
            return jsonify({"status": "error", "message": "Username too short (min 3 chars)"}), 400
        
        if len(password) < 6:
            return jsonify({"status": "error", "message": "Password too short (min 6 chars)"}), 400
        
        result = register_user(username, password, activation_code)
        return jsonify(result)
    
    except Exception as e:
        return jsonify({"status": "error", "message": f"Server error: {str(e)}"}), 500

@app.route('/api/login', methods=['POST'])
def login():
    """Вход существующего пользователя"""
    try:
        data = request.get_json()
        if not data or 'username' not in data or 'password' not in data:
            return jsonify({"status": "error", "message": "Missing username or password"}), 400
        
        username = data['username'].strip()
        password = data['password'].strip()
        
        result = login_user(username, password)
        return jsonify(result)
    
    except Exception as e:
        return jsonify({"status": "error", "message": f"Server error: {str(e)}"}), 500

@app.route('/api/check_user', methods=['POST'])
def check_user():
    """Проверка существования пользователя"""
    try:
        data = request.get_json()
        if not data or 'username' not in data:
            return jsonify({"status": "error", "message": "Missing username"}), 400
        
        username = data['username'].strip()
        
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT id FROM users WHERE username = ?", (username,))
        exists = c.fetchone() is not None
        conn.close()
        
        return jsonify({
            "status": "success",
            "exists": exists
        })
    
    except Exception as e:
        return jsonify({"status": "error", "message": f"Server error: {str(e)}"}), 500

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

@app.route('/api/admin/list_users', methods=['GET'])
@requires_auth
def list_users():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""SELECT u.id, u.username, u.created_at, u.last_login, 
                            c.code_type, a.expires_at
                     FROM users u
                     LEFT JOIN activations a ON u.id = a.user_id
                     LEFT JOIN codes c ON a.code_id = c.id
                     ORDER BY u.created_at DESC""")
        users = c.fetchall()
        conn.close()
        
        result = []
        for row in users:
            result.append({
                "id": row[0],
                "username": row[1],
                "created": row[2],
                "last_login": row[3],
                "code_type": row[4],
                "expires_at": row[5]
            })
        
        return jsonify({"status": "success", "users": result})
    
    except Exception as e:
        return jsonify({"status": "error", "message": f"Error: {str(e)}"}), 500

@app.route('/api/status', methods=['GET'])
def status():
    return jsonify({
        "status": "active", 
        "service": "Activation API with User Profiles",
        "endpoints": {
            "register": "/api/register",
            "login": "/api/login",
            "check_user": "/api/check_user"
        }
    })

@app.route('/admin')
@requires_auth
def admin_panel():
    return '''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Admin Panel - Activation Codes & Users</title>
        <meta charset="UTF-8">
        <style>
            body { font-family: Arial; margin: 40px; }
            .container { max-width: 1200px; margin: 0 auto; }
            .section { margin: 30px 0; padding: 20px; background: #f5f5f5; border-radius: 8px; }
            input, select, button { padding: 10px; margin: 5px; }
            input { width: 250px; }
            button { background: #4CAF50; color: white; border: none; cursor: pointer; }
            .tab { overflow: hidden; border: 1px solid #ccc; background-color: #f1f1f1; }
            .tab button { background-color: inherit; float: left; border: none; outline: none; cursor: pointer; padding: 14px 16px; }
            .tab button:hover { background-color: #ddd; }
            .tab button.active { background-color: #ccc; }
            .tabcontent { display: none; padding: 20px; border: 1px solid #ccc; border-top: none; }
            .result { padding: 10px; margin: 10px 0; border-radius: 5px; }
            .success { background: #d4edda; color: #155724; }
            .error { background: #f8d7da; color: #721c24; }
            .user-list, .code-list { max-height: 400px; overflow-y: auto; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🔧 Панель управления</h1>
            <p><strong>⚠️ Доступ только для администратора</strong></p>
            
            <div class="tab">
                <button class="tablinks active" onclick="openTab(event, 'codes')">Коды активации</button>
                <button class="tablinks" onclick="openTab(event, 'users')">Пользователи</button>
            </div>
            
            <div id="codes" class="tabcontent" style="display: block;">
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
                
                <h2>📋 Все коды в системе</h2>
                <button onclick="loadCodes()">Обновить список</button>
                <div id="codesList" class="code-list"></div>
            </div>
            
            <div id="users" class="tabcontent">
                <h2>👥 Зарегистрированные пользователи</h2>
                <button onclick="loadUsers()">Обновить список</button>
                <div id="usersList" class="user-list"></div>
            </div>
        </div>
        
        <script>
            function openTab(evt, tabName) {
                var i, tabcontent, tablinks;
                tabcontent = document.getElementsByClassName("tabcontent");
                for (i = 0; i < tabcontent.length; i++) {
                    tabcontent[i].style.display = "none";
                }
                tablinks = document.getElementsByClassName("tablinks");
                for (i = 0; i < tablinks.length; i++) {
                    tablinks[i].className = tablinks[i].className.replace(" active", "");
                }
                document.getElementById(tabName).style.display = "block";
                evt.currentTarget.className += " active";
            }
            
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
            
            async function loadUsers() {
                try {
                    const response = await fetch('/api/admin/list_users', {
                        credentials: 'include'
                    });
                    const data = await response.json();
                    
                    if (data.status === 'success') {
                        const usersList = document.getElementById('usersList');
                        usersList.innerHTML = '<h3>Всего пользователей: ' + data.users.length + '</h3>';
                        
                        data.users.forEach(user => {
                            const div = document.createElement('div');
                            div.style.padding = '10px';
                            div.style.margin = '5px';
                            div.style.background = '#e6f3ff';
                            div.style.border = '1px solid #ddd';
                            
                            const lastLogin = user.last_login ? new Date(user.last_login).toLocaleString() : 'Никогда';
                            const expires = user.expires_at ? new Date(user.expires_at).toLocaleDateString() : 'Бессрочно';
                            
                            div.innerHTML = `
                                <strong>${user.username}</strong> (ID: ${user.id})<br>
                                Зарегистрирован: ${new Date(user.created).toLocaleDateString()}<br>
                                Последний вход: ${lastLogin}<br>
                                Тип подписки: ${user.code_type || 'Нет'} |
                                Истекает: ${expires}
                            `;
                            
                            usersList.appendChild(div);
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
            
            // Загружаем коды при открытии
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
        <title>Activation API with User Profiles</title>
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
            <h1>🔑 Activation API with User Profiles</h1>
            <p>Полная система активации с профилями пользователей</p>
            <p><strong>⚠️ Админ-панель защищена паролем</strong></p>
            
            <div class="endpoint">
                <h3>📝 Регистрация пользователя</h3>
                <code>POST /api/register</code><br>
                Body: <code>{"username": "user", "password": "pass", "activation_code": "CODE"}</code>
            </div>
            
            <div class="endpoint">
                <h3>🔐 Вход пользователя</h3>
                <code>POST /api/login</code><br>
                Body: <code>{"username": "user", "password": "pass"}</code>
            </div>
            
            <div class="endpoint">
                <h3>🔍 Проверить имя пользователя</h3>
                <code>POST /api/check_user</code><br>
                Body: <code>{"username": "user"}</code>
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
