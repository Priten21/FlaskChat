import os
import google.generativeai as genai
from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, Response
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from flask_migrate import Migrate
from dotenv import load_dotenv
from datetime import datetime
from urllib.parse import quote_plus
import io
import uuid
import json

# Import form classes and validators
from flask_wtf import FlaskForm
from wtforms import StringField, PasswordField, SubmitField
from wtforms.validators import DataRequired, Length, EqualTo, ValidationError

# --- Extensions Initialization (outside the factory) ---
db = SQLAlchemy()
bcrypt = Bcrypt()
login_manager = LoginManager()
migrate = Migrate()
load_dotenv()
model = None # Will be initialized in create_app

# --- Database Models ---
class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    conversations = db.relationship('Conversation', backref='author', lazy=True, cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = bcrypt.generate_password_hash(password).decode('utf-8')

    def check_password(self, password):
        return bcrypt.check_password_hash(self.password_hash, password)

class Conversation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False, default="New Chat")
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    messages = db.relationship('Message', backref='conversation', lazy=True, cascade="all, delete-orphan", order_by='Message.created_at')
    is_public = db.Column(db.Boolean, nullable=False, default=False)
    share_uuid = db.Column(db.String(36), unique=True, nullable=True)


class Message(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    content = db.Column(db.Text, nullable=False)
    sender = db.Column(db.String(10), nullable=False) # 'user' or 'model'
    conversation_id = db.Column(db.Integer, db.ForeignKey('conversation.id'), nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

# --- Forms ---
class RegistrationForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired(), Length(min=4, max=20)])
    password = PasswordField('Password', validators=[DataRequired(), Length(min=6)])
    confirm_password = PasswordField('Confirm Password', validators=[DataRequired(), EqualTo('password')])
    submit = SubmitField('Sign Up')

    def validate_username(self, username):
        user = User.query.filter_by(username=username.data).first()
        if user:
            raise ValidationError('That username is already taken. Please choose a different one.')

class LoginForm(FlaskForm):
    username = StringField('Username', validators=[DataRequired()])
    password = PasswordField('Password', validators=[DataRequired()])
    submit = SubmitField('Login')

# --- Application Factory Function ---
def create_app():
    global model
    app = Flask(__name__, template_folder='templates', static_folder='static')

    # Configuration
    app.config['SECRET_KEY'] = os.getenv('SECRET_KEY', 'a-fallback-secret-key-for-development')
    db_user = os.getenv('DB_USER', 'root')
    db_password_raw = os.getenv('DB_PASSWORD', '')
    db_host = os.getenv('DB_HOST', 'localhost')
    db_name = os.getenv('DB_NAME', 'flaskchat_db')
    db_password = quote_plus(db_password_raw)
    app.config['SQLALCHEMY_DATABASE_URI'] = f'mysql+pymysql://{db_user}:{db_password}@{db_host}/{db_name}'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

    try:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY not found.")
        genai.configure(api_key=api_key)
        model = genai.GenerativeModel('gemini-1.5-flash')
    except ValueError as e:
        print(f"Error: {e}")
        exit()
    
    # Initialize Extensions with the App
    db.init_app(app)
    bcrypt.init_app(app)
    login_manager.init_app(app)
    migrate.init_app(app, db)
    
    # Flask-Login Configuration
    login_manager.login_view = 'login'
    login_manager.login_message_category = 'info'

    @login_manager.user_loader
    def load_user(user_id):
        return User.query.get(int(user_id))

    # --- Main Application Routes ---
    @app.route('/')
    @app.route('/conversation/<int:conv_id>')
    @login_required
    def home(conv_id=None):
        return render_template('chat.html')

    # --- Authentication Routes ---
    @app.route('/register', methods=['GET', 'POST'])
    def register():
        if current_user.is_authenticated:
            return redirect(url_for('home'))
        form = RegistrationForm()
        if form.validate_on_submit():
            hashed_password = bcrypt.generate_password_hash(form.password.data).decode('utf-8')
            user = User(username=form.username.data, password_hash=hashed_password)
            db.session.add(user)
            db.session.commit()
            flash('Your account has been created! You are now able to log in.', 'success')
            return redirect(url_for('login'))
        return render_template('register.html', title='Register', form=form)

    @app.route('/login', methods=['GET', 'POST'])
    def login():
        if current_user.is_authenticated:
            return redirect(url_for('home'))
        form = LoginForm()
        if form.validate_on_submit():
            user = User.query.filter_by(username=form.username.data).first()
            if user and bcrypt.check_password_hash(user.password_hash, form.password.data):
                login_user(user)
                next_page = request.args.get('next')
                return redirect(next_page) if next_page else redirect(url_for('home'))
            else:
                flash('Login Unsuccessful. Please check username and password.', 'error')
        return render_template('login.html', title='Login', form=form)

    @app.route('/logout')
    @login_required
    def logout():
        logout_user()
        flash('You have been logged out successfully.', 'success')
        return redirect(url_for('login'))
    
    # --- Public Share Route ---
    @app.route('/share/<uuid:share_id>')
    def shared_conversation(share_id):
        conv = Conversation.query.filter_by(share_uuid=str(share_id), is_public=True).first_or_404()
        return render_template('share_page.html', conversation=conv)


    # --- API Routes for Chat Functionality ---
    @app.route('/new_conversation', methods=['POST'])
    @login_required
    def new_conversation():
        new_conv = Conversation(author=current_user)
        db.session.add(new_conv)
        db.session.commit()
        return jsonify({'conversation_id': new_conv.id})

    @app.route('/conversations', methods=['GET'])
    @login_required
    def get_conversations():
        conversations = Conversation.query.filter_by(user_id=current_user.id).order_by(Conversation.created_at.desc()).all()
        return jsonify([{'id': c.id, 'title': c.title} for c in conversations])

    @app.route('/conversations/<int:conv_id>', methods=['GET'])
    @login_required
    def get_conversation_messages(conv_id):
        conv = Conversation.query.get_or_404(conv_id)
        if conv.user_id != current_user.id:
            return jsonify({'error': 'Unauthorized'}), 403
        messages = [{'content': m.content, 'sender': m.sender} for m in conv.messages]
        return jsonify({'title': conv.title, 'messages': messages})

    @app.route('/conversations/<int:conv_id>/send', methods=['POST'])
    @login_required
    def send_message(conv_id):
        conv = Conversation.query.get_or_404(conv_id)
        if conv.user_id != current_user.id:
            return jsonify({'error': 'Unauthorized'}), 403
        
        user_message_content = request.json.get('message')
        if not user_message_content:
            return jsonify({'error': 'Message cannot be empty'}), 400

        user_msg = Message(content=user_message_content, sender='user', conversation_id=conv.id)
        db.session.add(user_msg)
        
        history = [{'role': m.sender if m.sender == 'user' else 'model', 'parts': [m.content]} for m in conv.messages]
        history.append({'role': 'user', 'parts': [user_message_content]})
        
        try:
            response = model.generate_content(history)
            bot_response_content = response.text

            bot_msg = Message(content=bot_response_content, sender='model', conversation_id=conv.id)
            db.session.add(bot_msg)
            
            if len(conv.messages) <= 1 and conv.title == "New Chat":
                title_prompt = f"Based on this user's first question, create a short, relevant title for this conversation. The question was: '{user_message_content}'. The title should be no more than 5 words."
                title_response = model.generate_content(title_prompt)
                conv.title = title_response.text.strip().replace('"', '')
            
            db.session.commit()
            return jsonify({'response': bot_response_content})

        except Exception as e:
            db.session.rollback()
            print(f"Gemini API Error: {e}")
            return jsonify({'error': 'An error occurred while communicating with the AI.'}), 500

    @app.route('/conversations/<int:conv_id>/share', methods=['POST'])
    @login_required
    def share_chat(conv_id):
        conv = Conversation.query.get_or_404(conv_id)
        if conv.user_id != current_user.id:
            return jsonify({'error': 'Unauthorized'}), 403

        if not conv.share_uuid:
            conv.share_uuid = str(uuid.uuid4())
        
        conv.is_public = True
        db.session.commit()
        
        share_url = url_for('shared_conversation', share_id=conv.share_uuid, _external=True)
        return jsonify({'share_url': share_url})


    @app.route('/conversations/<int:conv_id>/export', methods=['GET'])
    @login_required
    def export_chat(conv_id):
        conv = Conversation.query.get_or_404(conv_id)
        if conv.user_id != current_user.id:
            return "Unauthorized", 403
        
        export_format = request.args.get('format', 'txt')
        
        if export_format == 'json':
            chat_data = {
                'title': conv.title,
                'created_at': conv.created_at.isoformat(),
                'messages': [
                    {
                        'sender': msg.sender,
                        'content': msg.content,
                        'timestamp': msg.created_at.isoformat()
                    } for msg in conv.messages
                ]
            }
            output = json.dumps(chat_data, indent=2)
            mimetype="application/json"
            filename = f"conversation_{conv.id}.json"
        else:
            output = f"Title: {conv.title}\n\n"
            for msg in conv.messages:
                output += f"[{msg.sender.capitalize()} - {msg.created_at.strftime('%Y-%m-%d %H:%M')}]\n{msg.content}\n\n"
            mimetype="text/plain"
            filename = f"conversation_{conv.id}.txt"

        return Response(
            output,
            mimetype=mimetype,
            headers={"Content-disposition": f"attachment; filename={filename}"}
        )

    return app

# --- Main Execution ---
if __name__ == '__main__':
    app = create_app()
    app.run(debug=True)
