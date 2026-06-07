import asyncio
import re
import unicodedata
from sqlalchemy.future import select
from app.core.database import engine, AsyncSessionLocal
from app.models.domain import Temple

def _slugify(text: str) -> str:
    """Generate a URL-safe slug from text."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    text = re.sub(r"[^\w\s-]", "", text.lower())
    return re.sub(r"[-\s]+", "-", text).strip("-")

async def main():
    print("Starting slug validation and repair run...")
    async with AsyncSessionLocal() as db:
        result = await db.execute(select(Temple))
        temples = result.scalars().all()
        
        total_temples = len(temples)
        valid_slugs = []
        missing_slugs = []
        invalid_slug_format = []
        slug_map = {}
        
        slug_regex = re.compile(r"^[a-z0-9-]+$")
        
        for temple in temples:
            slug = temple.domain
            if not slug or not slug.strip():
                missing_slugs.append(temple)
            elif not slug_regex.match(slug):
                invalid_slug_format.append(temple)
            else:
                valid_slugs.append(temple)
                slug_map.setdefault(slug, []).append(temple)
        
        print("\n--- SLUG VALIDATION REPORT ---")
        print(f"Total Temples: {total_temples}")
        print(f"Temples with Valid Slugs: {len(valid_slugs)}")
        print(f"Temples Missing Slugs: {len(missing_slugs)}")
        print(f"Temples with Invalid Slug Format: {len(invalid_slug_format)}")
        
        duplicates = {slug: t_list for slug, t_list in slug_map.items() if len(t_list) > 1}
        print(f"Duplicate Slug Conflicts: {len(duplicates)}")
        for slug, t_list in duplicates.items():
            print(f"  Slug '{slug}' is shared by:")
            for t in t_list:
                print(f"    - ID: {t.id}, Name: {t.name}")
                
        # Handle repair of missing/invalid/duplicate slugs
        any_changes = False
        
        # 1. Repair missing and invalid slugs
        for temple in missing_slugs + invalid_slug_format:
            old_slug = temple.domain
            new_slug = _slugify(temple.name)
            if not new_slug:
                new_slug = f"temple-{str(temple.id)[:8]}"
            
            # Ensure uniqueness
            base_slug = new_slug
            counter = 1
            while True:
                # Check current map and database
                dup_stmt = select(Temple).filter(Temple.domain == new_slug, Temple.id != temple.id)
                dup_res = await db.execute(dup_stmt)
                if dup_res.scalars().first() or new_slug in slug_map:
                    new_slug = f"{base_slug}-{counter}"
                    counter += 1
                else:
                    break
            
            temple.domain = new_slug
            slug_map.setdefault(new_slug, []).append(temple)
            print(f"Repaired temple '{temple.name}' (ID: {temple.id}): '{old_slug}' -> '{new_slug}'")
            any_changes = True
            
        # 2. Resolve duplicates
        for slug, t_list in duplicates.items():
            # Keep the first one, generate new slugs for the rest
            for i, temple in enumerate(t_list[1:], start=1):
                base_slug = slug
                new_slug = f"{base_slug}-{i}"
                counter = i + 1
                while True:
                    dup_stmt = select(Temple).filter(Temple.domain == new_slug, Temple.id != temple.id)
                    dup_res = await db.execute(dup_stmt)
                    if dup_res.scalars().first() or new_slug in slug_map:
                        new_slug = f"{base_slug}-{counter}"
                        counter += 1
                    else:
                        break
                
                temple.domain = new_slug
                slug_map.setdefault(new_slug, []).append(temple)
                print(f"Resolved duplicate slug for temple '{temple.name}' (ID: {temple.id}): '{slug}' -> '{new_slug}'")
                any_changes = True
                
        if any_changes:
            print("Persisting slug fixes to database...")
            await db.commit()
            print("Database updated successfully.")
        else:
            print("No slug fixes required.")

if __name__ == "__main__":
    asyncio.run(main())
