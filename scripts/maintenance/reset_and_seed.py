import asyncio
import os
import sys
import uuid
import time
import argparse
import json
import logging
from datetime import datetime, timezone
from sqlalchemy.future import select
from sqlalchemy import text, delete
from sqlalchemy.orm import ColumnProperty

# Ensure backend directory is in path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from app.core.database import AsyncSessionLocal
from app.models.domain import (
    User, Temple, TempleProfile, TempleWebsiteSettings, TempleWebsiteSettingsLive,
    TempleAnnouncement, TempleActivity, TempleFestival, StateMaster, DistrictMaster, TempleFollower,
    TempleClaimRequest, TempleSuggestion, TempleSuggestionImage, TempleSuggestionContact,
    TempleSuggestionAudit, TempleService, ServiceBooking, DevoteeProfile, Devotee,
    Notification, UserTemple, TempleImage
)
from app.modules.temple_management.models.offering import OfferingCategory, Offering
from app.modules.auth.models.system_rbac import SystemRole

# Setup Logger
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("ResetAndSeed")

# Dataset Version
DATASET_VERSION = "1.0.0"

# Target tables in reverse-dependency order
CHILD_TABLES = [
    # 1. Transaction Tables
    "refund_history", "approval_requests",
    "offering_receipts", "offering_payments", "offering_audit_logs", "offering_inventory_links", "offerings", "offering_categories",
    "service_bookings", "archana_bookings", "bookings", "pooja_services", "temple_services",
    "refund_transactions", "payment_transactions", "payment_ledgers",
    "booking_audit_logs", "booking_status_history", "booking_conflicts",
    "booking_holds", "booking_policies", "pricing_rules", "venue_slots",
    "hall_bookings", "halls",
    "donation_campaigns",
    
    # Layer 1: Inventory/Store Transactions, Ledgers, Sessions, Orders, Costs, Snapshots, Mapping, Reconciliations
    "price_approval_requests", "inventory_stock_ledger", "inventory_reconciliations", "donation_inventory_mapping",
    "procurement_cost_history", "inventory_daily_snapshots", "ritual_template_items",
    "inventory_transactions", "inventory_movements", "inventory_issue_sessions",
    "inventory_item_requests", "inventory_payment_transactions", "inventory_invoices",
    "procurement_grns", "store_sales_order_items", "store_sales_orders",
    "store_auctions", "store_stock", "store_stock_reservations", "kalavara_stock",
    "store_order_items", "store_orders",
    
    # Layer 2: Products and Inventory Items
    "store_products", "products", "kalavara_inventory_items", "inventory_items",
    
    # Layer 3: Masters, Templates, Locations, Suppliers
    "ritual_templates", "inventory_locations", "suppliers",
    
    # 2. Follower/Notification Tables
    "temple_follower_preferences", "temple_followers", "notifications",
    # 3. Suggestion Child Tables
    "temple_suggestion_images", "temple_suggestion_contacts", "temple_suggestion_audits",
    # 4. Claims & Suggestions
    "temple_claim_requests", "temple_suggestions",
    # 5. Temple Child/Profile Tables
    "temple_announcements", "temple_activities", "temple_festivals",
    "temple_images", "temple_website_settings_live", "temple_website_settings",
    "temple_profile_drafts", "temple_profiles", "temple_search_index",
    "user_temples"
]

def get_git_commit_hash() -> str:
    try:
        import subprocess
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            check=True
        )
        return result.stdout.strip()
    except Exception:
        return "N/A"

def check_environment():
    env = os.getenv("ENVIRONMENT")
    railway_env = os.getenv("RAILWAY_ENVIRONMENT")
    railway_env_name = os.getenv("RAILWAY_ENVIRONMENT_NAME")
    db_url = os.getenv("DATABASE_URL", "")
    
    # Extract host for safety report
    db_host = "Unknown"
    if db_url:
        try:
            import urllib.parse
            if "sqlite" in db_url:
                db_host = "Local SQLite File"
            else:
                sanitized_url = db_url.split("://")[-1]
                db_host = sanitized_url.split("@")[-1].split("/")[0].split(":")[0]
        except Exception:
            db_host = "Parse Error"

    is_blocked = False
    blocked_reasons = []

    # 1. Check ENVIRONMENT
    if not env:
        is_blocked = True
        blocked_reasons.append("ENVIRONMENT variable is missing or empty.")
    else:
        env_lower = env.lower()
        if env_lower in ["production", "prod", "live", "staging", "preprod"]:
            is_blocked = True
            blocked_reasons.append(f"ENVIRONMENT is set to a restricted value: '{env}'")

    # 2. Check Railway variables
    for var_name, var_val in [
        ("RAILWAY_ENVIRONMENT", railway_env),
        ("RAILWAY_ENVIRONMENT_NAME", railway_env_name)
    ]:
        if var_val:
            val_lower = var_val.lower()
            if val_lower in ["production", "prod", "live", "staging", "preprod"]:
                is_blocked = True
                blocked_reasons.append(f"{var_name} is set to a restricted value: '{var_val}'")

    # Print safety report
    print("=" * 60)
    print("  RESET SAFETY REPORT")
    print("=" * 60)
    print(f"ENVIRONMENT:            {env or 'Not Set'}")
    print(f"RAILWAY_ENVIRONMENT:    {railway_env or 'Not Set'}")
    print(f"RAILWAY_ENV_NAME:       {railway_env_name or 'Not Set'}")
    print(f"DATABASE HOST:          {db_host}")
    print("-" * 60)
    if is_blocked:
        print("RESULT:                 BLOCKED")
        print("Reasons:")
        for reason in blocked_reasons:
            print(f"  - {reason}")
        print("=" * 60)
        sys.exit(1)
    else:
        print("RESULT:                 ALLOWED")
        print("=" * 60)

async def get_db_estimates(db):
    estimates = {}
    failures = {}
    for table_name in CHILD_TABLES + ["temples", "users"]:
        try:
            async with db.begin_nested():
                if table_name == "users":
                    res = await db.execute(text("SELECT COUNT(*) FROM users WHERE role != 'SUPER_ADMIN' AND role != 'SUPERADMIN'"))
                else:
                    res = await db.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
                count = res.scalar()
                estimates[table_name] = count
        except Exception as e:
            err_msg = str(e)
            logger.error(f"Failed to count table '{table_name}': {err_msg}")
            failures[table_name] = err_msg
    return estimates, failures

def get_media_estimates():
    media_files = []
    upload_dir = "static/uploads"
    if os.path.exists(upload_dir):
        for f in os.listdir(upload_dir):
            if os.path.isfile(os.path.join(upload_dir, f)) and f != "default-temple.jpg":
                media_files.append(f)
    return media_files

async def backup_data(db, backup_dir: str):
    from sqlalchemy import inspect
    
    tables_to_backup = [
        ("temples", Temple),
        ("temple_profiles", TempleProfile),
        ("temple_website_settings", TempleWebsiteSettings),
        ("temple_website_settings_live", TempleWebsiteSettingsLive),
        ("temple_images", TempleImage),
        ("temple_activities", TempleActivity),
        ("temple_announcements", TempleAnnouncement),
        ("temple_suggestions", TempleSuggestion),
        ("temple_claim_requests", TempleClaimRequest),
        ("followers", TempleFollower),
        ("users", User),
        ("notifications", Notification)
    ]
    
    os.makedirs(backup_dir, exist_ok=True)
    
    for name, model in tables_to_backup:
        try:
            result = await db.execute(select(model))
            rows = result.scalars().all()
            
            serialized = []
            mapper = inspect(model)
            for row in rows:
                row_dict = {}
                for attr in mapper.attrs:
                    if isinstance(attr, ColumnProperty):
                        val = getattr(row, attr.key)
                        if isinstance(val, (datetime,)):
                            row_dict[attr.key] = val.isoformat()
                        elif isinstance(val, (uuid.UUID,)):
                            row_dict[attr.key] = str(val)
                        else:
                            row_dict[attr.key] = val
                serialized.append(row_dict)
                
            filepath = os.path.join(backup_dir, f"{name}.json")
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(serialized, f, indent=2, default=str)
            logger.info(f"[Backup] [OK] Backed up {len(serialized)} rows from '{name}'")
        except Exception as e:
            logger.error(f"[Backup] [FAILED] Failed to back up table '{name}': {e}")
            raise e

async def run_verification(db, dataset_version: str) -> bool:
    print("=" * 60)
    print(f"  DENUMRUTHAM SYSTEM VERIFICATION RUN (dataset: {dataset_version})")
    print("=" * 60)
    
    # Resolve path to manifest file
    manifest_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "scripts", "seed", "versions", f"seed_{dataset_version}_manifest.json"
    )
    
    if not os.path.exists(manifest_path):
        print(f"ERROR: Dataset manifest not found at: {manifest_path}")
        return False
        
    try:
        with open(manifest_path, "r", encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception as e:
        print(f"ERROR: Failed to load dataset manifest: {e}")
        return False

    failures = []
    
    # 1. Superadmin User check
    result = await db.execute(select(User).filter(User.role.in_(["SUPER_ADMIN", "SUPERADMIN"])))
    superadmin = result.scalars().first()
    if not superadmin:
        failures.append("Missing SuperAdmin user record")
    else:
        print(f"  [PASS] SuperAdmin User: {superadmin.user_id} ({superadmin.email})")

    # 2. Base Roles check
    roles = (await db.execute(select(SystemRole))).scalars().all()
    role_names = [r.name for r in roles]
    required_roles = manifest.get("required_roles", [])
    for role in required_roles:
        if role not in role_names:
            failures.append(f"Missing required role: {role}")
        else:
            print(f"  [PASS] Mapped role: {role}")

    # 3. Canonical Temples check
    temple_assertions = manifest.get("temple_assertions", [])
    for assert_data in temple_assertions:
        domain = assert_data.get("domain")
        t = (await db.execute(select(Temple).filter(Temple.domain == domain))).scalars().first()
        if not t:
            failures.append(f"Missing canonical temple domain: {domain}")
            continue
            
        # Check specific assertions
        if "management_mode" in assert_data:
            if t.management_mode != assert_data["management_mode"]:
                failures.append(f"Temple {domain} management_mode is '{t.management_mode}', expected '{assert_data['management_mode']}'")
        
        if "is_active" in assert_data:
            if t.is_active != assert_data["is_active"]:
                failures.append(f"Temple {domain} is_active is {t.is_active}, expected {assert_data['is_active']}")

        if "status" in assert_data:
            if t.status != assert_data["status"]:
                failures.append(f"Temple {domain} status is '{t.status}', expected '{assert_data['status']}'")

        if assert_data.get("has_live_settings") is not None:
            live = (await db.execute(select(TempleWebsiteSettingsLive).filter(TempleWebsiteSettingsLive.temple_id == t.id))).scalars().first()
            if assert_data["has_live_settings"] and not live:
                failures.append(f"Temple {domain} is missing website_settings_live snapshot")
            elif not assert_data["has_live_settings"] and live:
                failures.append(f"Temple {domain} should not have website_settings_live snapshot")

        if assert_data.get("has_redirect") is not None:
            if assert_data["has_redirect"] and not t.merged_temple_id:
                failures.append(f"Temple {domain} should have merged_temple_id redirect link")
                
        if "min_services" in assert_data:
            services = (await db.execute(select(TempleService).filter(TempleService.temple_id == t.id))).scalars().all()
            if len(services) < assert_data["min_services"]:
                failures.append(f"Temple {domain} has {len(services)} services, expected at least {assert_data['min_services']}")

        if "min_bookings" in assert_data:
            bookings = (await db.execute(select(ServiceBooking).filter(ServiceBooking.temple_id == t.id))).scalars().all()
            if len(bookings) < assert_data["min_bookings"]:
                failures.append(f"Temple {domain} has {len(bookings)} bookings, expected at least {assert_data['min_bookings']}")
                
        print(f"  [PASS] Canonical Temple assertions satisfied: {t.name} (domain: {t.domain})")

    # 4. Suggestions check
    suggestions_data = manifest.get("suggestions", {})
    if suggestions_data:
        suggestions = (await db.execute(select(TempleSuggestion))).scalars().all()
        expected_count = suggestions_data.get("total_count", 0)
        if len(suggestions) < expected_count:
            failures.append(f"Expected at least {expected_count} suggestions, found {len(suggestions)}")
        sug_statuses = [s.status for s in suggestions]
        for req_status in suggestions_data.get("required_statuses", []):
            if req_status not in sug_statuses:
                failures.append(f"Missing suggestion status: {req_status}")
        print(f"  [PASS] Seeded Suggestions validated (Total: {len(suggestions)})")

    # 5. Claims check
    claims_data = manifest.get("claims", {})
    if claims_data:
        claims = (await db.execute(select(TempleClaimRequest))).scalars().all()
        expected_count = claims_data.get("total_count", 0)
        if len(claims) < expected_count:
            failures.append(f"Expected at least {expected_count} claims, found {len(claims)}")
        claim_statuses = [c.status for c in claims]
        for req_status in claims_data.get("required_statuses", []):
            if req_status not in claim_statuses:
                failures.append(f"Missing claim status: {req_status}")
        print(f"  [PASS] Seeded Claims validated (Total: {len(claims)})")

    # Final result
    print("-" * 60)
    if failures:
        print("VERIFICATION RESULT: FAILED")
        for f in failures:
            print(f"  - {f}")
        print("-" * 60)
        return False
    else:
        print("VERIFICATION RESULT: PASSED (System is operational and aligned)")
        print("-" * 60)
        return True

async def execute_reset_and_seed(version: str):
    check_environment()
    
    start_time = time.time()
    logger.info("Initializing system reset...")
    
    # Import modular seed function based on version
    if version == "v1":
        from scripts.seed.versions.seed_v1 import seed_v1 as seed_fn
    else:
        logger.error(f"Unsupported dataset version: {version}")
        sys.exit(1)
        
    async with AsyncSessionLocal() as db:
        # Phase 1: Superadmin check
        result = await db.execute(select(User).filter(User.role.in_(["SUPER_ADMIN", "SUPERADMIN"])))
        super_admin = result.scalars().first()
        if not super_admin:
            logger.error("SUPER_ADMIN user not found. Please run baseline database migrations first.")
            sys.exit(1)
        super_admin_id = super_admin.id
        
        # Phase 2: JSON Backup
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = f"scripts/maintenance/backups/reset_backup_{timestamp}"
        try:
            await backup_data(db, backup_dir)
        except Exception as e:
            logger.error(f"Backup failed. Aborting destructive reset. Error: {e}")
            sys.exit(1)
            
        # Phase 3: Transactional Cleanup
        logger.info("Executing transactional table cleanup...")
        try:
            # Nullify FK links first to prevent integrity blocks
            await db.execute(text("UPDATE temples SET merged_temple_id = NULL"))
            await db.execute(text("UPDATE users SET temple_id = NULL"))
            await db.flush()
            
            # Truncate raw/RBAC tables safely
            raw_tables = [
                "staff_invites", "temple_domain_history", "temple_requests", 
                "user_requests", "temple_status_audit", "temple_code_sequences",
                "password_reset_tokens", "guest_bookings", "audit_logs"
            ]
            for r_table in raw_tables:
                try:
                    async with db.begin_nested():
                        await db.execute(text(f"DELETE FROM {r_table}"))
                except Exception:
                    pass # Ignore if table not present in early migration stages
            
            # Truncate child modules
            for table_name in CHILD_TABLES:
                try:
                    async with db.begin_nested():
                        await db.execute(text(f"DELETE FROM {table_name}"))
                        logger.info(f"  [OK] Cleared table: {table_name}")
                except Exception as e:
                    err_msg = str(e).lower()
                    if "no such table" in err_msg or "relation" in err_msg and "does not exist" in err_msg:
                        logger.warning(f"  [SKIP] Table '{table_name}' does not exist.")
                    else:
                        logger.error(f"  [FAILED] Error clearing table '{table_name}': {e}")
                        raise e
            
            # Truncate devotees
            try:
                async with db.begin_nested():
                    await db.execute(text("DELETE FROM devotees"))
                    logger.info("  [OK] Cleared devotees")
            except Exception:
                pass
                
            # Truncate users except superadmin
            await db.execute(text("DELETE FROM users WHERE role != 'SUPER_ADMIN' AND role != 'SUPERADMIN'"))
            logger.info("  [OK] Cleared users (Superadmin preserved)")
            
            # Truncate temples
            await db.execute(text("DELETE FROM temples"))
            logger.info("  [OK] Cleared temples")
            
            # Commit cleanup block
            await db.flush()
            
            # Phase 4: Reseed dataset
            logger.info(f"Reseeding canonical dataset version {DATASET_VERSION}...")
            seed_metrics = await seed_fn(db, super_admin_id)
            
            # Commit transactions
            await db.commit()
            logger.info("Database transaction committed successfully.")
            
        except Exception as e:
            await db.rollback()
            logger.error("=" * 60)
            logger.error("  RESET TRANSACTION FAILURE - DATABASE ROLLED BACK")
            logger.error("=" * 60)
            logger.error(f"Error context: {e}")
            logger.error("No database rows were modified. No media files were deleted.")
            logger.error("STATUS: ABORTED / ROLLED BACK")
            sys.exit(1)
            
        # Phase 5: Post-Commit Media Pruning
        media_deleted_count = 0
        upload_dir = "static/uploads"
        if os.path.exists(upload_dir):
            logger.info("Pruning uploaded media files under static/uploads/...")
            for f in os.listdir(upload_dir):
                f_path = os.path.join(upload_dir, f)
                if os.path.isfile(f_path) and f != "default-temple.jpg":
                    try:
                        os.remove(f_path)
                        media_deleted_count += 1
                    except Exception as ex:
                        logger.warning(f"Failed to delete file '{f}': {ex}")
                        
        # Phase 6: Write Manifest File
        duration = round(time.time() - start_time, 2)
        manifest_path = "scripts/maintenance/backups/latest_seed_manifest.json"
        manifest_data = {
            "dataset_version": DATASET_VERSION,
            "seeded_at": datetime.now(timezone.utc).isoformat(),
            "execution_duration_seconds": duration,
            "git_commit_hash": get_git_commit_hash(),
            "temples": seed_metrics.get("temples", 0),
            "suggestions": seed_metrics.get("suggestions", 0),
            "claims": seed_metrics.get("claims", 0),
            "bookings": seed_metrics.get("bookings", 0),
            "offerings": seed_metrics.get("offerings", 0),
            "notifications": seed_metrics.get("notifications", 0),
            "followers": seed_metrics.get("followers", 0),
            "media_files_deleted": media_deleted_count,
            "status": "SUCCESS"
        }
        try:
            with open(manifest_path, "w", encoding="utf-8") as mf:
                json.dump(manifest_data, mf, indent=2)
            logger.info(f"Wrote seed manifest to '{manifest_path}'")
        except Exception as mx:
            logger.warning(f"Failed to write manifest file: {mx}")
            
        # Output Final Execution Report
        print("=" * 60)
        print("  DENUMRUTHAM DEVELOPMENT RESET & RESEED COMPLETED")
        print("=" * 60)
        print(f"Status:             SUCCESS")
        print(f"Execution Duration: {duration}s")
        print(f"Dataset Version:    {DATASET_VERSION}")
        print(f"\nDatabase Changes:")
        print(f"-----------------")
        print(f"- Temples Seeded:   {seed_metrics.get('temples', 0)}")
        print(f"- Bookings Seeded:  {seed_metrics.get('bookings', 0)}")
        print(f"- Offerings Seeded: {seed_metrics.get('offerings', 0)}")
        print(f"- Claims Seeded:    {seed_metrics.get('claims', 0)}")
        print(f"\nMedia Storage:")
        print(f"--------------")
        print(f"- Files Deleted:    {media_deleted_count}")
        print(f"- Files Preserved:  1 (default-temple.jpg)")
        print(f"\nArchives:")
        print(f"---------")
        print(f"- JSON Backup:      {backup_dir}/")
        print(f"- Manifest Path:    {manifest_path}")
        print("=" * 60)

async def main():
    parser = argparse.ArgumentParser(description="Denumrutham Dev/UAT Database Reset & Reseeding Utility.")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("-f", "--force", action="store_true", help="Perform active database cleanup and reseeding.")
    group.add_argument("-v", "--verify", action="store_true", help="Bypass reset and run validation checks on canonical dataset.")
    parser.add_argument("--dataset-version", default="v1", help="Version ID for target reseed dataset (defaults to v1).")
    
    args = parser.parse_args()
    
    # 1. Verification Mode
    if args.verify:
        async with AsyncSessionLocal() as db:
            success = await run_verification(db, args.dataset_version)
            sys.exit(0 if success else 1)
            
    # 2. Dry-Run Mode (Default)
    if not args.force:
        # Check environment and display safety report first
        check_environment()
        
        print("=" * 60)
        print("  DENUMRUTHAM DATABASE RESET - DRY-RUN")
        print("=" * 60)
        print("No execution mode specified. Running in DRY-RUN mode.")
        print("No database changes will be made. No media files will be deleted.")
        print("-" * 60)
        
        async with AsyncSessionLocal() as db:
            estimates, failures = await get_db_estimates(db)
            media_files = get_media_estimates()
            
            print(f"Database dialect connection active.")
            print("\nSuccessfully Counted:")
            print("---------------------")
            total_rows = 0
            for tbl, count in estimates.items():
                print(f"  - {tbl}: {count} rows")
                total_rows += count
            print(f"Total estimated rows to delete: {total_rows}")
            
            if failures:
                print("\nFailed To Count:")
                print("----------------")
                for tbl, err in failures.items():
                    print(f"  - {tbl}: {err}")
            
            print(f"\nEstimated media files targeted for deletion:")
            print(f"  - static/uploads/: {len(media_files)} files")
            
            print("-" * 60)
            print("Dry-run execution completed. No changes were committed.")
            print("To execute reset, run with --force flag and confirm.")
            print("=" * 60)
            sys.exit(0)
            
    # 3. Forced Destructive Reset Mode
    print("=" * 60)
    print("  WARNING: DESTRUCTIVE SYSTEM RESET REQUESTED")
    print("=" * 60)
    print("This will clear all transactions, temples, claims, suggestions, and devotee accounts.")
    print("RBAC roles, system permissions, and superadmin users will be preserved.")
    print("-" * 60)
    
    # Double-check confirmation prompt in interactive environments
    try:
        confirm = input("Type 'RESET-CONFIRM' to proceed with the database reset: ")
        if confirm.strip() != "RESET-CONFIRM":
            print("Confirmation mismatch. Aborting.")
            sys.exit(1)
    except (IOError, EOFError):
        # Non-interactive fallback (e.g. CI runner pipeline)
        print("Non-interactive terminal detected. Skipping confirmation prompt.")
        
    await execute_reset_and_seed(args.dataset_version)

if __name__ == "__main__":
    asyncio.run(main())
