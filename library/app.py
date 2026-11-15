import os
import re
import uuid
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, request, render_template, url_for, session, flash, redirect, send_file, jsonify, Response # type: ignore
from werkzeug.utils import secure_filename # type: ignore
import bcrypt # type: ignore
import PyPDF2 # type: ignore
import razorpay # type: ignore
from itsdangerous import URLSafeTimedSerializer, SignatureExpired # type: ignore

from otp import genotp
from cmail import send_mail
from stoken import endata, dedata

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOADS_DIR = os.path.join(BASE_DIR, 'static', 'uploads')
IMAGES_DIR = os.path.join(BASE_DIR, 'static', 'images')
IMEGES_DIR = os.path.join(BASE_DIR, 'static', 'imeges')
SQLITE_DB_PATH = os.path.join(BASE_DIR, 'library.db')

os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(IMAGES_DIR, exist_ok=True)
os.makedirs(IMEGES_DIR, exist_ok=True)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "gif", "webp", "pdf", "avif"}
MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16 MB

# ---------------- Database Abstraction Layer ----------------
DB_TYPE = os.environ.get('DB_TYPE', 'sqlite').lower()

class SQLiteCursorWrapper:
    def __init__(self, cursor):
        self._cursor = cursor

    def execute(self, sql, params=None):
        # Convert %s placeholders to ? for SQLite
        if params is not None:
            formatted_sql = sql.replace('%s', '?')
            if isinstance(params, list):
                params = tuple(params)
            return self._cursor.execute(formatted_sql, params)
        return self._cursor.execute(sql)

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def close(self):
        try:
            self._cursor.close()
        except Exception:
            pass

class SQLiteConnectionWrapper:
    def __init__(self, db_path):
        self.db_path = db_path
        self._conn = None
        self._connect()

    def _connect(self):
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.create_function("uuid_to_bin", 1, lambda x: str(x) if x is not None else None)
        self._conn.create_function("bin_to_uuid", 1, lambda x: str(x) if x is not None else None)
        self._conn.create_function("uuid", 0, lambda: str(uuid.uuid4()))

    def cursor(self, buffered=True):
        try:
            return SQLiteCursorWrapper(self._conn.cursor())
        except Exception:
            self._connect()
            return SQLiteCursorWrapper(self._conn.cursor())

    def commit(self):
        self._conn.commit()

    def rollback(self):
        self._conn.rollback()

    def close(self):
        self._conn.close()

    def is_connected(self):
        return self._conn is not None

def init_sqlite_schema(conn):
    c = conn.cursor()
    c.execute('''
    CREATE TABLE IF NOT EXISTS admin (
        admin_id INTEGER PRIMARY KEY AUTOINCREMENT,
        adminname TEXT NOT NULL,
        phone_no TEXT UNIQUE,
        email TEXT UNIQUE NOT NULL,
        password TEXT,
        profile_img TEXT
    );
    ''')
    c.execute('''
    CREATE TABLE IF NOT EXISTS user (
        user_id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT NOT NULL,
        phone_no TEXT UNIQUE,
        email TEXT UNIQUE NOT NULL,
        password TEXT,
        agreed TEXT DEFAULT 'on',
        address TEXT,
        profile_img TEXT
    );
    ''')
    c.execute('''
    CREATE TABLE IF NOT EXISTS books (
        book_id TEXT PRIMARY KEY,
        book_name TEXT NOT NULL,
        price REAL DEFAULT 0,
        quantity INTEGER DEFAULT 0,
        category TEXT,
        description TEXT,
        book_image TEXT,
        added_by INTEGER,
        added_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        pdf_path TEXT
    );
    ''')
    c.execute('''
    CREATE TABLE IF NOT EXISTS pdf_files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        title TEXT,
        filepath TEXT
    );
    ''')
    c.execute('''
    CREATE TABLE IF NOT EXISTS reading_report (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        minutes INTEGER,
        seconds INTEGER,
        rent INTEGER,
        notes TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    ''')
    c.execute('''
    CREATE TABLE IF NOT EXISTS wishlist (
        wishlist_id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        book_id TEXT NOT NULL,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );
    ''')
    conn.commit()

# Database Connection Handler
active_db = None

def get_db():
    global active_db, DB_TYPE

    # Check if MySQL was explicitly requested or fallback to SQLite
    if DB_TYPE == 'mysql':
        try:
            from mysql.connector import connection
            if active_db is None or not getattr(active_db, 'is_connected', lambda: False)():
                active_db = connection.MySQLConnection(
                    user=os.environ.get('DB_USER', 'root'),
                    password=os.environ.get('DB_PASSWORD', 'anusha'),
                    host=os.environ.get('DB_HOST', 'localhost'),
                    port=int(os.environ.get('DB_PORT', 3306)),
                    database=os.environ.get('DB_NAME', 'librarydb')
                )
            return active_db
        except Exception as e:
            print(f"MySQL unavailable ({e}). Falling back automatically to SQLite.")
            DB_TYPE = 'sqlite'

    # SQLite Mode (Zero config, local & reliable)
    if active_db is None or not isinstance(active_db, SQLiteConnectionWrapper):
        active_db = SQLiteConnectionWrapper(SQLITE_DB_PATH)
        init_sqlite_schema(active_db)
    return active_db

# Initialize database at startup
try:
    db = get_db()
    print(f"[*] Database initialized successfully using: {DB_TYPE.upper()}")
except Exception as e:
    print(f"[!] Warning: Database initialization error: {e}")

# Razorpay client initialization
RAZORPAY_KEY_ID = os.environ.get('RAZORPAY_KEY_ID', "rzp_test_RhD85xqgyfh89M")
RAZORPAY_KEY_SECRET = os.environ.get('RAZORPAY_KEY_SECRET', "5f5C7wbx2A8Ms58ew8uNDTMl")
try:
    client = razorpay.Client(auth=(RAZORPAY_KEY_ID, RAZORPAY_KEY_SECRET))
except Exception as e:
    client = None
    print(f"Razorpay Client init warning: {e}")

app = Flask(__name__)
app.config['SESSION_TYPE'] = 'filesystem'
app.config['UPLOAD_FOLDER'] = UPLOADS_DIR
app.config['MAX_CONTENT_LENGTH'] = MAX_CONTENT_LENGTH
app.secret_key = os.environ.get('SECRET_KEY', b'a6*\xf9\xf6\x91\xb2\xc3\xd4')


# ---------------- Entry Routes ----------------
@app.route('/')
def index():
    return render_template('welcome.html')

@app.route('/welcome')
def welcome():
    return render_template('index.html')

@app.route('/homepage')
def homepage():
    db = get_db()
    cursor = db.cursor(buffered=True)
    user_email = session.get('user') or session.get('userdata')
    profile = None
    if user_email:
        cursor.execute('SELECT username, profile_img FROM user WHERE email = %s', [user_email])
        profile = cursor.fetchone()

    # Total Books
    cursor.execute("SELECT COUNT(*) FROM books")
    total_books_row = cursor.fetchone()
    total_books = total_books_row[0] if total_books_row else 0

    # Total Categories
    cursor.execute('SELECT COUNT(DISTINCT category) AS total_category FROM books')
    total_category_row = cursor.fetchone()
    total_category = total_category_row[0] if total_category_row else 0

    cursor.close()
    return render_template('homepage.html', profile=profile, total_books=total_books, total_category=total_category)


# ---------------- User Authentication ----------------
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == "POST":
        username = request.form['username']
        useremail = request.form['email']
        password = request.form['password']
        agree = request.form.get('agree', 'on')

        db = get_db()
        cursor = db.cursor(buffered=True)
        cursor.execute('SELECT count(*) FROM user WHERE email = %s', [useremail])
        count_useremail = cursor.fetchone()
        cursor.close()

        if count_useremail and count_useremail[0] == 0:
            gotp = genotp()
            userdata = {'username': username, 'useremail': useremail, 'password': password, 'agree': agree, 'otp': gotp}
            subject = 'OTP for E-Library Management System'
            body = f"Hello {username},\n\nYour OTP code is: {gotp}\n\nThank you!"
            try:
                send_mail(to=useremail, subject=subject, body=body)
                flash(f'OTP has been sent to given mail: {useremail}')
            except Exception as e:
                print(f"Email error: {e}")
                flash(f'Notice: OTP generated: {gotp}')
            return redirect(url_for('otpverify', udata=endata(data=userdata)))
        else:
            flash('Email already registered. Please log in.')
            return redirect(url_for('userlogin'))

    return render_template('user_register.html')

@app.route('/otpverify/<udata>', methods=['GET', 'POST'])
def otpverify(udata):
    if request.method == 'POST':
        user_otp = request.form['otp']
        try:
            de_userdata = dedata(data=udata)
        except Exception:
            flash('Invalid or expired OTP session. Please register again.')
            return redirect(url_for('register'))

        if de_userdata.get('otp') == user_otp:
            db = get_db()
            cursor = db.cursor(buffered=True)
            cursor.execute('INSERT INTO user (username, email, password, agreed) VALUES (%s, %s, %s, %s)',
                           [de_userdata['username'], de_userdata['useremail'], de_userdata['password'], de_userdata.get('agree', 'on')])
            db.commit()
            cursor.close()
            flash(f'Successfully registered! Please login, {de_userdata["username"]}')
            return redirect(url_for('userlogin'))
        else:
            flash('Wrong OTP, please try again')
            return redirect(url_for('otpverify', udata=udata))

    return render_template('otp.html')

@app.route('/userlogin', methods=['GET', 'POST'])
def userlogin():
    if request.method == "POST":
        login_email = request.form['email']
        login_password = request.form['password']

        db = get_db()
        cursor = db.cursor(buffered=True)
        cursor.execute('SELECT password FROM user WHERE email = %s', [login_email])
        stored_password = cursor.fetchone()
        cursor.close()

        if stored_password:
            stored = stored_password[0]
            pwd_match = False
            try:
                if stored.startswith('$2b$') or stored.startswith('$2a$'):
                    pwd_match = bcrypt.checkpw(login_password.encode('utf-8'), stored.encode('utf-8'))
                else:
                    pwd_match = (stored == login_password)
            except Exception:
                pwd_match = (stored == login_password)

            if pwd_match:
                session['user'] = login_email
                return redirect(url_for('homepage'))
            else:
                flash('Incorrect password')
                return redirect(url_for('userlogin'))
        else:
            flash('Email not found. Please register first.')
            return redirect(url_for('userlogin'))

    return render_template('user_login.html')

@app.route('/userlogout')
def userlogout():
    session.pop('user', None)
    return redirect(url_for('homepage'))

@app.route('/fgtpwd', methods=['GET', 'POST'])
def fgtpwd():
    if request.method == 'POST':
        useremail = request.form['email']
        db = get_db()
        cursor = db.cursor(buffered=True)
        cursor.execute('SELECT count(*) FROM user WHERE email = %s', [useremail])
        count_email = cursor.fetchone()
        cursor.close()

        if count_email and count_email[0] == 1:
            subject = 'Reset link for password E-Library Management System'
            reset_url = url_for('confirmpwd', udata=endata(data=useremail), _external=True)
            body = f"Use the given reset link for password update: {reset_url}"
            try:
                send_mail(to=useremail, subject=subject, body=body)
                flash(f'Reset link has been sent to {useremail}')
            except Exception as e:
                print(f"Mail error: {e}")
                flash(f'Reset link: {reset_url}')
            return redirect(url_for('fgtpwd'))
        else:
            flash('User email not found. Please register.')
            return redirect(url_for('register'))

    return render_template('forgotpassword.html')

@app.route('/confirmpwd/<udata>', methods=['GET', 'POST', 'PUT'])
def confirmpwd(udata):
    if request.method in ['PUT', 'POST']:
        npwd = None
        if request.is_json:
            npwd = request.get_json().get('password')
        else:
            npwd = request.form.get('password')

        if not npwd:
            flash('Password cannot be empty')
            return redirect(url_for('confirmpwd', udata=udata))

        try:
            de_udata = dedata(udata)
            db = get_db()
            cursor = db.cursor(buffered=True)
            cursor.execute('UPDATE user SET password = %s WHERE email = %s', [npwd, de_udata])
            db.commit()
            cursor.close()
            flash('New password updated successfully!')
            return redirect(url_for('userlogin')) if request.method == 'POST' else 'ok'
        except Exception as e:
            print(f"Error resetting password: {e}")
            flash('Could not update password')
            return redirect(url_for('fgtpwd'))

    return render_template('npassword.html', udata=udata)

@app.route('/userprofile', methods=['GET', 'POST'])
def userprofile():
    if not session.get('user'):
        flash('Please login to view profile')
        return redirect(url_for('userlogin'))

    db = get_db()
    cursor = db.cursor(buffered=True)
    cursor.execute('SELECT username, profile_img, email, address, phone_no FROM user WHERE email = %s', [session.get('user')])
    profile = cursor.fetchone()
    cursor.close()
    return render_template('user_profile.html', profile=profile)

@app.route('/userprofileupdate', methods=['GET', 'POST'])
def userprofileupdate():
    if not session.get('user'):
        flash('To update user profile please login')
        return redirect(url_for('userlogin'))

    db = get_db()
    cursor = db.cursor(buffered=True)

    if request.method == 'POST':
        try:
            cursor.execute('SELECT * FROM user WHERE email = %s', [session.get('user')])
            stored_data = cursor.fetchone()

            updated_username = request.form['username']
            updated_address = request.form.get('address', '')
            updated_phoneno = request.form.get('phone', '')
            updated_profilepic = request.files.get('file')

            display_img = stored_data[7] if stored_data else None

            if updated_profilepic and updated_profilepic.filename != '':
                ext = updated_profilepic.filename.rsplit('.', 1)[-1].lower()
                display_img = genotp() + '.' + ext

                for folder in [IMAGES_DIR, IMEGES_DIR, UPLOADS_DIR]:
                    dest_file = os.path.join(folder, display_img)
                    updated_profilepic.seek(0)
                    updated_profilepic.save(dest_file)

                if stored_data and stored_data[7]:
                    for folder in [IMAGES_DIR, IMEGES_DIR]:
                        old_img = os.path.join(folder, stored_data[7])
                        if os.path.exists(old_img):
                            try:
                                os.remove(old_img)
                            except Exception:
                                pass

            cursor.execute(
                'UPDATE user SET username = %s, phone_no = %s, address = %s, profile_img = %s WHERE email = %s',
                [updated_username, updated_phoneno, updated_address, display_img, session.get('user')]
            )
            db.commit()
            flash('Profile updated successfully')
            return redirect(url_for('userprofileupdate'))
        except Exception as e:
            print(f"Error updating user profile: {e}")
            flash('Could not update user details')
            return redirect(url_for('homepage'))
        finally:
            cursor.close()

    cursor.execute('SELECT * FROM user WHERE email = %s', [session.get('user')])
    stored_data = cursor.fetchone()
    cursor.execute('SELECT username, profile_img FROM user WHERE email = %s', [session.get('user')])
    profile = cursor.fetchone()
    cursor.close()

    return render_template('user_update.html', stored_data=stored_data, profile=profile)


# ---------------- Reader & PDF Routes ----------------
@app.route("/read_item/<bookid>")
def read_item(bookid):
    if not session.get('user'):
        flash('Please login to read books')
        return redirect(url_for('userlogin'))

    db = get_db()
    cursor = db.cursor(buffered=True)
    cursor.execute('SELECT username, profile_img FROM user WHERE email = %s', [session.get('user')])
    profile = cursor.fetchone()

    cursor.execute("SELECT pdf_path, book_name FROM books WHERE book_id = UUID_TO_BIN(%s)", (bookid,))
    item = cursor.fetchone()
    cursor.close()

    if not item:
        return "Book not found", 404

    return render_template("reader.html", bookid=bookid, book_title=item[1], profile=profile, rent=2)

@app.route("/pdfview/<bookid>")
def pdfview(bookid):
    db = get_db()
    cursor = db.cursor(buffered=True)
    cursor.execute("SELECT pdf_path FROM books WHERE book_id = UUID_TO_BIN(%s)", (bookid,))
    item = cursor.fetchone()
    cursor.close()

    if not item or not item[0]:
        return "Book PDF not found", 404

    pdf_filename = item[0]
    pdf_full_path = os.path.join(UPLOADS_DIR, pdf_filename)
    if not os.path.exists(pdf_full_path):
        return "PDF file not found on disk", 404

    return send_file(pdf_full_path, mimetype="application/pdf", as_attachment=False)

@app.route('/save_reading_report', methods=['POST'])
def save_reading_report():
    try:
        data = request.get_json(silent=True) or request.form
        minutes = int(data.get('minutes', 0))
        seconds = int(data.get('seconds', 0))
        rent = int(data.get('rent', 0))
        notes = data.get('notes', '')

        db = get_db()
        cursor = db.cursor(buffered=True)
        cursor.execute(
            "INSERT INTO reading_report (minutes, seconds, rent, notes) VALUES (%s, %s, %s, %s)",
            (minutes, seconds, rent, notes)
        )
        db.commit()
        cursor.close()
        return jsonify({'status': 'success', 'message': 'Report saved successfully'})
    except Exception as e:
        print(f"Error saving reading report: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


# ---------------- Book Browsing & Search ----------------
@app.route('/mybooks', methods=['GET', 'POST'])
def mybooks():
    if not session.get('user'):
        flash('Please login to access mybooks')
        return redirect(url_for('userlogin'))

    db = get_db()
    cursor = db.cursor(buffered=True)
    cursor.execute('SELECT username, profile_img FROM user WHERE email = %s', [session.get('user')])
    profile = cursor.fetchone()

    cursor.execute('SELECT BIN_TO_UUID(book_id), book_name, price, quantity, category, description, book_image FROM books')
    booksdata = cursor.fetchall()
    cursor.close()

    return render_template('mybooks.html', booksdata=booksdata, profile=profile)

@app.route('/category/<ctype>')
def category(ctype):
    if not session.get('user'):
        flash('Please login to view categories')
        return redirect(url_for('userlogin'))

    db = get_db()
    cursor = db.cursor(buffered=True)
    cursor.execute('SELECT username, profile_img FROM user WHERE email = %s', [session.get('user')])
    profile = cursor.fetchone()

    cursor.execute('SELECT BIN_TO_UUID(book_id), book_name, price, quantity, category, description, book_image FROM books WHERE category = %s', (ctype,))
    category_data = cursor.fetchall()
    cursor.close()

    return render_template('category.html', category_data=category_data, profile=profile)

@app.route('/user_search', methods=['GET', 'POST'])
def user_search():
    if not session.get('user'):
        flash('Please login to search books')
        return redirect(url_for('userlogin'))

    db = get_db()
    cursor = db.cursor(buffered=True)
    cursor.execute('SELECT username, profile_img FROM user WHERE email = %s', [session.get('user')])
    profile = cursor.fetchone()

    category_data = []
    if request.method == 'POST':
        sdata = request.form.get('search', '').strip()
        if sdata:
            search_param = '%' + sdata + '%'
            cursor.execute(
                '''SELECT BIN_TO_UUID(book_id), book_name, price, quantity, category, description, book_image 
                   FROM books 
                   WHERE book_name LIKE %s OR price LIKE %s OR description LIKE %s OR quantity LIKE %s OR category LIKE %s''',
                [search_param, search_param, search_param, search_param, search_param]
            )
            category_data = cursor.fetchall()
        else:
            flash('No search query provided')
            cursor.close()
            return redirect(url_for('homepage'))

    cursor.close()
    return render_template('category.html', category_data=category_data, profile=profile)

@app.route('/authors')
def authors():
    if not session.get('user'):
        flash('Please login to view authors')
        return redirect(url_for('userlogin'))

    db = get_db()
    cursor = db.cursor(buffered=True)
    cursor.execute('SELECT username, profile_img FROM user WHERE email = %s', [session.get('user')])
    profile = cursor.fetchone()
    cursor.close()
    return render_template('author.html', profile=profile)

@app.route('/popular')
def popular_books():
    if not session.get('user'):
        flash('Please login to view popular books')
        return redirect(url_for('userlogin'))

    db = get_db()
    cursor = db.cursor(buffered=True)
    cursor.execute('SELECT username, profile_img FROM user WHERE email = %s', [session.get('user')])
    profile = cursor.fetchone()
    cursor.close()
    return render_template('popularbooks.html', profile=profile)

@app.route('/desc_item/<bookid>')
def desc_item(bookid):
    if not session.get('user'):
        flash('Please login to view book details')
        return redirect(url_for('userlogin'))

    db = get_db()
    cursor = db.cursor(buffered=True)
    cursor.execute(
        'SELECT BIN_TO_UUID(book_id), book_name, description, price, quantity, category, book_image, added_at FROM books WHERE book_id = UUID_TO_BIN(%s)',
        [bookid]
    )
    storeditem_data = cursor.fetchone()
    cursor.close()

    if not storeditem_data:
        flash('Book not found')
        return redirect(url_for('homepage'))

    return render_template('desc.html', storeditem_data=storeditem_data)

@app.route('/available')
def available():
    if not session.get('user'):
        flash('Please login first')
        return redirect(url_for('userlogin'))

    db = get_db()
    cursor = db.cursor(buffered=True)
    cursor.execute('SELECT BIN_TO_UUID(book_id), book_name, price, added_at, book_image FROM books ORDER BY added_at DESC')
    stored_booksdata = cursor.fetchall()
    cursor.close()

    return render_template('available.html', ndata=stored_booksdata)


# ---------------- Admin Management ----------------
@app.route('/adminlogin', methods=['GET', 'POST'])
def adminlogin():
    if request.method == 'POST':
        login_email = request.form['email']
        login_password = request.form['password']

        db = get_db()
        cursor = db.cursor(buffered=True)
        cursor.execute('SELECT password FROM admin WHERE email = %s', [login_email])
        stored_password = cursor.fetchone()
        cursor.close()

        if stored_password:
            stored = stored_password[0]
            pwd_match = False
            try:
                if stored.startswith('$2b$') or stored.startswith('$2a$'):
                    pwd_match = bcrypt.checkpw(login_password.encode('utf-8'), stored.encode('utf-8'))
                else:
                    pwd_match = (stored == login_password)
            except Exception:
                pwd_match = (stored == login_password)

            if pwd_match:
                session['admin'] = login_email
                return redirect(url_for('adminpanel'))
            else:
                flash('Password was incorrect')
                return redirect(url_for('adminlogin'))
        else:
            flash('Admin email not found')
            return redirect(url_for('adminlogin'))

    return render_template('adminlogin.html')

@app.route('/adminregister', methods=['GET', 'POST'])
def adminregister():
    if request.method == 'POST':
        adminname = request.form['username']
        adminemail = request.form['email']
        adminpassword = request.form['password']
        adminagree = request.form.get('agree', 'on')

        db = get_db()
        cursor = db.cursor(buffered=True)
        cursor.execute('SELECT count(email) FROM admin WHERE email = %s', [adminemail])
        count_email = cursor.fetchone()
        cursor.close()

        if count_email and count_email[0] == 0:
            gotp = genotp()
            admindata = {
                'adminname': adminname,
                'adminemail': adminemail,
                'adminpassword': adminpassword,
                'adminagree': adminagree,
                'adminotp': gotp
            }
            subject = 'OTP for Admin Registration - E-Library'
            body = f'OTP for Admin registration: {gotp}'
            try:
                send_mail(to=adminemail, subject=subject, body=body)
                flash(f'OTP sent to {adminemail}')
            except Exception as e:
                print(f"Mail error: {e}")
                flash(f'Admin OTP: {gotp}')
            return redirect(url_for('adminotpverify', enadmin=endata(data=admindata)))
        else:
            flash('Admin email already exists. Please login.')
            return redirect(url_for('adminlogin'))

    return render_template('adminregister.html')

@app.route('/adminotpverify/<enadmin>', methods=['GET', 'POST'])
def adminotpverify(enadmin):
    try:
        deadmin = dedata(enadmin)
    except SignatureExpired:
        flash('OTP session has expired. Please register again.')
        return redirect(url_for('adminregister'))
    except Exception as e:
        flash('Could not verify OTP token.')
        return redirect(url_for('adminregister'))

    if request.method == 'POST':
        given_otp = request.form['otp']
        if given_otp == deadmin['adminotp']:
            try:
                hash_pwd = bcrypt.hashpw(deadmin['adminpassword'].encode('utf-8'), bcrypt.gensalt()).decode('utf-8')
                db = get_db()
                cursor = db.cursor(buffered=True)
                cursor.execute(
                    'INSERT INTO admin (adminname, email, password) VALUES (%s, %s, %s)',
                    [deadmin['adminname'], deadmin['adminemail'], hash_pwd]
                )
                db.commit()
                cursor.close()
                flash('Admin account created successfully! Please login.')
                return redirect(url_for('adminlogin'))
            except Exception as e:
                print(f"Error storing admin: {e}")
                flash('Could not store admin details.')
                return redirect(url_for('adminregister'))
        else:
            flash('Wrong OTP, please try again')

    return render_template('adminotp.html')

@app.route('/adminpanel')
def adminpanel():
    if not session.get('admin'):
        flash('Please login as admin first')
        return redirect(url_for('adminlogin'))

    db = get_db()
    cursor = db.cursor(buffered=True)
    cursor.execute('SELECT adminname, profile_img FROM admin WHERE email = %s', [session.get('admin')])
    adminpro = cursor.fetchone()

    cursor.execute("SELECT COUNT(*) FROM books")
    total_books_row = cursor.fetchone()
    total_books = total_books_row[0] if total_books_row else 0

    cursor.execute('SELECT COUNT(DISTINCT category) AS total_category FROM books')
    total_category_row = cursor.fetchone()
    total_category = total_category_row[0] if total_category_row else 0

    cursor.close()
    return render_template('adminpanel.html', adminpro=adminpro, total_books=total_books, total_category=total_category)

@app.route('/adminprofile', methods=['GET', 'POST'])
def adminprofile():
    if not session.get('admin'):
        flash('Please login as admin first')
        return redirect(url_for('adminlogin'))

    db = get_db()
    cursor = db.cursor(buffered=True)
    cursor.execute('SELECT adminname, profile_img, email, phone_no FROM admin WHERE email = %s', [session.get('admin')])
    adminpro = cursor.fetchone()
    cursor.close()

    return render_template('adminprofile.html', profile=adminpro)

@app.route('/adminprofileupdate', methods=['GET', 'POST'])
def adminprofileupdate():
    if not session.get('admin'):
        flash('Please login as admin first')
        return redirect(url_for('adminlogin'))

    db = get_db()
    cursor = db.cursor(buffered=True)

    if request.method == 'POST':
        try:
            adminname = request.form['adminname']
            phone = request.form.get('phone', '')
            file = request.files.get('file')

            cursor.execute('SELECT profile_img FROM admin WHERE email = %s', [session.get('admin')])
            curr = cursor.fetchone()
            display_img = curr[0] if curr else None

            if file and file.filename != '':
                ext = file.filename.rsplit('.', 1)[-1].lower()
                display_img = genotp() + '.' + ext

                for folder in [UPLOADS_DIR, IMAGES_DIR, IMEGES_DIR]:
                    dest = os.path.join(folder, display_img)
                    file.seek(0)
                    file.save(dest)

            cursor.execute(
                'UPDATE admin SET adminname = %s, phone_no = %s, profile_img = %s WHERE email = %s',
                [adminname, phone, display_img, session.get('admin')]
            )
            db.commit()
            flash('Admin profile updated successfully!', 'success')
            return redirect(url_for('adminprofile'))
        except Exception as e:
            print(f"Error updating admin: {e}")
            flash('Could not update admin profile', 'danger')
        finally:
            cursor.close()

    cursor.execute('SELECT adminname, phone_no, profile_img FROM admin WHERE email = %s', [session.get('admin')])
    stored_data = cursor.fetchone()
    cursor.close()

    return render_template('adminupdate.html', stored_data=stored_data)

@app.route('/addbook', methods=['GET', 'POST'])
def addbook():
    if not session.get('admin'):
        flash('Please login as admin to add books')
        return redirect(url_for('adminlogin'))

    db = get_db()
    cursor = db.cursor(buffered=True)
    cursor.execute('SELECT adminname, profile_img FROM admin WHERE email = %s', [session.get('admin')])
    adminpro = cursor.fetchone()

    if request.method == 'POST':
        book_name = request.form['book_name']
        book_price = request.form['price']
        book_quantity = request.form['quantity']
        book_category = request.form['category']
        book_description = request.form['description']

        book_imagedata = request.files.get('file')
        pdf_path = request.files.get('pdf')

        img_name = None
        pdf_name = None

        if book_imagedata and book_imagedata.filename:
            img_name = genotp() + '.' + book_imagedata.filename.rsplit('.', 1)[-1].lower()
            book_imagedata.save(os.path.join(UPLOADS_DIR, img_name))

        if pdf_path and pdf_path.filename:
            pdf_name = genotp() + '.' + pdf_path.filename.rsplit('.', 1)[-1].lower()
            pdf_full_path = os.path.join(UPLOADS_DIR, pdf_name)
            pdf_path.save(pdf_full_path)

            # Insert into pdf_files table
            cursor.execute('INSERT INTO pdf_files (title, filepath) VALUES (%s, %s)', [book_name, pdf_name])

        cursor.execute('SELECT admin_id FROM admin WHERE email = %s', [session.get('admin')])
        adminid_row = cursor.fetchone()

        if adminid_row:
            admin_id = adminid_row[0]
            cursor.execute(
                '''INSERT INTO books (book_id, book_name, price, quantity, category, description, book_image, pdf_path, added_by) 
                   VALUES (UUID_TO_BIN(UUID()), %s, %s, %s, %s, %s, %s, %s, %s)''',
                [book_name, book_price, book_quantity, book_category, book_description, img_name, pdf_name, admin_id]
            )
            db.commit()
            cursor.close()
            flash('Book details added successfully!')
            return redirect(url_for('addbook'))
        else:
            cursor.close()
            flash('Admin record not found')
            return redirect(url_for('addbook'))

    cursor.close()
    return render_template('addbook.html', adminpro=adminpro)

@app.route('/publisher')
def publisher():
    if not session.get('admin'):
        flash('Please login as admin first')
        return redirect(url_for('adminlogin'))

    db = get_db()
    cursor = db.cursor(buffered=True)
    cursor.execute('SELECT adminname, profile_img FROM admin WHERE email = %s', [session.get('admin')])
    adminpro = cursor.fetchone()
    cursor.close()

    return render_template('bookpublish.html', adminpro=adminpro)

@app.route('/booklist')
def booklist():
    if not session.get('admin'):
        flash('Please login as admin first')
        return redirect(url_for('adminlogin'))

    db = get_db()
    cursor = db.cursor(buffered=True)
    cursor.execute('SELECT adminname, profile_img FROM admin WHERE email = %s', [session.get('admin')])
    adminpro = cursor.fetchone()

    cursor.execute('SELECT admin_id FROM admin WHERE email = %s', [session.get('admin')])
    admin_row = cursor.fetchone()
    stored_booksdata = []

    if admin_row:
        cursor.execute('SELECT BIN_TO_UUID(book_id), book_name, price, added_by, book_image FROM books WHERE added_by = %s', [admin_row[0]])
        stored_booksdata = cursor.fetchall()

    cursor.close()
    return render_template('booklist.html', ndata=stored_booksdata, adminpro=adminpro)

@app.route('/admincategory/<ctype>')
def admincategory(ctype):
    if not session.get('admin'):
        flash('Please login as admin first')
        return redirect(url_for('adminlogin'))

    db = get_db()
    cursor = db.cursor(buffered=True)
    cursor.execute('SELECT adminname, profile_img FROM admin WHERE email = %s', [session.get('admin')])
    adminpro = cursor.fetchone()

    cursor.execute('SELECT BIN_TO_UUID(book_id), book_name, price, quantity, category, description, book_image FROM books WHERE category = %s', (ctype,))
    category_data = cursor.fetchall()
    cursor.close()

    return render_template('admincategory.html', category_data=category_data, adminpro=adminpro)

@app.route('/adminlogout')
def adminlogout():
    session.pop('admin', None)
    return redirect(url_for('homepage'))


# ---------------- Cart, Checkout & Payment ----------------
@app.route('/addcart/<bookid>')
def addcart(bookid):
    if not session.get('user'):
        flash("Please login first", "error")
        return redirect(url_for('userlogin'))

    user = session['user']
    if user not in session or not isinstance(session[user], dict):
        session[user] = {}

    db = get_db()
    cursor = db.cursor(buffered=True)
    cursor.execute(
        """SELECT BIN_TO_UUID(book_id), book_name, description, price, quantity, category, book_image, added_at 
           FROM books WHERE book_id = UUID_TO_BIN(%s)""",
        [bookid]
    )
    book_data = cursor.fetchone()
    cursor.close()

    if not book_data:
        flash("Book not found", "error")
        return redirect(url_for('homepage'))

    cart = session[user]
    if bookid not in cart:
        cart[bookid] = [
            book_data[1],          # Book Name
            float(book_data[3]) if book_data[3] is not None else 0.0,   # Price
            1,                     # Quantity
            book_data[5],          # Category
            book_data[6]           # Book Image
        ]
    else:
        cart[bookid][2] += 1

    session[user] = cart
    session.modified = True
    flash(f"{book_data[1]} added to cart", "success")

    return redirect(url_for('viewcart'))

@app.route('/viewcart')
def viewcart():
    if not session.get('user'):
        flash('Please login first to view your cart')
        return redirect(url_for('userlogin'))

    user = session.get('user')
    if "single_buy" in session:
        session.pop("single_buy")
        session.modified = True

    cart = session.get(user, {})
    books_total = 0.0
    books_for_display = []

    for bookid, data in cart.items():
        name = data[0]
        price = float(data[1]) if data[1] is not None else 0.0
        qty = int(data[2])
        category = data[3] if len(data) > 3 else ""
        img = data[4] if len(data) > 4 else ""

        subtotal = price * qty
        books_total += subtotal

        books_for_display.append({
            'id': bookid,
            'name': name,
            'price': price,
            'qty': qty,
            'subtotal': subtotal,
            'img': img,
            'category': category,
            6: img
        })

    delivery = 40 if books_for_display else 0
    tax = round(books_total * 0.05, 2)
    grand_total = books_total + delivery + tax

    return render_template(
        'cart.html',
        books=books_for_display,
        delivery=delivery,
        tax=tax,
        grand_total=grand_total,
        books_total=books_total
    )

@app.route('/buy_now', methods=['POST'])
def buy_now():
    if not session.get('user'):
        flash('Please login first')
        return redirect(url_for('userlogin'))

    bookid = request.form['bookid']
    db = get_db()
    cursor = db.cursor(buffered=True)
    cursor.execute(
        'SELECT BIN_TO_UUID(book_id), book_name, description, price, quantity, category, book_image, added_at FROM books WHERE book_id = UUID_TO_BIN(%s)',
        [bookid]
    )
    book_data = cursor.fetchone()
    cursor.close()

    if not book_data:
        flash('Could not find book')
        return redirect(url_for('homepage'))

    session['single_buy'] = {
        bookid: [book_data[1], float(book_data[3]) if book_data[3] is not None else 0.0, 1, book_data[5], book_data[6]]
    }
    session.modified = True
    return redirect(url_for('viewcart'))

@app.route('/remove_cart/<bookid>')
def remove_cart(bookid):
    if not session.get('user'):
        flash("Please login first")
        return redirect(url_for('userlogin'))

    email = session.get('user')
    cart = session.get(email, {})

    if bookid in cart:
        cart.pop(bookid)
        session[email] = cart
        session.modified = True
        flash("Item removed from cart")
    else:
        flash("Item not found in cart")

    return redirect(url_for('viewcart'))

@app.route('/pay_cart', methods=['GET', 'POST'])
def pay_cart():
    if not session.get('user'):
        flash('Please login first')
        return redirect(url_for('userlogin'))

    try:
        cart = session.get('single_buy') or session.get(session.get('user'), {})
        if not cart:
            flash('Your cart is empty')
            return redirect(url_for('homepage'))

        books_total = 0.0
        books_for_display = []
        for bookid, data in cart.items():
            name = data[0]
            price = float(data[1]) if data[1] is not None else 0.0
            qty = int(data[2])
            category = data[3] if len(data) > 3 else ""
            img = data[4] if len(data) > 4 else ""

            subtotal = price * qty
            books_total += subtotal

            books_for_display.append({
                'id': bookid,
                'name': name,
                'price': price,
                'qty': qty,
                'subtotal': subtotal,
                'img': img,
                'category': category
            })

        delivery = 40
        tax = round(books_total * 0.05, 2)
        grand_total = books_total + delivery + tax
        razorpay_amount = int(grand_total * 100)

        order = None
        if client:
            try:
                order = client.order.create({
                    'amount': razorpay_amount,
                    'currency': 'INR',
                    'receipt': f"receipt_{session.get('user')[:10]}",
                    'payment_capture': '1'
                })
            except Exception as e:
                print(f"Razorpay order create error: {e}")
                order = {'id': f"order_mock_{genotp()}", 'amount': razorpay_amount}
        else:
            order = {'id': f"order_mock_{genotp()}", 'amount': razorpay_amount}

        return render_template(
            'payment.html',
            order=order,
            cart_items=books_for_display,
            delivery=delivery,
            tax=tax,
            grand_total=grand_total
        )
    except Exception as e:
        print(f'Payment processing error: {e}')
        flash('Could not process payment')
        return redirect(url_for('homepage'))

@app.route('/success_cart', methods=['POST'])
def success_cart():
    if 'user' not in session:
        flash("Please login first")
        return redirect(url_for('userlogin'))

    user = session.get('user')
    session.pop(user, None)
    session.pop('single_buy', None)

    flash("Payment successful! Your order has been placed.")
    return redirect(url_for('homepage'))


# ---------------- Wishlist ----------------
@app.route('/wishlist/<bookid>', methods=['POST'])
def wishlist(bookid):
    if 'user' not in session:
        return jsonify({'success': False, 'message': 'Please login first'}), 401

    try:
        user_email = session['user']
        db = get_db()
        cursor = db.cursor(buffered=True)

        cursor.execute("SELECT user_id FROM user WHERE email = %s", (user_email,))
        user_data = cursor.fetchone()
        if not user_data:
            cursor.close()
            return jsonify({'success': False, 'message': 'User not found'}), 404

        user_id = user_data[0]

        cursor.execute("SELECT BIN_TO_UUID(book_id) FROM books WHERE book_id = UUID_TO_BIN(%s)", (bookid,))
        book_data = cursor.fetchone()
        if not book_data:
            cursor.close()
            return jsonify({'success': False, 'message': 'Book not found'}), 404

        book_uuid = book_data[0]

        cursor.execute(
            "SELECT wishlist_id FROM wishlist WHERE user_id = %s AND book_id = UUID_TO_BIN(%s)",
            (user_id, book_uuid)
        )
        existing = cursor.fetchone()

        if existing:
            cursor.execute(
                "DELETE FROM wishlist WHERE user_id = %s AND book_id = UUID_TO_BIN(%s)",
                (user_id, book_uuid)
            )
            db.commit()
            cursor.close()
            return jsonify({'success': True, 'wishlisted': False, 'message': 'Removed from wishlist'})
        else:
            cursor.execute(
                "INSERT INTO wishlist (user_id, book_id) VALUES (%s, UUID_TO_BIN(%s))",
                (user_id, book_uuid)
            )
            db.commit()
            cursor.close()
            return jsonify({'success': True, 'wishlisted': True, 'message': 'Added to wishlist'})

    except Exception as e:
        print(f"Wishlist error: {e}")
        return jsonify({'success': False, 'message': str(e)}), 500


# ---------------- Application Runner ----------------
if __name__ == "__main__":
    host = os.environ.get('HOST', '0.0.0.0')
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', 'True').lower() in ('true', '1')
    app.run(host=host, port=port, debug=debug)
