from flask import Flask, render_template, request, redirect, url_for, flash, session
from functools import wraps
import json
from user import User
from group import Group
from expense import Expense
from transaction import Transaction
from connector import Connector

app = Flask(__name__)
app.secret_key = 'your_secret_key'  # Change this to a random secret key

# Load database configuration
with open('db.json', 'r') as f:
    db_params = json.load(f)

connector = Connector(**db_params)

# Login required decorator
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session:
            flash('Please login to access this page', 'danger')
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

# Get current user
def get_current_user():
    if 'user_id' in session:
        return User.get_user(session['user_id'], connector)
    return None

# Routes for authentication
@app.route('/')
def index():
    if 'user_id' in session:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        
        try:
            user = User.login(email, password, connector)
            session['user_id'] = user.user_id
            session['name'] = user.name
            flash(f'Welcome, {user.name}!', 'success')
            return redirect(url_for('dashboard'))
        except ValueError as e:
            flash(str(e), 'danger')
    
    return render_template('login.html')

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        name = request.form['name']
        email = request.form['email']
        password = request.form['password']
        
        try:
            user = User(name, email, password, connector=connector)
            session['user_id'] = user.user_id
            session['name'] = user.name
            flash('Registration successful!', 'success')
            return redirect(url_for('dashboard'))
        except ValueError as e:
            flash(str(e), 'danger')
    
    return render_template('register.html')

@app.route('/logout')
def logout():
    session.clear()
    flash('You have been logged out', 'info')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    user = get_current_user()
    group_ids = user.get_groups()
    groups = []
    
    for group_id in group_ids:
        try:
            group = Group.get_group(group_id, connector)
            groups.append(group)
        except ValueError:
            pass
    
    # Get user's dues
    query = """
    SELECT e.expense_id, e.description, e.amount, ep.amount as owed_amount, g.name as group_name,
           u.name as paid_by
    FROM Expenses e
    JOIN ExpenseParticipants ep ON e.expense_id = ep.expense_id
    JOIN GroupDetails g ON e.group_id = g.group_id
    JOIN Users u ON e.paid_by = u.user_id
    WHERE ep.user_id = %s AND ep.settled != 'SETTLED'
    """
    dues = connector.execute(query, (user.user_id,))
    
    # Get recent activity
    activity_query = """
    (SELECT 'expense' as type, e.expense_id as id, e.description, e.timestamp, g.name as group_name
     FROM Expenses e
     JOIN GroupDetails g ON e.group_id = g.group_id
     WHERE e.paid_by = %s
     ORDER BY e.timestamp DESC
     LIMIT 5)
    UNION ALL
    (SELECT 'settlement' as type, t.trans_id as id, 
            CONCAT('Settlement for ', e.description) as description, 
            t.timestamp, g.name as group_name
     FROM Transactions t
     JOIN Expenses e ON t.expense_id = e.expense_id
     JOIN GroupDetails g ON e.group_id = g.group_id
     WHERE t.payer_id = %s OR t.payee_id = %s
     ORDER BY t.timestamp DESC
     LIMIT 5)
    ORDER BY timestamp DESC
    LIMIT 10
    """
    recent_activity = connector.execute(activity_query, (user.user_id, user.user_id, user.user_id))
    
    return render_template('dashboard.html', 
                         user=user, 
                         groups=groups, 
                         dues=dues,
                         recent_activity=recent_activity)

# Group routes
@app.route('/group/create', methods=['GET', 'POST'])
@login_required
def create_group():
    if request.method == 'POST':
        name = request.form['name']
        description = request.form.get('description', '')
        
        try:
            user = get_current_user()
            # Using the Group class constructor to create a new group
            group = Group(admin=user, name=name, members=[user], description=description, connector=connector)
            flash(f'Group "{name}" created successfully!', 'success')
            return redirect(url_for('view_groups'))
        except ValueError as e:
            flash(str(e), 'danger')
    
    return render_template('group/create.html')

@app.route('/group/view')
@login_required
def view_groups():
    user = get_current_user()
    group_ids = user.get_groups()
    groups = []
    
    for group_id in group_ids:
        try:
            # Using Group.get_group to retrieve group details
            group = Group.get_group(group_id, connector)
            groups.append(group)
        except ValueError:
            pass
    
    return render_template('group/view.html', groups=groups)

@app.route('/group/manage/<group_id>')
@login_required
def manage_group(group_id):
    try:
        group = Group.get_group(group_id, connector)
        user = get_current_user()
        is_admin = (group.admin.user_id == user.user_id)
        
        return render_template('group/manage.html', group=group, is_admin=is_admin)
    except ValueError as e:
        flash(str(e), 'danger')
        return redirect(url_for('view_groups'))

@app.route('/group/add_member/<group_id>', methods=['POST'])
@login_required
def add_member_to_group(group_id):
    email = request.form['email']
    
    try:
        group = Group.get_group(group_id, connector)
        user = get_current_user()
        
        if group.admin.user_id != user.user_id:
            flash('You are not the admin of this group', 'danger')
            return redirect(url_for('manage_group', group_id=group_id))
        
        # Using User.get_user_by_email to find the user
        member = User.get_user_by_email(email, connector)
        # Using Group.add_member to add the member
        group.add_member(member.user_id)
        flash(f'{member.name} has been added to the group', 'success')
    except ValueError as e:
        flash(str(e), 'danger')
    
    return redirect(url_for('manage_group', group_id=group_id))

@app.route('/group/remove_member/<group_id>/<user_id>')
@login_required
def remove_member_from_group(group_id, user_id):
    try:
        group = Group.get_group(group_id, connector)
        current_user = get_current_user()
        
        if group.admin.user_id != current_user.user_id:
            flash('You are not the admin of this group', 'danger')
            return redirect(url_for('manage_group', group_id=group_id))
        
        # Using Group.remove_member to remove the member
        group.remove_member(user_id)
        member = User.get_user(user_id, connector)
        flash(f'{member.name} has been removed from the group', 'success')
    except ValueError as e:
        flash(str(e), 'danger')
    
    return redirect(url_for('manage_group', group_id=group_id))

@app.route('/group/update/<group_id>', methods=['POST'])
@login_required
def update_group(group_id):
    try:
        group = Group.get_group(group_id, connector)
        current_user = get_current_user()
        
        if group.admin.user_id != current_user.user_id:
            flash('You are not the admin of this group', 'danger')
            return redirect(url_for('manage_group', group_id=group_id))
        
        # Using Group property setters to update group details
        if 'name' in request.form:
            group.name = request.form['name']
            flash('Group name updated successfully', 'success')
        
        if 'description' in request.form:
            group.description = request.form['description']
            flash('Group description updated successfully', 'success')
    except ValueError as e:
        flash(str(e), 'danger')
    
    return redirect(url_for('manage_group', group_id=group_id))

# Expense routes
@app.route('/expense/create', methods=['GET', 'POST'])
@login_required
def create_expense():
    user = get_current_user()
    group_ids = user.get_groups()
    groups = []
    
    for group_id in group_ids:
        try:
            group = Group.get_group(group_id, connector)
            groups.append(group)
        except ValueError:
            pass
    
    if request.method == 'POST':
        group_id = request.form['group_id']
        amount = float(request.form['amount'])
        description = request.form['description']
        tag = request.form.get('tag', '')
        
        try:
            group = Group.get_group(group_id, connector)
            
            # Create initial participants dict with all members
            participants = {}
            participants[user] = amount  # Payer initially pays the full amount
            
            for member in group.members:
                if member.user_id != user.user_id:
                    participants[member] = 0.0
            
            # Create the expense using the Expense constructor
            expense = Expense(
                amount=amount,
                payer=user,
                group=group,
                participants=participants,
                description=description,
                tag=tag,
                connector=connector
            )
            
            # Handle split method
            split_method = request.form['split_method']
            
            if split_method == 'equal':
                # Get selected participants
                selected_participants = request.form.getlist('participants')
                participant_users = [user]  # Start with payer
                
                for member in group.members:
                    if member.user_id != user.user_id and member.user_id in selected_participants:
                        participant_users.append(member)
                
                # Using Expense.calculate_and_split_expense to split the expense
                expense.calculate_and_split_expense('equal', participant_users)
            
            elif split_method == 'unequal':
                amounts = []
                participants = []
                
                for member in [user] + group.members:
                    if member.user_id != user.user_id:
                        amount_key = f'amount_{member.user_id}'
                        if amount_key in request.form and float(request.form[amount_key]) > 0:
                            participants.append(member)
                            amounts.append(float(request.form[amount_key]))
                
                # Using Expense.calculate_and_split_expense to split the expense
                expense.calculate_and_split_expense('unequal', participants, amounts=amounts)
            
            # Mark payer as settled
            update_query = "UPDATE ExpenseParticipants SET settled = 'SETTLED' WHERE expense_id = %s AND user_id = %s"
            connector.execute(update_query, (expense.expense_id, expense.payer.user_id))
            
            update_query = "UPDATE ExpenseParticipants SET amount = %s WHERE expense_id = %s AND user_id = %s"
            connector.execute(update_query, (0.0, expense.expense_id, expense.payer.user_id))
            
            # Mark members with zero amount as settled
            for member in expense.participants:
                if expense.participants[member] == 0.0:
                    update_query = "UPDATE ExpenseParticipants SET settled = 'SETTLED' WHERE expense_id = %s AND user_id = %s"
                    connector.execute(update_query, (expense.expense_id, member.user_id))
            
            flash('Expense added successfully!', 'success')
            return redirect(url_for('view_expenses'))
        
        except ValueError as e:
            flash(str(e), 'danger')
    
    return render_template('expense/create.html', groups=groups)

@app.route('/expense/view')
@login_required
def view_expenses():
    user = get_current_user()
    group_ids = user.get_groups()
    
    # Get all expenses from user's groups using Expense.get_group_expenses
    all_expenses = []
    for group_id in group_ids:
        try:
            expenses = Expense.get_group_expenses(group_id, connector)
            all_expenses.extend(expenses)
        except ValueError:
            pass
    
    # Get settlement status for each expense
    for expense in all_expenses:
        check_settled_query = "SELECT COUNT(*) as count FROM ExpenseParticipants WHERE expense_id = %s AND settled != 'SETTLED'"
        result = connector.execute(check_settled_query, (expense.expense_id,), fetchall=False)
        expense.is_settled = (result['count'] == 0)
    
    return render_template('expense/view.html', expenses=all_expenses, user=user)

@app.route('/expense/manage/<expense_id>', methods=['GET', 'POST'])
@login_required
def manage_expense(expense_id):
    user = get_current_user()
    
    try:
        # Using Expense.get_expense to retrieve the expense
        expense = Expense.get_expense(expense_id, connector)
        is_payer = (expense.payer.user_id == user.user_id)
        
        if request.method == 'POST' and is_payer:
            amount = float(request.form['amount'])
            description = request.form['description']
            tag = request.form.get('tag', '')
            
            # Create participants dict
            participants = {}
            for participant in expense.participants:
                amount_key = f'amount_{participant.user_id}'
                if amount_key in request.form:
                    participants[participant] = float(request.form[amount_key])
            
            # Using Expense.edit_expense to update the expense
            expense.edit_expense(
                amount=amount,
                description=description,
                tag=tag,
                participants=participants
            )
            
            # Mark payer as settled
            update_query = "UPDATE ExpenseParticipants SET settled = 'SETTLED' WHERE expense_id = %s AND user_id = %s"
            connector.execute(update_query, (expense.expense_id, expense.payer.user_id))
            
            update_query = "UPDATE ExpenseParticipants SET amount = %s WHERE expense_id = %s AND user_id = %s"
            connector.execute(update_query, (0.0, expense.expense_id, expense.payer.user_id))
            
            # Mark members with zero amount as settled
            for member in expense.participants:
                if expense.participants[member] == 0.0:
                    update_query = "UPDATE ExpenseParticipants SET settled = 'SETTLED' WHERE expense_id = %s AND user_id = %s"
                    connector.execute(update_query, (expense.expense_id, member.user_id))
            
            flash('Expense updated successfully!', 'success')
            return redirect(url_for('view_expenses'))
        
        return render_template('expense/manage.html', expense=expense, is_payer=is_payer)
    
    except ValueError as e:
        flash(str(e), 'danger')
        return redirect(url_for('view_expenses'))

@app.route('/expense/delete/<expense_id>')
@login_required
def delete_expense(expense_id):
    user = get_current_user()
    
    try:
        expense = Expense.get_expense(expense_id, connector)
        
        if expense.payer.user_id != user.user_id:
            flash('You are not authorized to delete this expense', 'danger')
            return redirect(url_for('view_expenses'))
        
        # Using Expense.delete_expense to delete the expense
        expense.delete_expense()
        flash('Expense deleted successfully!', 'success')
    except ValueError as e:
        flash(str(e), 'danger')
    
    return redirect(url_for('view_expenses'))

# Transaction routes
@app.route('/transaction/create', methods=['GET', 'POST'])
@login_required
def create_transaction():
    user = get_current_user()
    
    # Get all expenses where the user is a participant but not settled
    query = """
    SELECT e.expense_id, e.description, e.amount, ep.amount as owed_amount, g.name as group_name, u.name as payer_name
    FROM Expenses e
    JOIN ExpenseParticipants ep ON e.expense_id = ep.expense_id
    JOIN GroupDetails g ON e.group_id = g.group_id
    JOIN Users u ON e.paid_by = u.user_id
    WHERE ep.user_id = %s AND ep.settled != 'SETTLED'
    """
    expenses_data = connector.execute(query, (user.user_id,))
    
    return render_template('transaction/create.html', expenses_data=expenses_data)

@app.route('/transaction/create/<expense_id>', methods=['POST'])
@login_required
def create_transaction_for_expense(expense_id):
    user = get_current_user()
    
    try:
        expense = Expense.get_expense(expense_id, connector)
        amount = float(request.form['amount'])
        
        # Check if user is a participant
        is_participant = False
        amount_owed = 0
        
        for participant, owed in expense.participants.items():
            if participant.user_id == user.user_id:
                is_participant = True
                amount_owed = owed
                break
        
        if not is_participant:
            flash('You are not a participant in this expense', 'danger')
            return redirect(url_for('create_transaction'))
        
        # Check if already settled
        query = "SELECT settled FROM ExpenseParticipants WHERE expense_id = %s AND user_id = %s"
        result = connector.execute(query, (expense_id, user.user_id), fetchall=False)
        
        if result['settled'] == 'SETTLED':
            flash('You have already settled this expense', 'danger')
            return redirect(url_for('create_transaction'))
        
        # Check amount
        if amount > amount_owed:
            flash('You cannot pay more than you owe', 'danger')
            return redirect(url_for('create_transaction'))
        
        # Create transaction using the Transaction constructor
        transaction = Transaction(
            expense=expense,
            payer=user,
            payee=expense.payer,
            amount=amount,
            connector=connector
        )
        
        # Update ExpenseParticipants
        new_amount_owed = amount_owed - amount
        new_status = 'SETTLED' if new_amount_owed == 0 else 'PARTIAL'
        
        update_query = "UPDATE ExpenseParticipants SET amount = %s, settled = %s WHERE expense_id = %s AND user_id = %s"
        connector.execute(update_query, (new_amount_owed, new_status, expense_id, user.user_id))
        
        flash('Transaction created successfully!', 'success')
        return redirect(url_for('view_transactions'))
        
    except ValueError as e:
        flash(str(e), 'danger')
        return redirect(url_for('create_transaction'))
    
    
@app.route('/transaction/view')
@login_required
def view_transactions():
    user = get_current_user()
    
    # Use Transaction.get_transactions_for_user to get all transactions
    transactions = Transaction.get_transactions_for_user(user)
    
    # Format transactions for display
    formatted_transactions = []
    for transaction in transactions:
        formatted_transactions.append({
            'trans_id': transaction.trans_id,
            'expense_description': transaction.expense.description,
            'amount': transaction.amount,
            'payer_name': transaction.payer.name,
            'payer_id': transaction.payer.user_id,
            'payee_name': transaction.payee.name,
            'timestamp': transaction.timestamp
        })
    
    return render_template('transaction/view.html', transactions=formatted_transactions, user=user)

@app.route('/transaction/manage/<trans_id>', methods=['GET', 'POST'])
@login_required
def manage_transaction(trans_id):
    user = get_current_user()
    
    try:
        # Use Transaction.get_transaction to retrieve the transaction
        transaction = Transaction.get_transaction(trans_id, connector)
        is_payer = (transaction.payer.user_id == user.user_id)
        
        if request.method == 'POST' and is_payer:
            if 'delete' in request.form:
                # Use transaction.delete() to delete the transaction
                transaction.delete()
                
                # Update ExpenseParticipants to reflect the deletion
                update_query = "UPDATE ExpenseParticipants SET amount = amount + %s, settled = 'NO' WHERE expense_id = %s AND user_id = %s"
                connector.execute(update_query, (transaction.amount, transaction.expense.expense_id, user.user_id))
                
                flash('Transaction deleted successfully', 'success')
                return redirect(url_for('view_transactions'))
        
        return render_template('transaction/manage.html', transaction=transaction, is_payer=is_payer)
    
    except ValueError as e:
        flash(str(e), 'danger')
        return redirect(url_for('view_transactions'))

@app.route('/dues')
@login_required
def view_dues():
    user = get_current_user()
    
    # Get user's dues using the same query from main.py
    query = """
    SELECT e.expense_id, e.description, e.amount, ep.amount as owed_amount, g.name as group_name, u.name as payer_name
    FROM Expenses e
    JOIN ExpenseParticipants ep ON e.expense_id = ep.expense_id
    JOIN GroupDetails g ON e.group_id = g.group_id
    JOIN Users u ON e.paid_by = u.user_id
    WHERE ep.user_id = %s AND ep.settled != 'SETTLED'
    """
    
    dues = connector.execute(query, (user.user_id,))
    
    return render_template('dues.html', dues=dues)

@app.route('/group/dues/<group_id>')
@login_required
def view_group_dues(group_id):
    user = get_current_user()
    
    try:
        group = Group.get_group(group_id, connector)
        
        # Check if user is a member of the group
        is_member = False
        for member in group.members:
            if member.user_id == user.user_id:
                is_member = True
                break
        
        if not is_member and group.admin.user_id != user.user_id:
            flash('You are not a member of this group', 'danger')
            return redirect(url_for('view_groups'))
        
        # Get dues where current user is the payer
        query = """
        SELECT u.name, u.user_id, SUM(ep.amount) as total_owed
        FROM Expenses e
        JOIN ExpenseParticipants ep ON e.expense_id = ep.expense_id
        JOIN Users u ON ep.user_id = u.user_id
        WHERE e.group_id = %s AND e.paid_by = %s AND ep.settled != 'SETTLED' AND ep.user_id != %s
        GROUP BY u.user_id
        """
        
        dues = connector.execute(query, (group_id, user.user_id, user.user_id))
        
        return render_template('group/dues.html', dues=dues, group=group)
    
    except ValueError as e:
        flash(str(e), 'danger')
        return redirect(url_for('view_groups'))

@app.route('/expense/create_for_group/<group_id>', methods=['GET', 'POST'])
@login_required
def create_expense_for_group(group_id):
    try:
        group = Group.get_group(group_id, connector)
        current_user = get_current_user()
        
        if current_user.user_id not in [member.user_id for member in group.members]:
            flash('You are not a member of this group', 'danger')
            return redirect(url_for('view_groups'))
        
        if request.method == 'POST':
            description = request.form['description']
            amount = float(request.form['amount'])
            tag = request.form.get('tag', '')
            
            # Calculate shares
            shares = {}
            total_shares = 0
            for member in group.members:
                share = int(request.form.get(f'share_{member.user_id}', 1))
                shares[member.user_id] = share
                total_shares += share
            
            if total_shares == 0:
                flash('Total shares cannot be zero', 'danger')
                return render_template('expense/create_for_group.html', group=group)
            
            # Create expense with equal split
            expense = Expense(
                group_id=group_id,
                description=description,
                amount=amount,
                paid_by=current_user,
                tag=tag,
                connector=connector
            )
            
            # Add participants with their shares
            for member_id, share in shares.items():
                if member_id != current_user.user_id:  # Don't add the payer
                    share_amount = (amount * share) / total_shares
                    expense.add_participant(member_id, share_amount)
            
            flash('Expense created successfully!', 'success')
            return redirect(url_for('view_group_expenses', group_id=group_id))
        
        return render_template('expense/create_for_group.html', group=group)
    except ValueError as e:
        flash(str(e), 'danger')
        return redirect(url_for('view_groups'))

@app.route('/group/<group_id>/expenses')
@login_required
def view_group_expenses(group_id):
    try:
        group = Group.get_group(group_id, connector)
        current_user = get_current_user()
        
        if current_user.user_id not in [member.user_id for member in group.members]:
            flash('You are not a member of this group', 'danger')
            return redirect(url_for('view_groups'))
        
        # Get expenses for this group using Expense class
        query = """
        SELECT e.expense_id, e.description, e.amount, e.timestamp, e.tag,
               u.user_id as paid_by_id, u.name as paid_by_name
        FROM Expenses e
        JOIN Users u ON e.paid_by = u.user_id
        WHERE e.group_id = %s
        ORDER BY e.timestamp DESC
        """
        expenses_data = connector.execute(query, (group_id,))
        
        expenses = []
        for expense_data in expenses_data:
            expense = Expense(
                expense_id=expense_data['expense_id'],
                description=expense_data['description'],
                amount=expense_data['amount'],
                timestamp=expense_data['timestamp'],
                tag=expense_data['tag'],
                group_id=group_id,
                paid_by_id=expense_data['paid_by_id'],
                paid_by_name=expense_data['paid_by_name'],
                connector=connector
            )
            # Check if expense is settled
            check_settled_query = "SELECT COUNT(*) as count FROM ExpenseParticipants WHERE expense_id = %s AND settled != 'SETTLED'"
            result = connector.execute(check_settled_query, (expense.expense_id,), fetchall=False)
            expense.is_settled = (result['count'] == 0)
            expenses.append(expense)
        
        return render_template('expense/view.html', group=group, expenses=expenses, user=current_user)
    except ValueError as e:
        flash(str(e), 'danger')
        return redirect(url_for('view_groups'))

@app.route('/expense/<expense_id>')
@login_required
def view_expense_details(expense_id):
    try:
        expense = Expense.get_expense(expense_id, connector)
        group = Group.get_group(expense.group_id, connector)
        current_user = get_current_user()
        
        if current_user.user_id not in [member.user_id for member in group.members]:
            flash('You are not a member of this group', 'danger')
            return redirect(url_for('view_groups'))
        
        participants = expense.get_participants()
        return render_template('expense/details.html', 
                             expense=expense, 
                             group=group, 
                             participants=participants,
                             current_user=current_user)
    except ValueError as e:
        flash(str(e), 'danger')
        return redirect(url_for('view_groups'))

@app.route('/expense/<expense_id>/settle/<user_id>')
@login_required
def mark_as_settled(expense_id, user_id):
    try:
        expense = Expense.get_expense(expense_id, connector)
        group = Group.get_group(expense.group_id, connector)
        current_user = get_current_user()
        
        if current_user.user_id != expense.paid_by.user_id:
            flash('Only the person who paid can mark expenses as settled', 'danger')
            return redirect(url_for('view_expense_details', expense_id=expense_id))
        
        expense.mark_as_settled(user_id)
        flash('Expense marked as settled!', 'success')
        return redirect(url_for('view_expense_details', expense_id=expense_id))
    except ValueError as e:
        flash(str(e), 'danger')
        return redirect(url_for('view_groups'))

if __name__ == '__main__':
    app.run(debug=True)

