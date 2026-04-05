"""Database Configuration"""

DB_CONFIG = {
    'host': '192.168.1.30',
    'port': 1521,
    'service_name': 'freepdb1',
    'user': 'system',
    'password': 'oracle'
}

# Connection string for Oracle using pluggable database service name
DB_CONNECTION_STRING = f"{DB_CONFIG['user']}/{DB_CONFIG['password']}@{DB_CONFIG['host']}:{DB_CONFIG['port']}/{DB_CONFIG['service_name']}"
