#!/usr/bin/env python3
"""
MediaWiki API Update Script for AlphaView Documentation
Updates wiki pages via the MediaWiki API
"""

import requests
import json
from typing import Dict, Optional

class MediaWikiUpdater:
    def __init__(self, wiki_url: str, username: str, password: str):
        """
        Initialize MediaWiki API client
        
        Args:
            wiki_url: Base URL of your wiki (e.g., http://192.168.1.121/mediawiki)
            username: Your username with bot password (e.g., JudyWiki@apibot)
            password: The bot password from Special:BotPasswords
        """
        self.api_url = f"{wiki_url}/api.php"
        self.username = username
        self.password = password
        self.session = requests.Session()
        self.logged_in = False
        
    def login(self) -> bool:
        """Login to MediaWiki using bot credentials"""
        # Step 1: Get login token
        params = {
            'action': 'query',
            'meta': 'tokens',
            'type': 'login',
            'format': 'json'
        }
        
        r = self.session.get(self.api_url, params=params)
        login_token = r.json()['query']['tokens']['logintoken']
        
        # Step 2: Login
        login_data = {
            'action': 'login',
            'lgname': self.username,
            'lgpassword': self.password,
            'lgtoken': login_token,
            'format': 'json'
        }
        
        r = self.session.post(self.api_url, data=login_data)
        
        if r.json()['login']['result'] == 'Success':
            self.logged_in = True
            print(f"✅ Successfully logged in as {self.username}")
            return True
        else:
            print(f"❌ Login failed: {r.json()}")
            return False
    
    def get_csrf_token(self) -> str:
        """Get CSRF token for editing"""
        params = {
            'action': 'query',
            'meta': 'tokens',
            'format': 'json'
        }
        
        r = self.session.get(self.api_url, params=params)
        return r.json()['query']['tokens']['csrftoken']
    
    def create_or_update_page(self, title: str, content: str, summary: str = "Automated update") -> bool:
        """Create or update a wiki page"""
        if not self.logged_in:
            print("❌ Not logged in. Please login first.")
            return False
        
        csrf_token = self.get_csrf_token()
        
        edit_data = {
            'action': 'edit',
            'title': title,
            'text': content,
            'summary': summary,
            'token': csrf_token,
            'format': 'json',
            'bot': True  # Mark as bot edit
        }
        
        r = self.session.post(self.api_url, data=edit_data)
        result = r.json()
        
        if 'edit' in result and result['edit']['result'] == 'Success':
            print(f"✅ Successfully updated page: {title}")
            return True
        else:
            print(f"❌ Failed to update page: {result}")
            return False
    
    def check_page_exists(self, title: str) -> bool:
        """Check if a page already exists"""
        params = {
            'action': 'query',
            'titles': title,
            'format': 'json'
        }
        
        r = self.session.get(self.api_url, params=params)
        pages = r.json()['query']['pages']
        
        # If page ID is -1, it doesn't exist
        return not any(page.get('pageid', -1) == -1 for page in pages.values())

def main():
    """Update AlphaView documentation on JudyWiki"""
    
    # Configuration with your credentials
    WIKI_URL = "http://192.168.1.121/mediawiki"
    USERNAME = "JudyWiki@apibot"
    PASSWORD = "h7gg9agefq86caan3tukmaf6npvg6v7i"
    
    # Initialize updater
    wiki = MediaWikiUpdater(WIKI_URL, USERNAME, PASSWORD)
    
    # Login
    if not wiki.login():
        print("Failed to login. Check credentials.")
        return
    
    # Load the content files
    print("\n📝 Updating AlphaView documentation...")
    
    # Update User Administration page
    try:
        with open('/raid/for_Claude/User_Administration_MediaWiki.txt', 'r') as f:
            user_admin_content = f.read()
            # Fix category to match your structure
            user_admin_content = user_admin_content.replace(
                "[[Category:User Administration]]\n[[Category:AWS Cognito]]\n[[Category:AlphaView Dashboard]]",
                "[[Category:AlphaView]]"
            )
        
        wiki.create_or_update_page(
            title="AlphaView User Administration",
            content=user_admin_content,
            summary="Added comprehensive user administration guide for AlphaView Dashboard"
        )
    except FileNotFoundError:
        print("❌ User Administration file not found")
    except Exception as e:
        print(f"❌ Error updating User Administration: {e}")
    
    # First create the Server Management content
    server_mgmt_content = """= AlphaView Server Management =

== Overview ==

This guide covers server management tasks for the AlphaView Portfolio Dashboard running on AWS Lightsail.

== Server Details ==

{| class="wikitable"
! Property !! Value
|-
| '''Server Type''' || AWS Lightsail Ubuntu 22.04 LTS
|-
| '''Instance Size''' || 4 GB RAM, 2 vCPUs, 80 GB SSD
|-
| '''IP Address''' || 35.80.141.177
|-
| '''Dashboard Port''' || 8050 (internal) / 80 (external via Nginx)
|-
| '''Dashboard URL''' || http://35.80.141.177
|-
| '''Application Path''' || /opt/alphaview
|}

== SSH Access ==

=== Connect to Server ===
<pre>
ssh -i ~/.ssh/lightsail-django-8gb.pem ubuntu@35.80.141.177
</pre>

{{Note|Replace <code>~/.ssh/lightsail-django-8gb.pem</code> with your actual key path}}

== Service Management ==

=== Check Service Status ===
<pre>
sudo systemctl status alphaview
</pre>

Output shows:
* Service status (active/inactive)
* Memory usage
* CPU usage
* Recent log entries

=== Start Service ===
<pre>
sudo systemctl start alphaview
</pre>

=== Stop Service ===
<pre>
sudo systemctl stop alphaview
</pre>

=== Restart Service ===
<pre>
sudo systemctl restart alphaview
</pre>

=== Enable Auto-Start on Boot ===
<pre>
sudo systemctl enable alphaview
</pre>

== Log Management ==

=== View Recent Logs ===
<pre>
# Last 50 lines
sudo journalctl -u alphaview -n 50

# Follow logs in real-time
sudo journalctl -u alphaview -f

# Today's logs
sudo journalctl -u alphaview --since today
</pre>

=== Check Application Logs ===
<pre>
# Navigate to application directory
cd /opt/alphaview

# View error logs (if debug mode)
tail -f dashboard.log
</pre>

== Application Management ==

=== Virtual Environment ===
<pre>
# Activate virtual environment
cd /opt/alphaview
source venv/bin/activate

# Check installed packages
pip list

# Deactivate when done
deactivate
</pre>

=== Update Application Code ===
<pre>
# Backup current version
sudo cp /opt/alphaview/alphaview_fully_functional.py /opt/alphaview/alphaview_fully_functional.py.bak

# Copy new version (example)
sudo cp /path/to/new/alphaview_fully_functional.py /opt/alphaview/

# Restart service
sudo systemctl restart alphaview
</pre>

=== Install/Update Dependencies ===
<pre>
cd /opt/alphaview
source venv/bin/activate
pip install -r requirements.txt
# or for specific package
pip install package_name
deactivate
</pre>

== Database Management ==

=== Test Database Connection ===
<pre>
cd /opt/alphaview
source venv/bin/activate
python -c "from alphaview_fully_functional import get_rds_connection; conn = get_rds_connection(); print('✅ Database connection successful'); conn.close()"
</pre>

=== Daily Price Update (Cron) ===
<pre>
# View cron jobs
crontab -l

# Edit cron jobs
crontab -e

# Current daily update job
0 6 * * * /opt/alphaview/daily_update.sh >> /home/ubuntu/logs/daily_update.log 2>&1
</pre>

== Nginx Management ==

=== Check Nginx Status ===
<pre>
sudo systemctl status nginx
</pre>

=== Test Nginx Configuration ===
<pre>
sudo nginx -t
</pre>

=== Reload Nginx ===
<pre>
sudo systemctl reload nginx
</pre>

=== View Nginx Logs ===
<pre>
# Access logs
sudo tail -f /var/log/nginx/access.log

# Error logs
sudo tail -f /var/log/nginx/error.log
</pre>

== System Monitoring ==

=== Check System Resources ===
<pre>
# Memory usage
free -h

# Disk usage
df -h

# CPU and process info
htop
# or
top

# Network connections
sudo netstat -tlnp
</pre>

=== Check Python Processes ===
<pre>
ps aux | grep python
</pre>

== Troubleshooting ==

=== Service Won't Start ===
# Check logs: <code>sudo journalctl -u alphaview -n 100</code>
# Check port availability: <code>sudo lsof -i :8051</code>
# Verify Python path: <code>which python</code>
# Check permissions: <code>ls -la /opt/alphaview</code>

=== Dashboard Not Accessible ===
# Check service is running: <code>sudo systemctl status alphaview</code>
# Check firewall: <code>sudo ufw status</code>
# Test locally: <code>curl http://localhost:8051</code>
# Check Nginx: <code>sudo systemctl status nginx</code>

=== Database Connection Issues ===
# Test AWS credentials: <code>aws sts get-caller-identity</code>
# Check network to RDS: <code>telnet [rds-endpoint] 5432</code>
# Verify environment: <code>echo $AWS_PROFILE</code>

== Backup Procedures ==

=== Backup Application Code ===
<pre>
# Create backup directory
mkdir -p /home/ubuntu/backups/$(date +%Y%m%d)

# Backup application
sudo tar -czf /home/ubuntu/backups/$(date +%Y%m%d)/alphaview_backup.tar.gz /opt/alphaview/

# List backups
ls -la /home/ubuntu/backups/
</pre>

=== Backup Database (RDS) ===
* Automated backups configured in AWS RDS
* Manual snapshots via AWS Console
* Point-in-time recovery available

== Security Updates ==

=== System Updates ===
<pre>
# Update package list
sudo apt update

# Show available updates
sudo apt list --upgradable

# Install security updates only
sudo apt-get -s upgrade | grep -i security

# Full system update
sudo apt upgrade
</pre>

=== Python Package Updates ===
<pre>
cd /opt/alphaview
source venv/bin/activate
pip list --outdated
pip install --upgrade package_name
deactivate
</pre>

== Performance Tuning ==

=== Monitor Performance ===
<pre>
# Real-time monitoring
htop

# Check service memory usage
systemctl status alphaview | grep Memory

# Database query performance
# (Check application logs for slow queries)
</pre>

=== Restart Schedule ===
Consider adding a weekly restart to cron:
<pre>
# Sunday 3 AM restart
0 3 * * 0 sudo systemctl restart alphaview
</pre>

== Quick Reference ==

{| class="wikitable"
! Task !! Command
|-
| SSH to server || <code>ssh -i ~/.ssh/key.pem ubuntu@35.80.141.177</code>
|-
| Check status || <code>sudo systemctl status alphaview</code>
|-
| Restart service || <code>sudo systemctl restart alphaview</code>
|-
| View logs || <code>sudo journalctl -u alphaview -f</code>
|-
| Check resources || <code>htop</code>
|-
| Test locally || <code>curl http://localhost:8051</code>
|}

----
'''Last Updated''': 2025-07-13<br>
'''Service Name''': alphaview.service<br>
'''Dashboard Version''': Fully Functional with Authentication

[[Category:AlphaView]]"""
    
    # Update Server Management page
    try:
        wiki.create_or_update_page(
            title="AlphaView Server Management",
            content=server_mgmt_content,
            summary="Added comprehensive server management guide for AlphaView"
        )
    except Exception as e:
        print(f"❌ Error updating Server Management: {e}")
    
    # Create/Update main AlphaView category page
    category_content = """{{DISPLAYTITLE:AlphaView Portfolio Dashboard}}
= AlphaView Portfolio Dashboard =

== Overview ==
AlphaView is a professional portfolio management dashboard for Series 65 certification preparation, running on AWS infrastructure.

== System Architecture ==
* '''Frontend''': Dash/Plotly web application
* '''Backend''': Python with PostgreSQL databases
* '''Authentication''': AWS Cognito
* '''Hosting''': AWS Lightsail (Ubuntu 22.04)
* '''Database''': AWS RDS PostgreSQL

== Documentation ==
* [[AlphaView User Administration]] - Managing users and permissions
* [[AlphaView Server Management]] - Server operations and maintenance
* [[AlphaView Technical Reference]] - SSH access and technical details
* [[AlphaView Troubleshooting]] - Common issues and solutions

== Quick Links ==
* '''Dashboard URL''': http://35.80.141.177 (via Nginx)
* '''Internal Port''': 8050 (proxied by Nginx)
* '''AWS Region''': us-west-2
* '''Service Name''': alphaview.service
* '''Application Path''': /opt/alphaview

== Features ==
* Real-time portfolio tracking
* Performance analytics (VaR, CVaR, Sharpe Ratio)
* Trade execution (admin only)
* Transaction history
* Portfolio export (CSV, Excel, JSON)
* Role-based access control

== Related AWS Services ==
* [[AWS Cognito]] - User authentication
* [[AWS Lightsail]] - Server hosting
* [[AWS RDS]] - Database service
* [[AWS Secrets Manager]] - Credential storage

[[Category:AWS]]"""
    
    try:
        wiki.create_or_update_page(
            title="Category:AlphaView",
            content=category_content,
            summary="Updated AlphaView category page with comprehensive overview"
        )
    except Exception as e:
        print(f"❌ Error updating Category page: {e}")
    
    print("\n✅ Documentation update complete!")
    print("\nPages created/updated:")
    print("  - AlphaView User Administration")
    print("  - AlphaView Server Management")
    print("  - Category:AlphaView")
    print("\nYou can view them at:")
    print(f"  - {WIKI_URL}/index.php/AlphaView_User_Administration")
    print(f"  - {WIKI_URL}/index.php/AlphaView_Server_Management")
    print(f"  - {WIKI_URL}/index.php/Category:AlphaView")

if __name__ == "__main__":
    main()