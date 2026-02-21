import requests
from lxml import html
import time
import os
import re
import random
import concurrent.futures
import threading
import sqlite3
import json
import sys

# 全局锁，用于防止打印输出错乱
print_lock = threading.Lock()
# 数据库锁
db_lock = threading.Lock()

base_url = "https://www.javbus.com/"
db_path = "javbus.db"
IMG_DIR = "static/images"
MAX_WORKERS = 30
SERVER_API_BASE = os.environ.get("SERVER_API_BASE", "")
API_TOKEN = os.environ.get("API_TOKEN", "")

if not os.path.exists(IMG_DIR):
    os.makedirs(IMG_DIR)

def init_db():
    """初始化数据库"""
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS movies
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  code TEXT UNIQUE,
                  title TEXT,
                  img_url TEXT,
                  date TEXT,
                  magnet_links TEXT,
                  detail_url TEXT,
                  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP)''')
    conn.commit()
    conn.close()

def save_to_db(data):
    if SERVER_API_BASE:
        url = SERVER_API_BASE.rstrip("/") + "/api/save_movie"
        headers_api = {"X-API-Token": API_TOKEN} if API_TOKEN else {}
        try:
            resp = requests.post(url, json=data, headers=headers_api, timeout=10)
            if resp.status_code != 200:
                with print_lock:
                    print(f"远程写入失败: {resp.status_code} {resp.text}")
            return
        except Exception as e:
            with print_lock:
                print(f"远程写入异常: {e}")
            return
    with db_lock:
        try:
            conn = sqlite3.connect(db_path)
            c = conn.cursor()
            magnets_json = json.dumps(data['magnets'], ensure_ascii=False)
            c.execute('''INSERT OR REPLACE INTO movies (code, title, img_url, date, magnet_links, detail_url)
                         VALUES (?, ?, ?, ?, ?, ?)''',
                      (data['code'], data['title'], data['img_url'], data['date'], magnets_json, data['link']))
            conn.commit()
            conn.close()
        except Exception as e:
            with print_lock:
                print(f"数据库保存失败: {e}")
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/144.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "zh-CN,zh;q=0.9",
    "Cookie": "existmag=mag; PHPSESSID=c5tvoniit8iupd7743veu59uj3"
}

def safe_request(url, custom_headers=None, retries=3, delay=2):
    for attempt in range(1, retries + 1):
        try:
            req_headers = custom_headers if custom_headers else headers
            resp = requests.get(url, headers=req_headers, timeout=10)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            print(f"请求失败: {url} 错误: {e} 尝试: {attempt}/{retries}")
            if attempt < retries:
                time.sleep(delay * attempt)
    return None

def download_image(url, code):
    """下载图片到本地"""
    file_path = os.path.join(IMG_DIR, f"{code}.jpg")
    if os.path.exists(file_path):
        return
    
    try:
        resp = requests.get(url, headers=headers, timeout=10)
        if resp.status_code == 200:
            with open(file_path, "wb") as f:
                f.write(resp.content)
            with print_lock:
                print(f"图片下载成功: {code}")
    except Exception as e:
        with print_lock:
            print(f"图片下载失败 {code}: {e}")

def process_detail(data):
    """处理单个详情页的函数，用于线程池"""
    link, img, title, code, time_text, page_num, idx = data
    magnets = []
    
    # 随机延时，避免并发过快被封
    time.sleep(random.uniform(0.5, 2.0))
    
    detail_html = safe_request(link)
    if detail_html:
        # 尝试从 AJAX 获取磁力链接
        try:
            gid_match = re.search(r"var gid = (\d+);", detail_html)
            uc_match = re.search(r"var uc = (\d+);", detail_html)
            img_match = re.search(r"var img = '([^']+)';", detail_html)

            if gid_match and uc_match and img_match:
                gid = gid_match.group(1)
                uc = uc_match.group(1)
                img_val = img_match.group(1)
                floor = random.randint(1, 1000)

                ajax_url = f"https://www.javbus.com/ajax/uncledatoolsbyajax.php?gid={gid}&lang=zh&img={img_val}&uc={uc}&floor={floor}"
                
                # 构造新的 headers，必须包含 Referer
                ajax_headers = headers.copy()
                ajax_headers['Referer'] = link
                
                ajax_html = safe_request(ajax_url, custom_headers=ajax_headers)
                if ajax_html:
                    ajax_tree = html.fromstring(ajax_html)
                    # 尝试匹配所有磁力链接
                    magnets = ajax_tree.xpath('//a[contains(@href, "magnet:")]/@href')
        except Exception as e:
            with print_lock:
                print(f"获取磁力链接 AJAX 失败: {e}")

        # 如果 AJAX 失败或没找到，尝试旧方法
        if not magnets:
            detail_tree = html.fromstring(detail_html)
            magnets = detail_tree.xpath('//*[@id="magnet-table"]/tr/td[2]/a/@href')

    # 去重，保持顺序
    if magnets:
        magnets = list(dict.fromkeys(magnets))

    # 如果没有任何下载链接，则不入库，保留给下次运行重试
    if not magnets:
        with print_lock:
            print(f"番号 {code.strip()} 未找到下载链接，将在下次运行时重试")
            if detail_html:
                filename = f"page{page_num}_item{idx}.html"
                try:
                    with open(filename, "w", encoding="utf-8") as f:
                        f.write(detail_html)
                    print(f"已保存调试文件: {filename}")
                except Exception as e:
                    print(f"保存调试文件失败: {e}")
            print("-" * 50)
        return

    # 下载图片
    download_image(img, code.strip())

    # 保存到数据库（只保存有磁力链接的影片）
    movie_data = {
        'link': link,
        'img_url': img,
        'title': title.strip(),
        'code': code.strip(),
        'date': time_text.strip(),
        'magnets': magnets
    }
    save_to_db(movie_data)

    # 使用锁保证输出完整
    with print_lock:
        print(f"影片链接: {link}")
        print(f"图片地址: {img}")
        print(f"标题: {title.strip()}")
        print(f"番号: {code.strip()}")
        print(f"时间: {time_text.strip()}")
        print("下载链接:")
        for m in magnets:
            print(f"  {m}")
        print("-" * 50)

def fetch_page(url, page_num):
    html_text = safe_request(url)
    if not html_text:
        return False

    tree = html.fromstring(html_text)
    links = tree.xpath('//*[@id="waterfall"]/div/a/@href')
    images = tree.xpath('//*[@id="waterfall"]/div/a/div[1]/img/@src')
    titles = tree.xpath('//*[@id="waterfall"]/div/a/div[2]/span/text()[1]')
    codes = tree.xpath('//*[@id="waterfall"]/div/a/div[2]/span/date[1]/text()')
    times = tree.xpath('//*[@id="waterfall"]/div/a/div[2]/span/date[2]/text()')

    if not links:
        return False

    full_images = [
        img if img.startswith("http") else "https://www.javbus.com/" + img.lstrip("/")
        for img in images
    ]

    tasks = []
    stripped_codes = [c.strip() for c in codes]
    if SERVER_API_BASE:
        existing_complete = set()
        existing_incomplete = set()
    else:
        if stripped_codes:
            try:
                conn = sqlite3.connect(db_path)
                c = conn.cursor()
                placeholders = ",".join("?" for _ in stripped_codes)
                query = f"SELECT code, magnet_links FROM movies WHERE code IN ({placeholders})"
                c.execute(query, stripped_codes)
                existing_complete = set()
                existing_incomplete = set()
                for row in c.fetchall():
                    code_db, magnets_json = row
                    code_db = code_db.strip()
                    if magnets_json and magnets_json not in ("[]", "", "null", "NULL"):
                        existing_complete.add(code_db)
                    else:
                        existing_incomplete.add(code_db)
                conn.close()
            except Exception as e:
                existing_complete = set()
                existing_incomplete = set()
                print(f"检查重复失败: {e}")
        else:
            existing_complete = set()
            existing_incomplete = set()

    for idx, (link, img, title, code, time_text) in enumerate(
        zip(links, full_images, titles, codes, times), start=1):
        code_stripped = code.strip()
        if code_stripped in existing_complete:
            with print_lock:
                print(f"跳过已存在: {code_stripped}")
            continue
        if code_stripped in existing_incomplete:
            with print_lock:
                print(f"重新尝试获取磁力链接: {code_stripped}")
        tasks.append((link, img, title, code, time_text, page_num, idx))

    if not tasks:
        with print_lock:
            print(f"第 {page_num} 页全部已存在，跳过。")
        return True

    with concurrent.futures.ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
        executor.map(process_detail, tasks)

    return True

# 初始化数据库
init_db()

# 首页
print("正在抓取首页...")
fetch_page(base_url, 1)

# 分页
page = 2
while True:
    page_url = f"https://www.javbus.com/page/{page}"
    print(f"正在抓取第 {page} 页...")
    ok = fetch_page(page_url, page)
    if not ok:
        print("抓取结束。")
        break
    page += 1
    time.sleep(2)  # 延时，防止请求过快
