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

# Key tables for Beauty API and other services
key_tables = [
    'skin_scans',
    'menstrual_cycles',
    'terra_activity_data',
    'health_logs',
    'users',
    'profiles',
    'athlete_performances',
    'chat_messages',
    'lab_reports',
    'vitality_snapshots'
]

for table_name in key_tables:
    print(f'\n{"="*100}')
    print(f'TABLE: {table_name.upper()}')
    print(f'{"="*100}')
    
    # Get column info
    cursor.execute(f'DESCRIBE {table_name};')
    columns = cursor.fetchall()
    
    # Get row count
    cursor.execute(f'SELECT COUNT(*) as count FROM {table_name};')
    row_count = cursor.fetchone()['count']
    
    print(f'\nRows: {row_count:<6} | Columns: {len(columns)}\n')
    print(f'{"Column Name":<30} {"Type":<25} {"Null":<6} {"Key":<6} {"Default":<15}')
    print('-' * 100)
    
    for col in columns:
        field = col.get('Field', '')
        type_ = col.get('Type', '')
        null = col.get('Null', '')
        key = col.get('Key', '')
        default = str(col.get('Default', '')) if col.get('Default') is not None else 'NULL'
        
        print(f'{field:<30} {type_:<25} {null:<6} {key:<6} {default:<15}')

conn.close()
