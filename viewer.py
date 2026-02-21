import sqlite3
import json
import requests
import os
import pymysql
from flask import Flask, render_template, jsonify, request, Response

app = Flask(__name__)
DB_PATH = "javbus.db"
DB_TYPE = os.environ.get("DB_TYPE", "sqlite")
DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DB_PORT = int(os.environ.get("DB_PORT", "3306"))
DB_USER = os.environ.get("DB_USER", "root")
DB_PASSWORD = os.environ.get("DB_PASSWORD", "")
DB_NAME = os.environ.get("DB_NAME", "javbus")
API_TOKEN = os.environ.get("API_TOKEN", "")

def get_db_connection():
    if DB_TYPE == "mysql":
        conn = pymysql.connect(
            host=DB_HOST,
            port=DB_PORT,
            user=DB_USER,
            password=DB_PASSWORD,
            database=DB_NAME,
            charset="utf8mb4",
            cursorclass=pymysql.cursors.DictCursor,
            autocommit=True,
        )
        return conn
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

@app.route('/')
def index():
    return render_template('index.html')

@app.route('/api/movies')
def get_movies():
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    offset = (page - 1) * per_page
    
    conn = get_db_connection()
    if DB_TYPE == "mysql":
        with conn.cursor() as c:
            c.execute('SELECT COUNT(*) AS c FROM movies')
            total = c.fetchone()['c']
            c.execute('SELECT * FROM movies ORDER BY date DESC LIMIT %s OFFSET %s', (per_page, offset))
            movies = c.fetchall()
    else:
        total = conn.execute('SELECT COUNT(*) FROM movies').fetchone()[0]
        movies = conn.execute('SELECT * FROM movies ORDER BY date DESC LIMIT ? OFFSET ?', 
                              (per_page, offset)).fetchall()
        movies = [dict(m) for m in movies]
        conn.close()
    
    movie_list = []
    for movie in movies:
        movie_dict = dict(movie)
        
        # 检查本地图片
        local_img_path = f"static/images/{movie_dict['code']}.jpg"
        if os.path.exists(local_img_path):
             movie_dict['img_url'] = f"/{local_img_path}"
        else:
             # 如果本地没有，使用代理
             movie_dict['img_url'] = f"/proxy/image?url={movie_dict['img_url']}"

        # 解析磁力链接 JSON 以获取数量
        try:
            magnets = json.loads(movie_dict['magnet_links'])
            movie_dict['magnet_count'] = len(magnets)
        except:
            movie_dict['magnet_count'] = 0
            
        # 不在列表页返回具体的磁力链接，减少传输量
        del movie_dict['magnet_links']
        movie_list.append(movie_dict)
        
    return jsonify({
        'total': total,
        'page': page,
        'per_page': per_page,
        'movies': movie_list
    })

@app.route('/api/movie/<code>')
def get_movie_detail(code):
    conn = get_db_connection()
    if DB_TYPE == "mysql":
        with conn.cursor() as c:
            c.execute('SELECT * FROM movies WHERE code = %s', (code,))
            movie = c.fetchone()
    else:
        movie = conn.execute('SELECT * FROM movies WHERE code = ?', (code,)).fetchone()
        movie = dict(movie) if movie else None
    
    if movie is None:
        return jsonify({'error': 'Movie not found'}), 404
        
    movie_dict = dict(movie)
    
    # 检查本地图片
    local_img_path = f"static/images/{movie_dict['code']}.jpg"
    if os.path.exists(local_img_path):
            movie_dict['img_url'] = f"/{local_img_path}"
    else:
            movie_dict['img_url'] = f"/proxy/image?url={movie_dict['img_url']}"
            
    try:
        movie_dict['magnets'] = json.loads(movie_dict['magnet_links'])
    except:
        movie_dict['magnets'] = []
    
    return jsonify(movie_dict)

@app.route('/api/save_movie', methods=['POST'])
def save_movie():
    if API_TOKEN:
        token = request.headers.get('X-API-Token', '')
        if token != API_TOKEN:
            return jsonify({'error': 'unauthorized'}), 401
    data = request.get_json(silent=True) or {}
    code = (data.get('code') or '').strip()
    title = data.get('title') or ''
    img_url = data.get('img_url') or ''
    date = data.get('date') or ''
    magnets = data.get('magnets') or []
    link = data.get('link') or ''
    magnets_json = json.dumps(magnets, ensure_ascii=False)
    if not code:
        return jsonify({'error': 'invalid code'}), 400
    conn = get_db_connection()
    if DB_TYPE == "mysql":
        with conn.cursor() as c:
            c.execute("""
                INSERT INTO movies (code, title, img_url, date, magnet_links, detail_url)
                VALUES (%s, %s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                    title=VALUES(title),
                    img_url=VALUES(img_url),
                    date=VALUES(date),
                    magnet_links=VALUES(magnet_links),
                    detail_url=VALUES(detail_url)
            """, (code, title, img_url, date, magnets_json, link))
        return jsonify({'ok': True})
    conn.execute('''INSERT OR REPLACE INTO movies (code, title, img_url, date, magnet_links, detail_url)
                    VALUES (?, ?, ?, ?, ?, ?)''',
                 (code, title, img_url, date, magnets_json, link))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.route('/proxy/image')
def proxy_image():
    url = request.args.get('url')
    if not url:
        return "Missing URL", 400
        
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
        "Referer": "https://www.javbus.com/"
    }
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        excluded_headers = ['content-encoding', 'content-length', 'transfer-encoding', 'connection']
        headers = [(name, value) for (name, value) in resp.raw.headers.items()
                   if name.lower() not in excluded_headers]
        return Response(resp.content, resp.status_code, headers)
    except Exception as e:
        return str(e), 500

if __name__ == '__main__':
    print("启动 Web 服务...")
    print("请访问: http://127.0.0.1:5000")
    app.run(debug=True, port=5000)
