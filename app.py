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
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🔑 Activation API</h1>
            <p>API для активации кодов с разными сроками действия</p>
            
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
