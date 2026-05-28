import asyncio
import uuid
import sys
import os

# Set up paths to import the app modules
backend_dir = os.path.dirname(os.path.abspath(__file__))
if backend_dir not in sys.path:
    sys.path.insert(0, backend_dir)

from app.repositories.base import _to_uuid

def test_uuid_robustness():
    print("Testing UUID conversion robustness...")
    
    # Valid UUID string
    val_uuid = "b4be09c8-930a-409a-840e-7440938fc28e"
    res1 = _to_uuid(val_uuid)
    print(f"Valid UUID string '{val_uuid}' -> {type(res1)}: {res1}")
    assert isinstance(res1, uuid.UUID)

    # Invalid UUID string 'TEMP001'
    inv_uuid = "TEMP001"
    res2 = _to_uuid(inv_uuid)
    print(f"Invalid UUID string '{inv_uuid}' -> {type(res2)}: {res2}")
    assert res2 is None  # Should be None now

    # None
    res3 = _to_uuid(None)
    print(f"None -> {type(res3)}: {res3}")
    assert res3 is None
    
    print("\n[SUCCESS] Robust UUID conversion verified.")

if __name__ == "__main__":
    test_uuid_robustness()
