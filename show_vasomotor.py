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

print('\n' + '=' * 90)
print('TABLE STRUCTURE: vasomotor_logs')
print('=' * 90 + '\n')

cursor.execute('DESCRIBE vasomotor_logs;')
columns = cursor.fetchall()

print(f'{"Column Name":<28} {"Type":<30} {"Null":<6} {"Key":<6} {"Default"}')
print('-' * 90)
for col in columns:
    field = col.get('Field', '')
    type_ = col.get('Type', '')
    null = col.get('Null', '')
    key = col.get('Key', '')
    default = str(col.get('Default')) if col.get('Default') is not None else 'NULL'
    print(f'{field:<28} {type_:<30} {null:<6} {key:<6} {default}')

# Row count
cursor.execute('SELECT COUNT(*) as count FROM vasomotor_logs;')
total = cursor.fetchone()['count']

print('\n' + '=' * 90)
print(f'DATA ROWS: {total}')
print('=' * 90 + '\n')

cursor.execute('SELECT * FROM vasomotor_logs ORDER BY id DESC LIMIT 20;')
rows = cursor.fetchall()

if not rows:
    print('(no rows - table is empty)')
else:
    for row in rows:
        print(row)

conn.close()
print()
