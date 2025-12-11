import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from datetime import datetime, date, timedelta
import sqlite3
from openpyxl import Workbook
import shutil
from PIL import Image

try:
    from pyzbar import pyzbar
except (ImportError, OSError) as e:
    print(f"Warning: pyzbar library could not be loaded. Barcode scanning will be disabled. Error: {e}")
    print("This might be because the ZBar C-library is not installed or its DLLs are not found.")
    pyzbar = None

try:
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    import matplotlib.pyplot as plt
    matplotlib_available = True
except ImportError:
    matplotlib_available = False
    print("Warning: Matplotlib is not installed. Charts will be disabled. Install it with: pip install matplotlib")

try:
    import barcode
    from barcode.writer import ImageWriter
    from svglib.svglib import svg2rlg
    from reportlab.graphics import renderPM
    barcode_libs_available = True
except ImportError:
    barcode_libs_available = False

# === الإعدادات الأساسية ===
DB_NAME = "store.db"
current_user = None
current_role = None
current_user_permissions = {}
LOW_STOCK_THRESHOLD = 5
THEMES = {
    "light": {
        "bg": "#f0f0f0", "fg": "black",
        "sidebar_bg": "#2C3E50", "sidebar_fg": "white",
        "button_bg": "#34495E", "button_fg": "white",
        "accent_bg": "#007BFF", "accent_fg": "white",
        "entry_bg": "white", "entry_fg": "black",
        "tree_bg": "white", "tree_fg": "black", "tree_heading_bg": "#f0f0f0",
        "danger_bg": "#DC3545", "warning_bg": "#FFC107", "warning_fg": "black"
    },
    "dark": {
        "bg": "#2E2E2E", "fg": "white",
        "sidebar_bg": "#1C1C1C", "sidebar_fg": "white",
        "button_bg": "#4A4A4A", "button_fg": "white",
        "accent_bg": "#005CBF", "accent_fg": "white",
        "entry_bg": "#3E3E3E", "entry_fg": "white",
        "tree_bg": "#3E3E3E", "tree_fg": "white", "tree_heading_bg": "#2E2E2E",
        "danger_bg": "#A52A2A", "warning_bg": "#D29900", "warning_fg": "black"
    }
    ,
    "vibrant": {
        "bg": "#F5F5F5", "fg": "#212121",
        "sidebar_bg": "#008080", "sidebar_fg": "white",
        "button_bg": "#006666", "button_fg": "white",
        "accent_bg": "#FF7F50", "accent_fg": "white",
        "entry_bg": "white", "entry_fg": "black",
        "tree_bg": "white", "tree_fg": "black", "tree_heading_bg": "#E0E0E0",
        "danger_bg": "#DC3545", "warning_bg": "#FFC107", "warning_fg": "black"
    }
}
current_theme_name = 'light'

def get_theme():
    return THEMES[current_theme_name]

def set_theme(theme_name):
    global current_theme_name
    current_theme_name = theme_name if theme_name in THEMES else 'light'


# === 1. إنشاء قاعدة البيانات ===
def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS employees (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        role TEXT NOT NULL,
        password TEXT NOT NULL,
        can_apply_discount INTEGER NOT NULL DEFAULT 0
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL UNIQUE,
        cost_price REAL NOT NULL,
        sell_price REAL NOT NULL,
        quantity INTEGER NOT NULL,
        expiry_date TEXT,
        supplier TEXT
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS sales (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        invoice_id TEXT NOT NULL,
        product_name TEXT NOT NULL,
        sell_price REAL NOT NULL,
        quantity INTEGER NOT NULL DEFAULT 1,
        sale_time TEXT NOT NULL
    )
    ''')

    cursor.execute('''
    CREATE TABLE IF NOT EXISTS settings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_name TEXT UNIQUE,
        last_login_role TEXT,
        theme TEXT DEFAULT 'light',
        language TEXT DEFAULT 'ar'
    )
    ''')

    # إضافة أعمدة إذا كانت مفقودة
    for col_def in ["invoice_id TEXT", "quantity INTEGER DEFAULT 1"]:
        try:
            cursor.execute(f"ALTER TABLE sales ADD COLUMN {col_def}")
        except sqlite3.OperationalError:
            pass
    # التأكد من وجود عمود السمة
    try:
        cursor.execute("ALTER TABLE settings ADD COLUMN theme TEXT DEFAULT 'light'")
    except sqlite3.OperationalError:
            pass

    # إضافة عمود المورد
    try:
        cursor.execute("ALTER TABLE products ADD COLUMN supplier TEXT")
    except sqlite3.OperationalError:
        pass

    # التأكد من وجود عمود الصلاحيات
    try:
        cursor.execute("ALTER TABLE employees ADD COLUMN can_apply_discount INTEGER NOT NULL DEFAULT 0")
    except sqlite3.OperationalError:
        pass

    # إنشاء حسابات افتراضية
    defaults = [("مدير", "مدير", "123"), ("بائع", "بائع", "456"), ("مخزن", "مخزن", "789")]
    for name, role, pwd in defaults:
        cursor.execute("SELECT 1 FROM employees WHERE name = ?", (name,))
        if not cursor.fetchone():
            cursor.execute("INSERT INTO employees (name, role, password) VALUES (?, ?, ?)", (name, role, pwd))
    # منح صلاحية الخصم للمدير
    cursor.execute("UPDATE employees SET can_apply_discount = 1 WHERE role = 'مدير'")

    conn.commit()
    conn.close()

from contextlib import contextmanager

@contextmanager
def db_context():
    """مدير سياق للاتصال بقاعدة البيانات لضمان الفتح والإغلاق."""
    conn = sqlite3.connect(DB_NAME)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()

def save_user_settings(user_name, role, theme):
    with db_context() as conn:
        conn.execute("INSERT OR REPLACE INTO settings (id, user_name, last_login_role, theme) VALUES (1, ?, ?, ?)",
                     (user_name, role, theme))

def load_user_settings():
    with db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT user_name, last_login_role, theme FROM settings WHERE id = 1")
        return cursor.fetchone()

# === 2. دوال قاعدة البيانات ===
def get_employee(name, password):
    with db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name, role, can_apply_discount FROM employees WHERE name = ? AND password = ?", (name, password))
        return cursor.fetchone()

def get_all_employees(filter_name=""):
    with db_context() as conn:
        cursor = conn.cursor()
        if filter_name:
            cursor.execute("SELECT id, name, role FROM employees WHERE name LIKE ?", (f"%{filter_name}%",))
        else:
            cursor.execute("SELECT id, name, role FROM employees")
        return cursor.fetchall()

def get_employee_details(employee_id):
    with db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, role, can_apply_discount FROM employees WHERE id = ?", (employee_id,))
        return cursor.fetchone()

def get_products_filtered(filter_name="", expiry_filter=""):
    with db_context() as conn:
        cursor = conn.cursor()
        query = "SELECT id, name, cost_price, sell_price, quantity, expiry_date, supplier FROM products"
        params = []
        conditions = []

        if filter_name:
            conditions.append("name LIKE ?")
            params.append(f"%{filter_name}%")
        
        if expiry_filter:
            try:
                # التأكد من أن التاريخ صالح قبل إضافته للاستعلام
                datetime.strptime(expiry_filter, "%Y-%m-%d")
                conditions.append("expiry_date <= ?")
                params.append(expiry_filter)
            except ValueError:
                pass # تجاهل فلتر التاريخ إذا كان التنسيق غير صحيح

        if conditions:
            query += " WHERE " + " AND ".join(conditions)
        cursor.execute(query, tuple(params))
        rows = cursor.fetchall()
        return [
            {
                'id': r[0], 'name': r[1], 'cost_price': r[2],
                'sell_price': r[3], 'quantity': r[4], 'expiry_date': r[5], 'supplier': r[6]
            }
            for r in rows
        ]

def get_product_by_barcode(barcode):
    with db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT name, sell_price, quantity FROM products WHERE name = ?", (barcode,))
        result = cursor.fetchone()
        if result:
            return {'name': result[0], 'sell_price': result[1], 'quantity': result[2]}
        return None

def add_product_to_db(name, cost, sell, qty, expiry_str, supplier):
    with db_context() as conn:
        try:
            conn.execute('''
            INSERT INTO products (name, cost_price, sell_price, quantity, expiry_date, supplier)
            VALUES (?, ?, ?, ?, ?, ?)
            ''', (name, cost, sell, qty, expiry_str, supplier))
            return True
        except sqlite3.IntegrityError:
            return False

def delete_product_from_db(name):
    with db_context() as conn:
        conn.execute("DELETE FROM products WHERE name = ?", (name,))

def update_product_in_db(product_id, name, cost, sell, qty, expiry_str, supplier):
    with db_context() as conn:
        try:
            conn.execute('''
            UPDATE products 
            SET name = ?, cost_price = ?, sell_price = ?, quantity = ?, expiry_date = ?, supplier = ?
            WHERE id = ?
            ''', (name, cost, sell, qty, expiry_str, supplier, product_id))
            return True, ""
        except sqlite3.IntegrityError:
            return False, "اسم المنتج مستخدم مسبقًا."

def delete_employee_from_db(employee_id):
    with db_context() as conn:
        conn.execute("DELETE FROM employees WHERE id = ?", (employee_id,))

def update_employee_in_db(employee_id, role, can_apply_discount, password=None):
    with db_context() as conn:
        if password:
            conn.execute("UPDATE employees SET role = ?, password = ?, can_apply_discount = ? WHERE id = ?", (role, password, can_apply_discount, employee_id))
        else:
            conn.execute("UPDATE employees SET role = ?, can_apply_discount = ? WHERE id = ?", (role, can_apply_discount, employee_id))
        return True

def update_user_credentials(old_username, new_username=None, new_password=None):
    if not new_username and not new_password:
        return True, ""

    with db_context() as conn:
        updates = []
        params = []
        if new_username:
            updates.append("name = ?")
            params.append(new_username)
        if new_password:
            updates.append("password = ?")
            params.append(new_password)
        
        params.append(old_username)
        query = f"UPDATE employees SET {', '.join(updates)} WHERE name = ?"
        
        try:
            conn.execute(query, tuple(params))
            return True, ""
        except sqlite3.IntegrityError:
            return False, "اسم المستخدم الجديد مستخدم مسبقًا."

def generate_invoice_id():
    today = datetime.now().strftime("%Y%m%d")
    with db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(DISTINCT invoice_id) FROM sales WHERE invoice_id LIKE ?", (f"INV-{today}%",))
        count = cursor.fetchone()[0] + 1
        return f"INV-{today}-{count:03d}"

def sell_product(product_name, sell_price, quantity):
    with db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT quantity FROM products WHERE name = ?", (product_name,))
        row = cursor.fetchone()
        if not row:
            return False, "المنتج غير موجود"
        current_qty = row[0]
        if current_qty < quantity:
            return False, f"الكمية غير كافية! المتوفر: {current_qty}"
        
        new_qty = current_qty - quantity
        cursor.execute("UPDATE products SET quantity = ? WHERE name = ?", (new_qty, product_name))
        
        # This logic for invoice ID generation is complex and might lead to race conditions.
        # A simpler approach would be to use the last sale's invoice ID if it's for the same cart.
        # For now, we assume it works for this single-user context.
        today = datetime.now().strftime("%Y%m%d")
        cursor.execute("SELECT COUNT(DISTINCT invoice_id) FROM sales WHERE invoice_id LIKE ?", (f"INV-{today}%",))
        count = cursor.fetchone()[0]
        cursor.execute("SELECT invoice_id FROM sales WHERE invoice_id LIKE ? ORDER BY id DESC LIMIT 1", (f"INV-{today}%",))
        last_invoice = cursor.fetchone()
        if last_invoice and last_invoice[0].endswith(f"{count:03d}"):
            invoice_id = last_invoice[0]
        else:
            invoice_id = f"INV-{today}-{count + 1:03d}"
        sale_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cursor.execute('''
        INSERT INTO sales (invoice_id, product_name, sell_price, quantity, sale_time)
        VALUES (?, ?, ?, ?, ?)
        ''', (invoice_id, product_name, sell_price, quantity, sale_time))
        return True, invoice_id

def get_sales_by_invoice(invoice_id):
    with db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT product_name, sell_price, quantity, sale_time FROM sales WHERE invoice_id = ?", (invoice_id,))
        return cursor.fetchall()

def get_daily_sales(target_date):
    with db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT
                s.invoice_id,
                s.product_name,
                s.sell_price,
                s.quantity,
                p.cost_price
            FROM sales s
            JOIN products p ON s.product_name = p.name
            WHERE date(s.sale_time) = ?
        ''', (target_date,))
        return cursor.fetchall()

def get_all_invoices():
    """تجلب قائمة بجميع الفواتير مع إجمالي كل فاتورة."""
    with db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT
                invoice_id,
                MIN(sale_time),
                SUM(sell_price * quantity)
            FROM sales
            GROUP BY invoice_id
            ORDER BY MIN(sale_time) DESC
        ''')
        return cursor.fetchall()

def get_sales_summary_last_7_days():
    """تجلب ملخص المبيعات لآخر 7 أيام."""
    with db_context() as conn:
        cursor = conn.cursor()
        seven_days_ago = (datetime.now() - timedelta(days=6)).strftime('%Y-%m-%d')
        cursor.execute('''
            SELECT
                date(sale_time) as sale_date,
                SUM(sell_price * quantity) as total_sales
            FROM sales
            WHERE date(sale_time) >= ?
            GROUP BY sale_date
            ORDER BY sale_date ASC
        ''', (seven_days_ago,))
        return cursor.fetchall()

def get_best_selling_products(limit=10):
    """Fetches the best-selling products based on quantity sold."""
    with db_context() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT
                product_name,
                SUM(quantity) as total_quantity
            FROM sales
            GROUP BY product_name
            ORDER BY total_quantity DESC
            LIMIT ?
        ''', (limit,))
        return cursor.fetchall()

def check_expiry_alerts():
    products = get_products_filtered()
    today = date.today()
    alerts = []
    for p in products:
        if p['expiry_date']:
            try:
                exp_date = datetime.strptime(p['expiry_date'], "%Y-%m-%d").date()
                if 0 <= (exp_date - today).days <= 15:
                    alerts.append(f"{p['name']} — ينتهي في: {p['expiry_date']}")
            except (ValueError, TypeError): continue
    if alerts:
        messagebox.showwarning("تنبيه انتهاء الصلاحية", "\n".join(alerts))

# === 3. دوال واجهة المستخدم ===
def create_sidebar(parent, buttons):
    theme = get_theme()
    sidebar = tk.Frame(parent, bg=theme['sidebar_bg'], width=200)
    sidebar.pack(side=tk.RIGHT, fill=tk.Y)
    for text, command in buttons:
        btn = tk.Button(sidebar, text=text, command=command, bg=theme['button_bg'], fg=theme['button_fg'], font=("Arial", 11, "bold"), height=1, width=15)
        btn.pack(pady=5, padx=10, fill=tk.X)
    return sidebar

def create_search_bar(parent, on_search):
    theme = get_theme()
    frame = tk.Frame(parent, bg=theme['bg'])
    frame.pack(pady=5)
    tk.Label(frame, text="بحث باسم المنتج:", bg=theme['bg'], fg=theme['fg']).pack(side=tk.LEFT)
    entry = tk.Entry(frame, width=30, bg=theme['entry_bg'], fg=theme['entry_fg'])
    entry.pack(side=tk.LEFT, padx=5)
    tk.Button(frame, text="بحث", command=lambda: on_search(entry.get().strip()), bg=theme['accent_bg'], fg=theme['accent_fg'], font=("Arial", 10, "bold")).pack(side=tk.LEFT)
    entry.bind("<Return>", lambda e: on_search(entry.get().strip()))
    return entry

def create_product_search_frame(parent, on_search):
    theme = get_theme()
    frame = tk.Frame(parent, bg=theme['bg'])
    frame.pack(pady=5, fill=tk.X)

    tk.Label(frame, text="بحث بالاسم:", bg=theme['bg'], fg=theme['fg']).pack(side=tk.RIGHT, padx=(0, 5))
    name_entry = tk.Entry(frame, width=25, bg=theme['entry_bg'], fg=theme['entry_fg'])
    name_entry.pack(side=tk.RIGHT, padx=5)

    tk.Label(frame, text="بحث بتاريخ الصلاحية (YYYY-MM-DD):", bg=theme['bg'], fg=theme['fg']).pack(side=tk.RIGHT, padx=(0, 5))
    expiry_entry = tk.Entry(frame, width=20, bg=theme['entry_bg'], fg=theme['entry_fg'])
    expiry_entry.pack(side=tk.RIGHT, padx=5)

    def do_search():
        on_search(name_filter=name_entry.get().strip(), expiry_filter=expiry_entry.get().strip())

    tk.Button(frame, text="بحث", command=do_search, bg=theme['accent_bg'], fg=theme['accent_fg'], font=("Arial", 10, "bold")).pack(side=tk.RIGHT)
    return name_entry, expiry_entry

def apply_theme_to_widgets(widget_list):
    theme = get_theme()
    for widget in widget_list:
        widget_type = widget.winfo_class()
        try:
            if widget_type in ('Frame', 'TFrame', 'Labelframe'):
                widget.configure(bg=theme['bg'])
            elif widget_type in ('Label', 'TLabel'):
                widget.configure(bg=theme['bg'], fg=theme['fg'])
            elif widget_type in ('Entry', 'TEntry', 'Text'):
                widget.configure(bg=theme['entry_bg'], fg=theme['entry_fg'], insertbackground=theme['fg'])
            elif widget_type in ('Button', 'TButton'):
                # This is tricky as buttons are styled in create_sidebar etc.
                # We can check for specific buttons if needed.
                if widget.master.winfo_class() != 'Frame': # Avoid sidebar buttons
                    widget.configure(bg=theme['accent_bg'], fg=theme['accent_fg'], font=("Arial", 11, "bold"))
            elif widget_type == 'Treeview':
                style = ttk.Style()
                style.configure("Treeview", background=theme['tree_bg'], foreground=theme['tree_fg'], fieldbackground=theme['tree_bg'], font=("Arial", 12, "bold"), rowheight=30)
                style.map('Treeview', background=[('selected', theme['accent_bg'])])
                style.configure("Treeview.Heading", background=theme['tree_heading_bg'], foreground=theme['fg'], font=("Arial", 11, "bold"))
        except tk.TclError:
            pass # Some widgets might not support all options

def apply_theme_globally():
    theme = get_theme()
    root.configure(bg=theme['bg'])
    
    all_widgets = []
    def collect_widgets(parent):
        for child in parent.winfo_children():
            all_widgets.append(child)
            collect_widgets(child)
    collect_widgets(root)
    apply_theme_to_widgets(all_widgets)

def toggle_theme():
    global current_theme_name
    theme_cycle = ['light', 'dark', 'vibrant']
    try:
        current_index = theme_cycle.index(current_theme_name)
        new_theme = theme_cycle[(current_index + 1) % len(theme_cycle)]
    except ValueError:
        new_theme = 'light' # Fallback
    set_theme(new_theme)
    save_user_settings(current_user, current_role, new_theme)
    apply_theme_globally()

# === 4. واجهة تسجيل الدخول ===
def login_screen():
    global current_user, current_role, current_user_permissions
    for widget in root.winfo_children():
        widget.destroy()
    
    root.geometry("400x350")
    root.resizable(False, False)

    tk.Label(root, text="تسجيل الدخول", font=("Arial", 24, "bold")).pack(pady=30)

    tk.Label(root, text="اسم المستخدم:", font=("Arial", 12)).pack()
    name_entry = tk.Entry(root, width=30, font=("Arial", 12))
    user_settings = load_user_settings()
    if user_settings:
        name_entry.insert(0, user_settings[0])
    name_entry.pack(pady=5)

    tk.Label(root, text="كلمة المرور:", font=("Arial", 12)).pack()
    pass_entry = tk.Entry(root, show="*", width=30, font=("Arial", 12))
    pass_entry.pack(pady=5)

    def handle_login():
        global current_user, current_role, current_user_permissions
        name = name_entry.get().strip()
        pwd = pass_entry.get().strip()
        if not name or not pwd:
            messagebox.showwarning("تحذير", "الرجاء إدخال اسم المستخدم وكلمة المرور")
            return
        emp = get_employee(name, pwd)
        if emp:
            current_user, current_role, can_discount = emp
            current_user_permissions = {'can_apply_discount': bool(can_discount)}
            save_user_settings(current_user, current_role, current_theme_name)
            if current_role == "مدير":
                manager_interface()
            elif current_role == "بائع":
                seller_interface()
            elif current_role == "مخزن":
                warehouse_interface()
            else:
                messagebox.showerror("خطأ", "دور غير مدعوم")
        else:
            messagebox.showerror("خطأ", "اسم المستخدم أو كلمة المرور غير صحيحة")

    tk.Button(root, text="تسجيل الدخول", command=handle_login, width=20, font=("Arial", 12, "bold")).pack(pady=20)

    pass_entry.bind("<Return>", lambda e: handle_login())
    name_entry.bind("<Return>", lambda e: pass_entry.focus())
    
    apply_theme_globally()

# === 5. واجهات المستخدم ===
def manager_interface():
    root.geometry("1200x700")
    root.resizable(True, True)

    for widget in root.winfo_children():
        widget.destroy()

    buttons = [
        ("الرئيسية", manager_interface),
        ("الانتقال لواجهة البائع", lambda: seller_interface(came_from_manager=True)),
        ("الانتقال لواجهة المخزن", lambda: warehouse_interface(came_from_manager=True)),
        ("إضافة منتج", lambda: add_product_popup(load_products)),
        ("تعديل المنتج", lambda: edit_selected_product(tree, load_products)),
        ("إضافة موظف", add_employee_popup),
        ("عرض الموظفين", show_employees_window),
        ("تغيير معلومات الدخول", change_credentials_popup),
        ("تبديل السمة", toggle_theme),
        ("طباعة ملصق باركود", lambda: print_barcode_for_selected_product(tree)),
        ("استعراض الفواتير", show_invoices_list_window),
        ("تصدير تقرير", export_daily_report),
        ("نسخ احتياطي", backup_database),
        ("استعادة", restore_database),
        ("تسجيل خروج", login_screen),
    ]
    create_sidebar(root, buttons)

    main_frame = tk.Frame(root)
    main_frame.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)

    content_frame = tk.Frame(main_frame)
    content_frame.pack(fill=tk.BOTH, expand=True)

    products_frame = tk.Frame(content_frame)
    products_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 10))

    right_panel_frame = tk.Frame(content_frame, width=300)
    right_panel_frame.pack(side=tk.RIGHT, fill=tk.Y)
    right_panel_frame.pack_propagate(False)

    bestsellers_frame = tk.Frame(right_panel_frame)
    bestsellers_frame.pack(fill=tk.BOTH, expand=True)
    
    bottom_frame = tk.Frame(main_frame, height=250)
    bottom_frame.pack(fill=tk.X, pady=(10, 0))

    tk.Label(products_frame, text="قائمة المنتجات", font=("Arial", 16, "bold")).pack(pady=10)

    def load_products(name_filter="", expiry_filter=""):
        for row in tree.get_children():
            tree.delete(row)
        products = get_products_filtered(name_filter, expiry_filter)
        for p in products:
            exp_str = p.get('expiry_date') or "غير محدد"
            supplier_str = p.get('supplier') or "غير محدد"
            tree.insert("", "end", values=(p['id'], p['name'], p['sell_price'], p['quantity'], exp_str, supplier_str))
        check_expiry_alerts()

    columns = ("id", "name", "price", "qty", "expiry", "supplier")
    tree = ttk.Treeview(products_frame, columns=columns, show="headings", height=8)
    tree.column("id", width=40)
    for col, txt in zip(columns, ["ID", "الاسم", "سعر البيع", "الكمية", "الصلاحية", "المورد"]):
        tree.heading(col, text=txt)
    tree.pack(pady=10, fill=tk.BOTH, expand=True)

    # إضافة ألوان للمخزون
    theme = get_theme()
    tree.tag_configure('out_of_stock', background=theme['danger_bg'], foreground='white')
    tree.tag_configure('low_stock', background=theme['warning_bg'], foreground=theme['warning_fg'])

    create_product_search_frame(products_frame, load_products)

    # عرض المنتجات الأكثر مبيعاً
    tk.Label(bestsellers_frame, text="الأكثر مبيعاً", font=("Arial", 16, "bold")).pack(pady=10)
    bestsellers_tree = ttk.Treeview(bestsellers_frame, columns=("name", "qty"), show="headings", height=8)
    bestsellers_tree.heading("name", text="المنتج")
    bestsellers_tree.heading("qty", text="الكمية المباعة")
    bestsellers_tree.column("qty", width=100, anchor='center')
    bestsellers_tree.pack(fill=tk.BOTH, expand=True)
    for name, qty_sold in get_best_selling_products():
        bestsellers_tree.insert("", "end", values=(name, qty_sold))

    def create_sales_chart(parent):
        if not matplotlib_available:
            tk.Label(parent, text="مكتبة Matplotlib غير مثبتة. لا يمكن عرض الرسوم البيانية.").pack()
            return

        data = get_sales_summary_last_7_days()
        dates = [datetime.strptime(row[0], '%Y-%m-%d').strftime('%m-%d') for row in data]
        sales = [row[1] for row in data]

        theme = get_theme()
        plt.style.use('seaborn-v0_8-darkgrid' if current_theme_name == 'dark' else 'seaborn-v0_8-pastel')

        fig = Figure(figsize=(8, 3), dpi=100)
        fig.patch.set_facecolor(theme['bg'])
        ax = fig.add_subplot(111)
        ax.set_facecolor(theme['bg'])

        ax.bar(dates, sales, color=theme['accent_bg'])
        ax.set_ylabel("إجمالي المبيعات", color=theme['fg'])
        ax.set_xlabel("التاريخ", color=theme['fg'])
        ax.tick_params(axis='x', colors=theme['fg'])
        ax.tick_params(axis='y', colors=theme['fg'])
        fig.tight_layout()

        canvas = FigureCanvasTkAgg(fig, master=parent)
        canvas.draw()
        canvas.get_tk_widget().pack(fill=tk.BOTH, expand=True)

    create_sales_chart(bottom_frame)
    load_products()
    apply_theme_globally()

def warehouse_interface(came_from_manager=False):
    root.geometry("1200x700")
    root.resizable(True, True)

    for widget in root.winfo_children():
        widget.destroy()

    tk.Label(root, text="واجهة المخزن", font=("Arial", 18, "bold")).pack(pady=10)

    def load_products(name_filter="", expiry_filter=""):
        for row in tree.get_children():
            tree.delete(row)
        products = get_products_filtered(name_filter, expiry_filter) #
        for p in products:
            exp_str = p.get('expiry_date') or "غير محدد"
            supplier_str = p.get('supplier') or "غير محدد"
            tree.insert("", "end", values=(p['name'], p['sell_price'], p['quantity'], exp_str, supplier_str))
        check_expiry_alerts()

    columns = ("name", "price", "qty", "expiry", "supplier")
    tree = ttk.Treeview(root, columns=columns, show="headings", height=15)
    for col, txt in zip(columns, ["الاسم", "سعر البيع", "الكمية", "الصلاحية", "المورد"]):
        tree.heading(col, text=txt)
    tree.pack(pady=10, fill=tk.BOTH, expand=True)

    # إضافة ألوان للمخزون
    theme = get_theme()
    tree.tag_configure('out_of_stock', background=theme['danger_bg'], foreground='white')
    tree.tag_configure('low_stock', background=theme['warning_bg'], foreground=theme['warning_fg'])

    buttons = [
        ("الرئيسية", lambda: warehouse_interface(came_from_manager=came_from_manager)),
        ("إضافة منتج", lambda: add_product_popup(load_products)),
        ("حذف منتج", lambda: delete_selected(tree, load_products)),
        ("تسجيل خروج", login_screen),
    ]
    if came_from_manager:
        buttons.insert(1, ("العودة للمدير", manager_interface))
    create_sidebar(root, buttons)

    create_product_search_frame(root, load_products)
    load_products()
    apply_theme_globally()


def seller_interface(came_from_manager=False):
    root.geometry("1200x700")
    root.resizable(True, True)

    for widget in root.winfo_children():
        widget.destroy()

    # --- Nested Functions for Seller Interface ---
    def add_to_cart():
        sel = prod_tree.selection()
        if not sel: return
        item = prod_tree.item(sel[0])
        name, price, qty_avail = item['values']
        if qty_avail <= 0:
            messagebox.showwarning("نفدت الكمية", f"المنتج {name} غير متوفر")
            return
        for c in cart:
            if c['name'] == name:
                c['quantity'] += 1
                update_invoice()
                return
        cart.append({'name': name, 'price': float(price), 'quantity': 1})
        update_invoice()

    def scan_barcode():
        if not pyzbar:
            messagebox.showerror("خطأ", "يرجى تثبيت pyzbar:\npip install pyzbar")
            return
        file_path = filedialog.askopenfilename(
            title="اختر صورة باركود",
            filetypes=[("Image files", "*.jpg *.jpeg *.png *.bmp")]
        )
        if not file_path:
            return
        try:
            image = Image.open(file_path)
            barcodes = pyzbar.decode(image)
            if not barcodes:
                messagebox.showwarning("لا يوجد باركود", "لم يتم العثور على باركود في الصورة")
                return
            barcode_data = barcodes[0].data.decode("utf-8")
            product = get_product_by_barcode(barcode_data)
            if product:
                if product['quantity'] <= 0:
                    messagebox.showwarning("نفدت الكمية", f"المنتج {product['name']} غير متوفر")
                    return
                for c in cart:
                    if c['name'] == product['name']:
                        c['quantity'] += 1
                        update_invoice()
                        return
                cart.append({'name': product['name'], 'price': product['sell_price'], 'quantity': 1})
                update_invoice()
                messagebox.showinfo("تم", f"تمت إضافة المنتج:\n{product['name']}")
            else:
                messagebox.showerror("غير موجود", f"المنتج بالباركود:\n{barcode_data}\nغير مسجل في المخزن")
        except Exception as e:
            messagebox.showerror("خطأ", f"فشل في قراءة الباركود:\n{e}")

    def update_invoice():
        theme = get_theme()
        invoice_text.delete(1.0, tk.END)
        subtotal = 0
        for item in cart:
            line_total = item['price'] * item['quantity']
            invoice_text.insert(tk.END, f"{item['name']} × {item['quantity']} = {line_total:.2f}\n")
            subtotal += line_total
        
        discount_percentage = 0
        try:
            discount_val = discount_entry.get()
            if discount_val:
                discount_percentage = float(discount_val)
        except (ValueError, TypeError):
            discount_percentage = 0

        discount_amount = (subtotal * discount_percentage) / 100
        final_total = subtotal - discount_amount

        subtotal_label.config(text=f"المجموع الفرعي: {subtotal:.2f}")
        discount_amount_label.config(text=f"الخصم ({discount_percentage}%): -{discount_amount:.2f}", fg=theme['danger_bg'])
        total_label.config(text=f"الإجمالي النهائي: {final_total:.2f}")

    def finalize_sale():
        if not cart:
            messagebox.showwarning("فاتورة فارغة", "لا يوجد منتجات")
            return
        all_success = True
        invoice_id = None

        discount_percentage = 0
        try:
            discount_val = discount_entry.get()
            if discount_val:
                discount_percentage = float(discount_val)
        except (ValueError, TypeError):
            discount_percentage = 0
        
        discount_factor = 1 - (discount_percentage / 100)

        for item in cart:
            discounted_price = item['price'] * discount_factor
            success, msg = sell_product(item['name'], discounted_price, item['quantity'])
            if not success:
                messagebox.showerror("خطأ في البيع", msg)
                all_success = False
                break
            else:
                invoice_id = msg
        if all_success:
            export_invoice_to_excel(invoice_id)
            messagebox.showinfo("تم البيع", f"تم إنشاء الفاتورة:\n{invoice_id}")
            cart.clear()
            update_invoice()
            load_products()

    def preview_invoice_popup():
        if not cart:
            messagebox.showwarning("فاتورة فارغة", "لا يوجد منتجات في الفاتورة")
            return

        win = tk.Toplevel()
        win.title("معاينة الفاتورة")
        win.geometry("500x400")
        apply_theme_to_widgets([win])

        tk.Label(win, text="معاينة الفاتورة", font=("Arial", 14, "bold")).pack(pady=10)

        columns = ("name", "price", "qty", "subtotal")
        tree = ttk.Treeview(win, columns=columns, show="headings")
        tree.heading("name", text="المنتج")
        tree.heading("price", text="السعر")
        tree.heading("qty", text="الكمية")
        tree.heading("subtotal", text="المجموع الفرعي")
        tree.pack(pady=5, padx=10, fill=tk.BOTH, expand=True)

        subtotal = 0
        for item in cart:
            line_total = item['price'] * item['quantity']
            tree.insert("", "end", values=(item['name'], f"{item['price']:.2f}", item['quantity'], f"{line_total:.2f}"))
            subtotal += line_total

        discount_percentage = 0
        try:
            discount_val = discount_entry.get()
            if discount_val: discount_percentage = float(discount_val)
        except (ValueError, TypeError): pass

        discount_amount = (subtotal * discount_percentage) / 100
        final_total = subtotal - discount_amount

        total_frame_popup = tk.Frame(win)
        total_frame_popup.pack(pady=10, fill=tk.X, padx=10)
        tk.Label(total_frame_popup, text=f"المجموع الفرعي: {subtotal:.2f}", font=("Arial", 12)).pack(anchor='e')
        tk.Label(total_frame_popup, text=f"الخصم ({discount_percentage}%): -{discount_amount:.2f}", font=("Arial", 12), fg=get_theme()['danger_bg']).pack(anchor='e')
        tk.Label(total_frame_popup, text=f"الإجمالي النهائي: {final_total:.2f}", font=("Arial", 14, "bold")).pack(anchor='e')
        apply_theme_to_widgets(win.winfo_children())

    # Sidebar buttons
    buttons = [
        ("إضافة إلى الفاتورة", add_to_cart),
        ("قراءة باركود", scan_barcode),
        ("معاينة الفاتورة", preview_invoice_popup),
        ("تم البيع", finalize_sale),
        ("إلغاء", lambda: [cart.clear(), update_invoice()]),
        ("تسجيل خروج", login_screen),
    ]
    if came_from_manager:
        buttons.insert(0, ("العودة للمدير", manager_interface))
    create_sidebar(root, buttons)

    tk.Label(root, text="واجهة البائع", font=("Arial", 18, "bold")).pack(pady=10)

    def load_products(name_filter=""):
        for row in prod_tree.get_children():
            prod_tree.delete(row)
        products = get_products_filtered(name_filter)
        for p in products:
            prod_tree.insert("", "end", values=(p['name'], p['sell_price'], p['quantity']))

    columns = ("name", "price", "qty")
    prod_tree = ttk.Treeview(root, columns=columns, show="headings", height=10)
    prod_tree.heading("name", text="المنتج")
    prod_tree.heading("price", text="سعر البيع")
    prod_tree.heading("qty", text="الكمية")
    prod_tree.pack(pady=10, fill=tk.BOTH, expand=True)
    
    # إضافة ألوان للمخزون
    theme = get_theme()
    prod_tree.tag_configure('out_of_stock', background=theme['danger_bg'], foreground='white')
    prod_tree.tag_configure('low_stock', background=theme['warning_bg'], foreground=theme['warning_fg'])

    # إضافة شريط البحث
    create_search_bar(root, load_products)

    global cart
    cart = []
    invoice_frame = tk.Frame(root)
    invoice_frame.pack(pady=10, fill=tk.X)
    
    tk.Label(invoice_frame, text="الفاتورة", font=("Arial", 14, "bold")).pack()
    invoice_text = tk.Text(invoice_frame, height=8)
    invoice_text.pack(pady=5, fill=tk.X)

    discount_frame = tk.Frame(root)
    discount_frame.pack(pady=5, fill=tk.X)
    tk.Label(discount_frame, text="نسبة الخصم (%):").pack(side=tk.RIGHT, padx=5)
    discount_entry = tk.Entry(discount_frame, width=10)
    discount_entry.pack(side=tk.RIGHT) 
    discount_button = tk.Button(discount_frame, text="تطبيق الخصم", command=update_invoice, font=("Arial", 10, "bold"))
    discount_button.pack(side=tk.RIGHT, padx=5)

    total_frame = tk.Frame(root)
    total_frame.pack(pady=5, fill=tk.X)
    subtotal_label = tk.Label(total_frame, text="المجموع الفرعي: 0.00", font=("Arial", 12))
    subtotal_label.pack(anchor='e')
    discount_amount_label = tk.Label(total_frame, text="الخصم: -0.00", font=("Arial", 12))
    discount_amount_label.pack(anchor='e')
    total_label = tk.Label(total_frame, text="الإجمالي النهائي: 0.00", font=("Arial", 14, "bold"))
    total_label.pack(anchor='e')

    if not current_user_permissions.get('can_apply_discount', False):
        discount_entry.config(state=tk.DISABLED)
        discount_button.config(state=tk.DISABLED)

    apply_theme_globally()

    def export_invoice_to_excel(invoice_id):
        sales = get_sales_by_invoice(invoice_id)
        if not sales:
            return
        filepath = filedialog.asksaveasfilename(
            defaultextension=".xlsx",
            filetypes=[("Excel", "*.xlsx")],
            initialfile=f"{invoice_id}.xlsx"
        )
        if not filepath:
            return
        wb = Workbook()
        ws = wb.active
        ws.title = invoice_id
        ws.append(["فاتورة بيع"])
        ws.append(["رقم الفاتورة:", invoice_id])
        ws.append(["التاريخ:", sales[0][3][:10]])
        ws.append([])
        ws.append(["المنتج", "السعر", "الكمية", "المجموع"])
        total = 0
        for name, price, qty, _ in sales:
            line_total = price * qty
            ws.append([name, price, qty, line_total])
            total += line_total
        ws.append(["", "", "الإجمالي:", total])
        wb.save(filepath)

    load_products()
    apply_theme_globally()

# === 6. دوال الدعم ===
def add_product_popup(refresh_callback):
    win = tk.Toplevel()
    win.title("إضافة منتج")
    win.geometry("320x380")
    win.resizable(False, False)
    win.configure(bg=get_theme()['bg'])

    tk.Label(win, text="الاسم (يمكن أن يكون الباركود):").pack(pady=(10, 0))
    name_e = tk.Entry(win, width=35)
    name_e.pack()

    tk.Label(win, text="سعر الشراء (رقم عشري):").pack()
    cost_e = tk.Entry(win, width=35)
    cost_e.pack()

    tk.Label(win, text="سعر البيع (رقم عشري):").pack()
    sell_e = tk.Entry(win, width=35)
    sell_e.pack()

    tk.Label(win, text="الكمية (عدد صحيح):").pack()
    qty_e = tk.Entry(win, width=35)
    qty_e.pack()

    tk.Label(win, text="تاريخ الانتهاء (YYYY-MM-DD) [اختياري]:").pack()
    exp_e = tk.Entry(win, width=35)
    exp_e.pack()

    tk.Label(win, text="المورد [اختياري]:").pack()
    supplier_e = tk.Entry(win, width=35)
    supplier_e.pack()

    error_label = tk.Label(win, text="", fg="red")
    error_label.pack(pady=5)

    def save_prod():
        error_label.config(text="")

        name = name_e.get().strip()
        if not name:
            error_label.config(text="❌ الاسم مطلوب")
            return

        try:
            cost = float(cost_e.get().strip())
            if cost <= 0:
                error_label.config(text="❌ سعر الشراء يجب أن يكون > 0")
                return
        except ValueError:
            error_label.config(text="❌ سعر الشراء غير صحيح")
            return

        try:
            sell = float(sell_e.get().strip())
            if sell <= 0:
                error_label.config(text="❌ سعر البيع يجب أن يكون > 0")
                return
            if sell < cost:
                error_label.config(text="⚠️ سعر البيع أقل من سعر الشراء!")
        except ValueError:
            error_label.config(text="❌ سعر البيع غير صحيح")
            return

        try:
            qty = int(qty_e.get().strip())
            if qty < 0:
                error_label.config(text="❌ الكمية لا يمكن أن تكون سالبة")
                return
        except ValueError:
            error_label.config(text="❌ الكمية يجب أن تكون عددًا صحيحًا")
            return

        exp_str = exp_e.get().strip()
        if exp_str:
            try:
                datetime.strptime(exp_str, "%Y-%m-%d")
            except ValueError:
                error_label.config(text="❌ صيغة التاريخ: YYYY-MM-DD")
                return
        else:
            exp_str = None

        supplier = supplier_e.get().strip() or None

        if add_product_to_db(name, cost, sell, qty, exp_str, supplier):
            messagebox.showinfo("تم", f"✅ تم إضافة المنتج:\n{name}")
            refresh_callback()
            win.destroy()
        else:
            error_label.config(text="❌ اسم المنتج مستخدم مسبقًا")

    tk.Button(win, text="حفظ المنتج", command=save_prod, width=20, font=("Arial", 11, "bold")).pack(pady=15)
    
    # تطبيق السمة على النافذة المنبثقة
    apply_theme_to_widgets(win.winfo_children())

def edit_selected_product(tree, refresh_callback):
    selected = tree.selection()
    if not selected:
        messagebox.showwarning("تحذير", "الرجاء اختيار منتج لتعديله")
        return
    
    product_id = tree.item(selected[0])['values'][0]
    
    # جلب كل بيانات المنتج من قاعدة البيانات
    with db_context() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id, name, cost_price, sell_price, quantity, expiry_date, supplier FROM products WHERE id=?", (product_id,))
        product_data = cursor.fetchone()

    if not product_data:
        messagebox.showerror("خطأ", "لم يتم العثور على المنتج")
        return

    edit_product_popup(product_data, refresh_callback)

def edit_product_popup(product_data, refresh_callback):
    p_id, p_name, p_cost, p_sell, p_qty, p_expiry, p_supplier = product_data

    win = tk.Toplevel()
    win.title(f"تعديل المنتج: {p_name}")
    win.geometry("320x350")
    win.resizable(False, False)

    tk.Label(win, text="الاسم (يمكن أن يكون الباركود):").pack(pady=(10, 0)); name_e = tk.Entry(win, width=35); name_e.insert(0, p_name); name_e.pack()
    tk.Label(win, text="سعر الشراء:").pack(); cost_e = tk.Entry(win, width=35); cost_e.insert(0, p_cost); cost_e.pack()
    tk.Label(win, text="سعر البيع:").pack(); sell_e = tk.Entry(win, width=35); sell_e.insert(0, p_sell); sell_e.pack()
    tk.Label(win, text="الكمية:").pack(); qty_e = tk.Entry(win, width=35); qty_e.insert(0, p_qty); qty_e.pack()
    tk.Label(win, text="تاريخ الانتهاء (YYYY-MM-DD):").pack(); exp_e = tk.Entry(win, width=35); exp_e.insert(0, p_expiry or ""); exp_e.pack()
    tk.Label(win, text="المورد:").pack(); supplier_e = tk.Entry(win, width=35); supplier_e.insert(0, p_supplier or ""); supplier_e.pack()

    error_label = tk.Label(win, text="", fg="red")
    error_label.pack(pady=5)

    def save_changes():
        error_label.config(text="")
        name = name_e.get().strip()
        if not name:
            error_label.config(text="❌ الاسم مطلوب"); return

        try:
            cost = float(cost_e.get().strip())
            if cost <= 0:
                error_label.config(text="❌ سعر الشراء يجب أن يكون > 0"); return
        except ValueError:
            error_label.config(text="❌ سعر الشراء غير صحيح"); return

        try:
            sell = float(sell_e.get().strip())
            if sell <= 0:
                error_label.config(text="❌ سعر البيع يجب أن يكون > 0"); return
            if sell < cost:
                error_label.config(text="⚠️ سعر البيع أقل من سعر الشراء!")
        except ValueError:
            error_label.config(text="❌ سعر البيع غير صحيح"); return

        try:
            qty = int(qty_e.get().strip())
            if qty < 0:
                error_label.config(text="❌ الكمية لا يمكن أن تكون سالبة"); return
        except ValueError:
            error_label.config(text="❌ الكمية يجب أن تكون عددًا صحيحًا"); return

        exp_str = exp_e.get().strip() or None
        if exp_str:
            try:
                datetime.strptime(exp_str, "%Y-%m-%d")
            except ValueError:
                error_label.config(text="❌ صيغة التاريخ: YYYY-MM-DD"); return

        supplier = supplier_e.get().strip() or None

        success, msg = update_product_in_db(p_id, name, cost, sell, qty, exp_str, supplier)
        if success:
            messagebox.showinfo("تم", f"✅ تم تحديث المنتج:\n{name}", parent=win)
            refresh_callback()
            win.destroy()
        else:
            error_label.config(text=f"❌ {msg}")

    theme = get_theme()
    save_button = tk.Button(win, text="حفظ التغييرات", command=save_changes, width=20, font=("Arial", 11, "bold"))
    # استخدام لون مميز للحفظ
    save_button.config(bg=theme.get('accent_bg', '#28A745'), fg=theme.get('accent_fg', 'white'))
    save_button.pack(pady=15)
    
    apply_theme_to_widgets(win.winfo_children())

def show_employees_window():
    win = tk.Toplevel()
    win.title("قائمة الموظفين")
    win.geometry("450x450")

    columns = ("id", "name", "role")
    tree = ttk.Treeview(win, columns=columns, show="headings")
    tree.heading("id", text="المعرف")
    tree.heading("name", text="الاسم")
    tree.heading("role", text="الدور")
    tree.column("id", width=50)

    def refresh_employees(filter_name=""): # refresh_employees is already defined inside show_employees_window
        for row in tree.get_children():
            tree.delete(row)
        for emp_id, name, role in get_all_employees(filter_name):
            tree.insert("", "end", values=(emp_id, name, role))

    search_frame = tk.Frame(win) # search_frame is already defined inside show_employees_window
    search_frame.pack(pady=5, padx=10, fill=tk.X)
    search_entry = tk.Entry(search_frame)
    search_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 5))
    search_button = tk.Button(search_frame, text="بحث", command=lambda: refresh_employees(search_entry.get().strip()), font=("Arial", 10, "bold"))
    search_button.pack(side=tk.LEFT)
    search_entry.bind("<Return>", lambda event: refresh_employees(search_entry.get().strip()))
    tk.Label(search_frame, text=":بحث باسم الموظف").pack(side=tk.RIGHT)

    tree.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)

    def edit_selected_employee():
        selected = tree.selection()
        if not selected:
            messagebox.showwarning("تحذير", "الرجاء اختيار موظف لتعديله", parent=win)
            return
        
        emp_id = tree.item(selected[0])['values'][0]
        employee_details = get_employee_details(emp_id)

        if not employee_details:
            messagebox.showerror("خطأ", "لم يتم العثور على الموظف.", parent=win)
            return

        # employee_details[2] is the role
        if employee_details[2] == 'مدير':
            messagebox.showerror("خطأ", "لا يمكن تعديل بيانات حساب المدير.", parent=win)
            return

        edit_employee_popup(employee_details, refresh_employees)

    def delete_selected_employee():
        selected = tree.selection()
        if not selected:
            messagebox.showwarning("تحذير", "الرجاء اختيار موظف لحذفه", parent=win)
            return

        item = tree.item(selected[0])
        emp_id, name, role = item['values']

        if role == 'مدير':
            messagebox.showerror("خطأ", "لا يمكن حذف حساب المدير.", parent=win)
            return

        if messagebox.askyesno("تأكيد الحذف", f"هل أنت متأكد من حذف الموظف: {name}؟", parent=win):
            delete_employee_from_db(emp_id)
            messagebox.showinfo("تم", f"تم حذف الموظف: {name}", parent=win)
            refresh_employees()

    buttons_frame = tk.Frame(win)
    buttons_frame.pack(pady=10)
    theme = get_theme()
    tk.Button(buttons_frame, text="تعديل الموظف المحدد", command=edit_selected_employee, bg=theme['warning_bg'], fg=theme['warning_fg'], font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=5)
    tk.Button(buttons_frame, text="حذف الموظف المحدد", command=delete_selected_employee, bg=theme['danger_bg'], fg=theme['button_fg'], font=("Arial", 10, "bold")).pack(side=tk.LEFT, padx=5)

    refresh_employees()
    apply_theme_to_widgets(win.winfo_children())

def edit_employee_popup(employee_data, refresh_callback):
    win = tk.Toplevel()
    emp_id, emp_name, emp_role, can_discount = employee_data
    win.title(f"تعديل الموظف: {emp_name}")
    win.geometry("300x300")
    win.configure(bg=get_theme()['bg'])

    tk.Label(win, text=f"الاسم: {emp_name}", font=("Arial", 12, "bold")).pack(pady=10)

    tk.Label(win, text="الدور (بائع/مخزن):").pack()
    role_e = tk.Entry(win)
    role_e.insert(0, emp_role)
    role_e.pack()

    tk.Label(win, text="كلمة المرور الجديدة (اتركه فارغاً لعدم التغيير):").pack()
    pass_e = tk.Entry(win, show="*")
    pass_e.pack()

    can_discount_var = tk.IntVar(value=can_discount)
    discount_check = tk.Checkbutton(win, text="منح صلاحية تطبيق الخصم", variable=can_discount_var)
    discount_check.pack(pady=10)


    error_label = tk.Label(win, text="", fg="red")
    error_label.pack(pady=5)

    def save_changes():
        new_role = role_e.get().strip()
        new_password = pass_e.get().strip()

        new_can_discount = can_discount_var.get()

        if new_role not in ["بائع", "مخزن"]:
            error_label.config(text="الدور يجب أن يكون 'بائع' أو 'مخزن'")
            return

        if new_password:
            update_employee_in_db(emp_id, new_role, new_can_discount, new_password)
        else:
            update_employee_in_db(emp_id, new_role, new_can_discount)

        messagebox.showinfo("تم التحديث", f"تم تحديث بيانات الموظف: {emp_name}", parent=win)
        refresh_callback()
        win.destroy()

    tk.Button(win, text="حفظ التغييرات", command=save_changes, font=("Arial", 11, "bold")).pack(pady=15)
    apply_theme_to_widgets(win.winfo_children())

def show_invoices_list_window():
    win = tk.Toplevel()
    win.title("استعراض الفواتير")
    win.geometry("600x400")

    columns = ("id", "date", "total")
    tree = ttk.Treeview(win, columns=columns, show="headings")
    tree.heading("id", text="رقم الفاتورة")
    tree.heading("date", text="التاريخ")
    tree.heading("total", text="الإجمالي")
    tree.pack(pady=10, padx=10, fill=tk.BOTH, expand=True)

    for inv_id, sale_time, total in get_all_invoices():
        tree.insert("", "end", values=(inv_id, sale_time.split(" ")[0], f"{total:.2f}"))

    def view_details():
        selected = tree.selection()
        if not selected:
            messagebox.showwarning("تحذير", "الرجاء اختيار فاتورة لعرض تفاصيلها", parent=win)
            return
        invoice_id = tree.item(selected[0])['values'][0]
        show_invoice_details_popup(invoice_id)

    tk.Button(win, text="عرض تفاصيل الفاتورة", command=view_details, font=("Arial", 11, "bold")).pack(pady=10)
    apply_theme_to_widgets(win.winfo_children())

def show_invoice_details_popup(invoice_id):
    win = tk.Toplevel()
    win.title(f"تفاصيل الفاتورة: {invoice_id}")
    win.geometry("500x350")

    tk.Label(win, text=f"رقم الفاتورة: {invoice_id}", font=("Arial", 14, "bold")).pack(pady=10)

    columns = ("name", "price", "qty", "subtotal")
    tree = ttk.Treeview(win, columns=columns, show="headings")
    tree.heading("name", text="المنتج")
    tree.heading("price", text="السعر")
    tree.heading("qty", text="الكمية")
    tree.heading("subtotal", text="المجموع الفرعي")
    tree.pack(pady=5, padx=10, fill=tk.BOTH, expand=True)

    sales = get_sales_by_invoice(invoice_id)
    grand_total = 0
    for name, price, qty, _ in sales:
        subtotal = price * qty
        tree.insert("", "end", values=(name, f"{price:.2f}", qty, f"{subtotal:.2f}"))
        grand_total += subtotal

    total_frame = tk.Frame(win)
    total_frame.pack(pady=10, fill=tk.X, padx=10)
    tk.Label(total_frame, text="الإجمالي الكلي:", font=("Arial", 12, "bold")).pack(side=tk.LEFT)
    tk.Label(total_frame, text=f"{grand_total:.2f}", font=("Arial", 12, "bold")).pack(side=tk.RIGHT)
    apply_theme_to_widgets(win.winfo_children())

    def generate_printable_invoice_text(inv_id):
        sales_items = get_sales_by_invoice(inv_id)
        if not sales_items:
            return None

        header = f"""
*************************************
           فاتورة بيع
*************************************
رقم الفاتورة: {inv_id}
التاريخ: {sales_items[0][3]}
-------------------------------------
المنتج      الكمية    السعر    المجموع
-------------------------------------
"""
        body = ""
        total = 0
        for name, price, qty, _ in sales_items:
            subtotal = price * qty
            total += subtotal
            # تنسيق النص ليكون متراصفاً
            body += f"{name:<12} {qty:<8} {price:<8.2f} {subtotal:<8.2f}\n"

        footer = f"""
-------------------------------------
الإجمالي الكلي: {total:.2f}
*************************************
        شكراً لزيارتكم
*************************************
"""
        return header + body + footer

    def print_invoice():
        invoice_text_content = generate_printable_invoice_text(invoice_id)
        if not invoice_text_content:
            messagebox.showerror("خطأ", "لا يمكن إنشاء نص الفاتورة.", parent=win)
            return
        
        filepath = filedialog.asksaveasfilename(initialfile=f"{invoice_id}.txt", defaultextension=".txt", filetypes=[("Text files", "*.txt")])
        if filepath:
            with open(filepath, 'w', encoding='utf-8') as f:
                f.write(invoice_text_content)
            messagebox.showinfo("تم الحفظ", f"تم حفظ الفاتورة في:\n{filepath}", parent=win)
            import os
            os.startfile(filepath, 'print')

    tk.Button(win, text="طباعة الفاتورة", command=print_invoice, font=("Arial", 11, "bold")).pack(pady=10)
    apply_theme_to_widgets(win.winfo_children())

def print_barcode_for_selected_product(tree):
    if not barcode_libs_available:
        messagebox.showerror("خطأ", "مكتبات إنشاء الباركود غير مثبتة.\nيرجى التثبيت عبر:\npip install python-barcode svglib reportlab")
        return

    selected = tree.selection()
    if not selected:
        messagebox.showwarning("تحذير", "الرجاء اختيار منتج لطباعة ملصق له.")
        return

    product_name = tree.item(selected[0])['values'][1]
    generate_and_print_barcode_label(product_name)

def generate_and_print_barcode_label(product_name):
    try:
        # 1. إنشاء الباركود كصورة SVG في الذاكرة
        code128 = barcode.get_barcode_class('code128')
        barcode_instance = code128(product_name, writer=ImageWriter())
        
        # حفظ SVG في الذاكرة
        svg_buffer = io.BytesIO()
        barcode_instance.write(svg_buffer)
        svg_buffer.seek(0)

        # 2. تحويل SVG إلى صورة Pillow
        drawing = svg2rlg(svg_buffer)
        png_buffer = io.BytesIO()
        renderPM.drawToFile(drawing, png_buffer, fmt="PNG")
        png_buffer.seek(0)
        barcode_image = Image.open(png_buffer)

        # 3. إنشاء ملصق باستخدام Pillow
        label_width = 400
        label_height = 200
        label_image = Image.new('RGB', (label_width, label_height), 'white')
        
        # وضع صورة الباركود على الملصق
        barcode_width, barcode_height = barcode_image.size
        label_image.paste(barcode_image, ((label_width - barcode_width) // 2, 20))

        # إضافة اسم المنتج كنص
        from PIL import ImageDraw, ImageFont
        draw = ImageDraw.Draw(label_image)
        try:
            font = ImageFont.truetype("arial.ttf", 24)
        except IOError:
            font = ImageFont.load_default()
        
        text_bbox = draw.textbbox((0, 0), product_name, font=font)
        text_width = text_bbox[2] - text_bbox[0]
        draw.text(((label_width - text_width) / 2, 150), product_name, fill="black", font=font)

        # 4. حفظ الملصق وإرساله للطباعة
        filepath = f"barcode_{product_name}.png"
        label_image.save(filepath)
        import os
        os.startfile(filepath, 'print')
        messagebox.showinfo("تم", f"تم إرسال ملصق الباركود للمنتج '{product_name}' إلى الطابعة.")

    except Exception as e:
        messagebox.showerror("خطأ في إنشاء الباركود", f"حدث خطأ: {e}")





def add_employee_popup():
    win = tk.Toplevel()
    win.title("إضافة موظف")
    win.geometry("300x180")
    win.configure(bg=get_theme()['bg'])
    tk.Label(win, text="الاسم:").pack(); name_e = tk.Entry(win); name_e.pack()
    tk.Label(win, text="الدور (بائع/مخزن):").pack(); role_e = tk.Entry(win); role_e.pack()
    tk.Label(win, text="كلمة المرور:").pack(); pass_e = tk.Entry(win, show="*"); pass_e.pack()
    def save_emp():
        role = role_e.get().strip()
        if role not in ["بائع", "مخزن"]:
            messagebox.showerror("خطأ", "الدور يجب أن يكون 'بائع' أو 'مخزن'")
            return
        with db_context() as conn:
            try:
                conn.execute("INSERT INTO employees (name, role, password) VALUES (?, ?, ?)",
                               (name_e.get(), role, pass_e.get()))
                messagebox.showinfo("تم", "تمت إضافة الموظف")
                win.destroy()
            except sqlite3.IntegrityError:
                messagebox.showerror("خطأ", "اسم المستخدم مستخدم مسبقًا")
    tk.Button(win, text="حفظ", command=save_emp, font=("Arial", 11, "bold")).pack(pady=10)
    apply_theme_to_widgets(win.winfo_children())

def delete_selected(tree, refresh_callback):
    selected = tree.selection()
    if not selected:
        messagebox.showwarning("تحذير", "اختر منتجًا للحذف")
        return
    name = tree.item(selected[0])['values'][0]
    delete_product_from_db(name)
    refresh_callback()
    messagebox.showinfo("تم", f"تم حذف المنتج: {name}")

def export_daily_report():
    today = date.today().isoformat()
    sales = get_daily_sales(today)
    if not sales:
        messagebox.showinfo("لا توجد مبيعات", "لا توجد مبيعات اليوم")
        return
    invoices = {}
    for inv_id, name, price, qty in sales:
        if inv_id not in invoices:
            invoices[inv_id] = []
        invoices[inv_id].append((name, price, qty))
    filepath = filedialog.asksaveasfilename(
        defaultextension=".xlsx",
        filetypes=[("Excel", "*.xlsx")],
        initialfile=f"تقرير_اليوم_{today}.xlsx"
    )
    if not filepath:
        return
    wb = Workbook()
    ws = wb.active
    ws.sheet_view.rightToLeft = True
    ws.title = "التقرير اليومي"
    ws.append(["التقرير اليومي", today])
    ws.append([])
    ws.append(["رقم الفاتورة", "المنتج", "سعر الشراء", "سعر البيع", "الكمية", "إجمالي البيع", "إجمالي الربح"])
    grand_total = 0
    grand_profit = 0
    for inv_id, items in invoices.items():
        for i, (name, price, qty, cost) in enumerate(items):
            line_total = price * qty
            line_profit = (price - cost) * qty
            grand_total += line_total
            grand_profit += line_profit
            ws.append([inv_id if i == 0 else "", name, cost, price, qty, line_total, line_profit])
        ws.append([])
    ws.append(["", "", "", "", "الإجمالي الكلي للمبيعات:", grand_total])
    ws.append(["", "", "", "", "إجمالي الأرباح:", grand_profit])
    wb.save(filepath)
    messagebox.showinfo("تم", "تم حفظ التقرير اليومي")

def backup_database():
    """يقوم بإنشاء نسخة احتياطية من قاعدة البيانات."""
    try:
        backup_path = filedialog.asksaveasfilename(
            defaultextension=".db",
            filetypes=[("Database files", "*.db")],
            initialfile=f"backup_{datetime.now().strftime('%Y-%m-%d_%H-%M-%S')}.db",
            title="حفظ النسخة الاحتياطية"
        )
        if backup_path:
            shutil.copy(DB_NAME, backup_path)
            messagebox.showinfo("نجاح", f"تم حفظ النسخة الاحتياطية بنجاح في:\n{backup_path}")
    except Exception as e:
        messagebox.showerror("خطأ", f"فشل النسخ الاحتياطي: {e}")

def restore_database():
    """يقوم باستعادة قاعدة البيانات من نسخة احتياطية."""
    if not messagebox.askokcancel("تحذير خطير!", "سيتم استبدال جميع البيانات الحالية بالنسخة الاحتياطية.\nهل أنت متأكد من المتابعة؟\n\n**يجب إعادة تشغيل البرنامج بعد الاستعادة**"):
        return
    
    restore_path = filedialog.askopenfilename(filetypes=[("Database files", "*.db")], title="اختيار نسخة احتياطية للاستعادة")
    if restore_path:
        try:
            shutil.copy(restore_path, DB_NAME)
            messagebox.showinfo("نجاح", "تم استعادة قاعدة البيانات بنجاح.\nالرجاء إعادة تشغيل البرنامج الآن.")
            root.quit()
        except Exception as e:
            messagebox.showerror("خطأ", f"فشل الاستعادة: {e}")

def change_credentials_popup():
    win = tk.Toplevel()
    win.title("تغيير معلومات الدخول")
    win.geometry("350x300")
    win.configure(bg=get_theme()['bg'])

    tk.Label(win, text="كلمة المرور الحالية:").pack(pady=(10,0))
    current_pass_e = tk.Entry(win, show="*")
    current_pass_e.pack(pady=5)

    tk.Label(win, text="اسم المستخدم الجديد (اتركه فارغاً لعدم التغيير):").pack()
    new_user_e = tk.Entry(win)
    new_user_e.insert(0, current_user)
    new_user_e.pack(pady=5)

    tk.Label(win, text="كلمة المرور الجديدة (اتركه فارغاً لعدم التغيير):").pack()
    new_pass_e = tk.Entry(win, show="*")
    new_pass_e.pack(pady=5)

    tk.Label(win, text="تأكيد كلمة المرور الجديدة:").pack()
    confirm_pass_e = tk.Entry(win, show="*")
    confirm_pass_e.pack(pady=5)

    def perform_change():
        global current_user
        current_pass = current_pass_e.get()
        new_user = new_user_e.get().strip()
        new_pass = new_pass_e.get()
        confirm_pass = confirm_pass_e.get()

        # التحقق من كلمة المرور الحالية
        emp = get_employee(current_user, current_pass)
        if not emp:
            messagebox.showerror("خطأ", "كلمة المرور الحالية غير صحيحة.", parent=win); return

        if new_pass != confirm_pass:
            messagebox.showerror("خطأ", "كلمتا المرور الجديدتان غير متطابقتين.", parent=win); return

        # تحديد ما إذا كان اسم المستخدم قد تغير
        username_to_update = new_user if new_user and new_user != current_user else None
        password_to_update = new_pass if new_pass else None

        if not username_to_update and not password_to_update:
            messagebox.showinfo("لا تغيير", "لم يتم إدخال أي معلومات جديدة للتغيير.", parent=win); return

        success, msg = update_user_credentials(current_user, username_to_update, password_to_update)
        if success:
            if username_to_update:
                current_user = username_to_update
            save_user_settings(current_user, current_role, current_theme_name)
            messagebox.showinfo("نجاح", "تم تحديث معلومات الدخول بنجاح.", parent=win)
            win.destroy()
        else:
            messagebox.showerror("خطأ", msg, parent=win)

    tk.Button(win, text="حفظ التغييرات", command=perform_change, font=("Arial", 11, "bold")).pack(pady=15)
    apply_theme_to_widgets(win.winfo_children())

# === 7. بدء التشغيل ===
init_db()

user_settings = load_user_settings()
if user_settings:
    set_theme(user_settings[2])

root = tk.Tk()
root.title("متجر احترافي - إصدار محسّن")
root.geometry("1200x700")

login_screen()

root.mainloop()
