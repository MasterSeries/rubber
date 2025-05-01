from flask import Flask, render_template, request, redirect, session, url_for, flash
import os
import firebase_admin
from firebase_admin import credentials, firestore
from werkzeug.utils import secure_filename

# -------------------- Firebase Setup --------------------
cred = credentials.Certificate("firebase_key.json")
firebase_admin.initialize_app(cred)
db = firestore.client()

# -------------------- Flask Setup --------------------
app = Flask(__name__)
app.secret_key = 'supersecretkey'
UPLOAD_FOLDER = 'static/images'
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# -------------------- Helper Functions --------------------

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

def upload_image(image):
    if image and allowed_file(image.filename):
        filename = secure_filename(image.filename)
        filepath = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        image.save(filepath)
        return filename
    return None

def add_product_to_firebase(name, price, stock, image_filename):
    product_data = {
        'name': name,
        'price': price,
        'stock': stock,
        'image': image_filename or 'default.png'
    }
    doc_ref, _ = db.collection("products").add(product_data)
    return doc_ref.id

def get_all_products():
    return [{'id': p.id, **p.to_dict()} for p in db.collection('products').stream()]

def get_user_from_firebase(username):
    doc = db.collection('users').document(username).get()
    return doc.to_dict() if doc.exists else None

def add_user_to_firebase(username, password, role):
    db.collection('users').document(username).set({'password': password, 'role': role})

def save_order_to_firebase(username, product_id, quantity):
    db.collection('orders').add({'username': username, 'product_id': product_id, 'quantity': quantity})

def is_admin_locked():
    doc = db.collection('settings').document('admin').get()
    return doc.to_dict().get('lock_admin_login', False)

def lock_admin_login():
    db.collection('settings').document('admin').set({'lock_admin_login': True})

def unlock_admin_login():
    db.collection('settings').document('admin').set({'lock_admin_login': False})

# -------------------- Routes --------------------

@app.route('/')
def home():
    return redirect('/login')

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        uname = request.form['username']
        pwd = request.form['password']

        if uname == 'admin' and is_admin_locked():
            flash('Admin login is locked.')
            return redirect(url_for('login'))

        user = get_user_from_firebase(uname)
        if user and user['password'] == pwd:
            session['username'] = uname
            session['role'] = user['role']
            return redirect('/admin' if user['role'] == 'admin' else '/user')
        else:
            flash("Invalid credentials")
    return render_template('login.html')

@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        add_user_to_firebase(
            request.form['username'],
            request.form['password'],
            request.form['role']
        )
        return redirect('/login')
    return render_template('signup.html')

@app.route('/admin')
def admin_home():
    if session.get('role') == 'admin':
        return render_template('admin_home.html', products=get_all_products())
    return redirect('/login')

@app.route('/user')
def user_home():
    if session.get('role') == 'user':
        return render_template('user_home.html', products=get_all_products())
    return redirect('/login')

@app.route('/add_product', methods=['POST'])
def add_product():
    if session.get('role') != 'admin':
        return redirect('/login')

    image_filename = upload_image(request.files['image'])
    add_product_to_firebase(
        request.form['name'],
        float(request.form['price']),
        int(request.form['stock']),
        image_filename
    )
    return redirect('/admin')

@app.route('/order/<product_id>', methods=['POST'])
def order(product_id):
    if session.get('role') != 'user':
        return redirect('/login')

    quantity = int(request.form['quantity'])
    product_ref = db.collection('products').document(product_id)
    product = product_ref.get().to_dict()

    if product and product['stock'] >= quantity:
        save_order_to_firebase(session['username'], product_id, quantity)
        product_ref.update({'stock': product['stock'] - quantity})
    else:
        flash("Not enough stock!")

    return redirect('/user')

@app.route('/checkout')
def checkout():
    if session.get('role') != 'user':
        return redirect('/login')

    orders = [o.to_dict() for o in db.collection('orders').where('username', '==', session['username']).stream()]
    products = {p['id']: p for p in get_all_products()}

    total = 0
    detailed_orders = []
    for o in orders:
        product = products.get(o['product_id'])
        if product:
            subtotal = product['price'] * o['quantity']
            total += subtotal
            detailed_orders.append({
                **o,
                'product_name': product['name'],
                'price': product['price'],
                'subtotal': subtotal
            })

    return render_template('checkout.html', orders=detailed_orders, total=total)

@app.route('/admin/products', methods=['GET', 'POST'])
def admin_products():
    if session.get('role') != 'admin':
        return redirect('/login')

    if request.method == 'POST':
        image_filename = upload_image(request.files['image'])
        add_product_to_firebase(
            request.form['name'],
            float(request.form['price']),
            int(request.form['stock']),
            image_filename
        )
        return redirect('/admin/products')

    return render_template('admin_products.html', products=get_all_products())

@app.route('/admin/orders')
def admin_orders():
    if session.get('role') != 'admin':
        return redirect('/login')

    orders = [o.to_dict() for o in db.collection('orders').stream()]
    products = {p['id']: p for p in get_all_products()}

    return render_template('admin_orders.html', orders=orders, products=products)

@app.route('/admin/users', methods=['GET', 'POST'])
def admin_users():
    if session.get('role') != 'admin':
        return redirect('/login')

    if request.method == 'POST':
        user_to_remove = request.form.get('remove_user')
        if user_to_remove:
            db.collection('users').document(user_to_remove).delete()

    users = [{'username': u.id, **u.to_dict()} for u in db.collection('users').stream()]
    return render_template('admin_users.html', users=users)

@app.route('/admin/lock', methods=['POST'])
def lock_admin():
    if session.get('role') != 'admin':
        return redirect('/login')

    if request.form['action'] == 'lock':
        lock_admin_login()
    elif request.form['action'] == 'unlock':
        unlock_admin_login()

    return redirect('/admin')

@app.route('/admin/product/<product_id>')
def view_product(product_id):
    if session.get('role') != 'admin':
        return redirect('/login')

    product_ref = db.collection('products').document(product_id)
    product_doc = product_ref.get()

    if product_doc.exists:
        product = product_doc.to_dict()
        product['id'] = product_id
        return render_template('view_product.html', product=product)
    return "Product not found", 404

# -------------------- Main --------------------

if __name__ == '__main__':
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)
    app.run(debug=True)
