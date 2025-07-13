# AlphaView Portfolio Dashboard

A professional portfolio management dashboard for Series 65 certification preparation, featuring real-time portfolio tracking, performance analytics, and role-based access control.

## Features

- **Real-time Portfolio Tracking** - Live position monitoring with P&L calculations
- **Performance Analytics** - VaR, CVaR, Sharpe Ratio, drawdown analysis
- **Role-based Access Control** - Admin (trading) vs Viewer (read-only) roles
- **Portfolio Export** - CSV, Excel, JSON formats with customizable fields
- **Trade Execution** - Buy/sell functionality with real position updates
- **Authentication** - AWS Cognito integration with secure login flows

## System Architecture

- **Frontend**: Dash/Plotly web application
- **Backend**: Python with PostgreSQL databases
- **Authentication**: AWS Cognito User Pool
- **Hosting**: AWS Lightsail (Ubuntu 22.04)
- **Database**: AWS RDS PostgreSQL
- **Proxy**: Nginx reverse proxy

## Quick Start

### Production Access
- **Dashboard URL**: http://35.80.141.177
- **Demo Account**: viewer@alphaview.com

### Local Development
```bash
# Clone repository
git clone https://github.com/judy93536/alphaview-portfolio-dashboard.git
cd alphaview-portfolio-dashboard

# Install dependencies
pip install -r requirements.txt

# Set environment variables (see config/env.example)
export AWS_PROFILE=alphaview
export COGNITO_USER_POOL_ID=us-west-2_BzA3NZOv6
# ... other variables

# Run dashboard
python src/alphaview_fully_functional.py
```

## Project Structure

```
alphaview-portfolio-dashboard/
├── README.md                  # This file
├── requirements.txt           # Python dependencies
├── .gitignore                # Git ignore patterns
├── src/                      # Main application code
│   ├── alphaview_fully_functional.py  # Main dashboard app
│   ├── auth_utils_*.py       # Authentication utilities
│   └── cognito_config.py     # Cognito configuration
├── config/                   # Configuration files
│   ├── env.example          # Environment variables template
│   └── nginx.conf           # Nginx configuration
├── deployment/              # Deployment files
│   ├── alphaview.service    # Systemd service file
│   └── deploy.sh           # Deployment script
├── scripts/                 # Utility scripts
│   ├── update_mediawiki.py  # MediaWiki documentation updater
│   └── backup.sh           # Backup scripts
├── tests/                   # Test files
├── docs/                    # Documentation
│   ├── USER_ADMIN_README.md # User administration guide
│   └── User_Administration_MediaWiki.txt # Wiki documentation
└── archive/                 # Development versions and backups
```

## Configuration

### Required Environment Variables
```bash
AWS_PROFILE=alphaview
COGNITO_USER_POOL_ID=us-west-2_BzA3NZOv6
COGNITO_CLIENT_ID=your_client_id
RDS_SECRET_NAME=LightsailAlphaView_Key
```

### AWS Services Required
- **Cognito User Pool** - User authentication
- **RDS PostgreSQL** - Portfolio and price data
- **Secrets Manager** - Database credentials
- **Lightsail** - Application hosting

## User Management

See [docs/USER_ADMIN_README.md](docs/USER_ADMIN_README.md) for complete user administration guide.

### User Roles
- **Admin**: Full access including trade execution and price updates
- **Viewer**: Read-only access to portfolio data and analytics

## Deployment

### Production Server
- **Server**: AWS Lightsail Ubuntu 22.04
- **IP**: 35.80.141.177
- **Service**: systemd service `alphaview.service`
- **Port**: 8050 (internal) / 80 (external via Nginx)

### Deploy Updates
```bash
# Copy new code to server
scp -i deployment/lightsail-django-8gb.pem src/alphaview_fully_functional.py ubuntu@35.80.141.177:/opt/alphaview/

# Restart service
ssh -i deployment/lightsail-django-8gb.pem ubuntu@35.80.141.177 "sudo systemctl restart alphaview"
```

## Development

### Database Schema
- `portfolio_positions` - Current holdings
- `portfolio_targets` - Target allocations  
- `portfolio_executions` - Trade history
- `daily_prices` - Historical price data

### Adding New Features
1. Create feature branch
2. Update main dashboard file
3. Test locally
4. Deploy to production
5. Update documentation

## Security

- Database credentials stored in AWS Secrets Manager
- Authentication via AWS Cognito
- Role-based access control
- No hardcoded credentials in code

## Support

For technical issues:
1. Check logs: `sudo journalctl -u alphaview -f`
2. Verify service status: `sudo systemctl status alphaview`
3. Check database connectivity
4. Review user administration documentation

## License

Private repository - AlphaView Portfolio Management

---

**Last Updated**: 2025-07-13  
**Version**: 1.0.0  
**Author**: Judy (judy93536)