"""Flask Backend Application - pool-based database connections"""

from flask import Flask, jsonify, request
from flask_cors import CORS
from database import DatabaseManager
import traceback

app = Flask(__name__)
CORS(app, origins=["http://localhost:8080", "http://127.0.0.1:8080", "http://localhost:3000"])

# Global error handler to prevent server crashes
@app.errorhandler(Exception)
def handle_exception(e):
    """Handle any unhandled exceptions to prevent server crashes"""
    print(f"[ERROR] Unhandled exception: {str(e)}")
    traceback.print_exc()
    return jsonify({
        'success': False,
        'message': 'Internal server error',
        'error': str(e)
    }), 500

# Global database manager instance - lazy initialized
db_manager = None
print("Database manager initialized - will connect on first API call")

def get_db():
    """Get database manager with pool initialization and health check"""
    global db_manager
    
    # Lazy initialization
    if db_manager is None:
        print("Initializing database manager...")
        db_manager = DatabaseManager()
        print("[OK] Database manager initialized")
    
    # Ensure pool is ready
    if not db_manager.pool_ready:
        print("Pool not ready, initializing...")
        if not db_manager.init_pool():
            raise Exception("Failed to initialize database session pool")
        return db_manager
    
    # Quick health check
    if not db_manager.ensure_connection():
        raise Exception("Failed to establish database connection")
    
    return db_manager

def create_fresh_db_manager():
    """Create a completely fresh database manager instance"""
    print("[RETRY] Creating completely fresh database manager...")
    try:
        from database import DatabaseManager
        fresh_manager = DatabaseManager()
        if fresh_manager.init_pool():
            print("[OK] Fresh database manager created successfully")
            return fresh_manager
        else:
            print("[ERROR] Fresh database manager creation failed")
            return None
    except Exception as e:
        print(f"[ERROR] Error creating fresh database manager: {e}")
        return None

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    return jsonify({
        'status': 'healthy',
        'message': 'Server is running'
    }), 200

@app.route('/api/init-database', methods=['POST'])
def init_database():
    """Create tables and populate sample data - improved to handle existing tables"""
    try:
        # First try to get a working database manager
        try:
            db = get_db()
        except Exception as e:
            print(f"Initial get_db() failed: {e}")
            # Try creating a fresh manager as last resort
            fresh_manager = create_fresh_db_manager()
            if fresh_manager:
                db_manager = fresh_manager
                db = db_manager
            else:
                return jsonify({
                    'success': False,
                    'message': 'Failed to establish database connection'
                }), 500
        
        # Check if tables already exist
        print("Checking if tables exist...")
        success, tables_status = db.check_tables_exist()
        if success and any(tables_status.values()):
            # Tables already exist
            print(f"Tables already exist: {tables_status}")
            return jsonify({
                'success': False,
                'message': 'Tables already exist',
                'tables_exist': True,
                'existing_tables': [table for table, exists in tables_status.items() if exists]
            }), 200
        
        # Create tables (they don't exist yet or check failed)
        print("Creating database tables...")
        success, message = db.create_tables()
        if not success:
            print(f"[ERROR] Failed to create tables: {message}")
            return jsonify({
                'success': False,
                'message': f'Error creating tables: {message}'
            }), 500
        
        # Verify connection is still healthy after create
        print("Verifying connection health after table creation...")
        if not db.ensure_connection():
            print("[WARNING] Connection degraded after table creation, attempting recovery...")
            db.force_new_connection()
        
        print("Tables created successfully. Populating sample data...")
        # Populate sample data
        success, message = db.populate_sample_data()
        if not success:
            print(f"[ERROR] Failed to populate data: {message}")
            # Try to recover connection
            try:
                db.force_new_connection()
            except:
                pass
            return jsonify({
                'success': False,
                'message': f'Error populating data: {message}'
            }), 500
        
        # Final health check and message
        print("Verifying connection health after data population...")
        if db.ensure_connection():
            print("[OK] Database initialization completed successfully - connection verified")
            return jsonify({
                'success': True,
                'message': 'Database initialized successfully with tables and sample data'
            }), 200
        else:
            print("[WARNING] Data populated but connection degraded, attempting recovery...")
            db.force_new_connection()
            return jsonify({
                'success': True,
                'message': 'Database initialized successfully (connection recovering)'
            }), 200
    
    except Exception as e:
        error_msg = str(e)
        print(f"[ERROR] Exception during database initialization: {error_msg}")
        traceback.print_exc()
        
        # Handle protocol corruption specifically
        if "DPY-5000" in error_msg or "unknown protocol message" in error_msg:
            print("[RETRY] Protocol corruption detected, trying fresh database manager...")
            try:
                fresh_manager = create_fresh_db_manager()
                if fresh_manager:
                    db_manager = fresh_manager
                    print("[OK] Fresh database manager created, attempting initialization...")
                    # Try the initialization again with fresh manager
                    success, tables_status = fresh_manager.check_tables_exist()
                    if success and any(tables_status.values()):
                        return jsonify({
                            'success': False,
                            'message': 'Tables already exist (fresh manager)',
                            'tables_exist': True,
                            'existing_tables': [table for table, exists in tables_status.items() if exists]
                        }), 200
                    
                    success, message = fresh_manager.create_tables()
                    if success:
                        success, message = fresh_manager.populate_sample_data()
                        if success:
                            return jsonify({
                                'success': True,
                                'message': 'Database initialized successfully with fresh manager'
                            }), 200
                    
                    return jsonify({
                        'success': False,
                        'message': 'Fresh manager initialization failed'
                    }), 500
                else:
                    print("[ERROR] Failed to create fresh database manager")
            except Exception as fresh_error:
                print(f"[ERROR] Fresh manager attempt failed: {fresh_error}")
        
        # Attempt emergency recovery
        try:
            print("Attempting emergency connection recovery...")
            db_manager.force_new_connection()
            print("[OK] Emergency recovery successful")
        except Exception as recovery_error:
            print(f"[ERROR] Emergency recovery failed: {recovery_error}")
            # Last resort: reset manager
            try:
                print("Last resort: resetting database manager...")
                fresh_manager = create_fresh_db_manager()
                if fresh_manager:
                    db_manager = fresh_manager
                    print("[OK] Database manager reset successful")
                else:
                    print("[ERROR] Database manager reset failed")
            except Exception as recreate_error:
                print(f"✗ Reset failed: {recreate_error}")
        
        return jsonify({
            'success': False,
            'message': f'Error: {error_msg}'
        }), 500

@app.route('/api/check-tables', methods=['GET'])
def check_tables():
    """Check if database tables exist"""
    try:
        # First try to get a working database manager
        try:
            db = get_db()
        except Exception as e:
            print(f"Initial get_db() failed in check_tables: {e}")
            # Try creating a fresh manager as last resort
            fresh_manager = create_fresh_db_manager()
            if fresh_manager:
                db_manager = fresh_manager
                db = db_manager
            else:
                return jsonify({
                    'success': False,
                    'message': 'Failed to establish database connection'
                }), 500
        
        success, tables_status = db.check_tables_exist()
        
        if success:
            any_exist = any(tables_status.values())
            return jsonify({
                'success': True,
                'tables_exist': any_exist,
                'tables_status': tables_status
            }), 200
        else:
            return jsonify({
                'success': False,
                'message': 'Could not check tables'
            }), 500
    
    except Exception as e:
        error_msg = str(e)
        print(f"Exception in check_tables: {error_msg}")
        traceback.print_exc()
        
        # Handle protocol corruption specifically
        if "DPY-5000" in error_msg or "unknown protocol message" in error_msg:
            print("[RETRY] Protocol corruption in check_tables, trying fresh manager...")
            try:
                fresh_manager = create_fresh_db_manager()
                if fresh_manager:
                    db_manager = fresh_manager
                    success, tables_status = fresh_manager.check_tables_exist()
                    if success:
                        any_exist = any(tables_status.values())
                        return jsonify({
                            'success': True,
                            'tables_exist': any_exist,
                            'tables_status': tables_status
                        }), 200
            except Exception as fresh_error:
                print(f"[ERROR] Fresh manager check_tables failed: {fresh_error}")
        
        return jsonify({'success': False, 'message': error_msg}), 500

@app.route('/api/drop-tables', methods=['POST'])
def drop_tables():
    """Drop all database tables (with confirmation required from user)"""
    try:
        # First try to get a working database connection
        try:
            db = get_db()
        except Exception as e:
            print(f"Initial get_db() failed in drop_tables: {e}")
            # Try creating a fresh manager as last resort
            fresh_manager = create_fresh_db_manager()
            if fresh_manager:
                db_manager = fresh_manager
                db = db_manager
            else:
                return jsonify({
                    'success': False,
                    'message': 'Failed to establish database connection'
                }), 500
        
        # Check if user confirmed the action
        data = request.get_json() or {}
        confirmed = data.get('confirmed', False)
        
        if not confirmed:
            return jsonify({
                'success': False,
                'message': 'Action not confirmed. Please confirm deletion.'
            }), 400
        
        print("Starting table drop operation...")
        # Drop the tables
        success, message = db.drop_tables_safely()
        
        if success:
            print("✓ Tables dropped successfully")
            # Verify connection recovered from PL/SQL execution
            print("Verifying connection recovery after drop...")
            try:
                if db.ensure_connection():
                    print("✓ Connection verified healthy after drop")
                else:
                    print("⚠️ Connection needs recovery, forcing reset...")
                    db.force_new_connection()
            except Exception as verify_error:
                print(f"⚠️ Connection verification error (but tables were dropped): {verify_error}")
                try:
                    db.force_new_connection()
                except:
                    pass
            
            return jsonify({
                'success': True,
                'message': message
            }), 200
        else:
            print(f"✗ Table drop failed: {message}")
            # Attempt recovery even on failure
            try:
                db.force_new_connection()
            except:
                pass
            return jsonify({
                'success': False,
                'message': message
            }), 500
    
    except Exception as e:
        error_msg = str(e)
        print(f"✗ Exception during drop_tables: {error_msg}")
        traceback.print_exc()
        
        # Handle protocol corruption specifically
        if "DPY-5000" in error_msg or "unknown protocol message" in error_msg:
            print("🔄 Protocol corruption in drop_tables, trying fresh manager...")
            try:
                fresh_manager = create_fresh_db_manager()
                if fresh_manager:
                    db_manager = fresh_manager
                    print("✓ Fresh database manager created, attempting drop...")
                    # Try the drop again with fresh manager
                    data = request.get_json() or {}
                    confirmed = data.get('confirmed', False)
                    if confirmed:
                        success, message = fresh_manager.drop_tables_safely()
                        if success:
                            return jsonify({
                                'success': True,
                                'message': 'Tables dropped successfully (fresh manager)'
                            }), 200
                    
                    return jsonify({
                        'success': False,
                        'message': 'Fresh manager drop failed'
                    }), 500
                else:
                    print("✗ Failed to create fresh database manager")
            except Exception as fresh_error:
                print(f"✗ Fresh manager drop_tables failed: {fresh_error}")
        
        # Emergency recovery
        try:
            db_manager.force_new_connection()
        except Exception as recovery_error:
            print(f"[ERROR] Emergency recovery failed: {recovery_error}")
            # Last resort: reset manager
            try:
                print("Last resort: resetting database manager after drop error...")
                fresh_manager = create_fresh_db_manager()
                if fresh_manager:
                    db_manager = fresh_manager
                    print("[OK] Database manager reset successful")
                else:
                    print("✗ Database manager reset failed")
            except Exception as recreate_error:
                print(f"✗ Reset failed: {recreate_error}")
        
        return jsonify({
            'success': False,
            'message': error_msg
        }), 500

@app.route('/api/customers', methods=['GET'])
def get_customers():
    """Get all customers"""
    try:
        # First try to get a working database connection
        try:
            db = get_db()
        except Exception as e:
            print(f"Initial get_db() failed in get_customers: {e}")
            # Try creating a fresh manager as last resort
            fresh_manager = create_fresh_db_manager()
            if fresh_manager:
                global db_manager
                db_manager = fresh_manager
                db = db_manager
            else:
                return jsonify({
                    'success': False,
                    'message': 'Failed to establish database connection'
                }), 500
        
        # Try a simpler query first
        success, result = db.fetch_all("SELECT COUNT(*) as count FROM Customer")
        if not success:
            print(f"Error counting customers: {result}")
            return jsonify({
                'success': False,
                'message': f'Count query failed: {result}'
            }), 400
        
        count = result[0]['COUNT']
        print(f"Customer count: {count}")
        
        if count == 0:
            return jsonify({
                'success': True,
                'data': [],
                'count': 0
            }), 200
        
        # Try the full query
        success, result = db.fetch_all("SELECT customer_id, customer_name, email, city FROM Customer ORDER BY customer_id")
        if success:
            return jsonify({
                'success': True,
                'data': result,
                'count': len(result)
            }), 200
        else:
            print(f"Error fetching customers: {result}")
            return jsonify({
                'success': False,
                'message': f'Database error: {result}'
            }), 400
    except Exception as e:
        error_msg = str(e)
        print(f"Exception in get_customers: {error_msg}")
        traceback.print_exc()
        
        # Handle protocol corruption specifically
        if "DPY-5000" in error_msg or "unknown protocol message" in error_msg:
            print("🔄 Protocol corruption in get_customers, trying fresh manager...")
            try:
                fresh_manager = create_fresh_db_manager()
                if fresh_manager:
                    db_manager = fresh_manager
                    success, result = fresh_manager.fetch_all("SELECT customer_id, customer_name, email, city FROM Customer ORDER BY customer_id")
                    if success:
                        return jsonify({
                            'success': True,
                            'data': result,
                            'count': len(result)
                        }), 200
            except Exception as fresh_error:
                print(f"✗ Fresh manager get_customers failed: {fresh_error}")
        
        return jsonify({'success': False, 'message': error_msg}), 500

@app.route('/api/products', methods=['GET'])
def get_products():
    """Get all products"""
    try:
        # First try to get a working database connection
        try:
            db = get_db()
        except Exception as e:
            print(f"Initial get_db() failed in get_products: {e}")
            # Try creating a fresh manager as last resort
            fresh_manager = create_fresh_db_manager()
            if fresh_manager:
                global db_manager
                db_manager = fresh_manager
                db = db_manager
            else:
                return jsonify({
                    'success': False,
                    'message': 'Failed to establish database connection'
                }), 500
        
        success, result = db.fetch_all("SELECT product_id, product_name, category, CAST(price AS NUMBER(10,2)) as price, stock_quantity, location_id, supplier FROM Product ORDER BY product_id")
        if success:
            return jsonify({
                'success': True,
                'data': result,
                'count': len(result)
            }), 200
        else:
            print(f"Error fetching products: {result}")
            return jsonify({
                'success': False,
                'message': f'Database error: {result}'
            }), 400
    except Exception as e:
        error_msg = str(e)
        print(f"Exception in get_products: {error_msg}")
        traceback.print_exc()
        
        # Handle protocol corruption specifically
        if "DPY-5000" in error_msg or "unknown protocol message" in error_msg:
            print("🔄 Protocol corruption in get_products, trying fresh manager...")
            try:
                fresh_manager = create_fresh_db_manager()
                if fresh_manager:
                    db_manager = fresh_manager
                    success, result = fresh_manager.fetch_all("SELECT product_id, product_name, category, CAST(price AS NUMBER(10,2)) as price, stock_quantity, location_id, supplier FROM Product ORDER BY product_id")
                    if success:
                        return jsonify({
                            'success': True,
                            'data': result,
                            'count': len(result)
                        }), 200
            except Exception as fresh_error:
                print(f"✗ Fresh manager get_products failed: {fresh_error}")
        
        return jsonify({'success': False, 'message': error_msg}), 500

@app.route('/api/locations', methods=['GET'])
def get_locations():
    """Get all locations"""
    try:
        # First try to get a working database connection
        try:
            db = get_db()
        except Exception as e:
            print(f"Initial get_db() failed in get_locations: {e}")
            # Try creating a fresh manager as last resort
            fresh_manager = create_fresh_db_manager()
            if fresh_manager:
                global db_manager
                db_manager = fresh_manager
                db = db_manager
            else:
                return jsonify({
                    'success': False,
                    'message': 'Failed to establish database connection'
                }), 500
        
        success, result = db.fetch_all("SELECT location_id, location_name, city, country, CAST(latitude AS NUMBER(10,6)) as latitude, CAST(longitude AS NUMBER(10,6)) as longitude, warehouse_type FROM Location ORDER BY location_id")
        if success:
            return jsonify({
                'success': True,
                'data': result,
                'count': len(result)
            }), 200
        else:
            print(f"Error fetching locations: {result}")
            return jsonify({
                'success': False,
                'message': f'Database error: {result}'
            }), 400
    except Exception as e:
        error_msg = str(e)
        print(f"Exception in get_locations: {error_msg}")
        traceback.print_exc()
        
        # Handle protocol corruption specifically
        if "DPY-5000" in error_msg or "unknown protocol message" in error_msg:
            print("🔄 Protocol corruption in get_locations, trying fresh manager...")
            try:
                fresh_manager = create_fresh_db_manager()
                if fresh_manager:
                    db_manager = fresh_manager
                    success, result = fresh_manager.fetch_all("SELECT location_id, location_name, city, country, CAST(latitude AS NUMBER(10,6)) as latitude, CAST(longitude AS NUMBER(10,6)) as longitude, warehouse_type FROM Location ORDER BY location_id")
                    if success:
                        return jsonify({
                            'success': True,
                            'data': result,
                            'count': len(result)
                        }), 200
            except Exception as fresh_error:
                print(f"✗ Fresh manager get_locations failed: {fresh_error}")
        
        return jsonify({'success': False, 'message': error_msg}), 500

@app.route('/api/sales', methods=['GET'])
def get_sales():
    """Get all sales"""
    try:
        # First try to get a working database connection
        try:
            db = get_db()
        except Exception as e:
            print(f"Initial get_db() failed in get_sales: {e}")
            # Try creating a fresh manager as last resort
            fresh_manager = create_fresh_db_manager()
            if fresh_manager:
                global db_manager
                db_manager = fresh_manager
                db = db_manager
            else:
                return jsonify({
                    'success': False,
                    'message': 'Failed to establish database connection'
                }), 500
        
        success, result = db.fetch_all("""
            SELECT s.sales_id, s.customer_id, s.product_id, s.quantity, 
                   CAST(s.unit_price AS NUMBER(10,2)) as unit_price, 
                   CAST(s.total_amount AS NUMBER(10,2)) as total_amount, 
                   s.location_id, s.sales_date,
                   c.customer_name, p.product_name, l.location_name 
            FROM Sales s
            LEFT JOIN Customer c ON s.customer_id = c.customer_id
            LEFT JOIN Product p ON s.product_id = p.product_id
            LEFT JOIN Location l ON s.location_id = l.location_id
            ORDER BY s.sales_id
        """)
        if success:
            return jsonify({
                'success': True,
                'data': result,
                'count': len(result)
            }), 200
        else:
            print(f"Error fetching sales: {result}")
            return jsonify({
                'success': False,
                'message': f'Database error: {result}'
            }), 400
    except Exception as e:
        error_msg = str(e)
        print(f"Exception in get_sales: {error_msg}")
        
        # Handle protocol corruption specifically
        if "DPY-5000" in error_msg or "unknown protocol message" in error_msg:
            print("🔄 Protocol corruption in get_sales, trying fresh manager...")
            try:
                fresh_manager = create_fresh_db_manager()
                if fresh_manager:
                    db_manager = fresh_manager
                    success, result = fresh_manager.fetch_all("""
                        SELECT s.sales_id, s.customer_id, s.product_id, s.quantity, 
                               CAST(s.unit_price AS NUMBER(10,2)) as unit_price, 
                               CAST(s.total_amount AS NUMBER(10,2)) as total_amount, 
                               s.location_id, s.sales_date,
                               c.customer_name, p.product_name, l.location_name 
                        FROM Sales s
                        LEFT JOIN Customer c ON s.customer_id = c.customer_id
                        LEFT JOIN Product p ON s.product_id = p.product_id
                        LEFT JOIN Location l ON s.location_id = l.location_id
                        ORDER BY s.sales_id
                    """)
                    if success:
                        return jsonify({
                            'success': True,
                            'data': result,
                            'count': len(result)
                        }), 200
            except Exception as fresh_error:
                print(f"✗ Fresh manager get_sales failed: {fresh_error}")
        
        return jsonify({'success': False, 'message': error_msg}), 500

@app.route('/api/stats', methods=['GET'])
def get_stats():
    """Get statistics"""
    try:
        # First try to get a working database connection
        try:
            db = get_db()
        except Exception as e:
            print(f"Initial get_db() failed in get_stats: {e}")
            # Try creating a fresh manager as last resort
            fresh_manager = create_fresh_db_manager()
            if fresh_manager:
                global db_manager
                db_manager = fresh_manager
                db = db_manager
            else:
                return jsonify({
                    'success': False,
                    'message': 'Failed to establish database connection'
                }), 500
        
        # Get customer count
        success, customers = db.fetch_all("SELECT COUNT(*) as count FROM Customer")
        customer_count = customers[0]['COUNT'] if success and customers else 0
        
        # Get product count
        success, products = db.fetch_all("SELECT COUNT(*) as count FROM Product")
        product_count = products[0]['COUNT'] if success and products else 0
        
        # Get sales count
        success, sales = db.fetch_all("SELECT COUNT(*) as count FROM Sales")
        sales_count = sales[0]['COUNT'] if success and sales else 0
        
        # Get total sales revenue - simplified query
        success, revenue = db.fetch_all("SELECT SUM(total_amount) as total FROM Sales")
        total_revenue = 0.0
        if success and revenue and revenue[0]['TOTAL'] is not None:
            try:
                total_revenue = float(revenue[0]['TOTAL'])
            except:
                total_revenue = 0.0
        
        return jsonify({
            'success': True,
            'data': {
                'total_customers': customer_count,
                'total_products': product_count,
                'total_sales': sales_count,
                'total_revenue': total_revenue
            }
        }), 200
    except Exception as e:
        error_msg = str(e)
        print(f"Exception in get_stats: {error_msg}")
        traceback.print_exc()
        
        # Handle protocol corruption specifically
        if "DPY-5000" in error_msg or "unknown protocol message" in error_msg:
            print("🔄 Protocol corruption in get_stats, trying fresh manager...")
            try:
                fresh_manager = create_fresh_db_manager()
                if fresh_manager:
                    db_manager = fresh_manager
                    # Get customer count
                    success, customers = fresh_manager.fetch_all("SELECT COUNT(*) as count FROM Customer")
                    customer_count = customers[0]['COUNT'] if success and customers else 0
                    
                    # Get product count
                    success, products = fresh_manager.fetch_all("SELECT COUNT(*) as count FROM Product")
                    product_count = products[0]['COUNT'] if success and products else 0
                    
                    # Get sales count
                    success, sales = fresh_manager.fetch_all("SELECT COUNT(*) as count FROM Sales")
                    sales_count = sales[0]['COUNT'] if success and sales else 0
                    
                    # Get total sales revenue
                    success, revenue = fresh_manager.fetch_all("SELECT SUM(total_amount) as total FROM Sales")
                    total_revenue = 0.0
                    if success and revenue and revenue[0]['TOTAL'] is not None:
                        try:
                            total_revenue = float(revenue[0]['TOTAL'])
                        except:
                            total_revenue = 0.0
                    
                    return jsonify({
                        'success': True,
                        'data': {
                            'total_customers': customer_count,
                            'total_products': product_count,
                            'total_sales': sales_count,
                            'total_revenue': total_revenue
                        }
                    }), 200
            except Exception as fresh_error:
                print(f"✗ Fresh manager get_stats failed: {fresh_error}")
        
        return jsonify({'success': False, 'message': error_msg}), 500

@app.route('/api/sales-per-product-location', methods=['GET'])
def get_sales_per_product_location():
    """Get number of sales per product by location with timing"""
    try:
        # First try to get a working database manager
        try:
            db = get_db()
        except Exception as e:
            print(f"Initial get_db() failed in get_sales_per_product_location: {e}")
            # Try creating a fresh manager as last resort
            fresh_manager = create_fresh_db_manager()
            if fresh_manager:
                global db_manager
                db_manager = fresh_manager
                db = db_manager
            else:
                return jsonify({
                    'success': False,
                    'message': 'Failed to establish database connection'
                }), 500

        success, result, execution_time = db.get_sales_per_product_by_location()

        if success:
            return jsonify({
                'success': True,
                'data': result,
                'execution_time': round(execution_time, 4),
                'count': len(result)
            }), 200
        else:
            print(f"Error getting sales per product by location: {result}")
            return jsonify({
                'success': False,
                'message': f'Database error: {result}',
                'execution_time': round(execution_time, 4)
            }), 400
    except Exception as e:
        error_msg = str(e)
        print(f"Exception in get_sales_per_product_location: {error_msg}")
        traceback.print_exc()

        return jsonify({'success': False, 'message': error_msg}), 500

@app.route('/api/max-sales-per-product-location', methods=['GET'])
def get_max_sales_per_product_location():
    """Get maximum sales quantity per product by location with timing"""
    try:
        # First try to get a working database manager
        try:
            db = get_db()
        except Exception as e:
            print(f"Initial get_db() failed in get_max_sales_per_product_location: {e}")
            # Try creating a fresh manager as last resort
            fresh_manager = create_fresh_db_manager()
            if fresh_manager:
                global db_manager
                db_manager = fresh_manager
                db = db_manager
            else:
                return jsonify({
                    'success': False,
                    'message': 'Failed to establish database connection'
                }), 500

        success, result, execution_time = db.get_max_sales_per_product_by_location()

        if success:
            return jsonify({
                'success': True,
                'data': result,
                'execution_time': round(execution_time, 4),
                'count': len(result)
            }), 200
        else:
            print(f"Error getting max sales per product by location: {result}")
            return jsonify({
                'success': False,
                'message': f'Database error: {result}',
                'execution_time': round(execution_time, 4)
            }), 400
    except Exception as e:
        error_msg = str(e)
        print(f"Exception in get_max_sales_per_product_location: {error_msg}")
        traceback.print_exc()

        return jsonify({'success': False, 'message': error_msg}), 500

@app.route('/api/phase3/create-dimensions', methods=['POST'])
def create_phase3_dimensions():
    """Create phase 3 dimensional model objects and tables."""
    try:
        try:
            db = get_db()
        except Exception as e:
            print(f"Initial get_db() failed in create_phase3_dimensions: {e}")
            fresh_manager = create_fresh_db_manager()
            if fresh_manager:
                global db_manager
                db_manager = fresh_manager
                db = db_manager
            else:
                return jsonify({
                    'success': False,
                    'message': 'Failed to establish database connection'
                }), 500

        phase3_result = db.create_phase3_dimensions()
        if len(phase3_result) == 2:
            success, message = phase3_result
            warning = None
        else:
            success, message, warning = phase3_result

        if success:
            response_payload = {'success': True, 'message': message}
            if warning:
                response_payload['warning'] = warning
            return jsonify(response_payload), 200
        else:
            return jsonify({'success': False, 'message': message}), 400
    except Exception as e:
        error_msg = str(e)
        print(f"Exception in create_phase3_dimensions: {error_msg}")
        traceback.print_exc()
        return jsonify({'success': False, 'message': error_msg}), 500

@app.route('/api/phase4/create-data-mart', methods=['POST'])
def create_phase4_data_mart():
    """Create and populate the Sales Data Mart"""
    try:
        try:
            db = get_db()
        except Exception as e:
            print(f"Initial get_db() failed in create_phase4_data_mart: {e}")
            fresh_manager = create_fresh_db_manager()
            if fresh_manager:
                global db_manager
                db_manager = fresh_manager
                db = db_manager
            else:
                return jsonify({
                    'success': False,
                    'message': 'Failed to establish database connection'
                }), 500

        # Create the data mart table
        create_ok, create_msg = db.create_sales_data_mart()
        if not create_ok:
            return jsonify({'success': False, 'message': f'Failed to create data mart: {create_msg}'}), 400

        # Populate the data mart
        populate_ok, populate_msg = db.populate_sales_data_mart()
        if not populate_ok:
            return jsonify({'success': False, 'message': f'Failed to populate data mart: {populate_msg}'}), 400

        return jsonify({
            'success': True,
            'message': 'Sales Data Mart created and populated successfully'
        }), 200
    except Exception as e:
        error_msg = str(e)
        print(f"Exception in create_phase4_data_mart: {error_msg}")
        traceback.print_exc()
        return jsonify({'success': False, 'message': error_msg}), 500

@app.route('/api/phase3/status', methods=['GET'])
def get_phase3_status():
    try:
        try:
            db = get_db()
        except Exception as e:
            print(f"Initial get_db() failed in get_phase3_status: {e}")
            fresh_manager = create_fresh_db_manager()
            if fresh_manager:
                global db_manager
                db_manager = fresh_manager
                db = db_manager
            else:
                return jsonify({
                    'success': False,
                    'message': 'Failed to establish database connection'
                }), 500

        success, status = db.phase3_dimensions_exist()
        if success:
            return jsonify({
                'success': True,
                'ready': all(status.values()),
                'status': status
            }), 200
        else:
            return jsonify({
                'success': False,
                'message': 'Failed to check phase 3 dimension status'
            }), 400
    except Exception as e:
        error_msg = str(e)
        print(f"Exception in get_phase3_status: {error_msg}")
        traceback.print_exc()
        return jsonify({'success': False, 'message': error_msg}), 500

@app.route('/api/phase3/compare', methods=['GET'])
def compare_phase3_performance():
    try:
        try:
            db = get_db()
        except Exception as e:
            print(f"Initial get_db() failed in compare_phase3_performance: {e}")
            fresh_manager = create_fresh_db_manager()
            if fresh_manager:
                global db_manager
                db_manager = fresh_manager
                db = db_manager
            else:
                return jsonify({
                    'success': False,
                    'message': 'Failed to establish database connection'
                }), 500

        baseline_ok, baseline_sales, baseline_sales_time = db.get_sales_per_product_by_location()
        phase3_ok, phase3_sales, phase3_sales_time = db.get_sales_per_product_by_location_phase3()
        phase4_ok, phase4_sales, phase4_sales_time = db.get_sales_per_product_by_location_phase4()
        baseline_max_ok, baseline_max, baseline_max_time = db.get_max_sales_per_product_by_location()
        phase3_max_ok, phase3_max, phase3_max_time = db.get_max_sales_per_product_by_location_phase3()
        phase4_max_ok, phase4_max, phase4_max_time = db.get_max_sales_per_product_by_location_phase4()

        if not baseline_ok:
            return jsonify({'success': False, 'message': f'Baseline sales query failed: {baseline_sales}'}), 400
        if not phase3_ok:
            return jsonify({'success': False, 'message': f'Phase 3 sales query failed: {phase3_sales}'}), 400
        if not phase4_ok:
            return jsonify({'success': False, 'message': f'Phase 4 sales query failed: {phase4_sales}'}), 400
        if not baseline_max_ok:
            return jsonify({'success': False, 'message': f'Baseline max query failed: {baseline_max}'}), 400
        if not phase3_max_ok:
            return jsonify({'success': False, 'message': f'Phase 3 max query failed: {phase3_max}'}), 400
        if not phase4_max_ok:
            return jsonify({'success': False, 'message': f'Phase 4 max query failed: {phase4_max}'}), 400

        return jsonify({
            'success': True,
            'data': {
                'sales_analytics': {
                    'baseline_time': round(baseline_sales_time, 4),
                    'phase3_time': round(phase3_sales_time, 4),
                    'phase4_time': round(phase4_sales_time, 4),
                    'baseline_count': len(baseline_sales),
                    'phase3_count': len(phase3_sales),
                    'phase4_count': len(phase4_sales)
                },
                'max_sales_analytics': {
                    'baseline_time': round(baseline_max_time, 4),
                    'phase3_time': round(phase3_max_time, 4),
                    'phase4_time': round(phase4_max_time, 4),
                    'baseline_count': len(baseline_max),
                    'phase3_count': len(phase3_max),
                    'phase4_count': len(phase4_max)
                }
            }
        }), 200
    except Exception as e:
        error_msg = str(e)
        print(f"Exception in compare_phase3_performance: {error_msg}")
        traceback.print_exc()
        return jsonify({'success': False, 'message': error_msg}), 500

if __name__ == '__main__':
    try:
        print("Starting Flask server...")
        app.run(debug=True, host='0.0.0.0', port=5000, use_reloader=False)
    except Exception as e:
        print(f"Critical error starting Flask server: {str(e)}")
        traceback.print_exc()
        print(f"❌ Flask server crashed: {e}")
        traceback.print_exc()
