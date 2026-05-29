import asyncio
import httpx
import uuid
import sys
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from passlib.context import CryptContext

# Ensure console printing handles utf-8 characters properly
if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')
if hasattr(sys.stderr, 'reconfigure'):
    sys.stderr.reconfigure(encoding='utf-8')

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def get_password_hash(password: str) -> str:
    return pwd_context.hash(password)

async def run():
    db_url = "postgresql+asyncpg://neondb_owner:npg_R3hWbAYn0tuI@ep-proud-shadow-aom9gssv-pooler.c-2.ap-southeast-1.aws.neon.tech/neondb"
    engine = create_async_engine(db_url, connect_args={"ssl": True})
    
    api_base = "https://denumrutham-backend-production.up.railway.app/api/v1"
    temple_id = "b400aa3d-ecd3-4ed9-b6f6-2572bc59d069" # Demo Temple ID from database
    execution_id = "c1ea5a14-ef2a-4e9b-9e81-f0580f88816c" # WAITING execution ID from production log evidence
    
    priest_email = "prod_test_priest@demotemple.org"
    counter_email = "prod_test_counter@demotemple.org"
    test_password = "TestPassword@123"
    password_hash = get_password_hash(test_password)
    
    priest_user_id = None
    counter_user_id = None
    priest_role_id = None
    counter_role_id = None
    
    async with engine.connect() as conn:
        try:
            print("1. Seeding roles and permissions in database...")
            # Ensure permissions are seeded
            res_perm = await conn.execute(text("SELECT id FROM permissions WHERE resource_key = 'archana:start_ritual'"))
            start_perm_row = res_perm.fetchone()
            if not start_perm_row:
                # Create permission
                await conn.execute(text("""
                    INSERT INTO permissions (id, resource_type, resource_key, description, temple_id)
                    VALUES (gen_random_uuid(), 'feature', 'archana:start_ritual', 'Start Ritual', NULL);
                """))
            res_perm2 = await conn.execute(text("SELECT id FROM permissions WHERE resource_key = 'archana:complete_ritual'"))
            comp_perm_row = res_perm2.fetchone()
            if not comp_perm_row:
                await conn.execute(text("""
                    INSERT INTO permissions (id, resource_type, resource_key, description, temple_id)
                    VALUES (gen_random_uuid(), 'feature', 'archana:complete_ritual', 'Complete Ritual', NULL);
                """))
            
            # Fetch permission IDs
            start_perm_id = (await conn.execute(text("SELECT id FROM permissions WHERE resource_key = 'archana:start_ritual'"))).scalar()
            comp_perm_id = (await conn.execute(text("SELECT id FROM permissions WHERE resource_key = 'archana:complete_ritual'"))).scalar()
            view_queue_perm_id = (await conn.execute(text("SELECT id FROM permissions WHERE resource_key = 'archana:view_queue'"))).scalar()
            if not view_queue_perm_id:
                await conn.execute(text("""
                    INSERT INTO permissions (id, resource_type, resource_key, description, temple_id)
                    VALUES (gen_random_uuid(), 'feature', 'archana:view_queue', 'View Queue', NULL);
                """))
                view_queue_perm_id = (await conn.execute(text("SELECT id FROM permissions WHERE resource_key = 'archana:view_queue'"))).scalar()

            # Ensure roles exist
            res_role = await conn.execute(text(f"SELECT id FROM roles WHERE name = 'Test Priest' AND temple_id = '{temple_id}'"))
            priest_role_id = res_role.scalar()
            if not priest_role_id:
                priest_role_id = uuid.uuid4()
                await conn.execute(text(f"""
                    INSERT INTO roles (id, name, description, temple_id, is_active)
                    VALUES ('{priest_role_id}', 'Test Priest', 'Test Priest Role', '{temple_id}', true);
                """))
            
            res_role_c = await conn.execute(text(f"SELECT id FROM roles WHERE name = 'Test Counter Staff' AND temple_id = '{temple_id}'"))
            counter_role_id = res_role_c.scalar()
            if not counter_role_id:
                counter_role_id = uuid.uuid4()
                await conn.execute(text(f"""
                    INSERT INTO roles (id, name, description, temple_id, is_active)
                    VALUES ('{counter_role_id}', 'Test Counter Staff', 'Test Counter Staff Role', '{temple_id}', true);
                """))
            
            # Map permissions to roles
            await conn.execute(text(f"DELETE FROM role_permissions WHERE role_id IN ('{priest_role_id}', '{counter_role_id}')"))
            # Priest has start_ritual, complete_ritual, view_queue
            await conn.execute(text(f"""
                INSERT INTO role_permissions (id, role_id, permission_id, access_level)
                VALUES (gen_random_uuid(), '{priest_role_id}', '{start_perm_id}', 'full'),
                       (gen_random_uuid(), '{priest_role_id}', '{comp_perm_id}', 'full'),
                       (gen_random_uuid(), '{priest_role_id}', '{view_queue_perm_id}', 'full');
            """))
            # Counter staff has only view_queue
            await conn.execute(text(f"""
                INSERT INTO role_permissions (id, role_id, permission_id, access_level)
                VALUES (gen_random_uuid(), '{counter_role_id}', '{view_queue_perm_id}', 'full');
            """))

            # Create test users (with is_active = true)
            # Find and clean up any pre-existing rows from partial runs
            res_user = await conn.execute(text(f"SELECT id FROM users WHERE email = '{priest_email}'"))
            priest_user_id = res_user.scalar()
            res_user_c = await conn.execute(text(f"SELECT id FROM users WHERE email = '{counter_email}'"))
            counter_user_id = res_user_c.scalar()
            
            if priest_user_id or counter_user_id:
                ids = [str(i) for i in [priest_user_id, counter_user_id] if i is not None]
                ids_str = ", ".join([f"'{i}'" for i in ids])
                await conn.execute(text(f"DELETE FROM archana_booking_audit WHERE actor_id IN ({ids_str})"))
                await conn.execute(text(f"DELETE FROM user_roles WHERE user_id IN ({ids_str})"))
                await conn.execute(text(f"DELETE FROM users WHERE id IN ({ids_str})"))
            
            priest_user_id = uuid.uuid4()
            await conn.execute(text(f"""
                INSERT INTO users (id, user_id, email, password_hash, role, status, approval_status, temple_id, name, onboarding_method, is_active)
                VALUES ('{priest_user_id}', '{priest_email}', '{priest_email}', '{password_hash}', 'STAFF', 'ACTIVE', 'APPROVED', '{temple_id}', 'Test Priest User', 'ADMIN_CREATED', true);
            """))
            counter_user_id = uuid.uuid4()
            await conn.execute(text(f"""
                INSERT INTO users (id, user_id, email, password_hash, role, status, approval_status, temple_id, name, onboarding_method, is_active)
                VALUES ('{counter_user_id}', '{counter_email}', '{counter_email}', '{password_hash}', 'STAFF', 'ACTIVE', 'APPROVED', '{temple_id}', 'Test Counter Staff User', 'ADMIN_CREATED', true);
            """))

            # Map users to roles
            await conn.execute(text(f"""
                INSERT INTO user_roles (id, user_id, role_id, temple_id)
                VALUES (gen_random_uuid(), '{priest_user_id}', '{priest_role_id}', '{temple_id}'),
                       (gen_random_uuid(), '{counter_user_id}', '{counter_role_id}', '{temple_id}');
            """))
            
            # Reset execution record state to WAITING
            await conn.execute(text(f"""
                UPDATE archana_executions 
                SET status = 'WAITING', priest_id = NULL, started_by_user_id = NULL, completed_by_user_id = NULL, start_time = NULL, completed_at = NULL 
                WHERE id = '{execution_id}'
            """))
            
            await conn.commit()
            print("Database setup completed successfully.")
            
        except Exception as e:
            await conn.rollback()
            print("DB Setup failed:", str(e))
            return
            
    # Run REST API requests against the production API
    async with httpx.AsyncClient() as client:
        try:
            print("\n2. Logging in as Priest...")
            login_resp = await client.post(
                f"{api_base}/auth/login",
                data={"username": priest_email, "password": test_password}
            )
            assert login_resp.status_code == 200, f"Priest login failed: {login_resp.text}"
            priest_token = login_resp.json()["data"]["access_token"]
            priest_headers = {
                "Authorization": f"Bearer {priest_token}",
                "X-Temple-ID": temple_id
            }
            
            print("3. Logging in as Counter Staff...")
            login_resp_c = await client.post(
                f"{api_base}/auth/login",
                data={"username": counter_email, "password": test_password}
            )
            assert login_resp_c.status_code == 200, f"Counter login failed: {login_resp_c.text}"
            counter_token = login_resp_c.json()["data"]["access_token"]
            counter_headers = {
                "Authorization": f"Bearer {counter_token}",
                "X-Temple-ID": temple_id
            }
            
            # TEST 1: Counter Staff tries to start execution -> Should be 403 Forbidden
            print("\nTEST 1: Counter Staff tries to start execution (Expect 403)...")
            start_resp_c = await client.post(
                f"{api_base}/archana-bookings/executions/{execution_id}/start",
                json={"priest_id": str(uuid.uuid4())},
                headers=counter_headers
            )
            print(f"Status: {start_resp_c.status_code}")
            assert start_resp_c.status_code == 403, f"Expected 403, got {start_resp_c.status_code}"
            
            # TEST 2: Priest starts execution with a legacy priest_id payload -> Should succeed (200 OK)
            print("\nTEST 2: Priest starts execution with legacy priest_id (Expect 200 OK)...")
            start_resp_p = await client.post(
                f"{api_base}/archana-bookings/executions/{execution_id}/start",
                json={"priest_id": "057e7303-26d3-407d-93c6-7663ae798cd4"}, # Legacy priest_id
                headers=priest_headers
            )
            print(f"Status: {start_resp_p.status_code}")
            print(f"Response: {start_resp_p.text}")
            assert start_resp_p.status_code == 200, f"Expected 200, got {start_resp_p.status_code}"
            
            # TEST 3: Verify database state after start (priest_id == NULL, started_by_user_id == priest_user_id, status == IN_PROGRESS)
            print("\nTEST 3: Verifying database state post-start...")
            async with engine.connect() as conn:
                res = await conn.execute(text(f"SELECT status, priest_id, started_by_user_id, start_time FROM archana_executions WHERE id = '{execution_id}'"))
                status, priest_id_val, started_by, start_time = res.fetchone()
                print(f"DB Status: {status} (Expected: IN_PROGRESS)")
                print(f"DB Priest ID: {priest_id_val} (Expected: None)")
                print(f"DB Started By User: {started_by} (Expected: {priest_user_id})")
                print(f"DB Start Time: {start_time}")
                assert status == "IN_PROGRESS", f"Expected status IN_PROGRESS, got {status}"
                assert priest_id_val is None, f"Expected priest_id to be NULL, got {priest_id_val}"
                assert str(started_by) == str(priest_user_id), f"Expected started_by_user_id {priest_user_id}, got {started_by}"
                assert start_time is not None, "Expected start_time to be populated"
                
            # TEST 4: Counter Staff tries to complete execution -> Should be 403 Forbidden
            print("\nTEST 4: Counter Staff tries to complete execution (Expect 403)...")
            comp_resp_c = await client.post(
                f"{api_base}/archana-bookings/executions/{execution_id}/complete",
                json={},
                headers=counter_headers
            )
            print(f"Status: {comp_resp_c.status_code}")
            assert comp_resp_c.status_code == 403, f"Expected 403, got {comp_resp_c.status_code}"
            
            # TEST 5: Priest completes execution -> Should succeed (200 OK)
            print("\nTEST 5: Priest completes execution (Expect 200 OK)...")
            comp_resp_p = await client.post(
                f"{api_base}/archana-bookings/executions/{execution_id}/complete",
                json={},
                headers=priest_headers
            )
            print(f"Status: {comp_resp_p.status_code}")
            assert comp_resp_p.status_code == 200, f"Expected 200, got {comp_resp_p.status_code}"
            
            # TEST 6: Verify database state after complete (completed_by_user_id == priest_user_id, status == COMPLETED)
            print("\nTEST 6: Verifying database state post-completion...")
            async with engine.connect() as conn:
                res = await conn.execute(text(f"SELECT status, completed_by_user_id, completed_at FROM archana_executions WHERE id = '{execution_id}'"))
                status, completed_by, completed_at = res.fetchone()
                print(f"DB Status: {status} (Expected: COMPLETED)")
                print(f"DB Completed By User: {completed_by} (Expected: {priest_user_id})")
                print(f"DB Completed At: {completed_at}")
                assert status == "COMPLETED", f"Expected status COMPLETED, got {status}"
                assert str(completed_by) == str(priest_user_id), f"Expected completed_by_user_id {priest_user_id}, got {completed_by}"
                assert completed_at is not None, "Expected completed_at to be populated"
                
            print("\nALL PRODUCTION REST API INTEGRATION TESTS PASSED SUCCESSFULLY!")
            
        except Exception as e:
            print("API Test failed:", str(e))
        finally:
            # Clean up database test records
            print("\n4. Cleaning up database test records...")
            async with engine.connect() as conn:
                ids = [str(i) for i in [priest_user_id, counter_user_id] if i is not None]
                if ids:
                    ids_str = ", ".join([f"'{i}'" for i in ids])
                    await conn.execute(text(f"DELETE FROM archana_booking_audit WHERE actor_id IN ({ids_str})"))
                    await conn.execute(text(f"DELETE FROM user_roles WHERE user_id IN ({ids_str})"))
                    await conn.execute(text(f"DELETE FROM users WHERE id IN ({ids_str})"))
                
                # Delete temporary roles
                roles_to_del = [str(r) for r in [priest_role_id, counter_role_id] if r is not None]
                if roles_to_del:
                    roles_str = ", ".join([f"'{r}'" for r in roles_to_del])
                    await conn.execute(text(f"DELETE FROM role_permissions WHERE role_id IN ({roles_str})"))
                    await conn.execute(text(f"DELETE FROM roles WHERE id IN ({roles_str})"))
                
                await conn.commit()
            print("Cleanup completed.")
            
    await engine.dispose()

if __name__ == "__main__":
    asyncio.run(run())
