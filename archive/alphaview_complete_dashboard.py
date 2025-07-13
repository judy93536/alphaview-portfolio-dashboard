#!/usr/bin/env python3
"""
AlphaView Portfolio Dashboard - Complete Authenticated Version with Full Functionality
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
print(f"🚀 Starting AlphaView Portfolio Dashboard with Full Authentication...")
print(f"📊 Data available from {MIN_DATE} to {MAX_DATE}")

# Define initial layout with login form
app.layout = html.Div([
    dcc.Location(id='url', refresh=False),
    html.Div(id='page-content', children=[
        html.Div([
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

def render_performance():
    """Render Performance analysis with full functionality"""
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

# Performance analysis callback - FULL FUNCTIONALITY
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

# Other render functions (basic versions for now)
def render_target_vs_actual():
    """Render Target vs Actual allocation analysis"""
    try:
        positions = get_portfolio_positions()
        targets = get_portfolio_targets()
        
        if positions.empty:
            return html.Div([
                html.H3('📊 Target vs Actual Analysis'),
                html.Div('No portfolio positions found.', className='alert alert-info')
            ])
        
        # Calculate total portfolio value
        total_value = positions['current_value'].sum()
        
        return html.Div([
            html.H3('📊 Target vs Actual Analysis'),
            html.Div([
                html.H5(f"Total Portfolio Value: ${total_value:,.2f}"),
                html.P(f"Number of positions: {len(positions)}"),
                html.P("✅ Real data from AWS RDS"),
                html.P(f"Current user: {session.get('user')} ({session.get('role')})")
            ], className="alert alert-success")
        ])
        
    except Exception as e:
        return html.Div([
            html.H3('📊 Target vs Actual Analysis'),
            html.Div(f'Error loading data: {str(e)}', className='alert alert-danger')
        ])

def render_execute_trades():
    return html.Div([
        html.H3('🔒 Execute Trades (Admin Only)'),
        html.Div([
            html.P("✅ Admin access confirmed"),
            html.P("Execute trades functionality will be added next"),
            html.P(f"Current admin: {session.get('user')}")
        ], className="alert alert-success")
    ])

def render_update_prices():
    return html.Div([
        html.H3('💰 Update Prices'),
        html.P('Price update functionality for admin users.')
    ])

def render_transaction_log():
    return html.Div([
        html.H3('📋 Transaction History'),
        html.P('Transaction log functionality will be added next')
    ])

def render_portfolio_export():
    return html.Div([
        html.H3('📤 Portfolio Export'),
        html.P('Export functionality will be added next')
    ])

if __name__ == '__main__':
    print("🌐 Dashboard will be available at: http://localhost:8051")
    app.run(host='0.0.0.0', port=8051, debug=True)