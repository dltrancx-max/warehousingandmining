import oracledb, traceback
from backend.config import DB_CONFIG
cn=None
try:
    cn=oracledb.connect(user=DB_CONFIG['user'], password=DB_CONFIG['password'], host=DB_CONFIG['host'], port=DB_CONFIG['port'], service_name=DB_CONFIG['service_name'])
    cur=cn.cursor()
    cur.execute("select table_name from user_tables where table_name in ('CUSTOMER','LOCATION','PRODUCT','SALES')")
    rows=[r[0] for r in cur.fetchall()]
    print('FOUND:', rows)
except Exception:
    traceback.print_exc()
finally:
    if cn:
        cn.close()
