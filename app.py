"""
Database Statistics Dashboard
A Flask web application to display Valkey and PostgreSQL database statistics.
"""

import json
import os
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

import redis
import psycopg2
from psycopg2.extras import RealDictCursor
from flask import Flask, render_template, jsonify, request, Response
from functools import wraps
import base64
import hashlib
import hmac
import requests

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

def read_secret_file(file_path: str) -> Optional[str]:
    """Read a secret from a Docker secrets file."""
    try:
        if os.path.exists(file_path):
            with open(file_path, 'r') as f:
                secret = f.read().strip()
                if secret:
                    logger.debug(f"Successfully read secret from {file_path}")
                    return secret
                else:
                    logger.warning(f"Secret file {file_path} is empty")
        else:
            logger.debug(f"Secret file {file_path} does not exist")
    except Exception as e:
        logger.error(f"Error reading secret file {file_path}: {e}")
    return None

def get_secret_or_env(env_var: str, secret_file_env: Optional[str] = None) -> Optional[str]:
    """Get a value from Docker secrets file or fallback to environment variable."""
    # First try to read from Docker secrets if enabled
    use_secrets = os.getenv('USE_DOCKER_SECRETS', 'false').lower() == 'true'
    if use_secrets and secret_file_env:
        secret_file = os.getenv(secret_file_env)
        if secret_file:
            secret_value = read_secret_file(secret_file)
            if secret_value:
                return secret_value
    
    # Fallback to environment variable
    return os.getenv(env_var)

# Load configuration
def load_config():
    """Load configuration from environment variables, Docker secrets, and config files."""
    config = {
        'VALKEY_HOST': os.getenv('VALKEY_HOST', 'localhost'),
        'VALKEY_PORT': int(os.getenv('VALKEY_PORT', 6379)),
        'VALKEY_USER': os.getenv('VALKEY_USER'),
        'VALKEY_PASSWORD': get_secret_or_env('VALKEY_PASSWORD', 'VALKEY_PASSWORD_FILE'),
        'VALKEY_DB': int(os.getenv('VALKEY_DB', 0)),
        
        'POSTGRES_HOST': os.getenv('POSTGRES_HOST', 'localhost'),
        'POSTGRES_PORT': int(os.getenv('POSTGRES_PORT', 5432)),
        'POSTGRES_DATABASE': os.getenv('POSTGRES_DATABASE', 'webapp_db'),
        'POSTGRES_USER': os.getenv('POSTGRES_USER', 'postgres'),
        'POSTGRES_PASSWORD': get_secret_or_env('POSTGRES_PASSWORD', 'POSTGRES_PASSWORD_FILE'),
        
        'APP_PORT': int(os.getenv('APP_PORT', 8080)),
        'DEBUG': os.getenv('DEBUG', 'false').lower() == 'true',
        
        # Security settings
        'AUTH_USERNAME': os.getenv('AUTH_USERNAME', 'admin'),
        'AUTH_PASSWORD': get_secret_or_env('AUTH_PASSWORD', 'AUTH_PASSWORD_FILE'),
        'ALLOWED_IPS': os.getenv('ALLOWED_IPS', '').split(',') if os.getenv('ALLOWED_IPS') else [],
        'SECURITY_TOKEN': get_secret_or_env('SECURITY_TOKEN', 'SECURITY_TOKEN_FILE'),
        
        # DigitalOcean Spaces settings
        'SPACES_BUCKET': os.getenv('SPACES_BUCKET'),
        'SPACES_PUBLIC_BASE_URL': os.getenv('SPACES_PUBLIC_BASE_URL'),
        'SPACES_ACCESS_KEY': os.getenv('SPACES_ACCESS_KEY'),
        'SPACES_SECRET_KEY': get_secret_or_env('SPACES_SECRET_KEY', 'SPACES_SECRET_KEY_FILE'),
        'SPACES_ENDPOINT': os.getenv('SPACES_ENDPOINT', 'https://fra1.digitaloceanspaces.com')
    }
    
    # Load from config file if it exists
    config_file = os.getenv('CONFIG_FILE', 'production.config.json')
    if os.path.exists(config_file):
        try:
            with open(config_file, 'r') as f:
                file_config = json.load(f)
                config.update(file_config)
        except Exception as e:
            logger.warning(f"Could not load config file {config_file}: {e}")
    
    return config

config = load_config()

# Security functions
def check_auth(username, password):
    """Check if a username/password combination is valid."""
    if not config.get('AUTH_PASSWORD'):
        return True  # No password set, allow access (for development)
    
    return (username == config['AUTH_USERNAME'] and 
            password == config['AUTH_PASSWORD'])

def authenticate():
    """Send a 401 response that enables basic auth."""
    return Response(
        'Authentication required. Please provide valid credentials.',
        401,
        {'WWW-Authenticate': 'Basic realm="Database Dashboard"'}
    )

def check_ip_whitelist():
    """Check if the client IP is in the allowed list."""
    if not config.get('ALLOWED_IPS') or not any(config['ALLOWED_IPS']):
        return True  # No IP restriction if list is empty
    
    client_ip = request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)
    if client_ip:
        # Handle multiple IPs in X-Forwarded-For header
        client_ip = client_ip.split(',')[0].strip()
    
    logger.info(f"Client IP: {client_ip}, Allowed IPs: {config['ALLOWED_IPS']}")
    return client_ip in config['ALLOWED_IPS']

def check_security_token():
    """Check if a valid security token is provided."""
    if not config.get('SECURITY_TOKEN'):
        return True  # No token required if not set
    
    # Check URL parameter
    token = request.args.get('token')
    if not token:
        # Check Authorization header
        auth_header = request.headers.get('Authorization')
        if auth_header and auth_header.startswith('Bearer '):
            token = auth_header.split(' ')[1]
    
    return token == config['SECURITY_TOKEN']

def requires_auth(f):
    """Decorator that requires authentication."""
    @wraps(f)
    def decorated(*args, **kwargs):
        # Check IP whitelist first
        if not check_ip_whitelist():
            logger.warning(f"Access denied from IP: {request.environ.get('HTTP_X_FORWARDED_FOR', request.remote_addr)}")
            return Response('Access denied: IP not allowed', 403)
        
        # Check security token if enabled
        if not check_security_token():
            logger.warning(f"Access denied: Invalid or missing security token")
            return Response('Access denied: Invalid or missing security token', 403)
        
        # Check basic auth if password is set
        if config.get('AUTH_PASSWORD'):
            auth = request.authorization
            if not auth or not check_auth(auth.username, auth.password):
                logger.warning(f"Authentication failed for user: {auth.username if auth else 'None'}")
                return authenticate()
        
        return f(*args, **kwargs)
    return decorated

# Database connections
def get_valkey_connection():
    """Get Valkey (Redis-compatible) connection."""
    logger.info(f"Attempting Valkey connection to {config['VALKEY_HOST']}:{config['VALKEY_PORT']}")
    try:
        # Connection parameters
        conn_params = {
            'host': config['VALKEY_HOST'],
            'port': config['VALKEY_PORT'],
            'db': config['VALKEY_DB'],
            'decode_responses': True,
            'socket_connect_timeout': 5,
            'socket_timeout': 5
        }
        
        # Add SSL for DigitalOcean managed databases
        if 'ondigitalocean.com' in config['VALKEY_HOST']:
            logger.info("Adding SSL configuration for DigitalOcean managed Valkey")
            conn_params['ssl'] = True
            conn_params['ssl_cert_reqs'] = None  # Don't verify SSL certificates for managed DB
        
        # Add authentication
        if config['VALKEY_USER']:
            logger.info(f"Using Valkey username: {config['VALKEY_USER']}")
            conn_params['username'] = config['VALKEY_USER']
        if config['VALKEY_PASSWORD']:
            logger.info("Valkey password provided")
            conn_params['password'] = config['VALKEY_PASSWORD']
            
        logger.info("Creating Redis client...")
        client = redis.Redis(**conn_params)
        
        logger.info("Testing connection with ping...")
        client.ping()
        logger.info("✅ Valkey connection successful!")
        return client
    except Exception as e:
        logger.error(f"❌ Error connecting to Valkey: {e}")
        return None

def get_postgres_connection():
    """Get PostgreSQL connection."""
    logger.info(f"Attempting PostgreSQL connection to {config['POSTGRES_HOST']}:{config['POSTGRES_PORT']}")
    try:
        # Connection parameters
        conn_params = {
            'host': config['POSTGRES_HOST'],
            'port': config['POSTGRES_PORT'],
            'database': config['POSTGRES_DATABASE'],
            'user': config['POSTGRES_USER'],
            'password': config['POSTGRES_PASSWORD'],
            'connect_timeout': 10
        }
        
        # Add SSL configuration for managed databases
        if 'ondigitalocean.com' in config['POSTGRES_HOST'] or os.getenv('POSTGRES_SSLMODE'):
            conn_params['sslmode'] = os.getenv('POSTGRES_SSLMODE', 'require')
            
        logger.info("Creating PostgreSQL connection...")
        conn = psycopg2.connect(**conn_params)
        logger.info("✅ PostgreSQL connection successful!")
        return conn
    except Exception as e:
        logger.error(f"❌ Error connecting to PostgreSQL: {e}")
        return None

def get_queue_info_with_timeout(client, timeout_seconds=10) -> Dict[str, Any]:
    """Get queue information with timeout protection to prevent hanging."""
    import signal
    import time
    
    def timeout_handler(signum, frame):
        raise TimeoutError("Queue scan timed out")
    
    try:
        # Set up timeout
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(timeout_seconds)
        
        logger.info(f"Starting queue scan with {timeout_seconds}s timeout...")
        
        # Common queue patterns used in Redis/Valkey applications
        queue_patterns = [
            'queue:*',          # Standard queue pattern
            '*:queue',          # Alternative queue pattern
            'job:*',            # Job queue pattern
            'task:*',           # Task queue pattern
            'work:*',           # Work queue pattern
            'pending:*',        # Pending work pattern
            'processing:*',     # Currently processing pattern
            'celery',           # Celery default queue
            'rq:*',             # Python RQ pattern
            'bull:*',           # Bull.js pattern
            'kue:*',            # Kue pattern
            'snapshots',        # Based on sample keys found
            'snapshot:*',       # Snapshot variations
            'frames',           # Frame queue pattern
            'frame:*',          # Frame variations
            'images',           # Image queue pattern
            'image:*',          # Image variations
            'messages',         # Generic message queue
            'message:*',        # Message variations
            'data',             # Generic data queue
            'data:*',           # Data variations
            'buffer',           # Buffer queue
            'buffer:*',         # Buffer variations
            '*_queue',          # Suffix queue pattern
            '*_jobs',           # Suffix jobs pattern
            '*_tasks',          # Suffix tasks pattern
        ]
        
        total_messages = 0
        queue_details = []
        
        # First, let's scan for some sample keys to understand the naming patterns
        try:
            cursor = 0
            sample_keys = []
            scan_count = 0
            while cursor != 0 or scan_count == 0:
                cursor, keys = client.scan(cursor=cursor, count=50)
                sample_keys.extend(keys[:10])  # Take first 10 from each scan
                scan_count += 1
                if len(sample_keys) >= 30 or scan_count > 5:  # Limit sample size
                    break
            
            logger.info(f"Sample keys in database: {sample_keys[:20]}")
        except Exception as e:
            logger.warning(f"Error sampling keys: {e}")
        
        # Now scan for queue patterns
        all_queue_keys = set()
        for pattern in queue_patterns:
            try:
                # Use SCAN instead of KEYS for better performance
                cursor = 0
                while True:
                    cursor, keys = client.scan(cursor=cursor, match=pattern, count=100)
                    all_queue_keys.update(keys)
                    if cursor == 0:
                        break
                    # Additional safety check within the loop
                    if time.time() % 1 == 0:  # Check every ~1 second worth of operations
                        signal.alarm(timeout_seconds)  # Reset timeout
            except Exception as e:
                logger.warning(f"Error scanning pattern {pattern}: {e}")
                continue
        
        logger.info(f"Found {len(all_queue_keys)} potential queue keys")
        if len(all_queue_keys) > 0:
            logger.info(f"Queue keys found: {list(all_queue_keys)[:10]}")
        
        # Check each key to see if it's actually a queue (list) and get its length
        for key in list(all_queue_keys)[:50]:  # Limit to first 50 keys to prevent long scans
            try:
                key_type = client.type(key)
                logger.info(f"Checking key '{key}': type={key_type}")
                
                if key_type == 'list':
                    length = client.llen(key)
                    logger.info(f"List key '{key}' has length: {length}")
                    if length > 0:
                        total_messages += length
                        queue_details.append({
                            'name': key,
                            'length': length,
                            'type': 'list'
                        })
                elif key_type == 'zset':
                    # Sorted sets are sometimes used for delayed queues
                    length = client.zcard(key)
                    logger.info(f"Sorted set key '{key}' has length: {length}")
                    if length > 0:
                        total_messages += length
                        queue_details.append({
                            'name': key,
                            'length': length,
                            'type': 'sorted_set'
                        })
                elif key_type == 'set':
                    # Sets might be used for unique job tracking
                    length = client.scard(key)
                    logger.info(f"Set key '{key}' has length: {length}")
                    if length > 0:
                        total_messages += length
                        queue_details.append({
                            'name': key,
                            'length': length,
                            'type': 'set'
                        })
                elif key_type == 'stream':
                    # Redis Streams are commonly used for message queues
                    # Focus on PEL (Pending Entry List) - the key issue!
                    pending_count = 0
                    total_stream_length = client.xlen(key)
                    stream_info = {
                        'total_length': total_stream_length, 
                        'pending_count': 0, 
                        'consumer_groups': [],
                        'pel_details': [],  # Add detailed PEL info
                        'available_unread': 0  # Messages in stream not yet read
                    }
                    
                    try:
                        # Get consumer groups for this stream
                        groups_info = client.xinfo_groups(key)
                        logger.info(f"Stream key '{key}' has {len(groups_info)} consumer groups")
                        
                        for group_info in groups_info:
                            group_name = group_info['name']
                            lag = group_info.get('lag', 0)  # Messages not yet delivered to consumers
                            stream_info['consumer_groups'].append({
                                'name': group_name,
                                'lag': lag
                            })
                            
                            # Get detailed PEL information - this is the key!
                            try:
                                # Get pending messages summary first
                                pending_summary = client.xpending(key, group_name)
                                if pending_summary and len(pending_summary) >= 4:
                                    total_pending = pending_summary[0]
                                    pending_count += total_pending
                                    
                                    # Get individual pending messages (limited sample for performance)
                                    pending_info = client.xpending_range(key, group_name, min='-', max='+', count=100)
                                    
                                    pel_detail = {
                                        'group_name': group_name,
                                        'total_pending': total_pending,
                                        'oldest_age_ms': pending_summary[2] if len(pending_summary) > 2 else 0,
                                        'sample_messages': len(pending_info)
                                    }
                                    
                                    # Calculate processing delay indicators
                                    if pending_info:
                                        oldest_msg = pending_info[0]
                                        age_ms = oldest_msg[1]  # Age in milliseconds
                                        pel_detail['oldest_message_age_seconds'] = age_ms / 1000
                                        
                                    stream_info['pel_details'].append(pel_detail)
                                    
                                    logger.info(f"🚨 PEL ISSUE DETECTED: Group '{group_name}' has {total_pending} messages in PEL, oldest {age_ms/1000:.1f}s old")
                                else:
                                    logger.info(f"Consumer group '{group_name}' has empty PEL")
                                    
                            except Exception as e:
                                logger.warning(f"Error getting PEL details for group {group_name}: {e}")
                            
                            # Track available unread messages (lag)
                            stream_info['available_unread'] += lag
                                
                        stream_info['pending_count'] = pending_count
                        
                    except Exception as e:
                        logger.info(f"Stream '{key}' has no consumer groups or error getting groups: {e}")
                        # If no consumer groups, treat total length as 'pending' (unprocessed)
                        pending_count = total_stream_length
                        stream_info['pending_count'] = pending_count
                        stream_info['available_unread'] = total_stream_length
                    
                    # For streams with consumer groups, count BOTH PEL and undelivered messages
                    # PEL = delivered but not ACKed (the main issue you mentioned)
                    # Undelivered = in stream but not yet delivered to consumers (lag)
                    if len(stream_info['consumer_groups']) > 0:
                        # Count both PEL messages AND undelivered messages (lag)
                        effective_count = pending_count + stream_info['available_unread']
                    else:
                        # No consumer groups, so all messages are unprocessed
                        effective_count = total_stream_length
                    
                    logger.info(f"Stream '{key}': total={total_stream_length}, PEL_pending={pending_count}, unread={stream_info['available_unread']}, effective={effective_count}")
                    
                    # Show all streams, even with 0 effective count, to demonstrate the issue
                    if total_stream_length > 0 or effective_count > 0:
                        total_messages += effective_count
                        queue_details.append({
                            'name': key,
                            'length': effective_count,
                            'type': 'stream',
                            'stream_info': stream_info
                        })
                else:
                    logger.info(f"Key '{key}' has unsupported type '{key_type}' for queue detection")
            except Exception as e:
                logger.warning(f"Error checking key {key}: {e}")
                continue
        
        # Cancel the alarm
        signal.alarm(0)
        
        # Sort queue details by length (descending)
        queue_details.sort(key=lambda x: x['length'], reverse=True)
        
        # Calculate PEL-specific statistics
        total_pel_messages = 0
        total_streams = 0
        total_consumer_groups = 0
        pel_problem_detected = False
        oldest_pel_age = 0
        
        for queue in queue_details:
            if queue.get('type') == 'stream' and 'stream_info' in queue:
                total_streams += 1
                stream_info = queue['stream_info']
                total_consumer_groups += len(stream_info.get('consumer_groups', []))
                
                for pel_detail in stream_info.get('pel_details', []):
                    pel_count = pel_detail.get('total_pending', 0)
                    total_pel_messages += pel_count
                    
                    # Check for PEL problem (messages older than 30 seconds indicate processing delays)
                    age_seconds = pel_detail.get('oldest_message_age_seconds', 0)
                    if pel_count > 0 and age_seconds > 30:
                        pel_problem_detected = True
                    oldest_pel_age = max(oldest_pel_age, age_seconds)
        
        # Calculate estimated processing time with PEL consideration
        estimated_time = "N/A"
        pel_backlog_time = "N/A"
        
        if total_messages > 0:
            # Use the instantaneous ops per second, but provide a conservative estimate
            ops_per_sec = client.info().get('instantaneous_ops_per_sec', 0)
            if ops_per_sec > 0:
                # Assume a portion of ops are queue processing (conservative estimate: 50%)
                queue_processing_rate = max(1, ops_per_sec * 0.5)
                estimated_seconds = total_messages / queue_processing_rate
                if estimated_seconds < 60:
                    estimated_time = f"{int(estimated_seconds)} seconds"
                elif estimated_seconds < 3600:
                    estimated_time = f"{int(estimated_seconds/60)} minutes"
                else:
                    estimated_time = f"{estimated_seconds/3600:.1f} hours"
        
        # Specific PEL backlog calculation assuming 16-second processing time per message
        if total_pel_messages > 0:
            # Based on the scenario: 16 seconds per message processing time
            pel_processing_seconds = total_pel_messages * 16
            if pel_processing_seconds < 60:
                pel_backlog_time = f"{int(pel_processing_seconds)} seconds"
            elif pel_processing_seconds < 3600:
                pel_backlog_time = f"{int(pel_processing_seconds/60)} minutes"
            else:
                pel_backlog_time = f"{pel_processing_seconds/3600:.1f} hours"
        
        logger.info(f"✅ Queue scan completed: {total_messages} total messages ({total_pel_messages} in PEL, {total_undelivered_messages} undelivered) across {len(queue_details)} queues")
        if pel_problem_detected:
            logger.warning(f"🚨 PEL PROBLEM: {total_pel_messages} messages stuck in PEL, oldest {oldest_pel_age:.1f}s old")
        elif total_undelivered_messages > 0:
            logger.info(f"📬 {total_undelivered_messages} undelivered messages waiting in streams (not yet read by consumers)")
        
        # Calculate undelivered messages separately for better reporting
        total_undelivered_messages = 0
        for queue in queue_details:
            if queue.get('type') == 'stream' and 'stream_info' in queue:
                stream_info = queue['stream_info']
                total_undelivered_messages += stream_info.get('available_unread', 0)
        
        return {
            'total_messages_in_queues': {
                'value': total_messages,
                'description': f'Total queue messages: {total_pel_messages} in PEL (delivered but unprocessed) + {total_undelivered_messages} undelivered = {total_messages} total'
            },
            'pel_messages': {
                'value': total_pel_messages,
                'description': f'Messages in Pending Entry List (PEL) - delivered to consumers but not yet ACKed. These are the "hidden" queue!'
            },
            'pel_problem_indicator': {
                'value': 'DETECTED' if pel_problem_detected else 'OK',
                'description': f'PEL accumulation issue detected' if pel_problem_detected else 'No significant PEL accumulation'
            },
            'oldest_pending_age': {
                'value': f"{oldest_pel_age:.1f}s" if oldest_pel_age > 0 else "N/A",
                'description': 'Age of oldest message in PEL (indicates processing delays)'
            },
            'pel_processing_backlog': {
                'value': pel_backlog_time,
                'description': f'Time to clear PEL backlog at 16s/message (based on {total_pel_messages} pending messages)'
            },
            'stream_summary': {
                'value': f"{total_streams} streams, {total_consumer_groups} consumer groups",
                'description': f'Redis streams infrastructure: {total_streams} streams with {total_consumer_groups} consumer groups'
            },
            'queue_details': {
                'value': queue_details[:10],  # Top 10 queues by size
                'description': f'Queue details (showing {min(10, len(queue_details))} of {len(queue_details)} total) - streams show PEL counts'
            },
            'estimated_processing_time': {
                'value': estimated_time,
                'description': 'General processing time estimate (may not reflect PEL processing delays)'
            }
        }
        
    except TimeoutError:
        logger.warning(f"❌ Queue scan timed out after {timeout_seconds} seconds")
        return {
            'total_messages_in_queues': {
                'value': 'Timeout',
                'description': f'Queue scan timed out after {timeout_seconds} seconds'
            },
            'queue_details': {
                'value': [],
                'description': 'Queue scan timed out before completion'
            },
            'estimated_processing_time': {
                'value': "N/A",
                'description': 'Not available due to timeout'
            }
        }
    except Exception as e:
        logger.error(f"❌ Error during queue scan: {e}")
        return {
            'total_messages_in_queues': {
                'value': 'Error',
                'description': f'Queue scan failed: {str(e)}'
            },
            'queue_details': {
                'value': [],
                'description': 'Queue scan failed due to error'
            },
            'estimated_processing_time': {
                'value': "N/A",
                'description': 'Not available due to error'
            }
        }
    finally:
        # Always cancel the alarm
        try:
            signal.alarm(0)
        except:
            pass

def get_valkey_stats() -> Dict[str, Any]:
    """Get Valkey database statistics."""
    logger.info("📊 Starting get_valkey_stats()")
    client = get_valkey_connection()
    if not client:
        logger.error("❌ Failed to get Valkey client in get_valkey_stats()")
        return {'error': 'Cannot connect to Valkey database'}
    
    try:
        logger.info("Getting Valkey info()...")
        info = client.info()
        logger.info(f"Received info with {len(info)} keys")
        
        stats = {
            'server': {
                'redis_version': {
                    'value': info.get('redis_version'),
                    'description': 'Version of the Redis/Valkey server'
                },
                'uptime_in_seconds': {
                    'value': info.get('uptime_in_seconds'),
                    'description': 'Total time the server has been running (seconds)'
                },
                'uptime_in_days': {
                    'value': info.get('uptime_in_days'),
                    'description': 'Server uptime converted to days'
                },
            },
            'memory': {
                'used_memory': {
                    'value': info.get('used_memory'),
                    'description': 'Total bytes of memory used by Redis'
                },
                'used_memory_human': {
                    'value': info.get('used_memory_human'),
                    'description': 'Human readable memory usage (MB/GB)'
                },
                'used_memory_peak': {
                    'value': info.get('used_memory_peak'),
                    'description': 'Peak memory usage since server start (bytes)'
                },
                'used_memory_peak_human': {
                    'value': info.get('used_memory_peak_human'),
                    'description': 'Peak memory usage in human readable format'
                },
            },
            'performance': {
                'total_connections_received': {
                    'value': info.get('total_connections_received'),
                    'description': 'Total number of connections accepted by the server'
                },
                'total_commands_processed': {
                    'value': info.get('total_commands_processed'),
                    'description': 'Total number of commands processed by the server'
                },
                'instantaneous_ops_per_sec': {
                    'value': info.get('instantaneous_ops_per_sec'),
                    'description': 'Number of commands processed per second (current rate)'
                },
                'keyspace_hits': {
                    'value': info.get('keyspace_hits'),
                    'description': 'Number of successful key lookups'
                },
                'keyspace_misses': {
                    'value': info.get('keyspace_misses'),
                    'description': 'Number of failed key lookups'
                },
            },
            'clients': {
                'connected_clients': {
                    'value': info.get('connected_clients'),
                    'description': 'Number of client connections (excluding replications)'
                },
                'blocked_clients': {
                    'value': info.get('blocked_clients'),
                    'description': 'Number of clients pending on a blocking call'
                }
            },
            'keyspace': {}
        }
        
        # Get keyspace information with descriptions
        logger.info("Getting keyspace information...")
        for key, value in info.items():
            if key.startswith('db'):
                # Parse keyspace info (format: "keys=X,expires=Y,avg_ttl=Z")
                keyspace_stats = {}
                if isinstance(value, str):
                    for item in value.split(','):
                        if '=' in item:
                            k, v = item.split('=', 1)
                            try:
                                keyspace_stats[k] = int(v)
                            except ValueError:
                                keyspace_stats[k] = v
                                
                stats['keyspace'][key] = {
                    'raw_value': value,
                    'parsed': keyspace_stats,
                    'description': f'Database {key[2:]} statistics: keys, expiring keys, and average TTL'
                }
        
        # Get database size
        try:
            db_size = client.dbsize()
            stats['database_size'] = {
                'value': db_size,
                'description': 'Total number of keys in the database'
            }
        except:
            stats['database_size'] = {
                'value': 0,
                'description': 'Total number of keys in the database'
            }
            
        # Calculate hit ratio
        hits = stats['performance']['keyspace_hits']['value'] or 0
        misses = stats['performance']['keyspace_misses']['value'] or 0
        if hits + misses > 0:
            hit_ratio = round((hits / (hits + misses)) * 100, 2)
        else:
            hit_ratio = 0
            
        stats['cache_efficiency'] = {
            'hit_ratio': {
                'value': f"{hit_ratio}%",
                'description': 'Percentage of successful key lookups vs total lookups'
            }
        }
        
        # Get queue information and process rates with timeout protection
        logger.info("Getting queue information with timeout protection...")
        process_rate = stats['performance']['instantaneous_ops_per_sec']['value'] or 0
        
        # Get queue info with timeout protection
        queue_info = get_queue_info_with_timeout(client)
        queue_info['process_rate_per_second'] = {
            'value': process_rate,
            'description': 'Current rate of commands/messages being processed per second'
        }
            
        stats['queues'] = queue_info
            
        logger.info("✅ Successfully gathered Valkey statistics")
        client.close()
        return stats
        
    except Exception as e:
        logger.error(f"❌ Error getting Valkey stats: {e}")
        if client:
            client.close()
        return {'error': f'Error retrieving Valkey statistics: {str(e)}'}

def get_postgres_stats() -> Dict[str, Any]:
    """Get PostgreSQL database statistics with enhanced descriptions and metrics."""
    logger.info("🐘 Starting get_postgres_stats()")
    conn = get_postgres_connection()
    if not conn:
        logger.error("❌ Failed to get PostgreSQL connection in get_postgres_stats()")
        return {'error': 'Cannot connect to PostgreSQL database'}
    
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        stats = {}
        
        # Database size with description
        cursor.execute("""
            SELECT pg_size_pretty(pg_database_size(current_database())) as size,
                   pg_database_size(current_database()) as size_bytes
        """)
        size_result = cursor.fetchone()
        stats['database_size'] = {
            'value': size_result['size'],
            'bytes': size_result['size_bytes'],
            'description': 'Total disk space used by the database including all tables, indexes, and data'
        }
        
        # Enhanced table statistics with better explanations
        cursor.execute("""
            SELECT 
                schemaname,
                relname as tablename,
                n_tup_ins as inserts,
                n_tup_upd as updates,
                n_tup_del as deletes,
                n_live_tup as live_tuples,
                n_dead_tup as dead_tuples,
                last_vacuum,
                last_autovacuum,
                last_analyze,
                last_autoanalyze,
                pg_size_pretty(pg_total_relation_size(schemaname||'.'||relname)) as table_size
            FROM pg_stat_user_tables
            ORDER BY n_live_tup DESC
        """)
        tables = cursor.fetchall()
        
        # Add table health indicators
        enhanced_tables = []
        for table in tables:
            table_dict = dict(table)
            # Calculate table health metrics
            live = table_dict['live_tuples'] or 0
            dead = table_dict['dead_tuples'] or 0
            total_ops = (table_dict['inserts'] or 0) + (table_dict['updates'] or 0) + (table_dict['deletes'] or 0)
            
            # Table bloat indicator (dead tuples vs live tuples ratio)
            if live > 0:
                bloat_ratio = (dead / live) * 100
                table_dict['bloat_percentage'] = round(bloat_ratio, 1)
                if bloat_ratio > 20:
                    table_dict['health_status'] = 'Needs Vacuum'
                elif bloat_ratio > 10:
                    table_dict['health_status'] = 'Fair'
                else:
                    table_dict['health_status'] = 'Good'
            else:
                table_dict['bloat_percentage'] = 0
                table_dict['health_status'] = 'Empty' if total_ops == 0 else 'Good'
            
            enhanced_tables.append(table_dict)
        
        stats['tables'] = {
            'data': enhanced_tables,
            'description': 'Individual table statistics showing current row counts, operations, and health status',
            'metrics_explained': {
                'live_tuples': 'Current number of active/visible rows in the table',
                'dead_tuples': 'Rows marked for deletion but not yet cleaned up by VACUUM',
                'inserts': 'Total INSERT operations since last statistics reset',
                'updates': 'Total UPDATE operations since last statistics reset', 
                'deletes': 'Total DELETE operations since last statistics reset',
                'health_status': 'Table health based on dead/live tuple ratio (Good < 10%, Fair < 20%, Needs Vacuum > 20%)'
            }
        }
        
        # Connection statistics with descriptions
        cursor.execute("""
            SELECT 
                count(*) as total_connections,
                count(*) FILTER (WHERE state = 'active') as active_connections,
                count(*) FILTER (WHERE state = 'idle') as idle_connections,
                count(*) FILTER (WHERE state = 'idle in transaction') as idle_in_transaction
            FROM pg_stat_activity
            WHERE datname = current_database()
        """)
        conn_result = cursor.fetchone()
        stats['connections'] = {
            'data': dict(conn_result),
            'description': 'Current database connection status and usage',
            'metrics_explained': {
                'total_connections': 'All current connections to this database',
                'active_connections': 'Connections currently executing queries',
                'idle_connections': 'Connections not currently executing queries',
                'idle_in_transaction': 'Connections holding open transactions (potential concern if high)'
            }
        }
        
        # Enhanced database activity with explanations
        cursor.execute("""
            SELECT 
                xact_commit as committed_transactions,
                xact_rollback as rolled_back_transactions,
                blks_read as blocks_read,
                blks_hit as blocks_hit,
                tup_returned as tuples_returned,
                tup_fetched as tuples_fetched,
                tup_inserted as tuples_inserted,
                tup_updated as tuples_updated,
                tup_deleted as tuples_deleted,
                temp_files as temp_files_created,
                temp_bytes as temp_bytes_written
            FROM pg_stat_database 
            WHERE datname = current_database()
        """)
        activity_result = cursor.fetchone()
        activity_data = dict(activity_result)
        
        # Calculate additional metrics
        total_transactions = activity_data['committed_transactions'] + activity_data['rolled_back_transactions']
        if total_transactions > 0:
            rollback_ratio = (activity_data['rolled_back_transactions'] / total_transactions) * 100
        else:
            rollback_ratio = 0
            
        stats['activity'] = {
            'data': activity_data,
            'rollback_ratio': round(rollback_ratio, 2),
            'description': 'Database transaction and I/O activity since last statistics reset',
            'metrics_explained': {
                'committed_transactions': 'Successfully completed transactions',
                'rolled_back_transactions': 'Transactions that were rolled back (higher values may indicate issues)',
                'blocks_read': 'Data blocks read from disk (slower)',
                'blocks_hit': 'Data blocks found in memory cache (faster)',
                'tuples_returned': 'Total rows returned by queries',
                'tuples_fetched': 'Rows actually retrieved by applications'
            }
        }
        
        # Calculate and explain cache hit ratio
        total_blocks = stats['activity']['data']['blocks_read'] + stats['activity']['data']['blocks_hit']
        if total_blocks > 0:
            hit_ratio = (stats['activity']['data']['blocks_hit'] / total_blocks) * 100
        else:
            hit_ratio = 0
            
        stats['cache_hit_ratio'] = {
            'value': round(hit_ratio, 2),
            'description': 'Percentage of data blocks found in memory vs read from disk',
            'interpretation': 'Higher is better (>95% is excellent, 90-95% is good, <90% may indicate memory issues)'
        }
        
        # Database summary metrics
        total_live_tuples = sum(table['live_tuples'] or 0 for table in enhanced_tables)
        total_dead_tuples = sum(table['dead_tuples'] or 0 for table in enhanced_tables)
        tables_needing_vacuum = len([t for t in enhanced_tables if t['health_status'] == 'Needs Vacuum'])
        
        stats['summary'] = {
            'total_live_rows': {
                'value': total_live_tuples,
                'description': 'Total active rows across all application tables'
            },
            'total_dead_rows': {
                'value': total_dead_tuples,
                'description': 'Total deleted/updated rows waiting for cleanup'
            },
            'tables_needing_maintenance': {
                'value': tables_needing_vacuum,
                'description': 'Number of tables that would benefit from VACUUM operation'
            },
            'overall_health': {
                'value': 'Good' if tables_needing_vacuum == 0 else f'{tables_needing_vacuum} tables need attention',
                'description': 'Overall database health assessment based on table statistics'
            }
        }
            
        # Check for observations table (main application table)
        try:
            cursor.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'observations'")
            if cursor.fetchone()[0] > 0:
                cursor.execute("""
                    SELECT 
                        COUNT(*) as total_observations,
                        COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '24 hours') as recent_observations,
                        COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '1 hour') as hourly_observations,
                        COUNT(DISTINCT object_class) as unique_object_types
                    FROM observations
                """)
                obs_result = cursor.fetchone()
                stats['application_metrics'] = {
                    'data': dict(obs_result),
                    'description': 'Application-specific metrics from the observations table',
                    'metrics_explained': {
                        'total_observations': 'All observations/detections stored in the database',
                        'recent_observations': 'New observations in the last 24 hours', 
                        'hourly_observations': 'New observations in the last hour',
                        'unique_object_types': 'Different types of objects being detected'
                    }
                }
        except Exception as e:
            logger.debug(f"Application metrics not available: {e}")
            stats['application_metrics'] = {
                'data': {'total_observations': 0, 'recent_observations': 0, 'hourly_observations': 0},
                'description': 'Application table not found or not accessible'
            }
            
        cursor.close()
        conn.close()
        return stats
        
    except Exception as e:
        logger.error(f"Error getting PostgreSQL stats: {e}")
        if conn:
            conn.close()
        return {'error': f'Error retrieving PostgreSQL statistics: {str(e)}'}

def get_rtsp_reader_stats() -> Dict[str, Any]:
    """Get RTSP Reader service statistics from health endpoint."""
    logger.info("📹 Starting get_rtsp_reader_stats()")
    
    try:
        # Make request to RTSP Reader health endpoint
        response = requests.get('https://rtsp-reader.altfred.com/health', timeout=5)
        response.raise_for_status()
        
        raw_data = response.json()
        
        # Structure the data with descriptions and enhanced metrics
        stats = {
            'service_info': {
                'status': raw_data.get('status', 'unknown'),
                'service': raw_data.get('service', 'rtsp-reader'),
                'version': raw_data.get('version', 'unknown'),
                'uptime': {
                    'value': raw_data.get('uptime', 0),
                    'formatted': format_uptime(raw_data.get('uptime', 0)),
                    'description': 'Service uptime in seconds since last restart'
                }
            },
            'streams': {
                'data': raw_data.get('streams', {}),
                'total': raw_data.get('streams', {}).get('total', 0),
                'running': raw_data.get('streams', {}).get('running', 0),
                'health_status': 'Good' if raw_data.get('streams', {}).get('total', 0) == raw_data.get('streams', {}).get('running', 0) else 'Warning',
                'description': 'RTSP stream processing status and counts'
            },
            'publisher': {
                'data': raw_data.get('publisher', {}),
                'connected': raw_data.get('publisher', {}).get('connected', False),
                'stats': raw_data.get('publisher', {}).get('stats', {}),
                'description': 'Message publisher connection and performance metrics'
            },
            'dynamic_config': {
                'data': raw_data.get('dynamic_config', {}),
                'monitoring_enabled': raw_data.get('dynamic_config', {}).get('monitoring', False),
                'last_check': raw_data.get('dynamic_config', {}).get('last_check', 0),
                'current_streams': raw_data.get('dynamic_config', {}).get('current_streams', 0),
                'description': 'Runtime configuration and monitoring status'
            },
            'circuit_breaker': {
                'open': raw_data.get('publisher', {}).get('stats', {}).get('circuit_breaker_open', False),
                'failures': raw_data.get('publisher', {}).get('stats', {}).get('circuit_breaker_failures', 0),
                'status': 'Closed' if not raw_data.get('publisher', {}).get('stats', {}).get('circuit_breaker_open', False) else 'Open',
                'description': 'Publisher circuit breaker protection status'
            }
        }
        
        logger.info("✅ Successfully gathered RTSP Reader statistics")
        return stats
        
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ Error connecting to RTSP Reader: {e}")
        return {'error': f'Cannot connect to RTSP Reader service: {str(e)}'}
    except Exception as e:
        logger.error(f"❌ Error getting RTSP Reader stats: {e}")
        return {'error': f'Error retrieving RTSP Reader statistics: {str(e)}'}

def format_uptime(seconds: float) -> str:
    """Format uptime seconds into a human-readable string."""
    if not seconds or seconds <= 0:
        return 'N/A'
    
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    minutes = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    
    if days > 0:
        return f"{days}d {hours}h {minutes}m {secs}s"
    elif hours > 0:
        return f"{hours}h {minutes}m {secs}s"
    elif minutes > 0:
        return f"{minutes}m {secs}s"
    else:
        return f"{secs}s"

@app.route('/')
@requires_auth
def dashboard():
    """Main dashboard page."""
    return render_template('dashboard.html')

@app.route('/api/stats')
@requires_auth
def api_stats():
    """API endpoint to get all database and service statistics."""
    valkey_stats = get_valkey_stats()
    postgres_stats = get_postgres_stats()
    rtsp_reader_stats = get_rtsp_reader_stats()
    
    return jsonify({
        'valkey': valkey_stats,
        'postgres': postgres_stats,
        'rtsp_reader': rtsp_reader_stats,
        'timestamp': datetime.utcnow().isoformat()
    })

@app.route('/api/valkey')
@requires_auth
def api_valkey():
    """API endpoint to get Valkey statistics."""
    logger.info("🌐 API /api/valkey endpoint called")
    try:
        stats = get_valkey_stats()
        logger.info(f"📋 Returning Valkey stats: {len(str(stats))} characters")
        return jsonify(stats)
    except Exception as e:
        logger.error(f"❌ Error in /api/valkey endpoint: {e}")
        return jsonify({'error': f'API error: {str(e)}'}), 500

@app.route('/api/postgres')
@requires_auth
def api_postgres():
    """API endpoint to get PostgreSQL statistics."""
    return jsonify(get_postgres_stats())

@app.route('/api/rtsp-reader')
@requires_auth
def api_rtsp_reader():
    """API endpoint to get RTSP Reader service statistics."""
    logger.info("🌐 API /api/rtsp-reader endpoint called")
    try:
        stats = get_rtsp_reader_stats()
        logger.info(f"📋 Returning RTSP Reader stats: {len(str(stats))} characters")
        return jsonify(stats)
    except Exception as e:
        logger.error(f"❌ Error in /api/rtsp-reader endpoint: {e}")
        return jsonify({'error': f'API error: {str(e)}'}), 500

@app.route('/observations')
@requires_auth
def observations_page():
    """Observations page."""
    return render_template('observations.html')

@app.route('/api/clients')
@requires_auth
def api_clients():
    """API endpoint to get distinct client IDs with observation counts."""
    logger.info("🔍 API /api/clients endpoint called")
    
    conn = get_postgres_connection()
    if not conn:
        return jsonify({'error': 'Cannot connect to PostgreSQL database'}), 503
        
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Get distinct client IDs with counts and latest observation
        cursor.execute("""
            SELECT 
                client_id,
                COUNT(*) as observation_count,
                MAX(created_at) as last_observation,
                COUNT(DISTINCT object_class) as object_types,
                AVG(confidence) as avg_confidence
            FROM observations 
            WHERE client_id IS NOT NULL AND client_id != ''
            GROUP BY client_id
            ORDER BY MAX(created_at) DESC
        """)
        
        clients = []
        for row in cursor.fetchall():
            client_data = dict(row)
            # Format the last observation timestamp
            if client_data['last_observation']:
                client_data['last_observation'] = client_data['last_observation'].isoformat()
            # Round average confidence
            if client_data['avg_confidence']:
                client_data['avg_confidence'] = round(float(client_data['avg_confidence']), 3)
            clients.append(client_data)
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'clients': clients,
            'total_clients': len(clients)
        })
        
    except Exception as e:
        logger.error(f"❌ Error getting clients: {e}")
        if conn:
            conn.close()
        return jsonify({'error': f'Error retrieving clients: {str(e)}'}), 500

@app.route('/api/observations')
@requires_auth
def api_observations():
    """API endpoint to get observations data with sorting and filtering."""
    logger.info("🔍 API /api/observations endpoint called")
    
    # Get query parameters
    page = int(request.args.get('page', 1))
    limit = min(int(request.args.get('limit', 50)), 1000)  # Max 1000 records
    search = request.args.get('search', '').strip()
    sort_by = request.args.get('sort', 'created_at')
    sort_order = request.args.get('order', 'desc').lower()
    
    # Validate sort parameters
    allowed_sort_columns = [
        'id', 'job_id', 'client_id', 'stream_id', 'observation_type', 'object_class',
        'confidence', 'ts_start', 'ts_end', 'created_at', 'tracking_id', 'detection_id'
    ]
    if sort_by not in allowed_sort_columns:
        sort_by = 'created_at'
    if sort_order not in ['asc', 'desc']:
        sort_order = 'desc'
        
    conn = get_postgres_connection()
    if not conn:
        return jsonify({'error': 'Cannot connect to PostgreSQL database'}), 503
        
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        
        # Build the WHERE clause for search
        where_conditions = []
        params = []
        
        if search:
            # Handle special client_id filter syntax: client_id:value
            if search.startswith('client_id:'):
                client_id = search.replace('client_id:', '').strip()
                where_conditions.append("client_id = %s")
                params.append(client_id)
            elif 'client_id:' in search:
                # Handle mixed search with client filter
                parts = search.split()
                client_filter = None
                search_terms = []
                
                for part in parts:
                    if part.startswith('client_id:'):
                        client_filter = part.replace('client_id:', '').strip()
                    else:
                        search_terms.append(part)
                
                if client_filter:
                    where_conditions.append("client_id = %s")
                    params.append(client_filter)
                
                if search_terms:
                    search_text = ' '.join(search_terms)
                    search_fields = [
                        'job_id', 'stream_id', 'observation_type', 'object_class'
                    ]
                    search_conditions = []
                    for field in search_fields:
                        search_conditions.append(f"{field}::text ILIKE %s")
                        params.append(f'%{search_text}%')
                    where_conditions.append(f"({' OR '.join(search_conditions)})")
            else:
                # Regular search across multiple text fields
                search_fields = [
                    'job_id', 'client_id', 'stream_id', 'observation_type', 'object_class'
                ]
                search_conditions = []
                for field in search_fields:
                    search_conditions.append(f"{field}::text ILIKE %s")
                    params.append(f'%{search}%')
                where_conditions.append(f"({' OR '.join(search_conditions)})")
        
        where_clause = 'WHERE ' + ' AND '.join(where_conditions) if where_conditions else ''
        
        # Get total count
        count_query = f"SELECT COUNT(*) as total FROM observations {where_clause}"
        cursor.execute(count_query, params)
        total_count = cursor.fetchone()['total']
        
        # Get paginated data
        offset = (page - 1) * limit
        data_query = f"""
            SELECT 
                id, job_id, client_id, stream_id, observation_type, object_class,
                confidence, bbox_x, bbox_y, bbox_w, bbox_h,
                ts_start, ts_end, last_refresh_at, spatial_bucket, tracking_id,
                pose_json, image_path, created_at, detection_id
            FROM observations 
            {where_clause}
            ORDER BY {sort_by} {sort_order.upper()}
            LIMIT %s OFFSET %s
        """
        
        cursor.execute(data_query, params + [limit, offset])
        observations = [dict(row) for row in cursor.fetchall()]
        
        # Helper to build signed Spaces image URL
        def build_image_url(path: str) -> str:
            try:
                if not path:
                    return path
                    
                # Check if we have Spaces credentials for signing
                spaces_key = config.get('SPACES_ACCESS_KEY')
                spaces_secret = config.get('SPACES_SECRET_KEY')
                spaces_endpoint = config.get('SPACES_ENDPOINT', 'https://fra1.digitaloceanspaces.com')
                bucket = config.get('SPACES_BUCKET')
                
                if not bucket:
                    return path
                    
                # Normalize path
                p = path.lstrip('/')
                if p.startswith(bucket + '/'):
                    p = p[len(bucket)+1:]
                
                if spaces_key and spaces_secret:
                    # Generate pre-signed URL (valid for 1 hour)
                    try:
                        import boto3
                        from botocore.config import Config
                        
                        # Configure S3 client for DigitalOcean Spaces
                        s3_client = boto3.client(
                            's3',
                            endpoint_url=spaces_endpoint,
                            aws_access_key_id=spaces_key,
                            aws_secret_access_key=spaces_secret,
                            region_name='fra1',
                            config=Config(signature_version='s3v4')
                        )
                        
                        # Generate pre-signed URL
                        signed_url = s3_client.generate_presigned_url(
                            'get_object',
                            Params={'Bucket': bucket, 'Key': p},
                            ExpiresIn=3600  # 1 hour
                        )
                        return signed_url
                        
                    except ImportError:
                        # boto3 not available, fall back to public URL
                        pass
                    except Exception as e:
                        logger.warning(f"Failed to generate signed URL: {e}")
                        
                # Fall back to public URL
                base_url = config.get('SPACES_PUBLIC_BASE_URL')
                if base_url:
                    return f"{base_url.rstrip('/')}/{p}"
                else:
                    return f"{spaces_endpoint}/{bucket}/{p}"
                    
            except Exception as e:
                logger.error(f"Error building image URL: {e}")
                return path
        
        # Convert timestamps and image paths
        for obs in observations:
            for key in ['ts_start', 'ts_end', 'last_refresh_at', 'created_at']:
                if obs[key]:
                    obs[key] = obs[key].isoformat()
            if 'image_path' in obs and obs['image_path']:
                obs['image_path'] = build_image_url(obs['image_path'])
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'observations': observations,
            'pagination': {
                'page': page,
                'limit': limit,
                'total': total_count,
                'pages': (total_count + limit - 1) // limit
            },
            'search': search,
            'sort': {'column': sort_by, 'order': sort_order}
        })
        
    except Exception as e:
        logger.error(f"❌ Error getting observations: {e}")
        if conn:
            conn.close()
        return jsonify({'error': f'Error retrieving observations: {str(e)}'}), 500

@app.route('/health')
def health_check():
    """Health check endpoint."""
    valkey_client = get_valkey_connection()
    postgres_conn = get_postgres_connection()
    
    valkey_healthy = valkey_client is not None
    postgres_healthy = postgres_conn is not None
    
    if valkey_client:
        valkey_client.close()
    if postgres_conn:
        postgres_conn.close()
    
    status = 'healthy' if valkey_healthy and postgres_healthy else 'unhealthy'
    status_code = 200 if status == 'healthy' else 503
    
    return jsonify({
        'status': status,
        'valkey': 'connected' if valkey_healthy else 'disconnected',
        'postgres': 'connected' if postgres_healthy else 'disconnected',
        'timestamp': datetime.utcnow().isoformat()
    }), status_code

if __name__ == '__main__':
    app.run(
        host='0.0.0.0',
        port=config['APP_PORT'],
        debug=config['DEBUG']
    )