from flask import Flask, render_template, request, redirect, url_for, flash, jsonify
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import os
import datetime
from dotenv import load_dotenv
import firebase_admin
from firebase_admin import credentials, firestore

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'eco_reward_secret_123')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///ecoreward.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

# Firebase Initialization
FIREBASE_ENABLED = False
if os.path.exists('serviceAccountKey.json'):
    try:
        cred = credentials.Certificate('serviceAccountKey.json')
        firebase_admin.initialize_app(cred)
        firebase_db = firestore.client()
        FIREBASE_ENABLED = True
    except Exception as e:
        print(f"Firebase Init Error: {e}")

db = SQLAlchemy(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

# Database Models
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100))
    email = db.Column(db.String(100), unique=True)
    password = db.Column(db.String(200))
    points = db.Column(db.Integer, default=0)
    items_recycled = db.Column(db.Integer, default=0)
    transactions = db.relationship('Transaction', backref='user', lazy=True)

class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10))
    points = db.Column(db.Integer)
    timestamp = db.Column(db.DateTime, default=datetime.datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

class GeneratedCode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    code = db.Column(db.String(10), unique=True)
    points = db.Column(db.Integer, default=10)
    is_used = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.datetime.utcnow)

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# Initialize database
with app.app_context():
    db.create_all()

@app.route('/')
def index():
    return render_template('onboarding.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()
        
        if user and check_password_hash(user.password, password):
            login_user(user)
            return redirect(url_for('dashboard'))
        
        flash('Invalid email or password', 'error')
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        email = request.form.get('email')
        name = request.form.get('name')
        password = request.form.get('password')
        
        if User.query.filter_by(email=email).first():
            flash('Email already exists', 'error')
            return redirect(url_for('signup'))
        
        new_user = User(
            name=name,
            email=email,
            password=generate_password_hash(password, method='scrypt')
        )
        db.session.add(new_user)
        db.session.commit()
        
        login_user(new_user)
        return redirect(url_for('dashboard'))
    return render_template('signup.html')

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', user=current_user, activity=current_user.transactions[:5])

@app.route('/wallet')
@login_required
def wallet():
    return render_template('wallet.html', user=current_user, activity=current_user.transactions)

@app.route('/redeem', methods=['GET', 'POST'])
@login_required
def redeem():
    if request.method == 'POST':
        code_str = request.form.get('code').upper()
        
        # Validate code from database
        db_code = GeneratedCode.query.filter_by(code=code_str, is_used=False).first()
        
        if not db_code:
            flash('Invalid or expired code. Please try again.', 'error')
            return render_template('redeem.html')
            
        points_to_add = db_code.points
        
        # --- REAL FIREBASE LOGIC ---
        if FIREBASE_ENABLED:
            try:
                # Save to Firestore
                doc_ref = firebase_db.collection('transactions').document()
                doc_ref.set({
                    'code': code_str,
                    'points': points_to_add,
                    'user_id': current_user.email,
                    'timestamp': firestore.SERVER_TIMESTAMP
                })
                
                # Update User Points in Firestore
                user_ref = firebase_db.collection('users').document(current_user.email)
                user_ref.set({
                    'name': current_user.name,
                    'points': firestore.Increment(points_to_add),
                    'items_recycled': firestore.Increment(1)
                }, merge=True)
            except Exception as e:
                print(f"Firestore Sync Error: {e}")

        # Update local SQLite (Mirroring for session speed)
        db_code.is_used = True
        new_tx = Transaction(code=code_str, points=points_to_add, user_id=current_user.id)
        current_user.points += points_to_add
        current_user.items_recycled += 1
        
        db.session.add(new_tx)
        db.session.commit()
        
        flash(f'Success! {code_str} redeemed for {points_to_add} points.', 'success')
        return render_template('redeem.html')
    return render_template('redeem.html')

# --- API FOR SMART BIN ---
@app.route('/api/bin/disposal', methods=['POST'])
def bin_disposal():
    """
    Endpoint for the physical Smart Bin to request a code after disposal.
    Expected JSON: { "bin_id": "BIN_001", "waste_type": "plastic" }
    """
    data = request.get_json()
    if not data or 'bin_id' not in data:
        return jsonify({"error": "Missing bin_id"}), 400
        
    # Generate a random 6-character code
    import random, string
    code_str = ''.join(random.choices(string.ascii_uppercase + string.digits, k=6))
    
    new_code = GeneratedCode(code=code_str, points=10)
    db.session.add(new_code)
    db.session.commit()
    
    return jsonify({
        "status": "success",
        "code": code_str,
        "message": "Disposal recorded. Please show this code on the bin screen."
    })

@app.route('/leaderboard')
@login_required
def leaderboard():
    if FIREBASE_ENABLED:
        try:
            users_ref = firebase_db.collection('users')
            query = users_ref.order_by('points', direction=firestore.Query.DESCENDING).limit(10)
            leaders = [doc.to_dict() for doc in query.stream()]
            # Ensure keys match template expectations
            for leader in leaders:
                leader['count'] = leader.get('items_recycled', 0)
            return render_template('leaderboard.html', leaders=leaders)
        except Exception as e:
            print(f"Firebase Leaderboard Error: {e}")

    leaders = User.query.order_by(User.points.desc()).limit(10).all()
    return render_template('leaderboard.html', leaders=leaders)

@app.route('/profile')
@login_required
def profile():
    return render_template('profile.html', user=current_user)

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True, port=5000)
