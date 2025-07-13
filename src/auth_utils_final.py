from flask import session, redirect, url_for
from functools import wraps
import boto3
from jose import jwt
import requests
from cognito_config import COGNITO_CONFIG

class CognitoAuth:
    def __init__(self):
        self.region = COGNITO_CONFIG['region']
        self.user_pool_id = COGNITO_CONFIG['user_pool_id']
        self.client_id = COGNITO_CONFIG['client_id']
        self.client_secret = COGNITO_CONFIG['client_secret']
        session = boto3.Session(profile_name='alphaview')
        self.cognito = session.client('cognito-idp', region_name=self.region)

    def get_user_groups(self, username):
        """Get groups for a user"""
        try:
            response = self.cognito.admin_list_groups_for_user(
                Username=username,
                UserPoolId=self.user_pool_id
            )
            return [group['GroupName'] for group in response['Groups']]
        except:
            return []

    def get_user_role(self, username):
        """Get user role based on group membership"""
        groups = self.get_user_groups(username)
        if 'admin' in groups:
            return 'admin'
        elif 'viewer' in groups:
            return 'viewer'
        return None
    
    def authenticate_user(self, username, password):
        """Authenticate user with Cognito"""
        try:
            response = self.cognito.initiate_auth(
                ClientId=self.client_id,
                AuthFlow='USER_PASSWORD_AUTH',
                AuthParameters={
                    'USERNAME': username,
                    'PASSWORD': password,
                    'SECRET_HASH': self._get_secret_hash(username)
                }
            )

            # Check if password change is required
            if 'ChallengeName' in response and response['ChallengeName'] == 'NEW_PASSWORD_REQUIRED':
                return {'success': False, 'challenge': 'NEW_PASSWORD_REQUIRED', 'session': response['Session']}

            # Check if authentication was successful
            if 'AuthenticationResult' in response:
                access_token = response['AuthenticationResult']['AccessToken']
                
                return {
                    'success': True,
                    'username': username,
                    'access_token': access_token,
                    'id_token': response['AuthenticationResult']['IdToken']
                }
            else:
                return {'success': False, 'error': 'Authentication failed - no result'}

        except Exception as e:
            return {'success': False, 'error': str(e)}

    def handle_new_password_challenge(self, username, new_password, session_token):
        """Handle new password required challenge"""
        try:
            response = self.cognito.respond_to_auth_challenge(
                ClientId=self.client_id,
                ChallengeName='NEW_PASSWORD_REQUIRED',
                Session=session_token,
                ChallengeResponses={
                    'USERNAME': username,
                    'NEW_PASSWORD': new_password,
                    'SECRET_HASH': self._get_secret_hash(username)
                }
            )
            
            if 'AuthenticationResult' in response:
                return {
                    'success': True,
                    'username': username,
                    'access_token': response['AuthenticationResult']['AccessToken'],
                    'id_token': response['AuthenticationResult']['IdToken']
                }
            else:
                return {'success': False, 'error': 'Password change failed'}
                
        except Exception as e:
            return {'success': False, 'error': str(e)}

    def _get_secret_hash(self, username):
        """Calculate secret hash for Cognito"""
        import hmac
        import hashlib
        import base64

        message = bytes(username + self.client_id, 'utf-8')
        key = bytes(self.client_secret, 'utf-8')
        secret_hash = base64.b64encode(
            hmac.new(key, message, digestmod=hashlib.sha256).digest()
        ).decode()
        return secret_hash

def login_required(f):
    """Decorator to require login"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return redirect('/login')
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    """Decorator to require admin role"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session or session.get('role') != 'admin':
            return "Access Denied - Admin Only"
        return f(*args, **kwargs)
    return decorated_function