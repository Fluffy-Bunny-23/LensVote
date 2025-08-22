import os
import sqlite3
from datetime import datetime
from pathlib import Path
from flask import Flask, request, jsonify, send_from_directory, render_template, url_for
from werkzeug.utils import secure_filename

BASE_DIR = Path(__file__).resolve().parent
UPLOAD_FOLDER = BASE_DIR / 'uploads'
INSTANCE_FOLDER = BASE_DIR / 'instance'
DB_PATH = INSTANCE_FOLDER / 'family_rater.db'
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif', '.webp'}

app = Flask(__name__, instance_path=str(INSTANCE_FOLDER), instance_relative_config=True)
app.config['UPLOAD_FOLDER'] = str(UPLOAD_FOLDER)
app.config['MAX_CONTENT_LENGTH'] = None  # Unlimited upload size

UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)
INSTANCE_FOLDER.mkdir(parents=True, exist_ok=True)

# ...existing code...

# Get all users for dropdown
@app.get('/api/all_users')
def all_users():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT DISTINCT user FROM ratings ORDER BY user')
    users = [row['user'] for row in cur.fetchall()]
    conn.close()
    return jsonify({'users': users})

# Yes/No voting endpoint
@app.post('/api/rate_yesno')
def rate_yesno():
    image_id = request.json.get('image_id')
    user = request.json.get('user')
    yesno = request.json.get('yesno')
    if yesno not in ('Yes', 'No'):
        return jsonify({'error': 'Invalid vote'}), 400
    conn = get_db()
    # Store yes/no as rating 1 for No, 5 for Yes, or add a separate column if needed
    rating = 5 if yesno == 'Yes' else 1
    now = datetime.utcnow().isoformat()
    conn.execute('''
        INSERT INTO ratings (image_id, user, rating, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(image_id, user) DO UPDATE SET rating=excluded.rating, updated_at=excluded.updated_at
    ''', (image_id, user, rating, now, now))
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cur = conn.cursor()
    cur.executescript(
        '''
        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            created_at TEXT NOT NULL,
            hidden INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS ratings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            image_id INTEGER NOT NULL,
            user TEXT NOT NULL,
            rating INTEGER NOT NULL CHECK (rating >= 1 AND rating <= 5),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            UNIQUE(image_id, user),
            FOREIGN KEY (image_id) REFERENCES images(id) ON DELETE CASCADE
        );
        '''
    )
    # Add hidden column if missing
    try:
        cur.execute('ALTER TABLE images ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0')
    except sqlite3.OperationalError:
        pass
    conn.commit()
    conn.close()
# Hide/unhide photo
@app.post('/api/hide_photo')
def hide_photo():
    image_id = request.json.get('image_id')
    hide = int(request.json.get('hide', 1))
    conn = get_db()
    conn.execute('UPDATE images SET hidden = ? WHERE id = ?', (hide, image_id))
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})

# Delete photo and its ratings
@app.post('/api/delete_photo')
def delete_photo():
    image_id = request.json.get('image_id')
    conn = get_db()
    conn.execute('DELETE FROM ratings WHERE image_id = ?', (image_id,))
    conn.execute('DELETE FROM images WHERE id = ?', (image_id,))
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})

# Delete all data
@app.post('/api/delete_all_data')
def delete_all_data():
    conn = get_db()
    conn.execute('DELETE FROM ratings')
    conn.execute('DELETE FROM images')
    conn.commit()
    conn.close()
    # Optionally, remove files from uploads folder
    for f in os.listdir(UPLOAD_FOLDER):
        try:
            os.remove(UPLOAD_FOLDER / f)
        except Exception:
            pass
    return jsonify({'status': 'ok'})

# Ensure DB is initialized before running the app
init_db()

init_db()

def allowed_file(filename: str) -> bool:
    ext = os.path.splitext(filename)[1].lower()
    return ext in ALLOWED_EXTENSIONS

@app.route('/')
def home():
    return render_template('gallery.html', title='Gallery')

@app.route('/admin')
def admin():
    return render_template('admin.html', title='Admin')

@app.route('/gallery')
def gallery():
    return render_template('gallery.html', title='Gallery')

@app.post('/upload')
def upload():
    files = request.files.getlist('photos')
    saved = []
    for f in files:
        if not f.filename:
            continue
        if not allowed_file(f.filename):
            return ('Unsupported file type', 400)
        fname = secure_filename(f.filename)
        # Prevent overwrite by appending timestamp if exists
        dest = UPLOAD_FOLDER / fname
        if dest.exists():
            stem, ext = os.path.splitext(fname)
            fname = f"{stem}_{int(datetime.now().timestamp())}{ext}"
            dest = UPLOAD_FOLDER / fname
        f.save(dest)
        # add to db
        conn = get_db()
        conn.execute('INSERT INTO images (filename, created_at) VALUES (?, ?)', (fname, datetime.utcnow().isoformat()))
        conn.commit()
        conn.close()
        saved.append(fname)
    return jsonify({'saved': saved})

@app.get('/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename, as_attachment=False)

# Remove all votes
@app.post('/api/remove_votes')
def remove_votes():
    conn = get_db()
    conn.execute('DELETE FROM ratings')
    conn.commit()
    conn.close()
    return jsonify({'status': 'ok'})

# Download votes as JSON (filenames only)
@app.get('/api/download_votes')
def download_votes():
    conn = get_db()
    cur = conn.cursor()
    cur.execute('''
        SELECT i.filename, r.user, r.rating, r.created_at, r.updated_at
        FROM ratings r
        JOIN images i ON r.image_id = i.id
        ORDER BY i.filename, r.user
    ''')
    votes = {}
    for row in cur.fetchall():
        fname = row['filename']
        if fname not in votes:
            votes[fname] = []
        votes[fname].append({
            'user': row['user'],
            'rating': row['rating'],
            'created_at': row['created_at'],
            'updated_at': row['updated_at']
        })
    conn.close()
    return jsonify(votes)

def image_row_to_dict(row, user_rating=None):
    d = dict(row)
    d['url'] = url_for('uploaded_file', filename=row['filename'])
    d['avg_rating'] = row['avg_rating']
    d['rating_count'] = row['rating_count']
    if user_rating is not None:
        d['user_rating'] = user_rating
    return d

@app.get('/api/images')
def api_images():
    # Optional query: id=single image id
    # Optional: include_user_rating=1&user=Name
    image_id = request.args.get('id')
    include_user = request.args.get('include_user_rating') == '1'
    user = request.args.get('user', '')

    conn = get_db()
    cur = conn.cursor()
    if image_id:
        cur.execute(
            '''
            SELECT i.id, i.filename, i.created_at,
                   AVG(r.rating) AS avg_rating,
                   COUNT(r.id) AS rating_count
            FROM images i
            LEFT JOIN ratings r ON r.image_id = i.id
            WHERE i.id = ?
            GROUP BY i.id
            ORDER BY i.id DESC
            ''', (image_id,)
        )
    else:
        cur.execute(
            '''
            SELECT i.id, i.filename, i.created_at,
                   AVG(r.rating) AS avg_rating,
                   COUNT(r.id) AS rating_count
            FROM images i
            LEFT JOIN ratings r ON r.image_id = i.id
            GROUP BY i.id
            ORDER BY i.id DESC
            '''
        )
    rows = cur.fetchall()
    images = []
    if include_user and user:
        # fetch user ratings in one query
        ids = [row['id'] for row in rows]
        user_ratings = {}
        if ids:
            qmarks = ','.join('?' for _ in ids)
            cur.execute(f'SELECT image_id, rating FROM ratings WHERE user = ? AND image_id IN ({qmarks})', [user] + ids)
            for r in cur.fetchall():
                user_ratings[r['image_id']] = r['rating']
        for row in rows:
            images.append(image_row_to_dict(row, user_ratings.get(row['id'])))
    else:
        for row in rows:
            images.append(image_row_to_dict(row))
    conn.close()
    return jsonify({'images': images})

@app.post('/api/rate')
def api_rate():
    data = request.get_json(force=True)
    image_id = int(data.get('image_id'))
    user = (data.get('user') or '').strip()
    rating = int(data.get('rating'))
    if not user:
        return ('Missing user', 400)
    if rating < 1 or rating > 5:
        return ('Rating must be 1–5', 400)
    # upsert rating for (image_id, user)
    conn = get_db()
    cur = conn.cursor()
    now = datetime.utcnow().isoformat()
    # Try update first
    cur.execute('UPDATE ratings SET rating=?, updated_at=? WHERE image_id=? AND user=?', (rating, now, image_id, user))
    if cur.rowcount == 0:
        cur.execute('INSERT INTO ratings (image_id, user, rating, created_at, updated_at) VALUES (?, ?, ?, ?, ?)', (image_id, user, rating, now, now))
    conn.commit()
    conn.close()
    return jsonify({'ok': True})

@app.get('/api/top')
def api_top():
    limit = int(request.args.get('limit', '5'))
    conn = get_db()
    cur = conn.cursor()
    cur.execute(
        '''
        SELECT i.id, i.filename, i.created_at,
               AVG(r.rating) AS avg_rating,
               COUNT(r.id) AS rating_count
        FROM images i
        LEFT JOIN ratings r ON r.image_id = i.id
        GROUP BY i.id
        HAVING rating_count > 0
        ORDER BY avg_rating DESC, rating_count DESC, i.id DESC
        LIMIT ?
        ''', (limit,)
    )
    rows = cur.fetchall()
    images = [{
        'id': row['id'],
        'filename': row['filename'],
        'created_at': row['created_at'],
        'url': url_for('uploaded_file', filename=row['filename']),
        'avg_rating': row['avg_rating'],
        'rating_count': row['rating_count'],
    } for row in rows]
    conn.close()
    return jsonify({'images': images})

if __name__ == '__main__':
    app.run(debug=True)
