from passlib.context import CryptContext

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")
h = "$2b$12$jOXFZraG1DxhdBN8vmM.ke436RNgHDohkr0ruhDzoUffNAKX.MLZS"
p = "AdminPassword123!"

try:
    matches = pwd_context.verify(p, h)
    print(f"Match: {matches}")
except Exception as e:
    print(f"Error: {e}")
