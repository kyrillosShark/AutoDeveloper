# app.py
from flask import Flask
from flask_socketio import SocketIO

app = Flask(__name__, static_folder='static')

socketio = SocketIO(
    app,
    cors_allowed_origins="*",
    manage_session=False,
    ping_timeout=120,
    ping_interval=25
)

# Import routes and event handlers to register them with Flask and SocketIO
import routes
import socketio_handlers
