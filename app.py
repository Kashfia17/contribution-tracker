from flask import Flask, render_template, request, redirect, url_for, session, jsonify
import pymysql
import os
from werkzeug.security import generate_password_hash, check_password_hash
import bcrypt
from pymysql import IntegrityError
from flask import send_from_directory
from datetime import timedelta
import uuid
 #flash k bole eikhan theke main file shuru
app = Flask(__name__)
app.secret_key = 'your_fixed_secret_key_here'
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_SECURE'] = False

# Database connection
def get_db():
    return pymysql.connect(
        host='localhost',
        user='root',
        password='',
        database='contribution_db',
        cursorclass=pymysql.cursors.DictCursor
    )

@app.route("/", methods=["GET"])
def index():
    return render_template("index.html")

@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")
        
        db = get_db()
        cursor = db.cursor()
        cursor.execute("SELECT * FROM users WHERE email = %s", (email,))
        user = cursor.fetchone()
        db.close()

        if user and user.get('password_hash'):
            if bcrypt.checkpw(password.encode('utf-8'), user['password_hash'].encode('utf-8')):
                # 1. Set session persistence
                session.permanent = True
                app.permanent_session_lifetime = timedelta(minutes=60)

                # 2. Set basic user data
                session["user_id"] = user["id"]
                session["role"] = user["role"]
                session["user_name"] = user["name"]

                # 3. Fetch and set group_id BEFORE redirecting
                db = get_db()
                cursor = db.cursor()
                cursor.execute("SELECT group_id FROM group_members WHERE user_id = %s", (user["id"],))
                group_data = cursor.fetchone()
                if group_data:
                    session["group_id"] = group_data["group_id"]
                db.close()
                
                # 4. Redirect after all session data is saved
                return redirect(url_for('leader_dashboard' if user['role'] == 'leader' else 'member_dashboard'))
            else:
                return "Invalid credentials"
        else:
            return "Invalid credentials or account setup incomplete."
            
    return render_template("login.html")

@app.route('/create_group', methods=['GET', 'POST'])
def create_group():
    if 'user_id' not in session or session.get('role') != 'leader':
        return redirect(url_for('login'))

    if request.method == 'POST':
        group_name = request.form.get('group_name')
        # Generate a unique 8-character invite code
        invite_code = str(uuid.uuid4())[:8].upper()
        
        db = get_db()
        cursor = db.cursor()
        
        try:
            # 1. Insert the new group
            cursor.execute(
                "INSERT INTO groups (name, invite_code, leader_id) VALUES (%s, %s, %s)",
                (group_name, invite_code, session['user_id'])
            )
            group_id = cursor.lastrowid
            
            # 2. Automatically link the leader to the group_members table
            cursor.execute(
                "INSERT INTO group_members (group_id, user_id) VALUES (%s, %s)",
                (group_id, session['user_id'])
            )
            
            db.commit()
            db.close()
            return redirect(url_for('leader_dashboard'))
        except Exception as e:
            db.rollback()
            db.close()
            return "An error occurred while creating the group."

    return render_template('create_group.html')

@app.route('/join_group', methods=['GET', 'POST'])
def join_group():
    if 'user_id' not in session:
        return redirect(url_for('login'))

    error = None
    if request.method == 'POST':
        invite_code = request.form.get('invite_code')
        
        db = get_db()
        cursor = db.cursor()
        
        # 1. Find the group by the invite code
        cursor.execute("SELECT id, name FROM groups WHERE invite_code = %s", (invite_code,))
        group = cursor.fetchone()
        
        if group:
            # 2. Add user to group_members table
            try:
                cursor.execute(
                    "INSERT INTO group_members (group_id, user_id) VALUES (%s, %s)",
                    (group['id'], session['user_id'])
                )
                db.commit()
                db.close()
                return redirect(url_for('member_dashboard'))
            except Exception as e:
                db.rollback()
                error = "You are already in a group or an error occurred."
        else:
            error = "Invalid invite code. Please try again."
        
        db.close()

    return render_template('join_group.html', error=error)


@app.route('/signup', methods=['GET', 'POST'])
def signup():
    if request.method == 'POST':
        name = request.form.get('name')
        email = request.form.get('email')
        role = request.form.get('role')
        password = request.form.get('password')

        # 1. Validation: Ensure password is provided
        if not password:
            return jsonify({"status": "error", "message": "Password is required."}), 400

        # 2. Hashing: Use bcrypt to match the login logic
        # Convert password to bytes, then hash with a salt
        bytes_pw = password.encode('utf-8')
        pw_hash = bcrypt.hashpw(bytes_pw, bcrypt.gensalt()).decode('utf-8')

        db = get_db()
        cursor = db.cursor()

        try:
            cursor.execute(
                "INSERT INTO users (name, email, password_hash, role) VALUES (%s, %s, %s, %s)",
                (name, email, pw_hash, role)
            )
            db.commit()

            # Store user info in session
            session['user_id'] = cursor.lastrowid
            session['role'] = role
            db.close()

            # Success: Redirect user to the correct page
            return jsonify({
                "status": "success",
                "redirect": url_for('create_group') if role == 'leader' else url_for('join_group')
            })

        except IntegrityError:
            db.rollback()
            db.close()
            return jsonify({
                "status": "error",
                "message": "An account with this email already exists."
            }), 400
        except Exception as e:
            db.rollback()
            db.close()
            return jsonify({"status": "error", "message": "Database error occurred."}), 500

    return render_template('signup.html')
# --- DASHBOARDS & TASKS ---

@app.route('/leader_dashboard', methods=['GET', 'POST'])
def leader_dashboard():
    # 1. Auth & Session Check
    print(f"DEBUG: SESSION CONTENT -> {session}") 
    
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
        
    db = get_db()
    cursor = db.cursor()
    g_id = session.get('group_id')

    # 2. Handle Task Assignment
    if request.method == 'POST' and 'assign_task' in request.form:
        cursor.execute("""
            INSERT INTO tasks (group_id, assigned_to, title, deadline, status) 
            VALUES (%s, %s, %s, %s, 'Pending')
        """, (g_id, request.form['assigned_to'], request.form['title'], request.form['deadline']))
        db.commit()

    # Replace the "Fetch Members" section with this:
    cursor.execute("""
    SELECT u.* FROM users u
    JOIN group_members gm ON u.id = gm.user_id
    WHERE gm.group_id = %s
      """, (g_id,))
    members = cursor.fetchall()
    
    # 2. Fetch Group details
    cursor.execute("SELECT * FROM groups WHERE id = %s", (g_id,))
    group = cursor.fetchone()

    # 4. Fetch Tasks (Mapping: tasks)
    cursor.execute("""
        SELECT t.*, u.name 
        FROM tasks t 
        JOIN users u ON t.assigned_to = u.id 
        WHERE t.group_id = %s 
        ORDER BY t.deadline ASC
    """, (g_id,))
    tasks = cursor.fetchall()
    
    # 5. Fetch Submissions (Mapping: submissions + tasks)
    cursor.execute("""
        SELECT s.*, t.title, u.name as submitted_by 
        FROM submissions s 
        JOIN tasks t ON s.task_id = t.id 
        JOIN users u ON s.user_id = u.id 
        WHERE t.group_id = %s AND t.status = 'Submitted'
    """, (g_id,))
    submissions = cursor.fetchall()

    # 6. Fetch Chart Data (Mapping: work_sessions)
    cursor.execute("""
        SELECT u.name, SUM(ws.duration) as total 
        FROM users u 
        JOIN work_sessions ws ON u.id = ws.user_id 
        WHERE ws.group_id = %s 
        GROUP BY u.id
    """, (g_id,))
    chart_raw = cursor.fetchall()
    
    # Prepare data for Chart.js
    labels = [row['name'] for row in chart_raw]
    data = [float(row['total'])/3600 for row in chart_raw]

    # 7. Fetch Team Status Monitor
    cursor.execute("""
        SELECT u.name, u.role, MAX(ws.end_time) as last_act 
        FROM users u 
        JOIN group_members gm ON u.id = gm.user_id 
        LEFT JOIN work_sessions ws ON u.id = ws.user_id 
        WHERE gm.group_id = %s 
        GROUP BY u.id
    """, (g_id,))
    team_status_raw = cursor.fetchall()
    
    # Logic for Active/Offline status
    team_status = []
    for m in team_status_raw:
        # Simple logic: Active if last_act is within 5 minutes (300s)
        is_online = False
        if m['last_act']:
            import datetime
            time_diff = (datetime.datetime.now() - m['last_act']).total_seconds()
            is_online = time_diff < 300
            
        team_status.append({
            'name': m['name'],
            'role': m['role'],
            'is_online': is_online,
            'status_text': 'Active Now' if is_online else 'Offline'
        })

    db.close()
    return render_template('leader_dashboard.html', 
                           members=members, tasks=tasks, 
                           submissions=submissions, 
                           team_status=team_status,
                           chart_labels=labels, chart_data=data,
                           user={'user_name': session.get('user_name'), 'role': session.get('role')},
                           group={'group_name': group['name'] if group else 'No Group'},
                           my_id=session.get('user_id'))

@app.route('/member_dashboard')
def member_dashboard():
    if 'user_id' not in session or session.get('role') != 'member':
        return redirect(url_for('login'))
    
    db = get_db()
    cursor = db.cursor()
    
    u_id = session['user_id']
    g_id = session.get('group_id')
    
    # In app.py - Update this line:
    cursor.execute("SELECT id, name as user_name FROM users WHERE id = %s", (u_id,))
    user = cursor.fetchone()

    # 2. Fetch Group details
    cursor.execute("SELECT * FROM groups WHERE id = %s", (g_id,))
    group = cursor.fetchone()

    # FETCH GROUP: Force the key to be 'group_name' to match your template
    cursor.execute("SELECT id, name as group_name, invite_code FROM groups WHERE id = %s", (g_id,))
    group = cursor.fetchone()
    
    # FETCH USER: Include 'role' and map 'name' to 'user_name'
    cursor.execute("SELECT id, name as user_name, role FROM users WHERE id = %s", (u_id,))
    user = cursor.fetchone()

    # In app.py - Update this line:
    cursor.execute("""
    SELECT t.*, COALESCE(u.name, 'Unassigned') as assignee_name 
    FROM tasks t 
    LEFT JOIN users u ON t.assigned_to = u.id 
    WHERE t.group_id = %s
""", (g_id,))
    tasks = cursor.fetchall()

    # 4. Fetch Team Status
    cursor.execute("""
        SELECT u.name, u.role, u.is_tracking 
        FROM users u 
        JOIN group_members gm ON u.id = gm.user_id 
        WHERE gm.group_id = %s
    """, (g_id,))
    raw_status = cursor.fetchall()
    
    team_status = []
    for m in raw_status:
        is_online = bool(m.get('is_tracking', 0))
        team_status.append({
            'name': m.get('name', 'Unknown'),
            'role': m.get('role', 'Member'),
            'is_online': is_online,
            'status_text': 'Active Now' if is_online else 'Offline'
        })
    
    # 5. Fetch Chart Data
    chart_labels = []
    chart_data = []
    if g_id:
        cursor.execute("""
            SELECT u.name, SUM(ws.duration) as total_duration 
            FROM work_sessions ws 
            JOIN users u ON ws.user_id = u.id 
            WHERE ws.group_id = %s 
            GROUP BY u.id
        """, (g_id,))
        results = cursor.fetchall()
        chart_labels = [row['name'] for row in results]
        chart_data = [float(row['total_duration'])/3600 for row in results]
    
    db.close()
    
    return render_template(
        'member_dashboard.html', 
        user=user, 
        group=group, 
        tasks=tasks,
        team_status=team_status,
        chart_labels=chart_labels, 
        chart_data=chart_data,
        my_id=u_id
    )

# This route handles requests to /uploads/<filename>
@app.route('/uploads/<filename>')
def uploaded_file(filename):
    return send_from_directory('uploads', filename)

@app.route('/assign_task', methods=['POST'])
def assign_task():
    if 'user_id' not in session or session.get('role') != 'leader':
        return redirect(url_for('login'))

    # Get data from the form
    task_title = request.form.get('title')
    assigned_to = request.form.get('assigned_to') # This is the user_id
    deadline = request.form.get('deadline')
    g_id = session.get('group_id')

    if task_title and assigned_to and deadline:
        db = get_db()
        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO tasks (group_id, assigned_to, title, deadline, status) 
            VALUES (%s, %s, %s, %s, 'Pending')
        """, (g_id, assigned_to, task_title, deadline))
        db.commit()
        db.close()
        
    return redirect(url_for('leader_dashboard'))

@app.route('/submit_task', methods=['POST'])
def submit_task():
    task_id = request.form.get('task_id')
    file = request.files.get('fileToUpload')
    
    if file:
        # Save the file (ensure you have an 'uploads' directory)
        file_path = os.path.join('uploads', file.filename)
        file.save(file_path)
        
        db = get_db()
        cursor = db.cursor()
        # Insert the submission into the database
        cursor.execute(
            "INSERT INTO submissions (task_id, user_id, file_path) VALUES (%s, %s, %s)",
            (task_id, session['user_id'], file_path)
        )
        # Update task status
        cursor.execute("UPDATE tasks SET status = 'Submitted' WHERE id = %s", (task_id,))
        db.commit()
        db.close()
        
    return redirect(url_for('leader_dashboard'))

@app.route('/approve_task', methods=['POST'])
def approve_task():
    task_id = request.form['task_id']
    db = get_db()
    cursor = db.cursor()
    cursor.execute("UPDATE tasks SET status = 'Done' WHERE id = %s", (task_id,))
    db.commit()
    db.close()
    return redirect(url_for('leader_dashboard'))

# --- UTILITIES & TRACKING ---

@app.route('/log_session', methods=['POST'])
def log_session():
    data = request.form
    db = get_db()
    cursor = db.cursor()
    cursor.execute("INSERT INTO work_sessions (user_id, group_id, duration, end_time) VALUES (%s, %s, %s, NOW())",
                   (data['user_id'], data['group_id'], data['duration']))
    db.commit()
    db.close()
    return jsonify({"status": "success"})

@app.route('/update_timer_status', methods=['POST'])
def update_timer_status():
    db = get_db()
    cursor = db.cursor()
    cursor.execute("UPDATE users SET is_tracking = %s WHERE id = %s", 
                   (request.form['is_tracking'], request.form['user_id']))
    db.commit()
    db.close()
    return jsonify({"status": "updated"})

@app.route('/get_chart_data')
def get_chart_data():
    group_id = request.args.get('group_id')
    db = get_db()
    cursor = db.cursor()
    cursor.execute("""SELECT users.name, SUM(work_sessions.duration) as total_duration 
                      FROM users JOIN work_sessions ON users.id = work_sessions.user_id 
                      WHERE work_sessions.group_id = %s GROUP BY users.id""", (group_id,))
    data = cursor.fetchall()
    db.close()
    return jsonify(data)

@app.route('/task_archive')
def task_archive():
    if 'user_id' not in session:
        return redirect(url_for('login'))
        
    g_id = session.get('group_id')
    db = get_db()
    cursor = db.cursor()

    # Changed 'Approved' to 'Done' to match your database data
    cursor.execute("""
        SELECT s.*, t.title, u.name as submitted_by 
        FROM submissions s 
        JOIN tasks t ON s.task_id = t.id 
        JOIN users u ON s.user_id = u.id 
        WHERE t.group_id = %s AND t.status = 'Done'
    """, (g_id,))
    
    approved_tasks = cursor.fetchall()
    return render_template('archive.html', approved_tasks=approved_tasks)

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login'))

if __name__ == '__main__':
    app.run(debug=True)
    


