#!/usr/bin/env python3
"""
AlphaView Portfolio Dashboard with AWS Cognito Authentication
"""

import os
os.environ['AWS_PROFILE'] = 'alphaview'

import dash
from dash import dcc, html, Input, Output, State, dash_table, callback_context
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

# Import our existing modules
from auth_utils import CognitoAuth, login_required, admin_required
from cognito_config import COGNITO_CONFIG

# Import all functions from original dashboard
from standalone_dashboard import (
    get_rds_config, get_rds_connection, get_portfolio_positions,
    get_portfolio_targets, get_portfolio_executions, get_daily_prices,
    get_date_range, calculate_stocks_on_date, calculate_comprehensive_metrics
)

# Initialize Dash app with Flask server access
app = dash.Dash(__name__, 
               external_stylesheets=[
                   'https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css'
               ],
               suppress_callback_exceptions=True)  # This prevents the callback errors

# Configure secret key for sessions
app.server.secret_key = 'alphaview-secret-key-change-in-production'

# Initialize Cognito auth
cognito_auth = CognitoAuth()

# Get date range for the app
MIN_DATE, MAX_DATE = get_date_range()
print(f"🚀 Starting AlphaView Portfolio Dashboard with Authentication...")
print(f"📊 Data available from {MIN_DATE} to {MAX_DATE}")

# Define initial layout with login form
app.layout = html.Div([
    dcc.Location(id='url', refresh=False),
    html.Div(id='page-content', children=[
        # Initial login form
        html.Div([
            html.Div([
                html.H2('AlphaView Portfolio Dashboard', className='text-center mb-4'),
                html.Div([
                    html.H4('Login', className='text-center mb-3'),
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
    [Input('login-button', 'n_clicks'),
     Input('url', 'pathname')],
    [State('username', 'value'),
     State('password', 'value')],
    prevent_initial_call=False
)
def handle_authentication(login_clicks, pathname, username, password):
    ctx = callback_context
    
    # Handle logout
    if pathname == '/logout':
        session.clear()
        return display_login_form("Logged out successfully")
    
    # Check if user is already authenticated
    if 'user' in session:
        return display_dashboard()
    
    # Handle login attempt
    if login_clicks and username and password:
        result = cognito_auth.authenticate_user(username, password)
        
        if result.get('challenge') == 'NEW_PASSWORD_REQUIRED':
            return display_password_change_form(username, result['session'])
        elif result.get('success'):
            # Store user info in session
            session['user'] = username
            session['role'] = cognito_auth.get_user_role(username)
            session['access_token'] = result['access_token']
            return display_dashboard()
        else:
            return display_login_form(f"Login failed: {result.get('error', 'Unknown error')}")
    
    # Show login form
    return display_login_form()

def display_login_form(message=""):
    message_class = 'text-danger' if 'failed' in message.lower() else 'text-success' if message else ''
    
    return html.Div([
        html.Div([
            html.H2('AlphaView Portfolio Dashboard', className='text-center mb-4'),
            html.Div([
                html.H4('Login', className='text-center mb-3'),
                html.P('Test Users:', className='text-muted'),
                html.P('Admin: admin@alphaview.com', className='text-muted small'),
                html.P('Viewer: viewer@alphaview.com', className='text-muted small'),
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

def display_password_change_form(username, session_token):
    return html.Div([
        html.Div([
            html.H2('Password Change Required', className='text-center mb-4'),
            html.Div([
                html.P(f'Please set a new password for {username}'),
                dcc.Input(id='new-password', type='password', placeholder='New Password',
                         className='form-control mb-3'),
                html.Button('Change Password', id='change-password-button', n_clicks=0,
                           className='btn btn-primary w-100'),
                html.Div(id='password-change-message', className='mt-3')
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

# Tab content callback (only active when dashboard is displayed)
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
    username = session.get('user', 'Unknown')
    
    # Check admin access for restricted tabs
    if active_tab in ['execute-trades', 'update-prices'] and user_role != 'admin':
        return html.Div([
            html.H3("🔒 Access Denied", className="text-danger"),
            html.P("This feature requires admin privileges."),
            html.P("Please contact the administrator for access.")
        ], className="alert alert-danger")
    
    # Render tab content
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

# Render functions for each tab
def render_target_vs_actual():
    user_role = session.get('role', 'viewer')
    return html.Div([
        html.H3('📊 Portfolio Allocation Analysis'),
        html.Div([
            html.H5("Current Status"),
            html.P(f"✅ Authenticated as: {session.get('user')}"),
            html.P(f"✅ Access Level: {user_role.title()}"),
            html.P("Portfolio allocation analysis would be displayed here."),
            html.P("This tab shows target vs actual portfolio allocations."),
        ], className="alert alert-info")
    ])

def render_execute_trades():
    return html.Div([
        html.H3('🔒 Execute Trades (Admin Only)'),
        html.Div([
            html.H5("Trade Execution System"),
            html.P("🛡️ This is where portfolio trades would be executed."),
            html.P("✅ Access granted - Admin user confirmed"),
            html.P(f"Current admin: {session.get('user')}"),
            html.Hr(),
            html.P("Features would include:"),
            html.Ul([
                html.Li("Buy/Sell orders"),
                html.Li("Position sizing"),
                html.Li("Order confirmation"),
                html.Li("Trade execution log")
            ])
        ], className="alert alert-success")
    ])

def render_update_prices():
    return html.Div([
        html.H3('💰 Update Prices'),
        html.P('Price update functionality for admin users.'),
        html.P('This would connect to your daily price update pipeline.')
    ])

def render_performance():
    return html.Div([
        html.H3('📈 Performance Analysis'),
        html.P('Portfolio performance charts and metrics would be displayed here.'),
        html.P('This would show your enhanced performance visualizations with dynamic stock counts.')
    ])

def render_transaction_log():
    return html.Div([
        html.H3('📋 Transaction History'),
        html.P('Complete transaction history would be displayed here.'),
        html.P('Read-only access for all authenticated users.')
    ])

def render_portfolio_export():
    return html.Div([
        html.H3('📤 Portfolio Export'),
        html.P('Portfolio export functionality would be displayed here.'),
        html.P('Generate reports and download portfolio data.')
    ])

if __name__ == '__main__':
    print("🌐 Dashboard will be available at: http://localhost:8051")
    app.run(host='0.0.0.0', port=8051, debug=True)