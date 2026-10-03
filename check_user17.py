import pymysql
from pymysql.cursors import DictCursor
import sys

USER_ID = int(sys.argv[1]) if len(sys.argv) > 1 else 17

conn = pymysql.connect(
    host='mysql-database.cc98ouaycdke.us-east-1.rds.amazonaws.com',
    port=3306,
    user='pulse',
    password='Pul$e2026_mysql',
    database='pulse_mysql',
    cursorclass=DictCursor
)

cursor = conn.cursor()

tables_to_check = [
    'users',
    'profiles',
    'menstrual_cycles',
    'period_logs',
    'vasomotor_logs',
    'gsm_checkin_logs',
    'menopause_symptom_insights',
    'perimenopause_profiles',
    'symptom_logs',
    'health_logs',
    'health_trends',
    'hormone_snapshots',
    'skin_scans',
    'terra_activity_data',
    'athlete_performances',
    'vitality_snapshots',
    'chat_messages',
    'lab_reports',
    'cycle_daily_logs',
]

print('\n' + '=' * 70)
print(f'DATA AVAILABILITY FOR USER_ID = {USER_ID}')
print('=' * 70 + '\n')
print(f'{"Table":<34} {"Rows":<8} {"Status"}')
print('-' * 70)

for table in tables_to_check:
    try:
        if table == 'users':
            cursor.execute(f'SELECT COUNT(*) as count FROM {table} WHERE id = %s;', (USER_ID,))
        else:
            cursor.execute(f'SELECT COUNT(*) as count FROM {table} WHERE user_id = %s;', (USER_ID,))
        count = cursor.fetchone()['count']
        status = 'HAS DATA' if count > 0 else 'empty'
        marker = '[+]' if count > 0 else '[ ]'
        print(f'{marker} {table:<30} {count:<8} {status}')
    except Exception as e:
        print(f'[!] {table:<30} {"N/A":<8} error: {str(e)[:30]}')

# Show details for perimenopause-relevant tables
print('\n' + '=' * 70)
print('PERIMENOPAUSE-RELEVANT DETAILS')
print('=' * 70 + '\n')

# User info
cursor.execute('SELECT id, full_name, email, user_type FROM users WHERE id = %s;', (USER_ID,))
user = cursor.fetchone()
print('USER:', user)

# Menstrual cycles
cursor.execute('SELECT id, period_start_date, period_end_date, cycle_length, current_phase, is_completed FROM menstrual_cycles WHERE user_id = %s ORDER BY period_start_date DESC LIMIT 5;', (USER_ID,))
cycles = cursor.fetchall()
print(f'\nMENSTRUAL_CYCLES (last 5 of {len(cycles)} shown):')
for c in cycles:
    print('  ', c)

# Period logs
cursor.execute('SELECT COUNT(*) as c, MIN(created_at) as first, MAX(created_at) as last FROM period_logs WHERE user_id = %s;', (USER_ID,))
print('\nPERIOD_LOGS summary:', cursor.fetchone())

conn.close()
print('\n' + '=' * 70 + '\n')
