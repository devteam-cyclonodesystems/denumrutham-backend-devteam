import os
import sys
import sqlite3
import subprocess

def run_migration_replay():
    print("=== STARTING MIGRATION DRY-RUN REPLAY ===")
    
    # 1. Define temp DB path
    temp_db_name = os.path.abspath("tms_replay_temp.db")
    if os.path.exists(temp_db_name):
        print(f"Removing old temp database: {temp_db_name}")
        os.remove(temp_db_name)

    # 2. Pre-create legacy tables in sqlite
    print("Pre-initializing legacy schema tables...")
    conn = sqlite3.connect(temp_db_name)
    cursor = conn.cursor()
    legacy_tables = [
        "CREATE TABLE users (id CHAR(36) PRIMARY KEY, temple_id CHAR(36), user_id VARCHAR, password_hash VARCHAR, role VARCHAR)",
        "CREATE TABLE temples (id CHAR(36) PRIMARY KEY, name VARCHAR, domain VARCHAR, location VARCHAR, state VARCHAR, address_line_1 VARCHAR, address_line_2 VARCHAR, district VARCHAR, pincode VARCHAR, contact_number VARCHAR, alternate_contact VARCHAR, email VARCHAR, description TEXT, status VARCHAR, operational_state VARCHAR)",
        "CREATE TABLE audit_logs (id CHAR(36) PRIMARY KEY)",
        "CREATE TABLE employees (id CHAR(36) PRIMARY KEY, temple_id CHAR(36))",
        "CREATE TABLE halls (id CHAR(36) PRIMARY KEY, temple_id CHAR(36))",
        "CREATE TABLE inventory_items (id CHAR(36) PRIMARY KEY, temple_id CHAR(36))",
        "CREATE TABLE payments (id CHAR(36) PRIMARY KEY)",
        "CREATE TABLE user_temples (id CHAR(36) PRIMARY KEY, user_id CHAR(36), temple_id CHAR(36))",
        "CREATE TABLE temple_services (id CHAR(36) PRIMARY KEY, temple_id CHAR(36))",
        "CREATE TABLE devotees (id CHAR(36) PRIMARY KEY)",
        "CREATE TABLE poojas (id CHAR(36) PRIMARY KEY, temple_id CHAR(36))",
        "CREATE TABLE events (id CHAR(36) PRIMARY KEY, temple_id CHAR(36))",
        "CREATE TABLE tickets (id CHAR(36) PRIMARY KEY, temple_id CHAR(36))",
        "CREATE TABLE temple_profiles (id CHAR(36) PRIMARY KEY, temple_id CHAR(36))",
        "CREATE TABLE temple_images (id CHAR(36) PRIMARY KEY, temple_id CHAR(36))",
        "CREATE TABLE transactions (id CHAR(36) PRIMARY KEY, temple_id CHAR(36))",
        "CREATE TABLE archana_bookings (id CHAR(36) PRIMARY KEY, temple_id CHAR(36))",
        "CREATE TABLE suppliers (id CHAR(36) PRIMARY KEY, temple_id CHAR(36))",
        "CREATE TABLE inventory_invoices (id CHAR(36) PRIMARY KEY, temple_id CHAR(36))",
        "CREATE TABLE inventory_item_requests (id CHAR(36) PRIMARY KEY, temple_id CHAR(36))",
        "CREATE TABLE roles (id CHAR(36) PRIMARY KEY, temple_id CHAR(36), name VARCHAR, description TEXT, created_at TIMESTAMP)",
        "CREATE TABLE permissions (id CHAR(36) PRIMARY KEY, temple_id CHAR(36), resource_type VARCHAR, resource_key VARCHAR, description TEXT, created_at TIMESTAMP)",
        "CREATE TABLE role_permissions (id CHAR(36) PRIMARY KEY, role_id CHAR(36), permission_id CHAR(36), access_level VARCHAR, created_at TIMESTAMP)",
        "CREATE TABLE pooja_slots (id CHAR(36) PRIMARY KEY, temple_id CHAR(36))",
        "CREATE TABLE bookings (id CHAR(36) PRIMARY KEY, temple_id CHAR(36))",
        "CREATE TABLE donations (id CHAR(36) PRIMARY KEY, temple_id CHAR(36))",
        "CREATE TABLE service_bookings (id CHAR(36) PRIMARY KEY, temple_id CHAR(36))",
        "CREATE TABLE hall_bookings (id CHAR(36) PRIMARY KEY, temple_id CHAR(36))",
        "CREATE TABLE leaves (id CHAR(36) PRIMARY KEY, temple_id CHAR(36))",
        "CREATE TABLE user_roles (id CHAR(36) PRIMARY KEY)",
        "CREATE TABLE inventory_movements (id CHAR(36) PRIMARY KEY, temple_id CHAR(36))",
        "CREATE TABLE inventory_transactions (id CHAR(36) PRIMARY KEY, temple_id CHAR(36))",
        "CREATE TABLE enterprise_archana_bookings (id CHAR(36) PRIMARY KEY, temple_id CHAR(36), ref_id VARCHAR, primary_devotee_id CHAR(36), primary_devotee_name VARCHAR, phone_number VARCHAR, email VARCHAR, whatsapp_consent BOOLEAN, booking_date DATETIME, ritual_time DATETIME, priority_slot BOOLEAN, total_amount FLOAT, dakshina FLOAT, delivery_charge FLOAT, grand_total FLOAT, payment_mode VARCHAR, booking_mode VARCHAR, prasadam_collection VARCHAR, status VARCHAR, remarks TEXT, created_by CHAR(36), assigned_priest_id CHAR(36), created_at DATETIME, updated_at DATETIME)",
        "CREATE TABLE archana_refunds (id CHAR(36) PRIMARY KEY, temple_id CHAR(36), ref_id VARCHAR, booking_id CHAR(36), refund_method VARCHAR, refund_status VARCHAR, status VARCHAR, amount FLOAT, reason TEXT, created_by CHAR(36), approved_by CHAR(36), created_at DATETIME, updated_at DATETIME)",
        "CREATE TABLE archana_booking_members (id CHAR(36) PRIMARY KEY, booking_id CHAR(36), name VARCHAR, nakshatra VARCHAR, is_primary BOOLEAN)",
        "CREATE TABLE archana_booking_items (id CHAR(36) PRIMARY KEY, member_id CHAR(36), service_id CHAR(36), quantity INTEGER, price_at_booking FLOAT, total_price FLOAT)",
        "CREATE TABLE archana_catalog (id CHAR(36) PRIMARY KEY, temple_id CHAR(36), name VARCHAR, price FLOAT, description TEXT, remarks TEXT, is_active BOOLEAN, daily_limit INTEGER, malayalam_name VARCHAR, category VARCHAR)",
        "CREATE TABLE archana_booking_payments (id CHAR(36) PRIMARY KEY, booking_id CHAR(36), amount FLOAT, payment_mode VARCHAR, transaction_ref VARCHAR, status VARCHAR, created_at DATETIME)",
        "CREATE TABLE ritual_queue (id CHAR(36) PRIMARY KEY, temple_id CHAR(36), booking_id CHAR(36), token_number VARCHAR, status VARCHAR, priest_id CHAR(36), priority INTEGER, estimated_start_time DATETIME, actual_start_time DATETIME, completed_at DATETIME)",
        "CREATE TABLE archana_booking_audit (id CHAR(36) PRIMARY KEY, booking_id CHAR(36), action VARCHAR, actor_id CHAR(36), old_state JSON, new_state JSON, timestamp DATETIME)",
        "CREATE TABLE devotee_profiles (id CHAR(36) PRIMARY KEY, user_id CHAR(36), name VARCHAR, nakshatra VARCHAR, gothram VARCHAR, address TEXT, created_at DATETIME)",
        "CREATE TABLE archana_sync_state (id CHAR(36) PRIMARY KEY, entity_id CHAR(36), entity_type VARCHAR, last_synced_at DATETIME, sync_status VARCHAR, version INTEGER)",
        "CREATE TABLE security_audit_events (id CHAR(36) PRIMARY KEY, temple_id CHAR(36), user_id CHAR(36), event_type VARCHAR, severity VARCHAR, ip_address VARCHAR, user_agent VARCHAR, details JSON, admin_metadata JSON, created_at DATETIME)",
        "CREATE TABLE archana_catalog_versions (id CHAR(36) PRIMARY KEY, catalog_id CHAR(36), version INTEGER, price FLOAT, metadata_snapshot JSON, effective_from DATETIME, effective_to DATETIME, created_by CHAR(36))"
    ]
    for table_sql in legacy_tables:
        cursor.execute(table_sql)
    conn.commit()
    conn.close()
    print("Legacy tables created.")

    # 3. Set environment variables
    db_url_path = temp_db_name.replace("\\", "/")
    os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{db_url_path}"
    os.environ["ENVIRONMENT"] = "testing"
    
    # 4. Run Alembic Upgrade to HEAD
    print("Executing migrations: base -> head...")
    try:
        res = subprocess.run(
            ["python", "-m", "alembic", "upgrade", "head"],
            cwd="backend" if os.path.exists("backend") else ".",
            capture_output=True,
            text=True,
            check=True
        )
        print("Migrations successfully applied!")
        print(res.stdout)
    except subprocess.CalledProcessError as e:
        print("Migration upgrade FAILED!", file=sys.stderr)
        print(e.stderr, file=sys.stderr)
        sys.exit(1)

    # 5. Run Sprint 4 Smoke Tests against the newly-migrated DB
    print("Executing smoke tests against migrated schema...")
    try:
        res_test = subprocess.run(
            ["python", "-m", "pytest", "tests/test_sprint4_requirements.py"],
            cwd="backend" if os.path.exists("backend") else ".",
            capture_output=True,
            text=True,
            check=True
        )
        print("Smoke tests passed successfully against replayed database!")
        print(res_test.stdout)
    except subprocess.CalledProcessError as e:
        print("Smoke tests failed!", file=sys.stderr)
        print(e.stderr, file=sys.stderr)
        sys.exit(1)

    # Clean up
    if os.path.exists(temp_db_name):
        os.remove(temp_db_name)
    print("=== MIGRATION DRY-RUN REPLAY COMPLETED SUCCESSFULLY ===")

if __name__ == "__main__":
    run_migration_replay()
