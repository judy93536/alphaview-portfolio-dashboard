#!/usr/bin/env python3
"""
AlphaView Portfolio Dashboard - Complete Authenticated Version with ALL Functionality
Combines authentication with full portfolio management capabilities
"""

import os
os.environ['AWS_PROFILE'] = 'alphaview'

import dash
from dash import dcc, html, Input, Output, State, dash_table, callback_context, no_update
from flask import session, redirect, request
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd
from decimal import Decimal
import datetime
import psycopg2
import boto3
import json
import numpy as np
from functools import wraps
import io
import zipfile

# Import our authentication modules
from auth_utils import CognitoAuth, login_required, admin_required
from cognito_config import COGNITO_CONFIG

# Database configuration
SHARADAR_CONFIG = {
    'host': '192.168.1.32',
    'database': 'sharadar',
    'user': 'options',
    'password': 'n841CM12'
}

def get_rds_config():
    """Get RDS database configuration from AWS Secrets Manager"""
    try:
        client = boto3.client('secretsmanager', region_name='us-west-2')
        response = client.get_secret_value(SecretId='LightsailAlphaView_Key')
        return json.loads(response['SecretString'])
    except Exception as e:
        print(f"Error getting RDS config: {e}")
        raise

def get_rds_connection():
    """Get connection to AWS RDS"""
    config = get_rds_config()
    return psycopg2.connect(
        host=config['host'],
        port=config['port'],
        database=config['dbname'],
        user=config['username'],
        password=config['password'],
        sslmode='require'
    )

def get_portfolio_positions():
    """Get current portfolio positions"""
    conn = get_rds_connection()
    query = """
    SELECT ticker, shares, avg_cost_basis, total_cost_basis, 
           current_value, unrealized_pnl, last_updated
    FROM portfolio_positions 
    WHERE shares > 0 
    ORDER BY ticker
    """
    df = pd.read_sql(query, conn)
    conn.close()
    return df

def get_portfolio_targets():
    """Get portfolio target allocations"""
    conn = get_rds_connection()
    query = """
    SELECT ticker, name, sector, target_weight, target_value, 
           target_shares, priority
    FROM portfolio_targets 
    ORDER BY target_weight DESC
    """
    df = pd.read_sql(query, conn)
    conn.close()
    return df

def get_portfolio_executions():
    """Get portfolio execution history"""
    conn = get_rds_connection()
    query = """
    SELECT ticker, action, shares, price, total_cost, fees, 
           execution_date, broker, notes
    FROM portfolio_executions 
    ORDER BY execution_date DESC, execution_time DESC
    LIMIT 100
    """
    df = pd.read_sql(query, conn)
    conn.close()
    return df

def get_daily_prices(ticker, start_date=None, end_date=None):
    """Get price data for a ticker"""
    conn = get_rds_connection()
    
    where_clause = "WHERE ticker = %s"
    params = [ticker]
    
    if start_date:
        where_clause += " AND date >= %s"
        params.append(start_date)
    
    if end_date:
        where_clause += " AND date <= %s"
        params.append(end_date)
    
    query = f"""
    SELECT ticker, date, open_price, high_price, low_price, 
           close_price, adj_close, volume
    FROM daily_prices
    {where_clause}
    ORDER BY date
    """
    
    df = pd.read_sql(query, conn, params=params)
    conn.close()
    return df

def get_date_range():
    """Get available date range from daily_prices"""
    conn = get_rds_connection()
    query = "SELECT MIN(date) as min_date, MAX(date) as max_date FROM daily_prices"
    result = pd.read_sql(query, conn)
    conn.close()
    return result.iloc[0]['min_date'], result.iloc[0]['max_date']

def calculate_stocks_on_date(executions, target_date):
    """Calculate number of unique stocks held on a specific date based on execution history"""
    if executions.empty:
        return 0
    
    # Convert target_date to same type as execution_date for comparison
    target_date = pd.to_datetime(target_date).date()
    
    # Get all executions up to and including the target date
    executions['execution_date'] = pd.to_datetime(executions['execution_date']).dt.date
    relevant_executions = executions[executions['execution_date'] <= target_date]
    
    if relevant_executions.empty:
        return 0
    
    # Calculate net shares for each ticker
    holdings = {}
    for _, execution in relevant_executions.iterrows():
        ticker = execution['ticker']
        action = execution['action'].upper()
        shares = execution['shares']
        
        if ticker not in holdings:
            holdings[ticker] = 0
        
        if action == 'BUY':
            holdings[ticker] += shares
        elif action == 'SELL':
            holdings[ticker] -= shares
    
    # Count tickers with positive holdings
    return sum(1 for shares in holdings.values() if shares > 0)

def prepare_export_data(positions, portfolio_fields, calculated_fields):
    """Prepare portfolio data with selected fields for export"""
    if positions.empty:
        return pd.DataFrame()
    
    # Start with base positions data
    export_data = positions.copy()
    
    # Calculate total portfolio value for weights
    total_value = positions['current_value'].sum()
    
    # Add calculated fields if requested
    if 'portfolio_weight' in calculated_fields:
        export_data['portfolio_weight'] = (positions['current_value'] / total_value * 100).round(2)
    
    if 'roi_percentage' in calculated_fields:
        export_data['roi_percentage'] = ((positions['current_value'] - positions['total_cost_basis']) / positions['total_cost_basis'] * 100).round(2)
    
    if 'current_price' in calculated_fields:
        # Get current prices for each ticker
        current_prices = []
        for ticker in positions['ticker']:
            try:
                prices = get_daily_prices(ticker)
                if not prices.empty:
                    current_prices.append(float(prices.iloc[-1]['adj_close']))
                else:
                    current_prices.append(0.0)
            except:
                current_prices.append(0.0)
        export_data['current_price'] = current_prices
    
    if 'price_change' in calculated_fields and 'current_price' in export_data.columns:
        export_data['price_change'] = (export_data['current_price'] - export_data['avg_cost_basis']).round(2)
    
    if 'days_held' in calculated_fields:
        # Calculate days since last update (approximation)
        import datetime
        if 'last_updated' in positions.columns:
            today = datetime.datetime.now()
            export_data['days_held'] = (today - pd.to_datetime(positions['last_updated'])).dt.days
        else:
            export_data['days_held'] = 0
    
    # Select only requested fields
    all_selected_fields = portfolio_fields + calculated_fields
    available_fields = [field for field in all_selected_fields if field in export_data.columns]
    
    return export_data[available_fields]

def calculate_comprehensive_metrics(returns):
    """Calculate comprehensive performance and risk metrics"""
    returns = returns.dropna()
    if len(returns) == 0:
        return {}
    
    # Basic metrics
    total_return = (1 + returns).prod() - 1
    annualized_return = (1 + total_return) ** (252 / len(returns)) - 1
    volatility = returns.std() * np.sqrt(252)
    
    # Sharpe ratio (assuming 2% risk-free rate)
    risk_free_rate = 0.02
    sharpe_ratio = (annualized_return - risk_free_rate) / volatility if volatility > 0 else 0
    
    # Maximum drawdown
    cumulative = (1 + returns).cumprod()
    rolling_max = cumulative.expanding().max()
    drawdown = cumulative / rolling_max - 1
    max_drawdown = drawdown.min()
    
    # VaR and CVaR (95% confidence)
    var_95 = np.percentile(returns, 5)
    cvar_95 = returns[returns <= var_95].mean()
    
    # Calmar ratio
    calmar_ratio = annualized_return / abs(max_drawdown) if max_drawdown != 0 else 0
    
    return {
        'Total Return (%)': total_return * 100,
        'Annualized Return (%)': annualized_return * 100,
        'Annualized Volatility (%)': volatility * 100,
        'Sharpe Ratio': sharpe_ratio,
        'Max Drawdown (%)': max_drawdown * 100,
        'VaR 95% (%)': var_95 * 100,
        'CVaR 95% (%)': cvar_95 * 100,
        'Calmar Ratio': calmar_ratio
    }

# Initialize Dash app
app = dash.Dash(__name__, 
               external_stylesheets=[
                   'https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css'
               ],
               suppress_callback_exceptions=True)

# Configure secret key for sessions
app.server.secret_key = 'alphaview-secret-key-change-in-production'

# Initialize Cognito auth
cognito_auth = CognitoAuth()

# Get date range for the app
MIN_DATE, MAX_DATE = get_date_range()
print(f"🚀 Starting AlphaView Portfolio Dashboard with Full Authentication and Functionality...")
print(f"📊 Data available from {MIN_DATE} to {MAX_DATE}")

# Define initial layout with login form
app.layout = html.Div([
    dcc.Location(id='url', refresh=False),
    dcc.Store(id='logout-trigger', data=0),  # Hidden store for logout state
    html.Div(id='page-content', children=[
        html.Div([
            html.Div([
                html.H2('AlphaView Portfolio Dashboard', className='text-center mb-4'),
                html.Div([
                    html.H4('Login', className='text-center mb-3'),
                    html.P('Demo Account:', className='text-muted'),
                    html.P('Demo Viewer: viewer@alphaview.com', className='text-muted small'),
                    dcc.Input(id='username', type='email', placeholder='Email',
                             className='form-control mb-3'),
                    dcc.Input(id='password', type='password', placeholder='Password',
                             className='form-control mb-3'),
                    html.Button('Login', id='login-button', n_clicks=0,
                               className='btn btn-primary w-100'),
                    html.Div(id='login-message', className='mt-3')
                ], className='card-body'),
            ], className='card mx-auto mt-5', style={'max-width': '400px'})
        ], className='container')
    ])
])

@app.callback(
    Output('page-content', 'children'),
    Input('url', 'pathname'),
    prevent_initial_call=False
)
def display_page(pathname):
    # Handle logout URL
    if pathname == '/logout':
        session.clear()
        return display_login_form("Logged out successfully")
    
    # Check if password change is required
    if 'password_change_required' in session:
        change_info = session['password_change_required']
        return display_password_change_form(
            change_info['username'], 
            change_info['session_token']
        )
    
    # Check if user is already authenticated
    if 'user' in session:
        return display_dashboard()
    else:
        return display_login_form()

# Separate callback for login handling
@app.callback(
    Output('url', 'pathname'),
    Input('login-button', 'n_clicks'),
    [State('username', 'value'),
     State('password', 'value')],
    prevent_initial_call=True
)
def handle_login(login_clicks, username, password):
    if login_clicks and username and password:
        result = cognito_auth.authenticate_user(username, password)
        
        if result.get('challenge') == 'NEW_PASSWORD_REQUIRED':
            # Store password change info in session for the page display callback
            session['password_change_required'] = {
                'username': username,
                'session_token': result.get('session')
            }
            return '/'  # Redirect to trigger password change form
        elif result.get('success'):
            # Store user info in session
            session['user'] = username
            session['role'] = cognito_auth.get_user_role(username)
            session['access_token'] = result['access_token']
            return '/'  # This will trigger the page display callback
        else:
            return '/'  # Stay on login page with error
    
    return no_update

# Login message callback
@app.callback(
    Output('login-message', 'children'),
    Input('login-button', 'n_clicks'),
    [State('username', 'value'),
     State('password', 'value')],
    prevent_initial_call=True
)
def show_login_message(login_clicks, username, password):
    if login_clicks and username and password:
        result = cognito_auth.authenticate_user(username, password)
        
        if result.get('challenge') == 'NEW_PASSWORD_REQUIRED':
            return html.Div("Password change required", className="text-warning")
        elif result.get('success'):
            return ""  # Clear message on success
        else:
            return html.Div(f"Login failed: {result.get('error', 'Unknown error')}", className="text-danger")
    elif login_clicks:
        return html.Div("Please enter username and password", className="text-warning")
    
    return ""

# Password change callback
@app.callback(
    [Output('url', 'pathname', allow_duplicate=True),
     Output('password-change-message', 'children', allow_duplicate=True)],
    Input('change-password-btn', 'n_clicks'),
    [State('new-password', 'value'),
     State('confirm-password', 'value'),
     State('change-password-data', 'data')],
    prevent_initial_call=True
)
def handle_password_change(change_clicks, new_password, confirm_password, change_data):
    if not change_clicks:
        return no_update, no_update
    
    # Validate inputs
    if not new_password or not confirm_password:
        return no_update, html.Div("Please fill in both password fields", className="text-warning")
    
    if new_password != confirm_password:
        return no_update, html.Div("Passwords do not match", className="text-danger")
    
    if len(new_password) < 8:
        return no_update, html.Div("Password must be at least 8 characters long", className="text-danger")
    
    try:
        # Handle the password change challenge
        result = cognito_auth.handle_new_password_challenge(
            change_data['username'], 
            new_password, 
            change_data['session']
        )
        
        if result.get('success'):
            # Clear password change requirement and login user
            if 'password_change_required' in session:
                del session['password_change_required']
            
            session['user'] = change_data['username']
            session['role'] = cognito_auth.get_user_role(change_data['username'])
            session['access_token'] = result['access_token']
            
            # Success - redirect to dashboard with a slight delay to show success message
            return '/', html.Div([
                "✅ Password updated successfully! Redirecting to dashboard...",
                # Add a client-side script to clear any form state after redirect
                html.Script("""
                    setTimeout(function() {
                        // Clear password fields to prevent browser from showing the form again
                        const newPasswordField = document.getElementById('new-password');
                        const confirmPasswordField = document.getElementById('confirm-password');
                        if (newPasswordField) newPasswordField.value = '';
                        if (confirmPasswordField) confirmPasswordField.value = '';
                    }, 1000);
                """)
            ], className="text-success")
        else:
            error_msg = result.get('error', 'Password change failed. Please try again.')
            return no_update, html.Div(f"❌ {error_msg}", className="text-danger")
            
    except Exception as e:
        print(f"Password change error: {e}")
        return no_update, html.Div("❌ An error occurred. Please try again.", className="text-danger")
    
    return no_update, no_update

# Removed duplicate password change message callback - now handled in main callback above

def display_login_form(message=""):
    message_class = 'text-danger' if 'failed' in message.lower() else 'text-success' if message else ''
    
    return html.Div([
        html.Div([
            html.H2('AlphaView Portfolio Dashboard', className='text-center mb-4'),
            html.Div([
                html.H4('Login', className='text-center mb-3'),
                html.P('Demo Account:', className='text-muted'),
                html.P('Demo Viewer: viewer@alphaview.com', className='text-muted small'),
                dcc.Input(id='username', type='email', placeholder='Email',
                         className='form-control mb-3'),
                dcc.Input(id='password', type='password', placeholder='Password',
                         className='form-control mb-3'),
                html.Button('Login', id='login-button', n_clicks=0,
                           className='btn btn-primary w-100'),
                html.Div(message, className=f'{message_class} mt-3')
            ], className='card-body'),
        ], className='card mx-auto mt-5', style={'max-width': '400px'})
    ], className='container')

def display_password_change_form(username, session_token, message=""):
    """Display password change form for NEW_PASSWORD_REQUIRED challenge"""
    message_class = 'text-danger' if 'failed' in message.lower() else 'text-warning' if message else ''
    
    return html.Div([
        dcc.Store(id='change-password-data', data={'username': username, 'session': session_token}),
        html.Div([
            html.H2('Password Change Required', className='text-center mb-4'),
            html.Div([
                html.H4('New Password Required', className='text-center mb-3'),
                html.P(f'Please set a new password for: {username}', className='text-muted text-center'),
                html.P('Your temporary password has expired. Please create a new secure password.', 
                       className='text-muted small text-center mb-3'),
                dcc.Input(id='new-password', type='password', 
                         placeholder='New Password (min 8 characters)',
                         className='form-control mb-3'),
                dcc.Input(id='confirm-password', type='password', 
                         placeholder='Confirm New Password',
                         className='form-control mb-3'),
                html.Button('Set New Password', id='change-password-btn', n_clicks=0,
                           className='btn btn-success w-100'),
                html.Div(id='password-change-message', className='mt-3'),
                html.Div(message, className=f'{message_class} mt-3'),
                html.Hr(className='mt-4'),
                html.A('← Back to Login', href='/', className='btn btn-link')
            ], className='card-body'),
        ], className='card mx-auto mt-5', style={'max-width': '400px'})
    ], className='container')

def display_dashboard():
    user_role = session.get('role', 'viewer')
    username = session.get('user', 'Unknown')
    
    # Define tabs based on role
    tabs = [
        dcc.Tab(label='Target vs Actual', value='target-vs-actual'),
        dcc.Tab(label='Performance', value='performance'),
        dcc.Tab(label='Transaction Log', value='transaction-log'),
        dcc.Tab(label='Portfolio Export', value='portfolio-export'),
    ]
    
    # Add admin-only tabs
    if user_role == 'admin':
        tabs.insert(1, dcc.Tab(label='🔒 Execute Trades', value='execute-trades'))
        tabs.insert(2, dcc.Tab(label='Update Prices', value='update-prices'))
    
    return html.Div([
        html.Div([
            html.Div([
                html.H1('AlphaView Portfolio Dashboard', className='h3'),
                html.P(f'Welcome, {username}', className='mb-1'),
                html.Span(f'Role: {user_role.title()}', 
                         className=f'badge bg-{"success" if user_role == "admin" else "info"}'),
            ], className='col'),
            html.Div([
                html.A('Logout', href='/logout', className='btn btn-sm btn-outline-secondary')
            ], className='col-auto')
        ], className='row align-items-center bg-light p-3 mb-4 rounded'),
        
        html.Div([
            dcc.Tabs(id='main-tabs', value='target-vs-actual', 
                     className='nav nav-tabs mb-3',
                     children=tabs),
            
            html.Div(id='tab-content', className='mt-3')
        ])
    ], className='container-fluid p-4')

# Main tab content callback
@app.callback(
    Output('tab-content', 'children'),
    Input('main-tabs', 'value'),
    prevent_initial_call=True
)
def render_tab_content(active_tab):
    # Check authentication
    if 'user' not in session:
        return html.Div("Please login to access dashboard", className="alert alert-warning")
    
    user_role = session.get('role', 'viewer')
    
    # Check admin access for restricted tabs
    if active_tab in ['execute-trades', 'update-prices'] and user_role != 'admin':
        return html.Div([
            html.H3("🔒 Access Denied", className="text-danger"),
            html.P("This feature requires admin privileges."),
            html.P("Please contact the administrator for access.")
        ], className="alert alert-danger")
    
    # Render appropriate tab content
    if active_tab == 'target-vs-actual':
        return render_target_vs_actual()
    elif active_tab == 'execute-trades':
        return render_execute_trades()
    elif active_tab == 'update-prices':
        return render_update_prices()
    elif active_tab == 'performance':
        return render_performance()
    elif active_tab == 'transaction-log':
        return render_transaction_log()
    elif active_tab == 'portfolio-export':
        return render_portfolio_export()
    
    return html.Div("Tab not found", className="alert alert-warning")

# ALL RENDER FUNCTIONS WITH FULL FUNCTIONALITY

def render_target_vs_actual():
    """Render Target vs Actual allocation analysis - FULL VERSION"""
    try:
        positions = get_portfolio_positions()
        targets = get_portfolio_targets()
        
        if positions.empty:
            return html.Div([
                html.H2('Target vs Actual Analysis'),
                html.Div('No portfolio positions found.', className='alert alert-info')
            ])
        
        # Calculate total portfolio value
        total_value = positions['current_value'].sum()
        
        if total_value == 0:
            return html.Div([
                html.H2('Target vs Actual Analysis'),
                html.Div('Portfolio has no current value.', className='alert alert-warning')
            ])
        
        # Prepare data for charts
        positions['actual_weight'] = (positions['current_value'] / total_value * 100).round(2)
        
        # Create target dictionary
        target_dict = dict(zip(targets['ticker'], targets['target_weight'] * 100))
        
        # Merge target weights
        positions['target_weight'] = positions['ticker'].map(target_dict).fillna(0)
        positions['weight_diff'] = positions['actual_weight'] - positions['target_weight']
        
        # Create pie charts
        fig_actual = px.pie(positions, values='current_value', names='ticker', 
                           title='Current Portfolio Allocation')
        fig_actual.update_layout(height=400)
        
        if not targets.empty:
            fig_target = px.pie(targets, values='target_weight', names='ticker',
                               title='Target Portfolio Allocation') 
            fig_target.update_layout(height=400)
        else:
            fig_target = go.Figure().add_annotation(text="No targets defined", 
                                                   xref="paper", yref="paper", 
                                                   x=0.5, y=0.5, showarrow=False)
        
        return html.Div([
            html.H2('Target vs Actual Analysis', className='mb-4'),
            
            # Summary cards
            html.Div([
                html.Div([
                    html.H5(f'${total_value:,.2f}', className='card-title text-primary'),
                    html.P('Total Portfolio Value', className='card-text')
                ], className='card-body text-center'),
            ], className='card mb-4'),
            
            # Charts
            html.Div([
                html.Div([
                    dcc.Graph(figure=fig_actual)
                ], className='col-md-6'),
                html.Div([
                    dcc.Graph(figure=fig_target)
                ], className='col-md-6'),
            ], className='row mb-4'),
            
            # Position details table
            html.H4('Position Details', className='mb-3'),
            dash_table.DataTable(
                data=positions.to_dict('records'),
                columns=[
                    {'name': 'Ticker', 'id': 'ticker'},
                    {'name': 'Shares', 'id': 'shares', 'type': 'numeric'},
                    {'name': 'Market Value', 'id': 'current_value', 'type': 'numeric', 
                     'format': {'specifier': '$,.2f'}},
                    {'name': 'Actual %', 'id': 'actual_weight', 'type': 'numeric',
                     'format': {'specifier': '.1f'}},
                    {'name': 'Target %', 'id': 'target_weight', 'type': 'numeric',
                     'format': {'specifier': '.1f'}},
                    {'name': 'Diff %', 'id': 'weight_diff', 'type': 'numeric',
                     'format': {'specifier': '.1f'}},
                    {'name': 'Unrealized P&L', 'id': 'unrealized_pnl', 'type': 'numeric',
                     'format': {'specifier': '$,.2f'}},
                ],
                style_cell={'textAlign': 'center', 'padding': '10px'},
                style_header={'backgroundColor': 'rgb(230, 230, 230)', 'fontWeight': 'bold'},
                style_data_conditional=[
                    {
                        'if': {'column_id': 'unrealized_pnl', 'filter_query': '{unrealized_pnl} < 0'},
                        'color': 'red',
                    },
                    {
                        'if': {'column_id': 'unrealized_pnl', 'filter_query': '{unrealized_pnl} > 0'},
                        'color': 'green',
                    },
                    {
                        'if': {'column_id': 'weight_diff', 'filter_query': '{weight_diff} < -2'},
                        'backgroundColor': 'rgba(255, 0, 0, 0.2)',
                    },
                    {
                        'if': {'column_id': 'weight_diff', 'filter_query': '{weight_diff} > 2'},
                        'backgroundColor': 'rgba(0, 255, 0, 0.2)',
                    }
                ],
                page_size=20
            )
        ])
        
    except Exception as e:
        return html.Div([
            html.H2('Target vs Actual Analysis'),
            html.Div(f'Error loading data: {str(e)}', className='alert alert-danger')
        ])

def render_execute_trades():
    """Render Execute Trades interface - FULL VERSION"""
    try:
        positions = get_portfolio_positions()
        targets = get_portfolio_targets()
        
        # Get all available tickers
        all_tickers = list(set(list(positions['ticker']) + list(targets['ticker'])))
        all_tickers.sort()
        
        return html.Div([
            html.H2('Execute Trades', className='mb-4'),
            
            html.Div([
                html.Div([
                    html.Label('Ticker', className='form-label'),
                    dcc.Dropdown(
                        id='trade-ticker',
                        options=[{'label': ticker, 'value': ticker} for ticker in all_tickers],
                        placeholder='Select ticker',
                        className='mb-3'
                    ),
                ], className='col-md-6'),
                
                html.Div([
                    html.Label('Action', className='form-label'),
                    dcc.RadioItems(
                        id='trade-action',
                        options=[
                            {'label': ' Buy', 'value': 'BUY'},
                            {'label': ' Sell', 'value': 'SELL'}
                        ],
                        value='BUY',
                        inline=True,
                        className='mb-3'
                    ),
                ], className='col-md-6'),
            ], className='row'),
            
            html.Div(id='ticker-info', className='mb-3'),
            
            html.Div([
                html.Div([
                    html.Label('Shares', className='form-label'),
                    dcc.Input(
                        id='trade-shares',
                        type='number',
                        placeholder='Number of shares',
                        min=1,
                        className='form-control'
                    ),
                ], className='col-md-4'),
                
                html.Div([
                    html.Label('Price per Share', className='form-label'),
                    html.Div([
                        dcc.Input(
                            id='trade-price',
                            type='number',
                            placeholder='Price per share',
                            min=0.01,
                            step=0.01,
                            className='form-control'
                        ),
                        html.Button('Get Latest', id='get-price-btn', 
                                  className='btn btn-outline-secondary ms-2')
                    ], className='d-flex')
                ], className='col-md-4'),
                
                html.Div([
                    html.Label('Trade Value', className='form-label'),
                    html.Div(id='trade-value-display', className='form-control-plaintext')
                ], className='col-md-4'),
            ], className='row mb-3'),
            
            html.Div(id='trade-preview', className='mb-3'),
            
            html.Button('Execute Trade', id='execute-trade-btn', 
                       className='btn btn-primary btn-lg'),
            
            html.Div(id='trade-result', className='mt-3')
        ])
        
    except Exception as e:
        return html.Div([
            html.H2('Execute Trades'),
            html.Div(f'Error loading interface: {str(e)}', className='alert alert-danger')
        ])

def render_update_prices():
    """Render Update Prices interface - FULL VERSION"""
    return html.Div([
        html.H2('Update Prices', className='mb-4'),
        html.P('Update portfolio position values with latest market prices.'),
        
        html.Button('Update All Positions with Latest Prices', 
                   id='update-all-prices-btn', 
                   className='btn btn-primary mb-3'),
        
        html.Div(id='price-update-result')
    ])

def render_performance():
    """Render Performance analysis with full functionality - ALREADY IMPLEMENTED"""
    return html.Div([
        html.H3('📈 Performance Analysis'),
        html.Div([
            html.Div([
                html.Label('Start Date:'),
                dcc.DatePickerSingle(
                    id='perf-start-date',
                    date=MIN_DATE,
                    display_format='YYYY-MM-DD'
                )
            ], className='col-md-3'),
            html.Div([
                html.Label('End Date:'),
                dcc.DatePickerSingle(
                    id='perf-end-date', 
                    date=MAX_DATE,
                    display_format='YYYY-MM-DD'
                )
            ], className='col-md-3'),
            html.Div([
                html.Label('Benchmark:'),
                dcc.Dropdown(
                    id='benchmark-select',
                    options=[
                        {'label': 'SPY (S&P 500)', 'value': 'SPY'},
                        {'label': 'No Benchmark', 'value': 'NONE'}
                    ],
                    value='SPY'
                )
            ], className='col-md-3'),
            html.Div([
                html.Label('Generate:'),
                html.Br(),
                html.Button('Generate Performance Report', id='generate-performance-btn', 
                           className='btn btn-primary')
            ], className='col-md-3')
        ], className='row mb-4'),
        
        html.Div(id='performance-output')
    ])

def render_transaction_log():
    """Render Transaction Log - FULL VERSION"""
    try:
        executions = get_portfolio_executions()
        
        if executions.empty:
            return html.Div([
                html.H2('Transaction Log'),
                html.Div('No transactions found.', className='alert alert-info')
            ])
        
        # Format the data - handle both datetime and date types
        if not executions.empty:
            executions['execution_date'] = pd.to_datetime(executions['execution_date']).dt.strftime('%Y-%m-%d')
        
        return html.Div([
            html.H2('Transaction Log', className='mb-4'),
            
            dash_table.DataTable(
                data=executions.to_dict('records'),
                columns=[
                    {'name': 'Date', 'id': 'execution_date'},
                    {'name': 'Ticker', 'id': 'ticker'},
                    {'name': 'Action', 'id': 'action'},
                    {'name': 'Shares', 'id': 'shares', 'type': 'numeric'},
                    {'name': 'Price', 'id': 'price', 'type': 'numeric', 
                     'format': {'specifier': '$,.2f'}},
                    {'name': 'Total', 'id': 'total_cost', 'type': 'numeric', 
                     'format': {'specifier': '$,.2f'}},
                    {'name': 'Fees', 'id': 'fees', 'type': 'numeric', 
                     'format': {'specifier': '$,.2f'}},
                    {'name': 'Broker', 'id': 'broker'},
                ],
                style_cell={'textAlign': 'center', 'padding': '8px'},
                style_header={'backgroundColor': 'rgb(230, 230, 230)', 'fontWeight': 'bold'},
                style_data_conditional=[
                    {
                        'if': {'column_id': 'action', 'filter_query': '{action} = BUY'},
                        'backgroundColor': 'rgba(0, 255, 0, 0.1)',
                    },
                    {
                        'if': {'column_id': 'action', 'filter_query': '{action} = SELL'},
                        'backgroundColor': 'rgba(255, 0, 0, 0.1)',
                    }
                ],
                page_size=25,
                sort_action='native'
            )
        ])
        
    except Exception as e:
        return html.Div([
            html.H2('Transaction Log'),
            html.Div(f'Error loading transactions: {str(e)}', className='alert alert-danger')
        ])

def render_portfolio_export():
    """Render Portfolio Export interface - ENHANCED VERSION"""
    return html.Div([
        html.H2('Portfolio Export', className='mb-4'),
        
        html.P('Export your portfolio data for external analysis or reporting.'),
        
        # Quick Export Section
        html.Div([
            html.H4('Quick Export', className='mb-3'),
            html.Div([
                html.Button('📊 Generate Summary Report', 
                           id='generate-summary-btn',
                           className='btn btn-primary m-2'),
                html.Button('📄 Export Default CSV', 
                           id='export-default-csv-btn', 
                           className='btn btn-success m-2'),
            ]),
        ], className='mb-5'),
        
        # Custom Export Section
        html.Div([
            html.H4('Custom Export', className='mb-3'),
            html.P('Select which fields to include in your export:', className='text-muted'),
            
            html.Div([
                html.Div([
                    html.H6('Portfolio Data', className='mb-2'),
                    dcc.Checklist(
                        id='portfolio-fields',
                        options=[
                            {'label': ' Ticker Symbol', 'value': 'ticker'},
                            {'label': ' Shares Held', 'value': 'shares'},
                            {'label': ' Average Cost Basis', 'value': 'avg_cost_basis'},
                            {'label': ' Total Cost Basis', 'value': 'total_cost_basis'},
                            {'label': ' Current Market Value', 'value': 'current_value'},
                            {'label': ' Unrealized P&L', 'value': 'unrealized_pnl'},
                            {'label': ' Last Updated', 'value': 'last_updated'},
                        ],
                        value=['ticker', 'shares', 'current_value', 'unrealized_pnl'],  # Default selection
                        inline=False,
                        className='mb-3'
                    ),
                ], className='col-md-6'),
                
                html.Div([
                    html.H6('Calculated Fields', className='mb-2'),
                    dcc.Checklist(
                        id='calculated-fields',
                        options=[
                            {'label': ' Portfolio Weight (%)', 'value': 'portfolio_weight'},
                            {'label': ' Return on Investment (%)', 'value': 'roi_percentage'},
                            {'label': ' Current Price', 'value': 'current_price'},
                            {'label': ' Price Change', 'value': 'price_change'},
                            {'label': ' Days Held', 'value': 'days_held'},
                        ],
                        value=['portfolio_weight', 'roi_percentage'],  # Default selection
                        inline=False,
                        className='mb-3'
                    ),
                ], className='col-md-6'),
            ], className='row'),
            
            html.Div([
                html.H6('Export Options', className='mb-2'),
                html.Div([
                    html.Div([
                        html.Label('Export Format:', className='form-label'),
                        dcc.RadioItems(
                            id='export-format',
                            options=[
                                {'label': ' CSV', 'value': 'csv'},
                                {'label': ' Excel (.xlsx)', 'value': 'xlsx'},
                                {'label': ' JSON', 'value': 'json'},
                            ],
                            value='csv',
                            inline=True,
                            className='mb-2'
                        ),
                    ], className='col-md-6'),
                    
                    html.Div([
                        html.Label('Include Transaction History:', className='form-label'),
                        dcc.RadioItems(
                            id='include-transactions',
                            options=[
                                {'label': ' No', 'value': False},
                                {'label': ' Yes (Separate Sheet/File)', 'value': True},
                            ],
                            value=False,
                            inline=True,
                            className='mb-2'
                        ),
                    ], className='col-md-6'),
                ], className='row'),
            ], className='mb-3'),
            
            html.Button('📋 Preview Custom Export', 
                       id='preview-custom-btn',
                       className='btn btn-info m-2'),
            html.Button('💾 Download Custom Export', 
                       id='download-custom-btn',
                       className='btn btn-warning m-2'),
        ], className='border p-3 rounded'),
        
        html.Div(id='export-result', className='mt-4'),
        
        # Hidden download components
        dcc.Download(id='download-default-csv'),
        dcc.Download(id='download-custom-file')
    ])

# PERFORMANCE ANALYSIS CALLBACK - ALREADY IMPLEMENTED IN COMPLETE DASHBOARD

@app.callback(
    Output('performance-output', 'children'),
    Input('generate-performance-btn', 'n_clicks'),
    [State('perf-start-date', 'date'),
     State('perf-end-date', 'date'),
     State('benchmark-select', 'value')],
    prevent_initial_call=True
)
def generate_performance_analysis(n_clicks, start_date, end_date, benchmark):
    try:
        positions = get_portfolio_positions()
        if positions.empty:
            return html.Div("No portfolio positions found", className="alert alert-warning")
        
        # Calculate portfolio weights
        total_value = positions['current_value'].sum()
        positions['weight'] = positions['current_value'] / total_value
        
        # Get price data for portfolio stocks
        portfolio_data = []
        for _, pos in positions.iterrows():
            ticker = pos['ticker']
            weight = pos['weight']
            prices = get_daily_prices(ticker, start_date, end_date)
            if not prices.empty:
                prices['weighted_return'] = prices['adj_close'].pct_change() * weight
                portfolio_data.append(prices[['date', 'weighted_return']].dropna())
        
        if not portfolio_data:
            return html.Div("No price data found for selected period", className="alert alert-warning")
        
        # Combine portfolio data
        portfolio_returns = portfolio_data[0][['date']].copy()
        portfolio_returns['portfolio_return'] = sum(df['weighted_return'] for df in portfolio_data)
        portfolio_returns['cumulative_return'] = (1 + portfolio_returns['portfolio_return']).cumprod() - 1
        
        # Calculate dynamic stock count based on execution history for each date
        executions = get_portfolio_executions()
        portfolio_returns['stock_count'] = portfolio_returns['date'].apply(
            lambda date: calculate_stocks_on_date(executions, date)
        )
        
        # Get benchmark data
        benchmark_returns = None
        if benchmark != 'NONE':
            spy_prices = get_daily_prices(benchmark, start_date, end_date)
            if not spy_prices.empty:
                spy_prices['return'] = spy_prices['adj_close'].pct_change()
                spy_prices['cumulative_return'] = (1 + spy_prices['return']).cumprod() - 1
                benchmark_returns = spy_prices
        
        # Create cumulative returns chart
        fig = go.Figure()
        
        fig.add_trace(go.Scatter(
            x=portfolio_returns['date'],
            y=portfolio_returns['cumulative_return'] * 100,
            mode='lines',
            name='Portfolio',
            line=dict(color='blue', width=2),
            customdata=portfolio_returns['stock_count'],
            hovertemplate='<b>Portfolio</b><br>' +
                         'Date: %{x}<br>' +
                         'Return: %{y:.2f}%<br>' +
                         'Stocks: %{customdata}<br>' +
                         '<extra></extra>'
        ))
        
        if benchmark_returns is not None:
            fig.add_trace(go.Scatter(
                x=benchmark_returns['date'],
                y=benchmark_returns['cumulative_return'] * 100,
                mode='lines',
                name=benchmark,
                line=dict(color='red', width=2, dash='dash')
            ))
        
        fig.update_layout(
            title='Cumulative Returns Comparison',
            xaxis_title='Date',
            yaxis_title='Cumulative Return (%)',
            hovermode='x unified',
            height=400,
            xaxis=dict(range=[portfolio_returns['date'].min(), portfolio_returns['date'].max()]),
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="center",
                x=0.5
            ),
            title_y=0.95,
            margin=dict(t=50, b=40)
        )
        
        # Create drawdown chart
        fig_drawdown = go.Figure()
        
        # Calculate portfolio drawdown
        portfolio_cumulative = (1 + portfolio_returns['portfolio_return']).cumprod()
        portfolio_rolling_max = portfolio_cumulative.expanding().max()
        portfolio_drawdown = (portfolio_cumulative / portfolio_rolling_max - 1) * 100
        
        # Add zero baseline first (for proper fill reference)
        fig_drawdown.add_trace(go.Scatter(
            x=portfolio_returns['date'],
            y=[0] * len(portfolio_returns),
            mode='lines',
            name='Zero Line',
            line=dict(color='black', width=1),
            showlegend=False
        ))
        
        # Add portfolio drawdown
        fig_drawdown.add_trace(go.Scatter(
            x=portfolio_returns['date'],
            y=portfolio_drawdown,
            mode='lines',
            name='Portfolio Drawdown',
            line=dict(color='red', width=2),
            fill='tonexty',
            fillcolor='rgba(255, 0, 0, 0.3)',
            customdata=portfolio_returns['stock_count'],
            hovertemplate='<b>Portfolio Drawdown</b><br>' +
                         'Date: %{x}<br>' +
                         'Drawdown: %{y:.2f}%<br>' +
                         'Stocks: %{customdata}<br>' +
                         '<extra></extra>'
        ))
        
        # Add benchmark drawdown if available
        if benchmark_returns is not None:
            bench_cumulative = (1 + benchmark_returns['return']).cumprod()
            bench_rolling_max = bench_cumulative.expanding().max()
            bench_drawdown = (bench_cumulative / bench_rolling_max - 1) * 100
            
            fig_drawdown.add_trace(go.Scatter(
                x=benchmark_returns['date'],
                y=bench_drawdown,
                mode='lines',
                name=f'{benchmark} Drawdown',
                line=dict(color='blue', width=2, dash='dash'),
                fill='tozeroy',
                fillcolor='rgba(0, 0, 255, 0.15)'
            ))
        
        fig_drawdown.update_layout(
            title='Drawdown Analysis',
            xaxis_title='Date',
            yaxis_title='Drawdown (%)',
            hovermode='x unified',
            height=300,
            yaxis=dict(zeroline=True, zerolinecolor='black', zerolinewidth=2),
            xaxis=dict(range=[portfolio_returns['date'].min(), portfolio_returns['date'].max()]),
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="center",
                x=0.5
            ),
            title_y=0.95,
            margin=dict(t=50, b=40)
        )
        
        # Calculate comprehensive performance statistics
        portfolio_stats = calculate_comprehensive_metrics(portfolio_returns['portfolio_return'])
        benchmark_stats = None
        
        if benchmark_returns is not None:
            benchmark_stats = calculate_comprehensive_metrics(benchmark_returns['return'].dropna())
        
        # Create statistics table
        metrics = [
            'Total Return (%)',
            'Annualized Return (%)', 
            'Annualized Volatility (%)',
            'Sharpe Ratio',
            'Max Drawdown (%)',
            'VaR 95% (%)',
            'CVaR 95% (%)',
            'Calmar Ratio'
        ]
        
        stats_data = []
        for metric in metrics:
            row = {'Metric': metric}
            portfolio_val = portfolio_stats.get(metric, 'N/A')
            row['Portfolio'] = f"{portfolio_val:.2f}" if isinstance(portfolio_val, (int, float)) else portfolio_val
            
            if benchmark_stats:
                bench_val = benchmark_stats.get(metric, 'N/A')
                row[benchmark] = f"{bench_val:.2f}" if isinstance(bench_val, (int, float)) else bench_val
            stats_data.append(row)
        
        columns = [{'name': 'Metric', 'id': 'Metric'}, {'name': 'Portfolio', 'id': 'Portfolio'}]
        if benchmark_returns is not None:
            columns.append({'name': benchmark, 'id': benchmark})
        
        return html.Div([
            dcc.Graph(figure=fig),
            dcc.Graph(figure=fig_drawdown),
            html.H4('Performance Metrics'),
            dash_table.DataTable(
                data=stats_data,
                columns=columns,
                style_cell={'textAlign': 'left'},
                style_data_conditional=[
                    {
                        'if': {'row_index': 0},
                        'backgroundColor': '#e8f5e8',
                        'color': 'black',
                    },
                ],
                style_header={
                    'backgroundColor': 'rgb(230, 230, 230)',
                    'fontWeight': 'bold'
                }
            )
        ])
        
    except Exception as e:
        return html.Div([
            html.H4("Error generating performance report"),
            html.P(f"Error: {str(e)}"),
            html.P("Please check your date range and try again.")
        ], className="alert alert-danger")

# EXECUTE TRADES CALLBACKS

@app.callback(
    Output('ticker-info', 'children'),
    Input('trade-ticker', 'value'),
    prevent_initial_call=True
)
def show_ticker_info(ticker):
    if not ticker:
        return ""
    
    try:
        positions = get_portfolio_positions()
        position = positions[positions['ticker'] == ticker]
        
        if not position.empty:
            pos = position.iloc[0]
            position_info = f"Current Position: {pos['shares']} shares, Avg Cost: ${pos['avg_cost_basis']:.2f}"
        else:
            position_info = "No current position"
        
        # Get latest price
        prices = get_daily_prices(ticker)
        if not prices.empty:
            latest_price = prices.iloc[-1]['adj_close']
            price_info = f"Latest Price: ${latest_price:.2f} ({prices.iloc[-1]['date']})"
        else:
            price_info = "No price data available"
        
        return html.Div([
            html.P(position_info, className='text-info'),
            html.P(price_info, className='text-muted')
        ])
        
    except Exception as e:
        return html.P(f"Error: {str(e)}", className='text-danger')

@app.callback(
    Output('trade-price', 'value'),
    Input('get-price-btn', 'n_clicks'),
    State('trade-ticker', 'value'),
    prevent_initial_call=True
)
def get_latest_price(n_clicks, ticker):
    if not ticker:
        return no_update
    
    try:
        prices = get_daily_prices(ticker)
        if not prices.empty:
            return float(prices.iloc[-1]['adj_close'])
    except:
        pass
    
    return dash.no_update

@app.callback(
    Output('trade-value-display', 'children'),
    [Input('trade-shares', 'value'),
     Input('trade-price', 'value')],
    prevent_initial_call=True
)
def calculate_trade_value(shares, price):
    if shares and price and shares > 0 and price > 0:
        total = shares * price
        return f"${total:,.2f}"
    return "Enter shares and price"

@app.callback(
    Output('trade-preview', 'children'),
    [Input('trade-ticker', 'value'),
     Input('trade-action', 'value'),
     Input('trade-shares', 'value'),
     Input('trade-price', 'value')],
    prevent_initial_call=True
)
def show_trade_preview(ticker, action, shares, price):
    if not all([ticker, action, shares, price]) or shares <= 0 or price <= 0:
        return ""
    
    trade_value = shares * price
    
    return html.Div([
        html.H5("Trade Preview:", className="text-primary"),
        html.P(f"{action} {shares} shares of {ticker} at ${price:.2f}"),
        html.P(f"Total Trade Value: ${trade_value:,.2f}", className="fw-bold")
    ], className="alert alert-info")

@app.callback(
    Output('trade-result', 'children'),
    Input('execute-trade-btn', 'n_clicks'),
    [State('trade-ticker', 'value'),
     State('trade-action', 'value'),
     State('trade-shares', 'value'),
     State('trade-price', 'value')],
    prevent_initial_call=True
)
def execute_trade(n_clicks, ticker, action, shares, price):
    if not all([ticker, action, shares, price]):
        return html.Div("Please fill in all fields", className="alert alert-danger")
    
    if shares <= 0 or price <= 0:
        return html.Div("Shares and price must be positive", className="alert alert-danger")
    
    try:
        conn = get_rds_connection()
        cursor = conn.cursor()
        
        # Check current position
        cursor.execute("""
            SELECT shares, total_cost_basis FROM portfolio_positions 
            WHERE ticker = %s
        """, (ticker,))
        
        result = cursor.fetchone()
        current_shares = result[0] if result else 0
        current_cost = result[1] if result else 0
        
        # Validate SELL
        if action == 'SELL' and current_shares < shares:
            return html.Div(
                f"Cannot sell {shares} shares - only {current_shares} available", 
                className="alert alert-danger"
            )
        
        # Calculate trade values
        trade_value = Decimal(str(shares)) * Decimal(str(price))
        
        # Insert execution record
        cursor.execute("""
            INSERT INTO portfolio_executions 
            (ticker, action, shares, price, total_cost, execution_date, fees)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (ticker, action, shares, price, float(trade_value), datetime.date.today(), 0))
        
        # Update position
        if action == 'BUY':
            if result:  # Position exists
                new_shares = current_shares + shares
                new_cost = current_cost + float(trade_value)
                new_avg_cost = new_cost / new_shares
                
                cursor.execute("""
                    UPDATE portfolio_positions 
                    SET shares = %s, total_cost_basis = %s, avg_cost_basis = %s,
                        current_value = %s * %s, last_updated = CURRENT_TIMESTAMP
                    WHERE ticker = %s
                """, (new_shares, new_cost, new_avg_cost, new_shares, price, ticker))
            else:  # New position
                cursor.execute("""
                    INSERT INTO portfolio_positions 
                    (ticker, shares, avg_cost_basis, total_cost_basis, current_value)
                    VALUES (%s, %s, %s, %s, %s)
                """, (ticker, shares, price, float(trade_value), float(trade_value)))
        
        else:  # SELL
            new_shares = current_shares - shares
            cost_per_share = current_cost / current_shares
            new_cost = cost_per_share * new_shares
            
            if new_shares > 0:
                cursor.execute("""
                    UPDATE portfolio_positions 
                    SET shares = %s, total_cost_basis = %s, avg_cost_basis = %s,
                        current_value = %s * %s, last_updated = CURRENT_TIMESTAMP
                    WHERE ticker = %s
                """, (new_shares, new_cost, new_cost/new_shares, new_shares, price, ticker))
            else:
                cursor.execute("DELETE FROM portfolio_positions WHERE ticker = %s", (ticker,))
        
        conn.commit()
        conn.close()
        
        return html.Div([
            html.H5("✅ Trade Executed Successfully!", className="text-success"),
            html.P(f"{action} {shares} shares of {ticker} at ${price:.2f}"),
            html.P(f"Trade Value: ${float(trade_value):,.2f}"),
        ], className="alert alert-success")
        
    except Exception as e:
        return html.Div(f"Error executing trade: {str(e)}", className="alert alert-danger")

# UPDATE PRICES CALLBACK

@app.callback(
    Output('price-update-result', 'children'),
    Input('update-all-prices-btn', 'n_clicks'),
    prevent_initial_call=True
)
def update_all_prices(n_clicks):
    try:
        positions = get_portfolio_positions()
        if positions.empty:
            return html.Div("No positions to update", className="alert alert-info")
        
        conn = get_rds_connection()
        cursor = conn.cursor()
        
        updated_count = 0
        for _, pos in positions.iterrows():
            ticker = pos['ticker']
            shares = pos['shares']
            
            # Get latest price
            prices = get_daily_prices(ticker)
            if not prices.empty:
                latest_price = float(prices.iloc[-1]['adj_close'])
                new_value = shares * latest_price
                unrealized_pnl = new_value - pos['total_cost_basis']
                
                cursor.execute("""
                    UPDATE portfolio_positions 
                    SET current_value = %s, unrealized_pnl = %s, last_updated = CURRENT_TIMESTAMP
                    WHERE ticker = %s
                """, (new_value, unrealized_pnl, ticker))
                
                updated_count += 1
        
        conn.commit()
        conn.close()
        
        return html.Div([
            html.H5("✅ Price Update Complete", className="text-success"),
            html.P(f"Updated {updated_count} positions with latest market prices")
        ], className="alert alert-success")
        
    except Exception as e:
        return html.Div(f"Error updating prices: {str(e)}", className="alert alert-danger")

# PORTFOLIO EXPORT CALLBACKS

@app.callback(
    Output('export-result', 'children'),
    [Input('generate-summary-btn', 'n_clicks'),
     Input('export-default-csv-btn', 'n_clicks'),
     Input('preview-custom-btn', 'n_clicks'),
     Input('download-custom-btn', 'n_clicks')],
    [State('portfolio-fields', 'value'),
     State('calculated-fields', 'value'),
     State('export-format', 'value'),
     State('include-transactions', 'value')],
    prevent_initial_call=True
)
def handle_export(summary_clicks, default_csv_clicks, preview_clicks, download_clicks,
                 portfolio_fields, calculated_fields, export_format, include_transactions):
    ctx = callback_context
    if not ctx.triggered:
        return ""
    
    button_id = ctx.triggered[0]['prop_id'].split('.')[0]
    
    try:
        positions = get_portfolio_positions()
        
        if button_id == 'generate-summary-btn':
            if positions.empty:
                return html.Div("No positions to summarize", className="alert alert-info")
            
            total_value = positions['current_value'].sum()
            total_cost = positions['total_cost_basis'].sum()
            total_pnl = positions['unrealized_pnl'].sum()
            return_pct = (total_pnl / total_cost * 100) if total_cost > 0 else 0
            
            return html.Div([
                html.H5("📊 Portfolio Summary Report", className="text-primary"),
                html.P(f"Total Positions: {len(positions)}"),
                html.P(f"Total Market Value: ${total_value:,.2f}"),
                html.P(f"Total Cost Basis: ${total_cost:,.2f}"),
                html.P(f"Total Unrealized P&L: ${total_pnl:,.2f}"),
                html.P(f"Overall Return: {return_pct:.2f}%", 
                       className="text-success" if return_pct >= 0 else "text-danger"),
                html.P(f"Report generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", 
                       className="text-muted small")
            ], className="alert alert-info")
            
        elif button_id == 'export-default-csv-btn':
            if positions.empty:
                return html.Div("No positions to export", className="alert alert-info")
            
            # Create default export data with standard fields
            default_fields = ['ticker', 'shares', 'avg_cost_basis', 'current_value', 'unrealized_pnl']
            default_calc_fields = ['portfolio_weight', 'roi_percentage']
            
            export_data = prepare_export_data(positions, default_fields, default_calc_fields)
            
            return html.Div([
                html.H5("📄 Default CSV Export Ready", className="text-success"),
                html.P(f"Portfolio data with {len(positions)} positions and {len(export_data.columns)} fields prepared"),
                html.P(f"Fields included: {', '.join(export_data.columns)}", className="text-muted small"),
                html.P("💡 In production, this would trigger an immediate CSV download.", 
                       className="text-muted small"),
                html.Hr(),
                html.H6("Preview (First 5 rows):", className="mt-3"),
                dash_table.DataTable(
                    data=export_data.head().to_dict('records'),
                    columns=[{'name': col, 'id': col} for col in export_data.columns],
                    style_cell={'textAlign': 'left', 'padding': '5px'},
                    style_header={'backgroundColor': 'rgb(230, 230, 230)', 'fontWeight': 'bold'},
                    page_size=5
                )
            ], className="alert alert-success")
            
        elif button_id == 'preview-custom-btn':
            if positions.empty:
                return html.Div("No positions to preview", className="alert alert-info")
            
            if not portfolio_fields and not calculated_fields:
                return html.Div("Please select at least one field to export", className="alert alert-warning")
            
            export_data = prepare_export_data(positions, portfolio_fields or [], calculated_fields or [])
            
            if export_data.empty:
                return html.Div("No data available with selected fields", className="alert alert-warning")
            
            # Get transaction data if requested
            transaction_preview = ""
            if include_transactions:
                transactions = get_portfolio_executions()
                if not transactions.empty:
                    transaction_preview = html.Div([
                        html.Hr(),
                        html.H6("Transaction History Preview (First 5 rows):", className="mt-3"),
                        dash_table.DataTable(
                            data=transactions.head().to_dict('records'),
                            columns=[{'name': col, 'id': col} for col in transactions.columns],
                            style_cell={'textAlign': 'left', 'padding': '5px'},
                            style_header={'backgroundColor': 'rgb(230, 230, 230)', 'fontWeight': 'bold'},
                            page_size=5
                        )
                    ])
            
            return html.Div([
                html.H5("📋 Custom Export Preview", className="text-info"),
                html.P(f"Format: {export_format.upper()}", className="fw-bold"),
                html.P(f"Portfolio fields: {len(export_data.columns)} fields, {len(positions)} positions"),
                html.P(f"Fields: {', '.join(export_data.columns)}", className="text-muted small"),
                html.Hr(),
                html.H6("Portfolio Preview (First 5 rows):", className="mt-3"),
                dash_table.DataTable(
                    data=export_data.head().to_dict('records'),
                    columns=[{'name': col, 'id': col} for col in export_data.columns],
                    style_cell={'textAlign': 'left', 'padding': '5px'},
                    style_header={'backgroundColor': 'rgb(230, 230, 230)', 'fontWeight': 'bold'},
                    page_size=5
                ),
                transaction_preview
            ], className="alert alert-info")
            
        elif button_id == 'download-custom-btn':
            if positions.empty:
                return html.Div("No positions to export", className="alert alert-info")
            
            if not portfolio_fields and not calculated_fields:
                return html.Div("Please select at least one field to export", className="alert alert-warning")
            
            export_data = prepare_export_data(positions, portfolio_fields or [], calculated_fields or [])
            
            if export_data.empty:
                return html.Div("No data available with selected fields", className="alert alert-warning")
            
            # Prepare file info
            file_extensions = {'csv': 'CSV', 'xlsx': 'Excel', 'json': 'JSON'}
            file_type = file_extensions.get(export_format, 'CSV')
            
            additional_info = ""
            if include_transactions:
                transactions = get_portfolio_executions()
                if not transactions.empty:
                    additional_info = f" + {len(transactions)} transaction records"
            
            return html.Div([
                html.H5("💾 Custom Export Ready for Download", className="text-warning"),
                html.P(f"Format: {file_type} ({export_format})", className="fw-bold"),
                html.P(f"Portfolio: {len(export_data.columns)} fields, {len(positions)} positions{additional_info}"),
                html.P(f"Fields: {', '.join(export_data.columns)}", className="text-muted small"),
                html.P("💡 In production, this would trigger a customized file download.", 
                       className="text-muted small"),
                html.P(f"Generated: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", 
                       className="text-muted small")
            ], className="alert alert-warning")
            
    except Exception as e:
        return html.Div(f"Export error: {str(e)}", className="alert alert-danger")

# Default CSV Download Callback
@app.callback(
    Output('download-default-csv', 'data'),
    Input('export-default-csv-btn', 'n_clicks'),
    prevent_initial_call=True
)
def download_default_csv(n_clicks):
    if n_clicks:
        try:
            positions = get_portfolio_positions()
            if positions.empty:
                return None
            
            # Create default export data
            default_fields = ['ticker', 'shares', 'avg_cost_basis', 'current_value', 'unrealized_pnl']
            default_calc_fields = ['portfolio_weight', 'roi_percentage']
            
            export_data = prepare_export_data(positions, default_fields, default_calc_fields)
            
            # Generate filename with timestamp
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"alphaview_portfolio_{timestamp}.csv"
            
            return dcc.send_data_frame(export_data.to_csv, filename, index=False)
            
        except Exception as e:
            print(f"Error generating default CSV: {e}")
            return None
    
    return None

# Custom File Download Callback
@app.callback(
    Output('download-custom-file', 'data'),
    Input('download-custom-btn', 'n_clicks'),
    [State('portfolio-fields', 'value'),
     State('calculated-fields', 'value'),
     State('export-format', 'value'),
     State('include-transactions', 'value')],
    prevent_initial_call=True
)
def download_custom_file(n_clicks, portfolio_fields, calculated_fields, export_format, include_transactions):
    if n_clicks:
        try:
            positions = get_portfolio_positions()
            if positions.empty:
                return None
            
            if not portfolio_fields and not calculated_fields:
                return None
            
            export_data = prepare_export_data(positions, portfolio_fields or [], calculated_fields or [])
            
            if export_data.empty:
                return None
            
            # Generate filename with timestamp
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            
            if export_format == 'csv':
                filename = f"alphaview_custom_{timestamp}.csv"
                
                if include_transactions:
                    # Create a ZIP file with both portfolio and transactions
                    # Get transaction data
                    transactions = get_portfolio_executions()
                    
                    # Create ZIP buffer
                    zip_buffer = io.BytesIO()
                    
                    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
                        # Add portfolio CSV
                        portfolio_csv = export_data.to_csv(index=False)
                        zip_file.writestr(f"portfolio_{timestamp}.csv", portfolio_csv)
                        
                        # Add transactions CSV
                        if not transactions.empty:
                            transactions_csv = transactions.to_csv(index=False)
                            zip_file.writestr(f"transactions_{timestamp}.csv", transactions_csv)
                    
                    zip_buffer.seek(0)
                    return dcc.send_bytes(zip_buffer.getvalue(), f"alphaview_export_{timestamp}.zip")
                else:
                    return dcc.send_data_frame(export_data.to_csv, filename, index=False)
                    
            elif export_format == 'xlsx':
                filename = f"alphaview_custom_{timestamp}.xlsx"
                
                try:
                    if include_transactions:
                        # Create Excel file with multiple sheets
                        excel_buffer = io.BytesIO()
                        
                        # Get transaction data first
                        transactions = get_portfolio_executions()
                        
                        with pd.ExcelWriter(excel_buffer, engine='openpyxl') as writer:
                            # Write portfolio data to first sheet
                            export_data.to_excel(writer, sheet_name='Portfolio', index=False)
                            
                            # Write transactions to second sheet if available
                            if not transactions.empty:
                                # Format transaction dates for Excel
                                transactions_copy = transactions.copy()
                                if 'execution_date' in transactions_copy.columns:
                                    transactions_copy['execution_date'] = pd.to_datetime(transactions_copy['execution_date']).dt.strftime('%Y-%m-%d')
                                transactions_copy.to_excel(writer, sheet_name='Transactions', index=False)
                        
                        excel_buffer.seek(0)
                        return dcc.send_bytes(excel_buffer.getvalue(), filename)
                    else:
                        return dcc.send_data_frame(export_data.to_excel, filename, index=False, sheet_name='Portfolio')
                except Exception as e:
                    print(f"Excel export error: {e}")
                    # Fallback to CSV if Excel creation fails
                    filename = f"alphaview_custom_{timestamp}.csv"
                    return dcc.send_data_frame(export_data.to_csv, filename, index=False)
                    
            elif export_format == 'json':
                filename = f"alphaview_custom_{timestamp}.json"
                
                if include_transactions:
                    # Create combined JSON
                    transactions = get_portfolio_executions()
                    combined_data = {
                        'portfolio': export_data.to_dict('records'),
                        'transactions': transactions.to_dict('records') if not transactions.empty else [],
                        'export_date': datetime.datetime.now().isoformat(),
                        'total_positions': len(export_data)
                    }
                    json_string = json.dumps(combined_data, indent=2, default=str)
                    return dict(content=json_string, filename=filename)
                else:
                    return dcc.send_data_frame(export_data.to_json, filename, orient='records', indent=2)
            
        except Exception as e:
            print(f"Error generating custom file: {e}")
            return None
    
    return None


if __name__ == '__main__':
    print("🌐 Dashboard will be available at: http://localhost:8050")
    app.run(host='0.0.0.0', port=8050, debug=True)