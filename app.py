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
from flask import Flask, render_template, jsonify, request
import requests

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)

# Load configuration
def load_config():
    """Load configuration from environment variables and config files."""
    config = {
        'VALKEY_HOST': os.getenv('VALKEY_HOST', 'localhost'),
        'VALKEY_PORT': int(os.getenv('VALKEY_PORT', 6379)),
        'VALKEY_USER': os.getenv('VALKEY_USER'),
        'VALKEY_PASSWORD': os.getenv('VALKEY_PASSWORD'),
        'VALKEY_DB': int(os.getenv('VALKEY_DB', 0)),
        
        'POSTGRES_HOST': os.getenv('POSTGRES_HOST', 'localhost'),
        'POSTGRES_PORT': int(os.getenv('POSTGRES_PORT', 5432)),
        'POSTGRES_DATABASE': os.getenv('POSTGRES_DATABASE', 'webapp_db'),
        'POSTGRES_USER': os.getenv('POSTGRES_USER', 'postgres'),
        'POSTGRES_PASSWORD': os.getenv('POSTGRES_PASSWORD'),
        
        'APP_PORT': int(os.getenv('APP_PORT', 8080)),
        'DEBUG': os.getenv('DEBUG', 'false').lower() == 'true'
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
        
        # Get queue information and process rates (disabled temporarily to fix hanging)
        logger.info("Getting process rates (queue scanning disabled)...")
        process_rate = stats['performance']['instantaneous_ops_per_sec']['value'] or 0
        
        # Simplified queue info without scanning to avoid hanging issues
        queue_info = {
            'total_messages_in_queues': {
                'value': 0,
                'description': 'Queue scanning disabled to prevent hanging - shows 0'
            },
            'process_rate_per_second': {
                'value': process_rate,
                'description': 'Current rate of commands/messages being processed per second'
            },
            'queue_details': {
                'value': [],
                'description': 'Queue scanning temporarily disabled for stability'
            },
            'estimated_processing_time': {
                'value': "N/A",
                'description': 'Not available when queue scanning is disabled'
            },
            'note': 'Queue scanning disabled to prevent hanging issues'
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
    """Get PostgreSQL database statistics."""
    logger.info("🐘 Starting get_postgres_stats()")
    conn = get_postgres_connection()
    if not conn:
        logger.error("❌ Failed to get PostgreSQL connection in get_postgres_stats()")
        return {'error': 'Cannot connect to PostgreSQL database'}
    
    try:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        stats = {}
        
        # Database size
        cursor.execute("""
            SELECT pg_size_pretty(pg_database_size(current_database())) as size,
                   pg_database_size(current_database()) as size_bytes
        """)
        size_result = cursor.fetchone()
        stats['database_size'] = size_result['size']
        stats['database_size_bytes'] = size_result['size_bytes']
        
        # Table statistics
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
                last_autoanalyze
            FROM pg_stat_user_tables
            ORDER BY n_live_tup DESC
        """)
        tables = cursor.fetchall()
        stats['tables'] = [dict(table) for table in tables]
        
        # Connection statistics
        cursor.execute("""
            SELECT 
                count(*) as total_connections,
                count(*) FILTER (WHERE state = 'active') as active_connections,
                count(*) FILTER (WHERE state = 'idle') as idle_connections
            FROM pg_stat_activity
            WHERE datname = current_database()
        """)
        conn_result = cursor.fetchone()
        stats['connections'] = dict(conn_result)
        
        # Database activity
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
                tup_deleted as tuples_deleted
            FROM pg_stat_database 
            WHERE datname = current_database()
        """)
        activity_result = cursor.fetchone()
        stats['activity'] = dict(activity_result)
        
        # Calculate cache hit ratio
        if stats['activity']['blocks_read'] + stats['activity']['blocks_hit'] > 0:
            hit_ratio = (stats['activity']['blocks_hit'] / 
                        (stats['activity']['blocks_read'] + stats['activity']['blocks_hit'])) * 100
            stats['cache_hit_ratio'] = round(hit_ratio, 2)
        else:
            stats['cache_hit_ratio'] = 0
            
        # Recent activity (last 24 hours) from our application tables if they exist
        try:
            cursor.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_name = 'user_activities'")
            if cursor.fetchone()[0] > 0:
                cursor.execute("""
                    SELECT COUNT(*) as recent_activities
                    FROM user_activities 
                    WHERE created_at > NOW() - INTERVAL '24 hours'
                """)
                recent_result = cursor.fetchone()
                stats['recent_activities'] = recent_result['recent_activities']
        except:
            stats['recent_activities'] = 0
            
        cursor.close()
        conn.close()
        return stats
        
    except Exception as e:
        logger.error(f"Error getting PostgreSQL stats: {e}")
        if conn:
            conn.close()
        return {'error': f'Error retrieving PostgreSQL statistics: {str(e)}'}

@app.route('/')
def dashboard():
    """Main dashboard page."""
    return render_template('dashboard.html')

@app.route('/api/stats')
def api_stats():
    """API endpoint to get all database statistics."""
    valkey_stats = get_valkey_stats()
    postgres_stats = get_postgres_stats()
    
    return jsonify({
        'valkey': valkey_stats,
        'postgres': postgres_stats,
        'timestamp': datetime.utcnow().isoformat()
    })

@app.route('/api/valkey')
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
def api_postgres():
    """API endpoint to get PostgreSQL statistics."""
    return jsonify(get_postgres_stats())

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