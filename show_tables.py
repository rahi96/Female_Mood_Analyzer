import pymysql
from pymysql.cursors import DictCursor

conn = pymysql.connect(
    host='mysql-database.cc98ouaycdke.us-east-1.rds.amazonaws.com',
    port=3306,
    user='pulse',
    password='Pul$e2026_mysql',
    database='pulse_mysql',
    cursorclass=DictCursor
)

cursor = conn.cursor()
cursor.execute('SHOW TABLES;')
tables = cursor.fetchall()

print('\n' + '=' * 80)
print('DATABASE TABLES IN pulse_mysql')
print('=' * 80 + '\n')

for i, table in enumerate(tables, 1):
    table_name = table['Tables_in_pulse_mysql']
    
    # Get row count for each table
    cursor.execute(f'SELECT COUNT(*) as count FROM {table_name};')
    row_count = cursor.fetchone()['count']
    
    # Get column info
    cursor.execute(f'DESCRIBE {table_name};')
    columns = cursor.fetchall()
    col_count = len(columns)
    
    print(f'{i}. {table_name:<35} | Columns: {col_count:<3} | Rows: {row_count:>6}')

print('\n' + '=' * 80)
cursor.execute('SELECT COUNT(*) as count FROM information_schema.TABLES WHERE TABLE_SCHEMA = "pulse_mysql"')
total = cursor.fetchone()['count']
print(f'Total Tables: {total}')
print('=' * 80 + '\n')

conn.close()
