"""Database connection and operations - pool-based, per-request cursors, robust recovery"""
import oracledb
import traceback
import time
import gc
from contextlib import contextmanager
from config import DB_CONFIG  # expects keys: user, password, host, port, database (service_name)

class DatabaseManager:
    def __init__(self):
        self.pool = None
        self.pool_ready = False
        # pool sizing - tune for your workload
        self.pool_min = 1
        self.pool_max = 5
        self.pool_increment = 1

    def init_pool(self):
        """Create or re-create the session pool"""
        try:
            # If an existing pool exists, close it fully first
            if self.pool is not None:
                try:
                    self.pool.close()
                except Exception:
                    pass
                self.pool = None
                self.pool_ready = False
                gc.collect()
                time.sleep(0.5)

            connect_kwargs = dict(
                user=DB_CONFIG['user'],
                password=DB_CONFIG['password'],
                dsn=oracledb.makedsn(DB_CONFIG['host'], DB_CONFIG['port'], service_name=DB_CONFIG['service_name']),
            )

            # create session pool
            self.pool = oracledb.SessionPool(
                min=self.pool_min,
                max=self.pool_max,
                increment=self.pool_increment,
                homogeneous=True,
                threaded=True,
                getmode=oracledb.SPOOL_ATTRVAL_WAIT,
                **connect_kwargs
            )
            self.pool_ready = True
            print("[OK] Session pool created")
            return True
        except Exception as e:
            print(f"✗ Failed to create session pool: {e}")
            traceback.print_exc()
            self.pool = None
            self.pool_ready = False
            return False

    @contextmanager
    def get_connection(self):
        """Context manager returning (conn, cursor). Caller must use 'with'."""
        if not self.pool_ready:
            ok = self.init_pool()
            if not ok:
                raise Exception("Failed to initialize DB session pool")
        conn = None
        cur = None
        try:
            conn = self.pool.acquire()
            cur = conn.cursor()
            yield conn, cur
        except Exception as e:
            # Wrap and re-raise for caller to handle and maybe trigger recovery
            raise
        finally:
            try:
                if cur is not None:
                    try:
                        cur.close()
                    except:
                        pass
            except:
                pass
            try:
                if conn is not None:
                    try:
                        # rollback any uncommitted work (safe)
                        conn.rollback()
                    except:
                        pass
                    try:
                        self.pool.release(conn)
                    except:
                        # if pool release fails, attempt to close conn
                        try:
                            conn.close()
                        except:
                            pass
            except:
                pass

    def _is_protocol_error(self, err):
        msg = str(err).upper()
        return "DPY-5000" in msg or "UNKNOWN PROTOCOL MESSAGE" in msg

    def force_new_connection(self):
        """Force full pool teardown and recreation"""
        print("🔄 Force creating new database connection/pool...")
        try:
            # Close existing pool
            try:
                if self.pool is not None:
                    self.pool.close()
            except Exception as e:
                print(f"⚠️ Error closing pool: {e}")
            self.pool = None
            self.pool_ready = False
            gc.collect()
            time.sleep(1.0)
            return self.init_pool()
        except Exception as e:
            print(f"✗ Failed to force new pool: {e}")
            return False

    def ensure_connection(self):
        """Quick health-check by acquiring a connection and running a trivial query"""
        try:
            with self.get_connection() as (conn, cur):
                cur.execute("SELECT 1 FROM DUAL")
                cur.fetchone()
            return True
        except Exception as e:
            print(f"✗ Connection health check failed: {e}")
            if self._is_protocol_error(e):
                print("🔄 Detected protocol corruption, forcing new pool...")
                return self.force_new_connection()
            else:
                # attempt recreate pool as recovery
                print("🔄 Recreating pool as recovery measure...")
                return self.force_new_connection()

    def execute_query(self, query, params=None, commit=True):
        """Execute a statement (INSERT/UPDATE/DDL) with per-request cursor"""
        try:
            with self.get_connection() as (conn, cur):
                if params:
                    cur.execute(query, params)
                else:
                    cur.execute(query)
                if commit:
                    try:
                        conn.commit()
                    except:
                        pass
            return True, "Query executed successfully"
        except Exception as e:
            err = str(e)
            print(f"✗ Query execution error: {err}")
            traceback.print_exc()
            if self._is_protocol_error(e):
                # try force recovery once
                if self.force_new_connection():
                    return False, f"Protocol error occurred; pool recreated: {err}"
            return False, err

    def fetch_all(self, query, params=None):
        """Fetch rows and return list[dict] using per-request cursor"""
        try:
            with self.get_connection() as (conn, cur):
                if params:
                    cur.execute(query, params)
                else:
                    cur.execute(query)
                cols = [d[0] for d in cur.description] if cur.description else []
                rows = cur.fetchall()
            processed = []
            for row in rows:
                rowd = {}
                for i, v in enumerate(row):
                    col = cols[i] if i < len(cols) else f"col{i}"
                    if v is None:
                        rowd[col] = None
                    elif isinstance(v, (int, float, str, bool)):
                        rowd[col] = v
                    else:
                        # fallback - try cast to native
                        try:
                            rowd[col] = float(v)
                        except:
                            try:
                                rowd[col] = str(v)
                            except:
                                rowd[col] = v
                processed.append(rowd)
            return True, processed
        except Exception as e:
            err = str(e)
            print(f"✗ fetch_all error: {err}")
            traceback.print_exc()
            if self._is_protocol_error(e):
                # recovery attempt
                if self.force_new_connection():
                    return False, f"Protocol error occurred; pool recreated: {err}"
            return False, err

    # ---- Higher level operations reimplemented to use per-request connections ----

    def create_tables(self):
        try:
            if not self.ensure_connection():
                return False, "Failed to connect to database"

            create_statements = [
                ("""
                CREATE TABLE Customer (
                    customer_id NUMBER PRIMARY KEY,
                    customer_name VARCHAR2(100) NOT NULL,
                    email VARCHAR2(100),
                    phone VARCHAR2(20),
                    address VARCHAR2(255),
                    city VARCHAR2(50),
                    country VARCHAR2(50),
                    created_date DATE DEFAULT SYSDATE
                )
                """, "Customer"),
                ("""
                CREATE TABLE Location (
                    location_id NUMBER PRIMARY KEY,
                    location_name VARCHAR2(100) NOT NULL,
                    city VARCHAR2(50),
                    country VARCHAR2(50),
                    latitude BINARY_DOUBLE,
                    longitude BINARY_DOUBLE,
                    warehouse_type VARCHAR2(50),
                    created_date DATE DEFAULT SYSDATE
                )
                """, "Location"),
                ("""
                CREATE TABLE Product (
                    product_id NUMBER PRIMARY KEY,
                    product_name VARCHAR2(100) NOT NULL,
                    category VARCHAR2(50),
                    price BINARY_DOUBLE,
                    stock_quantity NUMBER,
                    location_id NUMBER,
                    supplier VARCHAR2(100),
                    created_date DATE DEFAULT SYSDATE,
                    FOREIGN KEY (location_id) REFERENCES Location(location_id)
                )
                """, "Product"),
                ("""
                CREATE TABLE Sales (
                    sales_id NUMBER PRIMARY KEY,
                    customer_id NUMBER NOT NULL,
                    product_id NUMBER NOT NULL,
                    quantity NUMBER,
                    unit_price BINARY_DOUBLE,
                    total_amount BINARY_DOUBLE,
                    sales_date DATE DEFAULT SYSDATE,
                    location_id NUMBER,
                    FOREIGN KEY (customer_id) REFERENCES Customer(customer_id),
                    FOREIGN KEY (product_id) REFERENCES Product(product_id),
                    FOREIGN KEY (location_id) REFERENCES Location(location_id)
                )
                """, "Sales"),
            ]

            for sql, name in create_statements:
                try:
                    ok, msg = self.execute_query(sql, commit=True)
                    if ok:
                        print(f"✓ {name} table created")
                except Exception as e:
                    if "already exists" in str(e).lower():
                        print(f"ℹ️ {name} table already exists")
                    else:
                        raise
            return True, "All tables created successfully"
        except Exception as e:
            print(f"✗ Error creating tables: {e}")
            traceback.print_exc()
            return False, str(e)

    def populate_sample_data(self):
        try:
            if not self.ensure_connection():
                return False, "Failed to connect to database"

            customers = [
                (1, "John Smith", "john.smith@email.com", "+1-800-001", "123 Main St", "New York", "USA"),
                (2, "Emma Johnson", "emma.j@email.com", "+1-800-002", "456 Oak Ave", "Los Angeles", "USA"),
                (3, "Raj Kumar", "raj.kumar@email.com", "+1-800-003", "789 Pine Rd", "Chicago", "USA"),
                (4, "Sarah Williams", "sarah.w@email.com", "+1-800-004", "321 Elm St", "Houston", "USA"),
                (5, "Michael Brown", "m.brown@email.com", "+1-800-005", "654 Birch Ln", "Phoenix", "USA"),
            ]
            for c in customers:
                ok, msg = self.execute_query(
                    "INSERT INTO Customer (customer_id, customer_name, email, phone, address, city, country) VALUES (:1,:2,:3,:4,:5,:6,:7)",
                    params=c, commit=True
                )
                if not ok and "unique constraint" in str(msg).lower():
                    # skip duplicates
                    continue
                elif not ok:
                    raise Exception(msg)

            locations = [
                (1, "New York Warehouse", "New York", "USA", 40.7128, -74.0060, "Primary"),
                (2, "Los Angeles Hub", "Los Angeles", "USA", 34.0522, -118.2437, "Secondary"),
                (3, "Chicago Distribution", "Chicago", "USA", 41.8781, -87.6298, "Distribution"),
                (4, "Texas Logistics", "Houston", "USA", 29.7604, -95.3698, "Regional"),
            ]
            for l in locations:
                ok, msg = self.execute_query(
                    "INSERT INTO Location (location_id, location_name, city, country, latitude, longitude, warehouse_type) VALUES (:1,:2,:3,:4,:5,:6,:7)",
                    params=l, commit=True
                )
                if not ok and "unique constraint" in str(msg).lower():
                    continue
                elif not ok:
                    raise Exception(msg)

            products = [
                (1, "Laptop Pro", "Electronics", 1299.99, 50, 1, "TechCorp Inc"),
                (2, "Wireless Mouse", "Electronics", 29.99, 200, 2, "PeripheralTech"),
                (3, "Office Chair", "Furniture", 399.99, 30, 3, "FurnitureWorld"),
                (4, "4K Monitor", "Electronics", 599.99, 45, 1, "DisplayCo"),
                (5, "USB Cable Pack", "Accessories", 14.99, 500, 2, "CableMasters"),
            ]
            for p in products:
                ok, msg = self.execute_query(
                    "INSERT INTO Product (product_id, product_name, category, price, stock_quantity, location_id, supplier) VALUES (:1,:2,:3,:4,:5,:6,:7)",
                    params=p, commit=True
                )
                if not ok and "unique constraint" in str(msg).lower():
                    continue
                elif not ok:
                    raise Exception(msg)

            sales = [
                (1, 1, 1, 2, 1299.99, 2599.98, 4),
                (2, 2, 2, 5, 29.99, 149.95, 2),
                (3, 3, 3, 1, 399.99, 399.99, 3),
                (4, 4, 4, 3, 599.99, 1799.97, 1),
                (5, 5, 5, 10, 14.99, 149.90, 2),
                (6, 1, 2, 3, 29.99, 89.97, 2),
                (7, 2, 1, 1, 1299.99, 1299.99, 1),
            ]
            for s in sales:
                ok, msg = self.execute_query(
                    "INSERT INTO Sales (sales_id, customer_id, product_id, quantity, unit_price, total_amount, location_id) VALUES (:1,:2,:3,:4,:5,:6,:7)",
                    params=s, commit=True
                )
                if not ok and "unique constraint" in str(msg).lower():
                    continue
                elif not ok:
                    raise Exception(msg)

            return True, "Sample data populated successfully"
        except Exception as e:
            print(f"✗ Error populating data: {e}")
            traceback.print_exc()
            return False, str(e)

    def check_tables_exist(self):
        try:
            if not self.ensure_connection():
                return False, {}

            tables = ['Customer', 'Location', 'Product', 'Sales']
            status = {}
            for t in tables:
                ok, res = self.fetch_all(f"SELECT COUNT(*) AS CNT FROM {t}")
                status[t] = ok and isinstance(res, list)
            return True, status
        except Exception as e:
            print(f"Error checking tables: {e}")
            return False, {}

    def drop_tables_safely(self):
        try:
            if not self.ensure_connection():
                return False, "Failed to connect to database"

            drop_queries = [
                "BEGIN EXECUTE IMMEDIATE 'DROP TABLE Sales'; EXCEPTION WHEN OTHERS THEN NULL; END;",
                "BEGIN EXECUTE IMMEDIATE 'DROP TABLE Product'; EXCEPTION WHEN OTHERS THEN NULL; END;",
                "BEGIN EXECUTE IMMEDIATE 'DROP TABLE Location'; EXCEPTION WHEN OTHERS THEN NULL; END;",
                "BEGIN EXECUTE IMMEDIATE 'DROP TABLE Customer'; EXCEPTION WHEN OTHERS THEN NULL; END;",
            ]

            for q in drop_queries:
                ok, msg = self.execute_query(q, commit=True)
                # continue regardless; errors are tolerated per original behavior

            # After PL/SQL blocks, recreate pool to ensure clean protocol state
            print("Refreshing pool after PL/SQL execution...")
            if not self.force_new_connection():
                return False, "Failed to refresh pool after drop"
            return True, "Tables dropped successfully"
        except Exception as e:
            err = str(e)
            print(f"✗ Error dropping tables: {err}")
            traceback.print_exc()
            if self._is_protocol_error(e):
                if self.force_new_connection():
                    return True, "Tables dropped (with pool recovery)"
                return False, "Protocol error and recovery failed"
            return False, err

    def get_sales_per_product_by_location(self):
        """Get number of sales (count of transactions) per product by location with timing"""
        start_time = time.time()
        try:
            if not self.ensure_connection():
                return False, "Failed to connect to database", 0.0

            query = """
                SELECT 
                    p.product_name,
                    l.location_name,
                    COUNT(s.sales_id) as sales_count,
                    SUM(s.quantity) as total_quantity_sold,
                    SUM(s.total_amount) as total_revenue
                FROM Product p
                LEFT JOIN Sales s ON p.product_id = s.product_id
                LEFT JOIN Location l ON s.location_id = l.location_id
                GROUP BY p.product_name, l.location_name, p.product_id, l.location_id
                ORDER BY p.product_name, l.location_name
            """

            success, result = self.fetch_all(query)
            execution_time = time.time() - start_time

            if success:
                return True, result, execution_time
            else:
                return False, result, execution_time

        except Exception as e:
            execution_time = time.time() - start_time
            err = str(e)
            print(f"✗ Error in sales per product by location: {err}")
            traceback.print_exc()
            if self._is_protocol_error(e):
                if self.force_new_connection():
                    return False, f"Protocol error occurred; pool recreated: {err}", execution_time
            return False, err, execution_time

    def get_max_sales_per_product_by_location(self):
        """Get maximum sales quantity per product by location with timing"""
        start_time = time.time()
        try:
            if not self.ensure_connection():
                return False, "Failed to connect to database", 0.0

            query = """
                SELECT 
                    p.product_name,
                    l.location_name,
                    MAX(s.quantity) as max_quantity_sold,
                    AVG(s.quantity) as avg_quantity_sold,
                    COUNT(s.sales_id) as number_of_sales
                FROM Product p
                LEFT JOIN Sales s ON p.product_id = s.product_id
                LEFT JOIN Location l ON s.location_id = l.location_id
                GROUP BY p.product_name, l.location_name, p.product_id, l.location_id
                ORDER BY p.product_name, l.location_name
            """

            success, result = self.fetch_all(query)
            execution_time = time.time() - start_time

            if success:
                return True, result, execution_time
            else:
                return False, result, execution_time

        except Exception as e:
            execution_time = time.time() - start_time
            err = str(e)
            print(f"✗ Error in max sales per product by location: {err}")
            traceback.print_exc()
            if self._is_protocol_error(e):
                if self.force_new_connection():
                    return False, f"Protocol error occurred; pool recreated: {err}", execution_time
            return False, err, execution_time

    def create_oracle_dimension_objects(self):
        """Create Oracle OLAP dimensions using child-of hierarchies."""
        try:
            drop_statements = [
                "BEGIN EXECUTE IMMEDIATE 'DROP DIMENSION product_dim'; EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-942, -30333) THEN RAISE; END IF; END;",
                "BEGIN EXECUTE IMMEDIATE 'DROP DIMENSION location_dim'; EXCEPTION WHEN OTHERS THEN IF SQLCODE NOT IN (-942, -30333) THEN RAISE; END IF; END;"
            ]
            for sql in drop_statements:
                self.execute_query(sql, commit=True)

            create_statements = [
                ("""
                CREATE DIMENSION product_dim
                  LEVEL product_level IS (PRODUCT.PRODUCT_ID)
                  LEVEL category_level IS (PRODUCT.CATEGORY)
                  HIERARCHY product_hierarchy (
                    product_level CHILD OF
                    category_level
                  )
                  ATTRIBUTE product_level DETERMINES (PRODUCT.PRODUCT_NAME)
                """, "product_dim"),
                ("""
                CREATE DIMENSION location_dim
                  LEVEL facility_level IS (LOCATION.LOCATION_ID)
                  LEVEL city_level IS (LOCATION.CITY)
                  LEVEL country_level IS (LOCATION.COUNTRY)
                  HIERARCHY location_hierarchy (
                    facility_level CHILD OF
                    city_level CHILD OF
                    country_level
                  )
                """, "location_dim")
            ]

            for sql, name in create_statements:
                ok, msg = self.execute_query(sql, commit=True)
                if not ok:
                    raise Exception(f"Failed to create dimension {name}: {msg}")

            return True, "Oracle dimensions created successfully"
        except Exception as e:
            print(f"✗ Oracle dimension creation failed: {e}")
            return False, str(e)

    def populate_phase3_dimensions(self):
        try:
            if not self.ensure_connection():
                return False, "Failed to connect to database"

            self.execute_query("DELETE FROM Sales_Fact", commit=True)
            self.execute_query("DELETE FROM Product_Dim", commit=True)
            self.execute_query("DELETE FROM Location_Dim", commit=True)

            ok, products = self.fetch_all("SELECT product_id, product_name, category, supplier FROM Product")
            if not ok:
                return False, products

            category_map = {}
            category_base = 1000
            for product in products:
                category = product.get('CATEGORY') or 'Uncategorized'
                if category not in category_map:
                    category_map[category] = category_base
                    ok, msg = self.execute_query(
                        "INSERT INTO Product_Dim (product_dim_id, product_id, product_name, category, supplier, level_name, parent_dim_id) VALUES (:1, :2, :3, :4, :5, :6, :7)",
                        params=(category_base, None, None, category, None, 'CATEGORY', None), commit=True
                    )
                    if not ok:
                        return False, msg
                    category_base += 1

            for product in products:
                category = product.get('CATEGORY') or 'Uncategorized'
                parent_id = category_map.get(category)
                ok, msg = self.execute_query(
                    "INSERT INTO Product_Dim (product_dim_id, product_id, product_name, category, supplier, level_name, parent_dim_id) VALUES (:1, :2, :3, :4, :5, :6, :7)",
                    params=(product['PRODUCT_ID'], product['PRODUCT_ID'], product['PRODUCT_NAME'], product['CATEGORY'], product['SUPPLIER'], 'PRODUCT', parent_id), commit=True
                )
                if not ok:
                    return False, msg

            ok, locations = self.fetch_all("SELECT location_id, location_name, city, country, warehouse_type FROM Location")
            if not ok:
                return False, locations

            country_map = {}
            city_map = {}
            country_base = 2000
            city_base = 2100
            for location in locations:
                country = location.get('COUNTRY') or 'Unknown'
                city = location.get('CITY') or 'Unknown'

                if country not in country_map:
                    country_map[country] = country_base
                    ok, msg = self.execute_query(
                        "INSERT INTO Location_Dim (location_dim_id, location_id, location_name, city, country, warehouse_type, level_name, parent_dim_id) VALUES (:1, :2, :3, :4, :5, :6, :7, :8)",
                        params=(country_base, None, country, None, country, None, 'COUNTRY', None), commit=True
                    )
                    if not ok:
                        return False, msg
                    country_base += 1

                if city not in city_map:
                    city_map[city] = city_base
                    ok, msg = self.execute_query(
                        "INSERT INTO Location_Dim (location_dim_id, location_id, location_name, city, country, warehouse_type, level_name, parent_dim_id) VALUES (:1, :2, :3, :4, :5, :6, :7, :8)",
                        params=(city_base, None, city, city, country, None, 'CITY', country_map[country]), commit=True
                    )
                    if not ok:
                        return False, msg
                    city_base += 1

            for location in locations:
                city = location.get('CITY') or 'Unknown'
                parent_id = city_map.get(city)
                ok, msg = self.execute_query(
                    "INSERT INTO Location_Dim (location_dim_id, location_id, location_name, city, country, warehouse_type, level_name, parent_dim_id) VALUES (:1, :2, :3, :4, :5, :6, :7, :8)",
                    params=(location['LOCATION_ID'], location['LOCATION_ID'], location['LOCATION_NAME'], location['CITY'], location['COUNTRY'], location['WAREHOUSE_TYPE'], 'FACILITY', parent_id), commit=True
                )
                if not ok:
                    return False, msg

            ok, msg = self.execute_query(
                "INSERT INTO Sales_Fact (sales_fact_id, sales_id, product_id, product_dim_id, location_id, location_dim_id, quantity, unit_price, total_amount, sales_date) "
                "SELECT sales_id, sales_id, product_id, product_id, location_id, location_id, quantity, unit_price, total_amount, sales_date FROM Sales",
                commit=True
            )
            if not ok:
                return False, msg

            index_statements = [
                "CREATE INDEX idx_sales_fact_product_dim ON Sales_Fact(product_dim_id)",
                "CREATE INDEX idx_sales_fact_location_dim ON Sales_Fact(location_dim_id)",
                "CREATE INDEX idx_product_dim_category ON Product_Dim(category)",
                "CREATE INDEX idx_location_dim_city ON Location_Dim(city)"
            ]
            for sql in index_statements:
                self.execute_query(sql, commit=True)

            return True, "Phase 3 dimension tables and star-schema fact data populated"
        except Exception as e:
            print(f"✗ Error populating phase 3 dimensions: {e}")
            traceback.print_exc()
            return False, str(e)

    def create_phase3_dimensions(self):
        try:
            if not self.ensure_connection():
                return False, "Failed to connect to database"

            success, tables_status = self.check_tables_exist()
            if not success or not all(tables_status.values()):
                return False, "Base tables are missing. Initialize the database before creating Phase 3 dimensions."

            cleanup = [
                "BEGIN EXECUTE IMMEDIATE 'DROP TABLE Sales_Fact'; EXCEPTION WHEN OTHERS THEN NULL; END;",
                "BEGIN EXECUTE IMMEDIATE 'DROP TABLE Product_Dim'; EXCEPTION WHEN OTHERS THEN NULL; END;",
                "BEGIN EXECUTE IMMEDIATE 'DROP TABLE Location_Dim'; EXCEPTION WHEN OTHERS THEN NULL; END;"
            ]
            for sql in cleanup:
                self.execute_query(sql, commit=True)

            create_statements = [
                ("""
                CREATE TABLE Product_Dim (
                    product_dim_id NUMBER PRIMARY KEY,
                    product_id NUMBER,
                    product_name VARCHAR2(100),
                    category VARCHAR2(50),
                    supplier VARCHAR2(100),
                    level_name VARCHAR2(50),
                    parent_dim_id NUMBER,
                    FOREIGN KEY (parent_dim_id) REFERENCES Product_Dim(product_dim_id)
                )
                """, "Product_Dim"),
                ("""
                CREATE TABLE Location_Dim (
                    location_dim_id NUMBER PRIMARY KEY,
                    location_id NUMBER,
                    location_name VARCHAR2(100),
                    city VARCHAR2(50),
                    country VARCHAR2(50),
                    warehouse_type VARCHAR2(50),
                    level_name VARCHAR2(50),
                    parent_dim_id NUMBER,
                    FOREIGN KEY (parent_dim_id) REFERENCES Location_Dim(location_dim_id)
                )
                """, "Location_Dim"),
                ("""
                CREATE TABLE Sales_Fact (
                    sales_fact_id NUMBER PRIMARY KEY,
                    sales_id NUMBER,
                    product_id NUMBER,
                    product_dim_id NUMBER,
                    location_id NUMBER,
                    location_dim_id NUMBER,
                    quantity NUMBER,
                    unit_price BINARY_DOUBLE,
                    total_amount BINARY_DOUBLE,
                    sales_date DATE
                )
                """, "Sales_Fact")
            ]

            for sql, name in create_statements:
                ok, msg = self.execute_query(sql, commit=True)
                if not ok:
                    raise Exception(f"Failed to create table {name}: {msg}")

            dimension_ok, dimension_msg = self.create_oracle_dimension_objects()
            populate_ok, populate_msg = self.populate_phase3_dimensions()
            if not populate_ok:
                return False, populate_msg

            if not dimension_ok:
                return False, f"Oracle dimension creation failed: {dimension_msg}"

            return True, "Phase 3 dimensions created successfully"
        except Exception as e:
            print(f"✗ Error creating phase 3 dimensions: {e}")
            traceback.print_exc()
            return False, str(e)

    def phase3_dimensions_exist(self):
        try:
            if not self.ensure_connection():
                return False, {}

            tables = ['Product_Dim', 'Location_Dim', 'Sales_Fact']
            status = {}
            for t in tables:
                ok, res = self.fetch_all(f"SELECT COUNT(*) AS CNT FROM {t}")
                status[t] = ok and isinstance(res, list)
            return True, status
        except Exception as e:
            print(f"✗ Error checking phase 3 dimensions: {e}")
            traceback.print_exc()
            return False, {}

    def get_sales_per_product_by_location_phase3(self):
        start_time = time.time()
        try:
            if not self.ensure_connection():
                return False, "Failed to connect to database", 0.0

            query = """
                SELECT
                    pd.product_name,
                    ld.location_name,
                    COUNT(sf.sales_fact_id) AS sales_count,
                    SUM(sf.quantity) AS total_quantity_sold,
                    SUM(sf.total_amount) AS total_revenue
                FROM Product_Dim pd
                LEFT JOIN Sales_Fact sf ON pd.product_dim_id = sf.product_dim_id
                LEFT JOIN Location_Dim ld ON sf.location_dim_id = ld.location_dim_id AND ld.level_name = 'FACILITY'
                WHERE pd.level_name = 'PRODUCT'
                GROUP BY pd.product_name, ld.location_name, pd.product_dim_id, ld.location_dim_id
                ORDER BY pd.product_name, ld.location_name
            """

            success, result = self.fetch_all(query)
            execution_time = time.time() - start_time
            return (True, result, execution_time) if success else (False, result, execution_time)
        except Exception as e:
            execution_time = time.time() - start_time
            err = str(e)
            print(f"✗ Error in phase 3 sales per product by location: {err}")
            traceback.print_exc()
            if self._is_protocol_error(e):
                if self.force_new_connection():
                    return False, f"Protocol error occurred; pool recreated: {err}", execution_time
            return False, err, execution_time

    def get_max_sales_per_product_by_location_phase3(self):
        start_time = time.time()
        try:
            if not self.ensure_connection():
                return False, "Failed to connect to database", 0.0

            query = """
                SELECT
                    pd.product_name,
                    ld.location_name,
                    MAX(sf.quantity) AS max_quantity_sold,
                    AVG(sf.quantity) AS avg_quantity_sold,
                    COUNT(sf.sales_fact_id) AS number_of_sales
                FROM Product_Dim pd
                LEFT JOIN Sales_Fact sf ON pd.product_dim_id = sf.product_dim_id
                LEFT JOIN Location_Dim ld ON sf.location_dim_id = ld.location_dim_id AND ld.level_name = 'FACILITY'
                WHERE pd.level_name = 'PRODUCT'
                GROUP BY pd.product_name, ld.location_name, pd.product_dim_id, ld.location_dim_id
                ORDER BY pd.product_name, ld.location_name
            """

            success, result = self.fetch_all(query)
            execution_time = time.time() - start_time
            return (True, result, execution_time) if success else (False, result, execution_time)
        except Exception as e:
            execution_time = time.time() - start_time
            err = str(e)
            print(f"✗ Error in phase 3 max sales per product by location: {err}")
            traceback.print_exc()
            if self._is_protocol_error(e):
                if self.force_new_connection():
                    return False, f"Protocol error occurred; pool recreated: {err}", execution_time
            return False, err, execution_time

    def create_sales_data_mart(self):
        """Create the Sales Data Mart table with pre-aggregated sales data"""
        try:
            if not self.ensure_connection():
                return False, "Failed to connect to database"

            # Drop existing table and sequence if they exist
            try:
                self.execute_query("DROP TABLE Sales_Data_Mart CASCADE CONSTRAINTS", commit=True)
            except:
                pass  # Ignore if doesn't exist

            create_query = """
                CREATE TABLE Sales_Data_Mart (
                    mart_id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                    product_name VARCHAR2(100),
                    location_name VARCHAR2(100),
                    total_sales_count NUMBER,
                    total_quantity NUMBER,
                    total_revenue NUMBER(10,2),
                    max_quantity NUMBER,
                    avg_quantity NUMBER(10,2),
                    last_updated DATE DEFAULT SYSDATE
                )
            """
            success, msg = self.execute_query(create_query)
            if not success:
                return False, msg

            return True, "Sales Data Mart created successfully"
        except Exception as e:
            err = str(e)
            print(f"✗ Error creating Sales Data Mart: {err}")
            return False, err

    def populate_sales_data_mart(self):
        """Populate the Sales Data Mart with aggregated data from Sales_Fact"""
        try:
            if not self.ensure_connection():
                return False, "Failed to connect to database"

            # Clear existing data
            self.execute_query("DELETE FROM Sales_Data_Mart", commit=True)

            # Insert aggregated data
            insert_query = """
                INSERT INTO Sales_Data_Mart (product_name, location_name, total_sales_count, total_quantity, total_revenue, max_quantity, avg_quantity)
                SELECT 
                    pd.product_name,
                    ld.location_name,
                    COUNT(sf.sales_fact_id) AS total_sales_count,
                    SUM(sf.quantity) AS total_quantity,
                    SUM(sf.total_amount) AS total_revenue,
                    MAX(sf.quantity) AS max_quantity,
                    ROUND(AVG(sf.quantity), 2) AS avg_quantity
                FROM Product_Dim pd
                LEFT JOIN Sales_Fact sf ON pd.product_dim_id = sf.product_dim_id
                LEFT JOIN Location_Dim ld ON sf.location_dim_id = ld.location_dim_id AND ld.level_name = 'FACILITY'
                WHERE pd.level_name = 'PRODUCT'
                GROUP BY pd.product_name, ld.location_name
                ORDER BY pd.product_name, ld.location_name
            """
            success, msg = self.execute_query(insert_query)
            if not success:
                return False, msg

            return True, "Sales Data Mart populated successfully"
        except Exception as e:
            err = str(e)
            print(f"✗ Error populating Sales Data Mart: {err}")
            return False, err

    def get_sales_per_product_by_location_phase4(self):
        """Get sales per product by location from Data Mart (ultra-fast)"""
        start_time = time.time()
        try:
            if not self.ensure_connection():
                return False, "Failed to connect to database", 0.0

            query = """
                SELECT 
                    product_name,
                    location_name,
                    total_sales_count AS sales_count,
                    total_quantity AS total_quantity_sold,
                    total_revenue AS total_revenue
                FROM Sales_Data_Mart
                ORDER BY product_name, location_name
            """

            success, result = self.fetch_all(query)
            execution_time = time.time() - start_time
            return (True, result, execution_time) if success else (False, result, execution_time)
        except Exception as e:
            execution_time = time.time() - start_time
            err = str(e)
            print(f"✗ Error in phase 4 sales per product by location: {err}")
            traceback.print_exc()
            return False, err, execution_time

    def get_max_sales_per_product_by_location_phase4(self):
        """Get max sales per product by location from Data Mart (ultra-fast)"""
        start_time = time.time()
        try:
            if not self.ensure_connection():
                return False, "Failed to connect to database", 0.0

            query = """
                SELECT 
                    product_name,
                    location_name,
                    max_quantity AS max_quantity_sold,
                    avg_quantity AS avg_quantity_sold,
                    total_sales_count AS number_of_sales
                FROM Sales_Data_Mart
                ORDER BY product_name, location_name
            """

            success, result = self.fetch_all(query)
            execution_time = time.time() - start_time
            return (True, result, execution_time) if success else (False, result, execution_time)
        except Exception as e:
            execution_time = time.time() - start_time
            err = str(e)
            print(f"✗ Error in phase 4 max sales per product by location: {err}")
            traceback.print_exc()
            return False, err, execution_time
