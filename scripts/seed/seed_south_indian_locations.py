import asyncio
import sys
import os
import uuid
from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

# Add backend directory to path
sys.path.append("c:\\Denumrutham\\backend")

from app.models.domain import StateMaster, DistrictMaster

south_indian_states = {
    "KL": {
        "name": "Kerala",
        "slug": "kerala",
        "districts": [
            {"name": "Thiruvananthapuram", "slug": "thiruvananthapuram", "code": "TVM"},
            {"name": "Kollam", "slug": "kollam", "code": "KLM"},
            {"name": "Pathanamthitta", "slug": "pathanamthitta", "code": "PTA"},
            {"name": "Alappuzha", "slug": "alappuzha", "code": "ALP"},
            {"name": "Kottayam", "slug": "kottayam", "code": "KTM"},
            {"name": "Idukki", "slug": "idukki", "code": "IDK"},
            {"name": "Ernakulam", "slug": "ernakulam", "code": "EKM"},
            {"name": "Thrissur", "slug": "thrissur", "code": "TCR"},
            {"name": "Palakkad", "slug": "palakkad", "code": "PKD"},
            {"name": "Malappuram", "slug": "malappuram", "code": "MPM"},
            {"name": "Kozhikode", "slug": "kozhikode", "code": "KKD"},
            {"name": "Wayanad", "slug": "wayanad", "code": "WYD"},
            {"name": "Kannur", "slug": "kannur", "code": "KNR"},
            {"name": "Kasaragod", "slug": "kasaragod", "code": "KSD"}
        ]
    },
    "TN": {
        "name": "Tamil Nadu",
        "slug": "tamil-nadu",
        "districts": [
            {"name": "Ariyalur", "slug": "ariyalur", "code": "ARI"},
            {"name": "Chengalpattu", "slug": "chengalpattu", "code": "Cgp"},
            {"name": "Chennai", "slug": "chennai", "code": "CHN"},
            {"name": "Coimbatore", "slug": "coimbatore", "code": "CBE"},
            {"name": "Cuddalore", "slug": "cuddalore", "code": "CUD"},
            {"name": "Dharmapuri", "slug": "dharmapuri", "code": "DPI"},
            {"name": "Dindigul", "slug": "dindigul", "code": "DGL"},
            {"name": "Erode", "slug": "erode", "code": "ERD"},
            {"name": "Kallakurichi", "slug": "kallakurichi", "code": "KKI"},
            {"name": "Kanchipuram", "slug": "kanchipuram", "code": "KPM"},
            {"name": "Kanyakumari", "slug": "kanyakumari", "code": "KKM"},
            {"name": "Karur", "slug": "karur", "code": "KRR"},
            {"name": "Krishnagiri", "slug": "krishnagiri", "code": "KGI"},
            {"name": "Madurai", "slug": "madurai", "code": "MDU"},
            {"name": "Mayiladuthurai", "slug": "mayiladuthurai", "code": "MYD"},
            {"name": "Nagapattinam", "slug": "nagapattinam", "code": "NGP"},
            {"name": "Namakkal", "slug": "namakkal", "code": "NMK"},
            {"name": "Nilgiris", "slug": "nilgiris", "code": "NIL"},
            {"name": "Perambalur", "slug": "perambalur", "code": "PBL"},
            {"name": "Pudukkottai", "slug": "pudukkottai", "code": "PDK"},
            {"name": "Ramanathapuram", "slug": "ramanathapuram", "code": "RMD"},
            {"name": "Ranipet", "slug": "ranipet", "code": "RPT"},
            {"name": "Salem", "slug": "salem", "code": "SLM"},
            {"name": "Sivaganga", "slug": "sivaganga", "code": "SVG"},
            {"name": "Tenkasi", "slug": "tenkasi", "code": "TKS"},
            {"name": "Thanjavur", "slug": "thanjavur", "code": "TNJ"},
            {"name": "Theni", "slug": "theni", "code": "TNI"},
            {"name": "Thoothukudi", "slug": "thoothukudi", "code": "TUT"},
            {"name": "Tiruchirappalli", "slug": "tiruchirappalli", "code": "TRY"},
            {"name": "Tirunelveli", "slug": "tirunelveli", "code": "TIV"},
            {"name": "Tirupattur", "slug": "tirupattur", "code": "TPT"},
            {"name": "Tiruppur", "slug": "tiruppur", "code": "TPR"},
            {"name": "Tiruvallur", "slug": "tiruvallur", "code": "TVL"},
            {"name": "Tiruvannamalai", "slug": "tiruvannamalai", "code": "TVM_TN"},
            {"name": "Tiruvarur", "slug": "tiruvarur", "code": "TVR"},
            {"name": "Vellore", "slug": "vellore", "code": "VEL"},
            {"name": "Viluppuram", "slug": "viluppuram", "code": "VPM"}
        ]
    },
    "KA": {
        "name": "Karnataka",
        "slug": "karnataka",
        "districts": [
            {"name": "Bagalkot", "slug": "bagalkot", "code": "BAG"},
            {"name": "Ballari", "slug": "ballari", "code": "BAL"},
            {"name": "Belagavi", "slug": "belagavi", "code": "BEL"},
            {"name": "Bengaluru Rural", "slug": "bengaluru-rural", "code": "BLR-R"},
            {"name": "Bengaluru Urban", "slug": "bengaluru-urban", "code": "BLR"},
            {"name": "Bidar", "slug": "bidar", "code": "BID"},
            {"name": "Chamarajanagar", "slug": "chamarajanagar", "code": "CHM"},
            {"name": "Chikkaballapur", "slug": "chikkaballapur", "code": "CBP"},
            {"name": "Chikkamagaluru", "slug": "chikkamagaluru", "code": "CKM"},
            {"name": "Chitradurga", "slug": "chitradurga", "code": "CHI"},
            {"name": "Dakshina Kannada", "slug": "dakshina-kannada", "code": "DKN"},
            {"name": "Davanagere", "slug": "davanagere", "code": "DAV"},
            {"name": "Dharwad", "slug": "dharwad", "code": "DHA"},
            {"name": "Gadag", "slug": "gadag", "code": "GAD"},
            {"name": "Hassan", "slug": "hassan", "code": "HAS"},
            {"name": "Haveri", "slug": "haveri", "code": "HAV"},
            {"name": "Kalaburagi", "slug": "kalaburagi", "code": "KLB"},
            {"name": "Kodagu", "slug": "kodagu", "code": "KOD"},
            {"name": "Kolar", "slug": "kolar", "code": "KOL"},
            {"name": "Koppal", "slug": "koppal", "code": "KOP"},
            {"name": "Mandya", "slug": "mandya", "code": "MAN"},
            {"name": "Mysuru", "slug": "mysuru", "code": "MYS"},
            {"name": "Raichur", "slug": "raichur", "code": "RAI"},
            {"name": "Ramanagara", "slug": "ramanagara", "code": "RAM"},
            {"name": "Shivamogga", "slug": "shivamogga", "code": "SHM"},
            {"name": "Tumakuru", "slug": "tumakuru", "code": "TUM"},
            {"name": "Udupi", "slug": "udupi", "code": "UDP"},
            {"name": "Uttara Kannada", "slug": "uttara-kannada", "code": "UKN"},
            {"name": "Vijayapura", "slug": "vijayapura", "code": "VIJ"},
            {"name": "Vijayanagara", "slug": "vijayanagara", "code": "VJN"},
            {"name": "Yadgir", "slug": "yadgir", "code": "YAD"}
        ]
    },
    "AP": {
        "name": "Andhra Pradesh",
        "slug": "andhra-pradesh",
        "districts": [
            {"name": "Alluri Sitharama Raju", "slug": "alluri-sitharama-raju", "code": "ASR"},
            {"name": "Anakapalli", "slug": "anakapalli", "code": "AKP"},
            {"name": "Anantapur", "slug": "anantapur", "code": "ATP"},
            {"name": "Annamayya", "slug": "annamayya", "code": "AMY"},
            {"name": "Bapatla", "slug": "bapatla", "code": "BPT"},
            {"name": "Chittoor", "slug": "chittoor", "code": "CTR"},
            {"name": "East Godavari", "slug": "east-godavari", "code": "EG"},
            {"name": "Eluru", "slug": "eluru", "code": "ELR"},
            {"name": "Guntur", "slug": "guntur", "code": "GNT"},
            {"name": "Kakinada", "slug": "kakinada", "code": "KKD_AP"},
            {"name": "Konaseema", "slug": "konaseema", "code": "KSM"},
            {"name": "Krishna", "slug": "krishna", "code": "KRI"},
            {"name": "Kurnool", "slug": "kurnool", "code": "KNL"},
            {"name": "Nandyal", "slug": "nandyal", "code": "NDL"},
            {"name": "NTR", "slug": "ntr", "code": "NTR"},
            {"name": "Palnadu", "slug": "palnadu", "code": "PLD"},
            {"name": "Parvathipuram Manyam", "slug": "parvathipuram-manyam", "code": "PPM"},
            {"name": "Prakasam", "slug": "prakasam", "code": "PKM"},
            {"name": "Nellore", "slug": "nellore", "code": "NLR"},
            {"name": "Sri Sathya Sai", "slug": "sri-sathya-sai", "code": "SSS"},
            {"name": "Srikakulam", "slug": "srikakulam", "code": "SKM"},
            {"name": "Tirupati", "slug": "tirupati", "code": "TPT_AP"},
            {"name": "Visakhapatnam", "slug": "visakhapatnam", "code": "VSP"},
            {"name": "Vizianagaram", "slug": "vizianagaram", "code": "VZM"},
            {"name": "West Godavari", "slug": "west-godavari", "code": "WG"},
            {"name": "YSR Kadapa", "slug": "ysr-kadapa", "code": "KDP"}
        ]
    },
    "TG": {
        "name": "Telangana",
        "slug": "telangana",
        "districts": [
            {"name": "Adilabad", "slug": "adilabad", "code": "ADB"},
            {"name": "Bhadradri Kothagudem", "slug": "bhadradri-kothagudem", "code": "BKT"},
            {"name": "Hanamkonda", "slug": "hanamkonda", "code": "HNK"},
            {"name": "Hyderabad", "slug": "hyderabad", "code": "HYD"},
            {"name": "Jagtial", "slug": "jagtial", "code": "JGT"},
            {"name": "Jangaon", "slug": "jangaon", "code": "JNG"},
            {"name": "Jayashankar Bhupalpally", "slug": "jayashankar-bhupalpally", "code": "JBP"},
            {"name": "Jogulamba Gadwal", "slug": "jogulamba-gadwal", "code": "JGW"},
            {"name": "Kamareddy", "slug": "kamareddy", "code": "KMR"},
            {"name": "Karimnagar", "slug": "karimnagar", "code": "KMN"},
            {"name": "Khammam", "slug": "khammam", "code": "KHM"},
            {"name": "Kumuram Bheem Asifabad", "slug": "kumuram-bheem-asifabad", "code": "KBA"},
            {"name": "Mahabubabad", "slug": "mahabubabad", "code": "MHB"},
            {"name": "Mahabubnagar", "slug": "mahabubnagar", "code": "MBN"},
            {"name": "Mancherial", "slug": "mancherial", "code": "MCL"},
            {"name": "Medak", "slug": "medak", "code": "MDK"},
            {"name": "Medchal-Malkajgiri", "slug": "medchal-malkajgiri", "code": "MMG"},
            {"name": "Mulugu", "slug": "mulugu", "code": "MLG"},
            {"name": "Nagarkurnool", "slug": "nagarkurnool", "code": "NGK"},
            {"name": "Nalgonda", "slug": "nalgonda", "code": "NLG"},
            {"name": "Narayanpet", "slug": "narayanpet", "code": "NYP"},
            {"name": "Nirmal", "slug": "nirmal", "code": "NML"},
            {"name": "Nizamabad", "slug": "nizamabad", "code": "NZB"},
            {"name": "Peddapalli", "slug": "peddapalli", "code": "PDP"},
            {"name": "Rajanna Sircilla", "slug": "rajanna-sircilla", "code": "RSC"},
            {"name": "Rangareddy", "slug": "rangareddy", "code": "RRD"},
            {"name": "Sangareddy", "slug": "sangareddy", "code": "SRD"},
            {"name": "Siddipet", "slug": "siddipet", "code": "SDP"},
            {"name": "Suryapet", "slug": "suryapet", "code": "SRP"},
            {"name": "Vikarabad", "slug": "vikarabad", "code": "VKB"},
            {"name": "Wanaparthy", "slug": "wanaparthy", "code": "WNP"},
            {"name": "Warangal", "slug": "warangal", "code": "WGL"},
            {"name": "Yadadri Bhuvanagiri", "slug": "yadadri-bhuvanagiri", "code": "YBG"}
        ]
    }
}

async def seed_db(name, url, is_sqlite=False):
    print(f"\nSeeding {name}...")
    try:
        connect_args = {}
        if not is_sqlite and "localhost" not in url and "127.0.0.1" not in url:
            connect_args = {"ssl": True}
        engine = create_async_engine(url, connect_args=connect_args, echo=False)
        async_session = async_sessionmaker(
            bind=engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False
        )
        
        async with async_session() as db:
            for state_code, state_data in south_indian_states.items():
                # Get or create state
                state_stmt = select(StateMaster).filter(StateMaster.code == state_code)
                state_res = await db.execute(state_stmt)
                state_obj = state_res.scalars().first()
                
                if not state_obj:
                    state_obj = StateMaster(
                        id=uuid.uuid4(),
                        name=state_data["name"],
                        slug=state_data["slug"],
                        code=state_code
                    )
                    db.add(state_obj)
                    await db.flush()
                    print(f"Created State: {state_data['name']}")
                else:
                    print(f"State exists: {state_data['name']}")
                
                # Get or create districts
                for dist in state_data["districts"]:
                    dist_stmt = select(DistrictMaster).filter(
                        DistrictMaster.state_id == state_obj.id,
                        DistrictMaster.slug == dist["slug"]
                    )
                    dist_res = await db.execute(dist_stmt)
                    dist_obj = dist_res.scalars().first()

                    
                    if not dist_obj:
                        dist_obj = DistrictMaster(
                            id=uuid.uuid4(),
                            state_id=state_obj.id,
                            name=dist["name"],
                            slug=dist["slug"],
                            code=dist["code"]
                        )
                        db.add(dist_obj)
                        print(f"  Created District: {dist['name']}")
            
            await db.commit()
            print(f"Seeding completed successfully for {name}!")
        await engine.dispose()
    except Exception as e:
        print(f"Failed to seed {name}: {e}")

async def main():
    # 1. SQLite Local
    sqlite_url = "sqlite+aiosqlite:///c:/Denumrutham/backend/tms_local_sqlite.db"
    await seed_db("Local SQLite", sqlite_url, is_sqlite=True)
    
    # 2. Local Postgres (if running)
    local_pg_url = "postgresql+asyncpg://postgres:postgres@localhost:5432/tms_postgres"
    await seed_db("Local PostgreSQL (5432)", local_pg_url)
    
    # 3. Production Neon DB
    neon_url = "postgresql+asyncpg://neondb_owner:npg_Zwt1jpEPrWd7@ep-curly-shape-aow2jmi7-pooler.c-2.ap-southeast-1.aws.neon.tech/neondb"
    await seed_db("Production Neon DB", neon_url)

if __name__ == "__main__":
    asyncio.run(main())
