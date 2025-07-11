from flask import Flask, render_template, request, jsonify, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
import requests
import numpy as np
from flask import request
from datetime import datetime, timedelta

app = Flask(__name__)
app.secret_key = "supersecretkey"  # Change this in production!

# Database configuration
app.config['SQLALCHEMY_DATABASE_URI'] = (
    'postgresql://masteruser:ASDZXC12@portfolio-dbnew.cnsu4io8otma.ap-south-1.rds.amazonaws.com:5432/portfolioapp'
)
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# Flask-Login configuration
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = "login"

API_KEY = "8qL3vjv7pKPl5Q8U1CqUDKQN35QMvZE6"

# ===============================
# Models
# ===============================
class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    email = db.Column(db.String(100), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)

class Portfolio(db.Model):
    __tablename__ = 'portfolio'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id', ondelete='CASCADE'))
    stock_symbol = db.Column(db.String(10), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    buy_price = db.Column(db.Numeric(10,2), nullable=False)
    date_added = db.Column(db.DateTime, server_default=db.func.now())

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ===============================
# Stock Analysis Helpers
# ===============================
def calculate_rsi(prices, period=14):
    deltas = np.diff(prices)
    seed = deltas[:period]
    up = seed[seed >= 0].sum() / period
    down = -seed[seed < 0].sum() / period
    rs = up / down if down != 0 else 0
    rsi = np.zeros_like(prices)
    rsi[:period] = 100. - 100. / (1. + rs)

    for i in range(period, len(prices)):
        delta = deltas[i - 1]
        upval = max(delta, 0)
        downval = -min(delta, 0)

        up = (up * (period - 1) + upval) / period
        down = (down * (period - 1) + downval) / period
        rs = up / down if down != 0 else 0
        rsi[i] = 100. - 100. / (1. + rs)

    return rsi

def ema(prices, period):
    ema_values = np.zeros_like(prices)
    k = 2 / (period + 1)
    ema_values[0] = prices[0]
    for i in range(1, len(prices)):
        ema_values[i] = prices[i] * k + ema_values[i - 1] * (1 - k)
    return ema_values

def calculate_macd(prices, slow=26, fast=12, signal=9):
    ema_fast = ema(prices, fast)
    ema_slow = ema(prices, slow)
    macd_line = ema_fast - ema_slow
    signal_line = ema(macd_line, signal)
    histogram = macd_line - signal_line
    return macd_line, signal_line, histogram

# ===============================
# Routes
# ===============================

@app.route("/")
def index():
    return render_template("index.html")

# -------------------------------
# Registration Route
# -------------------------------
@app.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        username = request.form["username"]
        email = request.form["email"]
        password = request.form["password"]

        if User.query.filter_by(username=username).first():
            flash("Username already exists.")
            return redirect(url_for("register"))
        if User.query.filter_by(email=email).first():
            flash("Email already registered.")
            return redirect(url_for("register"))

        hashed_password = generate_password_hash(password)
        new_user = User(username=username, email=email, password_hash=hashed_password)
        db.session.add(new_user)
        db.session.commit()
        flash("Registration successful. Please log in.")
        return redirect(url_for("login"))
    return render_template("register.html")

# -------------------------------
# Login Route
# -------------------------------
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        username = request.form["username"]
        password = request.form["password"]
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            flash("Logged in successfully.")
            return redirect(url_for("index"))
        flash("Invalid username or password.")
    return render_template("login.html")


@app.route("/add_holding", methods=["POST"])
@login_required
def add_holding():
    symbol = request.form["symbol"]
    quantity = int(request.form["quantity"])
    buy_price = float(request.form["buy_price"])

    new_holding = Portfolio(
        user_id=current_user.id,
        stock_symbol=symbol,
        quantity=quantity,
        buy_price=buy_price
    )
    db.session.add(new_holding)
    db.session.commit()
    return redirect(url_for("portfolio"))

@app.route("/delete_holding/<int:holding_id>", methods=["POST"])
@login_required
def delete_holding(holding_id):
    holding = Portfolio.query.get_or_404(holding_id)
    if holding.user_id != current_user.id:
        return "Unauthorized", 403
    db.session.delete(holding)
    db.session.commit()
    return redirect(url_for("portfolio"))

# -------------------------------
# Logout Route
#-------------------------------
@app.route("/portfolio")
@login_required
def portfolio():
    holdings = Portfolio.query.filter_by(user_id=current_user.id).all()

    # Build a list of holdings with current market prices
    portfolio_data = []
    for h in holdings:
        # Fetch latest price
        url = f"https://api.polygon.io/v2/aggs/ticker/{h.stock_symbol.upper()}/prev"
        params = {"apiKey": API_KEY}
        resp = requests.get(url, params=params).json()
        if "results" in resp and resp["results"]:
            latest_price = resp["results"][0]["c"]
            profit_loss = (latest_price - float(h.buy_price)) * h.quantity
        else:
            latest_price = None
            profit_loss = None

        portfolio_data.append({
            "id": h.id,
            "symbol": h.stock_symbol.upper(),
            "quantity": h.quantity,
            "buy_price": float(h.buy_price),
            "latest_price": latest_price,
            "profit_loss": profit_loss,
            "date_added": h.date_added.strftime("%Y-%m-%d")
        })

    return render_template("portfolio.html", portfolio=portfolio_data)

@app.route("/logout")
@login_required
def logout():
    logout_user()
    flash("You have been logged out.")
    return redirect(url_for("login"))

# -------------------------------
# Stock Analysis API
# -------------------------------
@app.route("/api/analyze", methods=["GET"])
def analyze():
    symbol = request.args.get("symbol")
    if not symbol:
        return jsonify({"error": "No symbol provided"}), 400

    today = datetime.today()
    start_date = (today - timedelta(days=45)).strftime('%Y-%m-%d')
    end_date = today.strftime('%Y-%m-%d')

    url = f"https://api.polygon.io/v2/aggs/ticker/{symbol.upper()}/range/1/day/{start_date}/{end_date}"
    params = {
        "adjusted": "true",
        "sort": "desc",
        "limit": "30",
        "apiKey": API_KEY
    }
    response = requests.get(url, params=params)
    data = response.json()

    if "results" not in data or len(data["results"]) == 0:
        return jsonify({"error": "Invalid symbol or no data available"}), 400

    closes = [day["c"] for day in data["results"]]
    closes_array = np.array(closes)

    if len(closes_array) < 20:
        return jsonify({"error": "Not enough data to compute indicators"}), 400

    macd_line, signal_line, histogram = calculate_macd(closes_array)
    rsi_series = calculate_rsi(closes_array)
    rsi = rsi_series[-1]
    moving_avg = closes_array[:20].mean()

    if rsi < 30:
        recommendation = "Buy (Oversold)"
    elif rsi > 70:
        recommendation = "Sell (Overbought)"
    else:
        recommendation = "Hold"

    return jsonify({
        "symbol": symbol.upper(),
        "latest_price": closes_array[0],
        "rsi": round(rsi, 2),
        "moving_average_20": round(moving_avg, 2),
        "recommendation": recommendation,
        "dates": [datetime.utcfromtimestamp(day["t"]/1000).strftime('%Y-%m-%d') for day in data["results"]],
        "closes": closes,
        "rsi_series": list(rsi_series),
        "macd_line": list(macd_line),
        "signal_line": list(signal_line),
        "histogram": list(histogram)
    })

# ===============================
# Run
# ===============================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
