# AlphaView Portfolio Dashboard - User Administration Guide

## Overview

This guide explains how to add and manage users for the AlphaView Portfolio Dashboard using AWS Cognito. The system supports two user roles: **Admin** (full access) and **Viewer** (read-only access).

## Dashboard Access

- **Production URL**: http://35.80.141.177:8051
- **Authentication**: AWS Cognito User Pool
- **User Pool ID**: us-west-2_BzA3NZOv6

## User Roles

### 👑 Admin Group
- **Full Dashboard Access**: All tabs including Execute Trades and Update Prices
- **Trading Capabilities**: Can buy/sell stocks and execute portfolio trades
- **Price Updates**: Can update portfolio values with latest market prices
- **All Viewer Permissions**: Plus administrative functions

### 👁️ Viewer Group  
- **Read-Only Access**: Target vs Actual, Performance, Transaction Log, Portfolio Export
- **Analysis Tools**: Full performance analytics and reporting capabilities
- **Export Functions**: Can generate and download portfolio reports
- **No Trading**: Cannot execute trades or update prices

## Adding New Users

### Step 1: Access AWS Cognito Console

1. Log into AWS Console
2. Navigate to **Cognito** → **User pools**
3. Select your user pool: **User pool - kryhxh**

### Step 2: Create New User

1. Click **"Users"** tab
2. Click **"Create user"** button
3. Fill in user details:
   - **Email address**: Enter real email address (e.g., `john.doe@company.com`)
   - **Mark email as verified**: ✅ **REQUIRED - Check this box**
   - **Send an invitation**: ✅ Check this (sends login instructions via email)
   - **Temporary password**: 
     - Recommended: Let AWS generate one
     - Alternative: Set custom temporary password
   - **User must create a new password at next sign-in**: ✅ Check this

### Step 3: Assign User to Group

1. After creating the user, click on the user's email in the user list
2. Go to **"Group memberships"** tab
3. Click **"Add user to group"**
4. Select appropriate group:
   - **`admin`** - For users who need trading capabilities
   - **`viewer`** - For users who only need read-only access

## User Invitation Process

### What Happens When You Create a User

1. **Email Sent**: User receives an invitation email with:
   - Username (their email address)
   - Temporary password
   - Login URL: http://35.80.141.177:8051
   - Instructions for first login

2. **First Login Process**:
   - User visits the dashboard URL
   - Enters email + temporary password
   - System prompts for new permanent password
   - User creates secure password
   - Automatically redirected to dashboard based on role

## Managing Existing Users

### Change User Role
1. Go to **Users** → Select user → **Group memberships**
2. Remove from current group
3. Add to new group (`admin` or `viewer`)

### Reset User Password
1. Go to **Users** → Select user → **Actions** → **Reset password**
2. User will receive email with new temporary password

### Disable User Access
1. Go to **Users** → Select user → **Actions** → **Disable user**
2. User cannot login but account is preserved

### Delete User Account
1. Go to **Users** → Select user → **Actions** → **Delete user**
2. **Warning**: This permanently removes the user

## Example User Setup

```
Company: AlphaView Investment Management

Admin Users:
- portfolio.manager@alphaview.com (admin group)
- chief.trader@alphaview.com (admin group)
- risk.manager@alphaview.com (admin group)

Viewer Users:
- senior.analyst@alphaview.com (viewer group)
- investment.committee@alphaview.com (viewer group)
- compliance@alphaview.com (viewer group)
- client.reports@alphaview.com (viewer group)
```

## Dashboard Features by Role

### Admin Capabilities
- **Target vs Actual**: Portfolio allocation analysis with charts and tables
- **🔒 Execute Trades**: Buy/sell stocks with real-time position updates
- **Update Prices**: Refresh portfolio values with latest market data
- **Performance**: Advanced analytics with VaR, CVaR, Sharpe Ratio, drawdown analysis
- **Transaction Log**: Complete trade history with filtering and sorting
- **Portfolio Export**: CSV, Excel, JSON exports with custom field selection

### Viewer Capabilities
- **Target vs Actual**: Portfolio allocation analysis (read-only)
- **Performance**: All performance analytics and charting capabilities
- **Transaction Log**: View complete trade history (read-only)
- **Portfolio Export**: Full export capabilities with custom field selection
- **No Access**: Execute Trades and Update Prices tabs are hidden

## Security Best Practices

### User Management
- ✅ Always mark email addresses as verified when creating users
- ✅ Use strong temporary passwords or let AWS generate them
- ✅ Require users to create new passwords on first login
- ✅ Assign users to appropriate groups based on job function
- ✅ Regularly review user access and remove inactive accounts

### Email Verification
- **Critical**: Always check "Mark email as verified" 
- **Reason**: Prevents authentication issues and ensures proper email delivery
- **Impact**: Unverified emails cannot receive password reset notifications

### Group Assignment
- **Required**: Every user must be assigned to either `admin` or `viewer` group
- **No Group**: Users without group assignment cannot access the dashboard
- **Multiple Groups**: Not recommended - assign to one primary group

## Troubleshooting

### User Cannot Login
1. **Check email verification**: Ensure email is marked as verified in Cognito
2. **Check group membership**: User must be in `admin` or `viewer` group
3. **Check user status**: Ensure user is not disabled
4. **Password issues**: Reset password if user forgot new password

### User Gets "Access Denied"
1. **Wrong group**: Viewer trying to access admin-only features
2. **No group**: User not assigned to any group
3. **Session expired**: User needs to logout and login again

### Email Not Received
1. **Check spam folder**: Cognito emails may go to spam
2. **Email verification**: Ensure email is marked as verified
3. **Resend invitation**: Create new temporary password and resend

## Technical Details

### Authentication Flow
1. User enters credentials at login page
2. AWS Cognito validates credentials
3. System checks user's group membership
4. Dashboard loads with appropriate tabs based on role
5. All API calls are authenticated with Cognito session tokens

### Session Management
- **Session Duration**: Configured in Cognito settings
- **Logout**: Clears local session and redirects to login
- **Auto-logout**: Sessions expire based on Cognito configuration

### Database Access
- **Portfolio Data**: AWS RDS PostgreSQL (users see real portfolio data)
- **Price Data**: Daily S&P 500 universe from 2022-01-03 to present
- **Calculations**: Real-time portfolio metrics and performance analytics

## Support

For technical issues or user management questions:
1. Check this documentation first
2. Review AWS Cognito console for user status
3. Check dashboard server logs if needed
4. Contact system administrator for advanced troubleshooting

---

**Last Updated**: 2025-07-13  
**Dashboard Version**: Fully Functional with Authentication  
**AWS Region**: us-west-2