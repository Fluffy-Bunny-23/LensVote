import os
import re
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

# simple slugify for set folder names
def slugify(s: str) -> str:
    s = s.lower().strip()
    s = re.sub(r'[^a-z0-9]+', '-', s)
    s = s.strip('-')
    return s or 'set'

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


@app.get('/api/sets')
def api_sets():
    conn = get_db()
    cur = conn.cursor()
    # include image counts per set
    cur.execute('SELECT s.id, s.name, s.slug, s.created_at, (SELECT COUNT(*) FROM images i WHERE i.set_id = s.id) AS image_count FROM sets s ORDER BY s.created_at')
    sets = [dict(row) for row in cur.fetchall()]
    conn.close()
    return jsonify({'sets': sets})


@app.post('/api/migrate/normalize_default')
def migrate_normalize_default():
    """Move existing images with bare filenames into uploads/default/ and set their set_id/filename accordingly."""
    conn = get_db()
    cur = conn.cursor()
    # ensure default set exists
    cur.execute("SELECT id, slug FROM sets WHERE slug = 'default'")
    r = cur.fetchone()
    if not r:
        now = datetime.utcnow().isoformat()
        cur.execute('INSERT INTO sets (name, slug, created_at) VALUES (?, ?, ?)', ('Default', 'default', now))
        conn.commit()
        cur.execute("SELECT id, slug FROM sets WHERE slug = 'default'")
        r = cur.fetchone()
    default_id = r['id']
    default_slug = r['slug']

    moved = []
    updated = []
    missing = []

    # Find images whose filename does not start with 'slug/' or already have set_id different
    cur.execute("SELECT id, filename, set_id FROM images")
    for row in cur.fetchall():
        fid = row['id']
        fname = row['filename']
        sid = row['set_id'] if 'set_id' in row.keys() else None
        # if filename already has prefix default_slug/ skip
        if isinstance(fname, str) and fname.startswith(default_slug + '/'):
            # ensure set_id is default
            if sid != default_id:
                cur.execute('UPDATE images SET set_id = ? WHERE id = ?', (default_id, fid))
                updated.append(fid)
            continue
        # If filename contains a slash (other set), skip
        if isinstance(fname, str) and '/' in fname:
            # try to set set_id based on slug
            slug = fname.split('/', 1)[0]
            cur.execute('SELECT id FROM sets WHERE slug = ?', (slug,))
            srow = cur.fetchone()
            if srow and sid != srow['id']:
                cur.execute('UPDATE images SET set_id = ? WHERE id = ?', (srow['id'], fid))
                updated.append(fid)
            continue
        # Bare filename: look for file in uploads root or subfolders
        src_paths = [UPLOAD_FOLDER / fname, UPLOAD_FOLDER / fname.lower()]
        found = None
        for p in src_paths:
            if p.exists():
                found = p
                break
        if not found:
            # maybe already in a subfolder but DB doesn't say so - try search
            for root, dirs, files in os.walk(UPLOAD_FOLDER):
                if fname in files:
                    found = Path(root) / fname
                    break
        if not found:
            missing.append(fname)
            continue
        # ensure default folder exists
        dest_folder = UPLOAD_FOLDER / default_slug
        dest_folder.mkdir(parents=True, exist_ok=True)
        dest = dest_folder / found.name
        # avoid overwrite
        if dest.exists():
            # skip move, but update DB to point to default slug
            cur.execute('UPDATE images SET filename = ?, set_id = ? WHERE id = ?', (f"{default_slug}/{dest.name}", default_id, fid))
            updated.append(fid)
            moved.append(str(found) + ' -> ' + str(dest) + ' (skipped move)')
            continue
        try:
            found.rename(dest)
            cur.execute('UPDATE images SET filename = ?, set_id = ? WHERE id = ?', (f"{default_slug}/{dest.name}", default_id, fid))
            conn.commit()
            moved.append(str(found) + ' -> ' + str(dest))
            updated.append(fid)
        except Exception as e:
            missing.append(f"{fname} (move failed: {e})")

    conn.close()
    return jsonify({'moved': moved, 'updated_ids': updated, 'missing': missing})


@app.post('/api/sets')
def api_create_set():
    data = request.get_json(force=True)
    name = (data.get('name') or '').strip()
    if not name:
        return ('Missing name', 400)
    slug = slugify(name)
    now = datetime.utcnow().isoformat()
    conn = get_db()
    cur = conn.cursor()
    try:
        cur.execute('INSERT INTO sets (name, slug, created_at) VALUES (?, ?, ?)', (name, slug, now))
        conn.commit()
        set_id = cur.lastrowid
        # create uploads subfolder
        (UPLOAD_FOLDER / slug).mkdir(parents=True, exist_ok=True)
        conn.close()
        return jsonify({'id': set_id, 'name': name, 'slug': slug})
    except sqlite3.IntegrityError:
        conn.close()
        return ('Set already exists', 400)


@app.post('/api/sets/<int:set_id>/rename')
def api_rename_set(set_id):
    # Be tolerant about incoming data: prefer JSON, but fall back to form or raw body
    data = {}
    try:
        data = request.get_json(silent=True) or {}
    except Exception:
        data = {}
    # fallback to form fields if no JSON
    if not data:
        data = request.form.to_dict() or {}
    # last resort: try parsing raw body as urlencoded or JSON
    if not data and request.data:
        raw = request.get_data(as_text=True).strip()
        if raw:
            # try urlencoded like name=Foo
            try:
                from urllib.parse import parse_qs
                parsed = parse_qs(raw)
                if 'name' in parsed:
                    data['name'] = parsed.get('name', [''])[0]
                else:
                    # try JSON
                    import json
                    j = json.loads(raw)
                    if isinstance(j, dict):
                        data = j
            except Exception:
                # ignore parse errors
                pass
    new_name = (data.get('name') or '').strip()
    if not new_name:
        return ('Missing name', 400)
    new_slug = slugify(new_name)
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT id, name, slug FROM sets WHERE id = ?', (set_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return ('Set not found', 404)
    old_slug = row['slug']
    try:
        cur.execute('UPDATE sets SET name = ?, slug = ? WHERE id = ?', (new_name, new_slug, set_id))
        conn.commit()
        # move files folder if exists
        old_folder = UPLOAD_FOLDER / old_slug
        new_folder = UPLOAD_FOLDER / new_slug
        if old_folder.exists():
            old_folder.rename(new_folder)
            # update filenames in images table to reflect new slug prefix
            cur.execute('SELECT id, filename FROM images WHERE filename LIKE ? AND set_id = ?', (old_slug + '/%', set_id))
            for r in cur.fetchall():
                fname = Path(r['filename']).name
                cur.execute('UPDATE images SET filename = ? WHERE id = ?', (f"{new_slug}/{fname}", r['id']))
            conn.commit()
        conn.close()
        return jsonify({'id': set_id, 'name': new_name, 'slug': new_slug})
    except sqlite3.IntegrityError:
        conn.close()
        return ('Name or slug already in use', 400)


@app.post('/api/sets/<int:set_id>/delete')
def api_delete_set(set_id):
    conn = get_db()
    cur = conn.cursor()
    cur.execute('SELECT id, name, slug FROM sets WHERE id = ?', (set_id,))
    row = cur.fetchone()
    if not row:
        conn.close()
        return ('Set not found', 404)
    if row['slug'] == 'default':
        conn.close()
        return ('Cannot delete default set', 400)
    slug = row['slug']
    # delete images and ratings for images in this set
    cur.execute('SELECT id FROM images WHERE set_id = ?', (set_id,))
    ids = [r['id'] for r in cur.fetchall()]
    if ids:
        qmarks = ','.join('?' for _ in ids)
        cur.execute(f'DELETE FROM ratings WHERE image_id IN ({qmarks})', ids)
    cur.execute('DELETE FROM images WHERE set_id = ?', (set_id,))
    cur.execute('DELETE FROM sets WHERE id = ?', (set_id,))
    conn.commit()
    conn.close()
    # remove files folder
    folder = UPLOAD_FOLDER / slug
    if folder.exists() and folder.is_dir():
        for root, dirs, files in os.walk(folder, topdown=False):
            for fn in files:
                try:
                    os.remove(Path(root) / fn)
                except Exception:
                    pass
            for d in dirs:
                try:
                    os.rmdir(Path(root) / d)
                except Exception:
                    pass
        try:
            os.rmdir(folder)
        except Exception:
            pass
    return jsonify({'status': 'ok'})

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
        CREATE TABLE IF NOT EXISTS sets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            slug TEXT NOT NULL UNIQUE,
            created_at TEXT NOT NULL
        );
        '''
    )
    # Add hidden column if missing
    try:
        cur.execute('ALTER TABLE images ADD COLUMN hidden INTEGER NOT NULL DEFAULT 0')
    except sqlite3.OperationalError:
        pass
    # Add set_id column and ensure default set exists
    try:
        # Ensure a default set exists
        cur.execute("SELECT id FROM sets WHERE name = 'Default'")
        row = cur.fetchone()
        if not row:
            now = datetime.utcnow().isoformat()
            cur.execute('INSERT INTO sets (name, slug, created_at) VALUES (?, ?, ?)', ('Default', 'default', now))
            default_set_id = cur.lastrowid
        else:
            default_set_id = row[0]
        cur.execute('ALTER TABLE images ADD COLUMN set_id INTEGER NOT NULL DEFAULT %s' % (default_set_id,))
    except sqlite3.OperationalError:
        # column probably already exists
        pass
    # If old images exist with NULL/0 set_id, set them to default
    try:
        cur.execute("SELECT id FROM sets WHERE slug = 'default'")
        default_row = cur.fetchone()
        if default_row:
            default_set_id = default_row[0]
            cur.execute('UPDATE images SET set_id = ? WHERE set_id IS NULL OR set_id = 0', (default_set_id,))
    except Exception:
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
    # Optionally, remove files from uploads folder (handle subfolders)
    for root, dirs, files in os.walk(UPLOAD_FOLDER):
        for fn in files:
            try:
                os.remove(Path(root) / fn)
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
    # optional set parameter (form field or query string)
    set_param = request.form.get('set') or request.args.get('set')
    conn = get_db()
    cur = conn.cursor()
    set_id = None
    set_slug = 'default'
    if set_param:
        if set_param.isdigit():
            cur.execute('SELECT id, slug FROM sets WHERE id = ?', (int(set_param),))
            r = cur.fetchone()
            if r:
                set_id = r['id']; set_slug = r['slug']
        else:
            cur.execute('SELECT id, slug FROM sets WHERE slug = ?', (set_param,))
            r = cur.fetchone()
            if r:
                set_id = r['id']; set_slug = r['slug']
    if not set_id:
        cur.execute("SELECT id, slug FROM sets WHERE slug = 'default'")
        r = cur.fetchone()
        if r:
            set_id = r['id']; set_slug = r['slug']
    saved = []
    for f in files:
        if not f.filename:
            continue
        if not allowed_file(f.filename):
            return ('Unsupported file type', 400)
        fname = secure_filename(f.filename)
        # ensure set folder exists
        folder = UPLOAD_FOLDER / set_slug
        folder.mkdir(parents=True, exist_ok=True)
        dest = folder / fname
        # Prevent overwrite by appending timestamp if exists
        if dest.exists():
            stem, ext = os.path.splitext(fname)
            fname = f"{stem}_{int(datetime.now().timestamp())}{ext}"
            dest = folder / fname
        f.save(dest)
        # store filename with set prefix
        stored_name = f"{set_slug}/{fname}"
        now = datetime.utcnow().isoformat()
        cur.execute('INSERT INTO images (filename, created_at, set_id) VALUES (?, ?, ?)', (stored_name, now, set_id))
        conn.commit()
        saved.append(stored_name)
    conn.close()
    return jsonify({'saved': saved})

@app.get('/uploads/<path:filename>')
def uploaded_file(filename):
    # prevent directory traversal
    p = Path(filename)
    if '..' in p.parts:
        return ('Invalid filename', 400)
    full = UPLOAD_FOLDER / filename
    if full.exists():
        return send_from_directory(str(full.parent), full.name, as_attachment=False)
    # fallback: search by basename
    target = Path(filename).name
    for root, dirs, files in os.walk(UPLOAD_FOLDER):
        if target in files:
            return send_from_directory(root, target, as_attachment=False)
    return ('Not found', 404)

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
    # include set info if provided by query
    if 'set_name' in row.keys():
        d['set_name'] = row['set_name']
    if 'set_slug' in row.keys():
        d['set_slug'] = row['set_slug']
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
                   COUNT(r.id) AS rating_count,
                   s.name AS set_name, s.slug AS set_slug
            FROM images i
            LEFT JOIN ratings r ON r.image_id = i.id
            LEFT JOIN sets s ON s.id = i.set_id
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
                   COUNT(r.id) AS rating_count,
                   s.name AS set_name, s.slug AS set_slug
            FROM images i
            LEFT JOIN ratings r ON r.image_id = i.id
            LEFT JOIN sets s ON s.id = i.set_id
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
               COUNT(r.id) AS rating_count,
               s.name AS set_name, s.slug AS set_slug
        FROM images i
        LEFT JOIN ratings r ON r.image_id = i.id
        LEFT JOIN sets s ON s.id = i.set_id
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
