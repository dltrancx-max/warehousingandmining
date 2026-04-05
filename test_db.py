#!/usr/bin/env python3
"""Test database connection and tables"""

import sys
import os
sys.path.append(os.path.dirname(__file__))

from backend.database import DatabaseManager

def main():
    db = DatabaseManager()
    if db.connect():
        try:
            # Check what tables exist
            success, result = db.fetch_all('SELECT table_name FROM user_tables')
            if success:
                print('Tables in database:')
                for row in result:
                    print(f'  - {row["TABLE_NAME"]}')
            else:
                print(f'Error getting tables: {result}')

            # Check Customer table specifically
            success, result = db.fetch_all('SELECT COUNT(*) as count FROM Customer')
            if success:
                print(f'Customer table has {result[0]["COUNT"]} rows')
            else:
                print(f'Error querying Customer table: {result}')

            # Check Product table
            success, result = db.fetch_all('SELECT COUNT(*) as count FROM Product')
            if success:
                print(f'Product table has {result[0]["COUNT"]} rows')
            else:
                print(f'Error querying Product table: {result}')

        finally:
            db.disconnect()
    else:
        print('Failed to connect to database')

if __name__ == '__main__':
    main()