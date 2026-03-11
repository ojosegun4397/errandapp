import os
import requests
from flask import Flask, render_template, redirect, url_for, request, flash, jsonify, session
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_bcrypt import Bcrypt
from flask_socketio import SocketIO, emit, join_room, leave_room
from dotenv import load_dotenv
from datetime import datetime

# ─────────────────────────────────────────────
# LOAD SECRET KEYS FROM .env FILE
# ─────────────────────────────────────────────
load_dotenv()

# ─────────────────────────────────────────────
# CREATE THE APP
# ─────────────────────────────────────────────
app = Flask(__name__)
app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'fallback-secret-key')
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///errandapp.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

PAYSTACK_SECRET_KEY = os.getenv('PAYSTACK_SECRET_KEY', '')
PAYSTACK_PUBLIC_KEY = os.getenv('PAYSTACK_PUBLIC_KEY', '')

# ─────────────────────────────────────────────
# SET UP TOOLS
# ─────────────────────────────────────────────
db = SQLAlchemy(app)
bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'
socketio = SocketIO(app, cors_allowed_origins="*")

# ─────────────────────────────────────────────
# DATABASE MODELS (Tables in the database)
# ─────────────────────────────────────────────

# USER TABLE — stores everyone who signs up
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(100), nullable=False)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='customer')  # 'customer' or 'runner'
    phone = db.Column(db.String(20), nullable=True)
    location = db.Column(db.String(200), nullable=True)
    bio = db.Column(db.Text, nullable=True)
    rating = db.Column(db.Float, default=5.0)
    is_available = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ERRAND TABLE — stores all errands posted
class Errand(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    pickup_location = db.Column(db.String(300), nullable=False)
    delivery_location = db.Column(db.String(300), nullable=False)
    budget = db.Column(db.Float, nullable=False)
    status = db.Column(db.String(50), default='open')  # open, assigned, completed
    customer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    runner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    customer = db.relationship('User', foreign_keys=[customer_id], backref='posted_errands')
    runner = db.relationship('User', foreign_keys=[runner_id], backref='assigned_errands')

# MESSAGE TABLE — stores all chat messages
class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sender_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    receiver_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    errand_id = db.Column(db.Integer, db.ForeignKey('errand.id'), nullable=True)
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    sender = db.relationship('User', foreign_keys=[sender_id])
    receiver = db.relationship('User', foreign_keys=[receiver_id])

# PAYMENT TABLE — stores all payments
class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    errand_id = db.Column(db.Integer, db.ForeignKey('errand.id'), nullable=False)
    payer_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    payee_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    amount = db.Column(db.Float, nullable=False)
    reference = db.Column(db.String(200), unique=True)

status = db.Column(db.String(50), default='pending')  # pending, success, failed created_at = db.Column(db.DateTime, default=datetime.utcnow)

# ─────────────────────────────────────────────
# LOGIN MANAGER SETUP
# ─────────────────────────────────────────────
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ─────────────────────────────────────────────
# ROUTES (Pages of the app)
# ─────────────────────────────────────────────

# HOME PAGE
@app.route('/')
def index():
    runners = User.query.filter_by(role='runner', is_available=True).limit(6).all()
    errands = Errand.query.filter_by(status='open').limit(5).all()
    return render_template('index.html', runners=runners, errands=errands)

# REGISTER PAGE
@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        password = request.form.get('password')
        role = request.form.get('role', 'customer')
        phone = request.form.get('phone')
        location = request.form.get('location')
        bio = request.form.get('bio', '')

        # Check if email already exists
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash('Email already registered. Please login.', 'danger')
            return redirect(url_for('register'))

        # Hash the password (turn it into a secret code)
        hashed_password = bcrypt.generate_password_hash(password).decode('utf-8')

        # Create new user
        new_user = User(
            name=name, email=email, password=hashed_password,
            role=role, phone=phone, location=location, bio=bio
        )
        db.session.add(new_user)
        db.session.commit()
        flash('Account created! Please login.', 'success')
        return redirect(url_for('login'))

    return render_template('register.html')

# LOGIN PAGE
@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form.get('email')
        password = request.form.get('password')
        user = User.query.filter_by(email=email).first()

        if user and bcrypt.check_password_hash(user.password, password):
            login_user(user)
            flash(f'Welcome back, {user.name}!', 'success')
            return redirect(url_for('dashboard'))
        else:
            flash('Wrong email or password. Try again.', 'danger')

    return render_template('login.html')

# LOGOUT
@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('You have been logged out.', 'info')
    return redirect(url_for('index'))

# DASHBOARD
@app.route('/dashboard')
@login_required
def dashboard():
    if current_user.role == 'customer':
        errands = Errand.query.filter_by(customer_id=current_user.id).all()
    else:
        errands = Errand.query.filter_by(status='open').all()
    return render_template('dashboard.html', errands=errands)

# POST AN ERRAND
@app.route('/post-errand', methods=['GET', 'POST'])
@login_required
def post_errand():
    if request.method == 'POST':
        errand = Errand(
            title=request.form.get('title'),
            description=request.form.get('description'),
            pickup_location=request.form.get('pickup_location'),
            delivery_location=request.form.get('delivery_location'),
            budget=float(request.form.get('budget')),
            customer_id=current_user.id
        )
        db.session.add(errand)
        db.session.commit()
        flash('Errand posted successfully!', 'success')
        return redirect(url_for('dashboard'))
    return render_template('post_errand.html')

# BROWSE RUNNERS
@app.route('/runners')
def runners():
    all_runners = User.query.filter_by(role='runner').all()
    return render_template('runners.html', runners=all_runners)

# ACCEPT AN ERRAND (for runners)
@app.route('/accept-errand/<int:errand_id>')
@login_required
def accept_errand(errand_id):
    errand = Errand.query.get_or_404(errand_id)
    if current_user.role == 'runner' and errand.status == 'open':
        errand.runner_id = current_user.id
        errand.status = 'assigned'
        db.session.commit()
        flash('You accepted this errand!', 'success')
    return redirect(url_for('dashboard'))

# COMPLETE AN ERRAND
@app.route('/complete-errand/<int:errand_id>')
@login_required
def complete_errand(errand_id):
    errand = Errand.query.get_or_404(errand_id)
    if errand.runner_id == current_user.id:
        errand.status = 'completed'
        db.session.commit()
        flash('Errand marked as completed!', 'success')
    return redirect(url_for('dashboard'))

# CHAT PAGE
@app.route('/chat/<int:other_user_id>')
@login_required
def chat(other_user_id):
    other_user = User.query.get_or_404(other_user_id)
    # Get all messages between these two users
    messages = Message.query.filter(
        ((Message.sender_id == current_user.id) & (Message.receiver_id == other_user_id)) |
        ((Message.sender_id == other_user_id) & (Message.receiver_id == current_user.id))
    ).order_by(Message.timestamp.asc()).all()
    return render_template('chat.html', other_user=other_user, messages=messages)

# ─────────────────────────────────────────────
# SOCKET.IO — Real-time Chat
# ─────────────────────────────────────────────
@socketio.on('join')
def on_join(data):
    room = data['room']
    join_room(room)

@socketio.on('send_message')
def handle_message(data):
    # Save message to database
    msg = Message(
        sender_id=data['sender_id'],
        receiver_id=data['receiver_id'],
        content=data['message']
    )
    db.session.add(msg)
    db.session.commit()

    # Send message to the room
    emit('receive_message', {
        'sender': data['sender_name'],
        'message': data['message'],
        'timestamp': datetime.utcnow().strftime('%H:%M')
    }, room=data['room'])

# ─────────────────────────────────────────────
# PAYSTACK PAYMENT
# ─────────────────────────────────────────────

# PAYMENT PAGE — Show payment form
@app.route('/pay/<int:errand_id>', methods=['GET', 'POST'])
@login_required
def pay(errand_id):
    errand = Errand.query.get_or_404(errand_id)
    if request.method == 'POST':
        # Initiate payment with Paystack
        amount_in_kobo = int(errand.budget * 100)  # Paystack uses kobo (100 kobo = 1 Naira)
        reference = f"errand_{errand_id}_{current_user.id}_{int(datetime.utcnow().timestamp())}"

        headers = {
            'Authorization': f'Bearer {PAYSTACK_SECRET_KEY}',
            'Content-Type': 'application/json'
        }
        payload = {
            'email': current_user.email,
            'amount': amount_in_kobo,
            'reference': reference,
            'callback_url': url_for('verify_payment', _external=True)
        }

        response = requests.post('https://api.paystack.co/transaction/initialize', 
                                 json=payload, headers=headers)
        result = response.json()

        if result['status']:
            # Save payment record
            payment = Payment(
                errand_id=errand_id,
                payer_id=current_user.id,
                payee_id=errand.runner_id,
                amount=errand.budget,
                reference=reference,
                status='pending'
            )
            db.session.add(payment)
            db.session.commit()

            # Redirect user to Paystack payment page
            return redirect(result['data']['authorization_url'])
        else:
            flash('Payment initialization failed. Try again.', 'danger')

    return render_template('payment.html', errand=errand, pubkey=PAYSTACK_PUBLIC_KEY)

# VERIFY PAYMENT — Paystack redirects here after payment
@app.route('/verify-payment')
@login_required
def verify_payment():
    reference = request.args.get('reference')
    if not reference:
        flash('No payment reference found.', 'danger')
        return redirect(url_for('dashboard'))

    headers = {'Authorization': f'Bearer {PAYSTACK_SECRET_KEY}'}
    response = requests.get(f'https://api.paystack.co/transaction/verify/{reference}', 
                            headers=headers)
    result = response.json()

    if result['status'] and result['data']['status'] == 'success':
        # Update payment record
        payment = Payment.query.filter_by(reference=reference).first()
        if payment:
            payment.status = 'success'
            db.session.commit()
        flash('Payment successful! 🎉', 'success')
    else:
        flash('Payment failed or was cancelled.', 'danger')

    return redirect(url_for('dashboard'))

# ─────────────────────────────────────────────
# START THE APP
# ─────────────────────────────────────────────
if __name__ == '__main__':
    with app.app_context():
        db.create_all()  # Create all database tables
        print("✅ Database tables created!")
    socketio.run(app, debug=True)
