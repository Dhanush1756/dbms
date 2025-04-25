from flask import Flask, render_template, request, redirect, session, jsonify, url_for
import mysql.connector
from werkzeug.security import generate_password_hash, check_password_hash
from config import SECRET_KEY
from db import get_db_connection
import razorpay

app = Flask(__name__)
app.secret_key = SECRET_KEY

razorpay_client = razorpay.Client(auth=("your_razorpay_key_id", "your_razorpay_key_secret"))

@app.route('/')
def home():
    if 'user_type' in session:
        return redirect(url_for('buyer_home') if session['user_type'] == 'buyer' else url_for('seller_dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form['username']
        password = generate_password_hash(request.form['password'])
        email = request.form['email']
        user_type = request.form['user_type']

        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO users (username, password, email, user_type) VALUES (%s, %s, %s, %s)",
                       (username, password, email, user_type))
        conn.commit()
        conn.close()
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password_input = request.form['password']

        conn = get_db_connection()
        cursor = conn.cursor(dictionary=True)
        cursor.execute("SELECT * FROM users WHERE username = %s", (username,))
        user = cursor.fetchone()
        conn.close()

        if user and check_password_hash(user['password'], password_input):
            session['user_id'] = user['id']
            session['username'] = user['username']
            session['user_type'] = user['user_type']
            return redirect(url_for('buyer_home') if user['user_type'] == 'buyer' else url_for('seller_dashboard'))
        return "Invalid credentials"
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/buyer')
def buyer_home():
    if 'user_type' not in session or session['user_type'] != 'buyer':
        return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM products")
    products = cursor.fetchall()
    conn.close()
    return render_template('buyer_home.html', products=products)

@app.route('/add_to_cart', methods=['POST'])
def add_to_cart():
    if 'user_type' not in session or session['user_type'] != 'buyer':
        return redirect(url_for('login'))
    product_id = request.form['product_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM cart WHERE user_id = %s AND product_id = %s", (session['user_id'], product_id))
    if cursor.fetchone():
        cursor.execute("UPDATE cart SET quantity = quantity + 1 WHERE user_id = %s AND product_id = %s", (session['user_id'], product_id))
    else:
        cursor.execute("INSERT INTO cart (user_id, product_id, quantity) VALUES (%s, %s, 1)", (session['user_id'], product_id))
    conn.commit()
    conn.close()
    return redirect(url_for('buyer_home'))

@app.route('/cart')
def view_cart():
    if 'user_type' not in session or session['user_type'] != 'buyer':
        return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT c.id, p.name, p.price, c.quantity FROM cart c JOIN products p ON c.product_id = p.id WHERE c.user_id = %s", (session['user_id'],))
    items = cursor.fetchall()
    total = sum(item['price'] * item['quantity'] for item in items)
    conn.close()
    return render_template('cart.html', items=items, total=total)

@app.route('/checkout', methods=['POST'])
def checkout():
    if 'user_type' not in session or session['user_type'] != 'buyer':
        return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT c.product_id, c.quantity, p.price FROM cart c JOIN products p ON c.product_id = p.id WHERE c.user_id = %s", (session['user_id'],))
    items = cursor.fetchall()
    total = int(sum(item['price'] * item['quantity'] for item in items) * 100)
    order = razorpay_client.order.create({'amount': total, 'currency': 'INR', 'payment_capture': '1'})
    for item in items:
        cursor.execute("INSERT INTO orders (user_id, product_id, quantity, payment_status) VALUES (%s, %s, %s, 'paid')", (session['user_id'], item['product_id'], item['quantity']))
    cursor.execute("DELETE FROM cart WHERE user_id = %s", (session['user_id'],))
    conn.commit()
    conn.close()
    return redirect(url_for('buyer_home'))

@app.route('/orders')
def view_orders():
    if 'user_type' not in session:
        return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    if session['user_type'] == 'buyer':
        cursor.execute("SELECT o.id, p.name, o.quantity, o.payment_status, o.created_at FROM orders o JOIN products p ON o.product_id = p.id WHERE o.user_id = %s", (session['user_id'],))
    else:
        cursor.execute("SELECT o.id, p.name, o.quantity, u.username AS buyer, o.created_at FROM orders o JOIN products p ON o.product_id = p.id JOIN users u ON o.user_id = u.id WHERE p.seller_id = %s", (session['user_id'],))
    orders = cursor.fetchall()
    conn.close()
    return render_template('orders.html', orders=orders)

@app.route('/seller')
def seller_dashboard():
    if 'user_type' not in session or session['user_type'] != 'seller':
        return redirect(url_for('login'))
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)
    cursor.execute("SELECT * FROM products WHERE seller_id = %s", (session['user_id'],))
    products = cursor.fetchall()
    conn.close()
    return render_template('seller_dashboard.html', products=products)

@app.route('/add_product', methods=['POST'])
def add_product():
    if 'user_type' not in session or session['user_type'] != 'seller':
        return redirect(url_for('login'))
    name = request.form['name']
    desc = request.form['description']
    price = request.form['price']
    category = request.form['category']
    image = request.form['image']
    seller_id = session['user_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO products (name, description, price, category, image, seller_id) VALUES (%s, %s, %s, %s, %s, %s)",
                   (name, desc, price, category, image, seller_id))
    conn.commit()
    conn.close()
    return redirect(url_for('seller_dashboard'))

@app.route('/edit_product', methods=['POST', 'GET'])
def edit_product():
    if 'user_type' not in session or session['user_type'] != 'seller':
        return redirect(url_for('login'))

    product_id = request.form.get('product_id')
    conn = get_db_connection()
    cursor = conn.cursor(dictionary=True)

    if request.method == 'POST' and 'name' in request.form:
        name = request.form['name']
        desc = request.form['description']
        price = request.form['price']
        category = request.form['category']
        image = request.form['image']
        cursor.execute("""
            UPDATE products
            SET name = %s, description = %s, price = %s, category = %s, image = %s
            WHERE id = %s AND seller_id = %s
        """, (name, desc, price, category, image, product_id, session['user_id']))
        conn.commit()
        conn.close()
        return redirect(url_for('seller_dashboard'))

    cursor.execute("SELECT * FROM products WHERE id = %s AND seller_id = %s", (product_id, session['user_id']))
    product = cursor.fetchone()
    conn.close()
    return render_template('edit_product.html', product=product)

@app.route('/delete_product', methods=['POST'])
def delete_product():
    if 'user_type' not in session or session['user_type'] != 'seller':
        return redirect(url_for('login'))

    product_id = request.form['product_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM products WHERE id = %s AND seller_id = %s", (product_id, session['user_id']))
    conn.commit()
    conn.close()
    return redirect(url_for('seller_dashboard'))

@app.route('/delete_from_cart', methods=['POST'])
def delete_from_cart():
    if 'user_type' not in session or session['user_type'] != 'buyer':
        return redirect(url_for('login'))
    
    product_id = request.form['product_id']
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("DELETE FROM cart WHERE user_id = %s AND product_id = %s", (session['user_id'], product_id))
    conn.commit()
    conn.close()

    return redirect(url_for('view_cart'))  # Redirect back to the cart page to see updated cart.


if __name__ == '__main__':
    app.run(debug=True)
