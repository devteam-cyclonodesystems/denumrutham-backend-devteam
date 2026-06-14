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
    "offering_receipts", "offering_payments", "offerings", "offering_categories",
    "service_bookings", "archana_bookings", "bookings", "pooja_services", "temple_services",
    "store_order_items", "store_orders", "products", "hall_bookings", "halls",
    "donation_campaigns", "inventory_transactions", "inventory_movements",
    "inventory_item_requests", "inventory_invoices", "inventory_items", "suppliers",
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
    if not env:
        print("ERROR: ENVIRONMENT variable is missing or empty. Aborting for safety.")
        sys.exit(1)
        
    env_lower = env.lower()
    if env_lower in ["production", "prod", "live", "staging", "preprod"]:
        print(f"ERROR: Destructive operations are blocked in ENVIRONMENT: {env}. Aborting.")
        sys.exit(1)
        
    db_url = os.getenv("DATABASE_URL", "")
    if db_url:
        db_url_lower = db_url.lower()
        if any(keyword in db_url_lower for keyword in ["prod", "production", "live", "staging", "preprod", "neon.tech", "aws.com", "rds.amazonaws"]):
            print("ERROR: Remote/Production host detected in DATABASE_URL connection string. Aborting.")
            sys.exit(1)

async def get_db_estimates(db):
    estimates = {}
    for table_name in CHILD_TABLES + ["temples", "users"]:
        try:
            if table_name == "users":
                res = await db.execute(text("SELECT COUNT(*) FROM users WHERE role != 'SUPER_ADMIN' AND role != 'SUPERADMIN'"))
            else:
                res = await db.execute(text(f"SELECT COUNT(*) FROM {table_name}"))
            count = res.scalar()
            estimates[table_name] = count
        except Exception:
            estimates[table_name] = 0
    return estimates

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

async def run_verification(db) -> bool:
    print("=" * 60)
    print("  DENUMRUTHAM SYSTEM VERIFICATION RUN")
    print("=" * 60)
    
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
    required_roles = ["SUPER_ADMIN", "TEMPLE_ADMIN", "DEVOTEE"]
    for role in required_roles:
        if role not in role_names:
            failures.append(f"Missing required role: {role}")
        else:
            print(f"  [PASS] Mapped role: {role}")

    # 3. Canonical Temples A-F check
    temple_domains = [
        "sabarimala-sree-dharma-sastha",  # Stage 1
        "alappuzha-sree-krishna",         # Stage 2
        "vaikom-mahadeva",                # Stage 3
        "ambalappuzha-sree-krishna",       # Stage 4 / Merge target
        "ambalapuzha-krishna-duplicate",  # Merged redirect
        "old-inactive-shrine"             # Archived/Inactive
    ]
    for domain in temple_domains:
        t = (await db.execute(select(Temple).filter(Temple.domain == domain))).scalars().first()
        if not t:
            failures.append(f"Missing canonical temple domain: {domain}")
        else:
            # Check Stage 1 timing fallbacks and claiming CTA status
            if domain == "sabarimala-sree-dharma-sastha":
                if t.management_mode != "DIRECTORY_ONLY":
                    failures.append("Temple A Sabarimala is not configured as DIRECTORY_ONLY")
                # Preload website settings
                settings = (await db.execute(select(TempleWebsiteSettings).filter(TempleWebsiteSettings.temple_id == t.id))).scalars().first()
                if not settings:
                    failures.append("Temple A Sabarimala is missing website settings")
                live = (await db.execute(select(TempleWebsiteSettingsLive).filter(TempleWebsiteSettingsLive.temple_id == t.id))).scalars().first()
                if live:
                    failures.append("Temple A Sabarimala has active live settings (should be Stage 1)")
            
            # Check Stage 2 curation settings
            elif domain == "alappuzha-sree-krishna":
                live = (await db.execute(select(TempleWebsiteSettingsLive).filter(TempleWebsiteSettingsLive.temple_id == t.id))).scalars().first()
                if not live:
                    failures.append("Temple B Alappuzha has no live settings (should be Stage 2)")
                    
            # Check Stage 3 commerce configuration
            elif domain == "vaikom-mahadeva":
                if t.management_mode != "SELF_MANAGED":
                    failures.append("Temple C Vaikom is not configured as SELF_MANAGED")
                services = (await db.execute(select(TempleService).filter(TempleService.temple_id == t.id))).scalars().all()
                if len(services) < 2:
                    failures.append(f"Temple C Vaikom is missing services (found {len(services)})")
                bookings = (await db.execute(select(ServiceBooking).filter(ServiceBooking.temple_id == t.id))).scalars().all()
                if len(bookings) < 2:
                    failures.append(f"Temple C Vaikom is missing bookings (found {len(bookings)})")

            # Check Merged Redirection
            elif domain == "ambalapuzha-krishna-duplicate":
                if t.status != "MERGED" or not t.merged_temple_id:
                    failures.append("Temple E duplicate is not marked as MERGED or is missing merged_temple_id redirect link")
                    
            # Check Inactive Search target
            elif domain == "old-inactive-shrine":
                if t.is_active is not False:
                    failures.append("Temple F archived shrine is not inactive")
            
            print(f"  [PASS] Canonical Temple: {t.name} (domain: {t.domain})")

    # 4. Suggestions check
    suggestions = (await db.execute(select(TempleSuggestion))).scalars().all()
    sug_statuses = [s.status for s in suggestions]
    if "PENDING" not in sug_statuses:
        failures.append("Missing PENDING suggestion")
    if "APPROVED" not in sug_statuses:
        failures.append("Missing APPROVED suggestion")
    if "REJECTED" not in sug_statuses:
        failures.append("Missing REJECTED suggestion")
    
    print(f"  [PASS] Seeded Suggestions (Total: {len(suggestions)})")

    # 5. Claims check
    claims = (await db.execute(select(TempleClaimRequest))).scalars().all()
    claim_statuses = [c.status for c in claims]
    if "PENDING" not in claim_statuses:
        failures.append("Missing PENDING claim request")
    if "REJECTED" not in claim_statuses:
        failures.append("Missing REJECTED claim request")
    
    print(f"  [PASS] Seeded Claims (Total: {len(claims)})")

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
                    await db.execute(text(f"DELETE FROM {r_table}"))
                except Exception:
                    pass # Ignore if table not present in early migration stages
            
            # Truncate child modules
            for table_name in CHILD_TABLES:
                try:
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
            success = await run_verification(db)
            sys.exit(0 if success else 1)
            
    # 2. Dry-Run Mode (Default)
    if not args.force:
        print("=" * 60)
        print("  DENUMRUTHAM DATABASE RESET - DRY-RUN")
        print("=" * 60)
        print("No execution mode specified. Running in DRY-RUN mode.")
        print("No database changes will be made. No media files will be deleted.")
        print("-" * 60)
        
        async with AsyncSessionLocal() as db:
            estimates = await get_db_estimates(db)
            media_files = get_media_estimates()
            
            print(f"Database dialect connection active.")
            print("\nEstimated rows targeted for deletion:")
            total_rows = 0
            for tbl, count in estimates.items():
                if count > 0:
                    print(f"  - {tbl}: {count} rows")
                    total_rows += count
            print(f"Total estimated rows to delete: {total_rows}")
            
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
