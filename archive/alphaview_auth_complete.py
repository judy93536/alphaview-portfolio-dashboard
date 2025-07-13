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
app = dash.Dash(__name__, external_stylesheets=[
    'https://cdn.jsdelivr.net/npm/bootstrap@5.1.3/dist/css/bootstrap.min.css'
])

# Configure secret key for sessions
app.server.secret_key = 'alphaview-secret-key-change-in-production'

# Initialize Cognito auth
cognito_auth = CognitoAuth()

# Get date range for the app
MIN_DATE, MAX_DATE = get_date_range()
print(f"🚀 Starting AlphaView Portfolio Dashboard with Authentication...")
print(f"📊 Data available from {MIN_DATE} to {MAX_DATE}")

# Define layout
app.layout = html.Div([
    dcc.Location(id='url', refresh=False),
    html.Div(id='page-content')
])

@app.callback(
    Output('page-content', 'children'),
    [Input('url', 'pathname'),
     Input('login-button', 'n_clicks')],
    [State('username', 'value'),
     State('password', 'value')],
    prevent_initial_call=True
)
def handle_login_and_display(pathname, login_clicks, username, password):
    ctx = callback_context
    
    # Handle logout
    if pathname == '/logout':
        session.clear()
        return display_login_form("Logged out successfully")
    
    # Handle login button click
    if ctx.triggered and 'login-button.n_clicks' in str(ctx.triggered):
        if username and password:
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
        else:
            return display_login_form("Please enter username and password")
    
    # Check if user is already authenticated
    if 'user' in session:
        return display_dashboard()
    else:
        return display_login_form()

@app.callback(
    Output('page-content', 'children', allow_duplicate=True),
    Input('change-password-button', 'n_clicks'),
    [State('new-password', 'value'),
     State('username-hidden', 'value'),
     State('session-hidden', 'value')],
    prevent_initial_call=True
)
def handle_password_change(change_clicks, new_password, username, session_token):
    if change_clicks and new_password:
        result = cognito_auth.handle_new_password_challenge(username, new_password, session_token)
        
        if result.get('success'):
            # Store user info in session
            session['user'] = username
            session['role'] = cognito_auth.get_user_role(username)
            session['access_token'] = result['access_token']
            return display_dashboard()
        else:
            return display_password_change_form(username, session_token, f"Password change failed: {result.get('error')}")
    
    return display_login_form("Password change failed")

def display_login_form(message=""):
    return html.Div([
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
                html.Div(message, className='text-danger mt-3' if 'failed' in message.lower() else 'text-success mt-3')
            ], className='card-body'),
        ], className='card mx-auto mt-5', style={'max-width': '400px'})
    ], className='container')

def display_password_change_form(username, session_token, message=""):
    return html.Div([
        html.Div([
            html.H2('Change Password Required', className='text-center mb-4'),
            html.Div([
                html.P(f'Please set a new password for {username}'),
                dcc.Input(id='new-password', type='password', placeholder='New Password',
                         className='form-control mb-3'),
                html.Button('Change Password', id='change-password-button', n_clicks=0,
                           className='btn btn-primary w-100'),
                html.Div(message, className='text-danger mt-3'),
                # Hidden fields to store data
                html.Div(username, id='username-hidden', style={'display': 'none'}),
                html.Div(session_token, id='session-hidden', style={'display': 'none'})
            ], className='card-body'),
        ], className='card mx-auto mt-5', style={'max-width': '400px'})
    ], className='container')

def display_dashboard():
    user_role = session.get('role', 'viewer')
    
    # Define tabs based on role
    tabs = [
        dcc.Tab(label='Target vs Actual', value='target-vs-actual'),
        dcc.Tab(label='Performance', value='performance'),
        dcc.Tab(label='Transaction Log', value='transaction-log'),
        dcc.Tab(label='Portfolio Export', value='portfolio-export'),
    ]
    
    # Add admin-only tabs
    if user_role == 'admin':
        tabs.insert(1, dcc.Tab(label='Execute Trades', value='execute-trades'))
        tabs.insert(2, dcc.Tab(label='Update Prices', value='update-prices'))
    
    return html.Div([
        html.Div([
            html.Div([
                html.H1('AlphaView Portfolio Dashboard', className='display-4'),
                html.P(f'Welcome, {session.get("user", "User")} ({user_role})', 
                       className='lead'),
            ], className='col-md-8'),
            html.Div([
                html.A('Logout', href='/logout', className='btn btn-sm btn-secondary')
            ], className='col-md-4 text-end')
        ], className='row align-items-center jumbotron bg-light p-4 mb-4'),
        
        html.Div([
            dcc.Tabs(id='main-tabs', value='target-vs-actual', 
                     className='nav nav-tabs',
                     children=tabs),
            
            html.Div(id='tab-content', className='container-fluid mt-4')
        ], className='container-fluid')
    ], className='min-vh-100 bg-light')

# Copy the main tab content callback from standalone_dashboard.py
@app.callback(
    Output('tab-content', 'children'),
    Input('main-tabs', 'value')
)
def render_tab_content(active_tab):
    # Check authentication
    if 'user' not in session:
        return html.Div("Please login to access dashboard", className="alert alert-warning")
    
    user_role = session.get('role', 'viewer')
    
    # Check admin access for restricted tabs
    if active_tab in ['execute-trades', 'update-prices'] and user_role != 'admin':
        return html.Div([
            html.H3("Access Denied"),
            html.P("This feature requires admin privileges."),
            html.P("Please contact the administrator for access.")
        ], className="alert alert-danger")
    
    # Import and call the appropriate render function from standalone_dashboard
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

# Import render functions from standalone_dashboard (simplified versions)
def render_target_vs_actual():
    return html.Div([
        html.H2('Target vs Actual Analysis'),
        html.P('Portfolio allocation analysis will be displayed here.'),
        html.P(f'User role: {session.get("role", "unknown")}')
    ])

def render_execute_trades():
    return html.Div([
        html.H2('Execute Trades'),
        html.Div([
            html.H4("🔒 Admin Only Feature"),
            html.P("This is where portfolio trades would be executed."),
            html.P("Only admin users can access this functionality."),
            html.P(f'Current user: {session.get("user")} ({session.get("role")})')
        ], className="alert alert-info")
    ])

def render_update_prices():
    return html.Div([
        html.H2('Update Prices'),
        html.P('Price update functionality for admin users.')
    ])

def render_performance():
    return html.Div([
        html.H2('Performance Analysis'),
        html.P('Portfolio performance charts and metrics will be displayed here.')
    ])

def render_transaction_log():
    return html.Div([
        html.H2('Transaction Log'),
        html.P('Transaction history will be displayed here.')
    ])

def render_portfolio_export():
    return html.Div([
        html.H2('Portfolio Export'),
        html.P('Portfolio export functionality will be displayed here.')
    ])

if __name__ == '__main__':
    print("🌐 Dashboard will be available at: http://localhost:8051")
    app.run(host='0.0.0.0', port=8051, debug=True)