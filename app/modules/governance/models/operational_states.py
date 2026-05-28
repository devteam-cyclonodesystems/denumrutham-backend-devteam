import enum

class TempleOperationalState(str, enum.Enum):
    ACTIVE = "ACTIVE"
    DEACTIVATED = "DEACTIVATED"
    SUSPENDED = "SUSPENDED"
    READ_ONLY = "READ_ONLY"
    QUARANTINED = "QUARANTINED"
    INVESTIGATION = "INVESTIGATION"
    SYNC_LOCKED = "SYNC_LOCKED"
    OFFLINE_ONLY = "OFFLINE_ONLY"
    RECOVERY_MODE = "RECOVERY_MODE"

class OperationalCapability(str, enum.Enum):
    CAN_LOGIN = "CAN_LOGIN"
    CAN_SYNC = "CAN_SYNC"
    CAN_WRITE = "CAN_WRITE"
    CAN_READ = "CAN_READ"
    CAN_BOOK = "CAN_BOOK"
    CAN_ADMIN = "CAN_ADMIN"
    CAN_RECONCILE = "CAN_RECONCILE"
    CAN_USE_OFFLINE = "CAN_USE_OFFLINE"

# Capability Matrix defining what each state is allowed to do.
STATE_CAPABILITIES = {
    TempleOperationalState.ACTIVE: {
        OperationalCapability.CAN_LOGIN,
        OperationalCapability.CAN_SYNC,
        OperationalCapability.CAN_WRITE,
        OperationalCapability.CAN_READ,
        OperationalCapability.CAN_BOOK,
        OperationalCapability.CAN_ADMIN,
        OperationalCapability.CAN_RECONCILE,
        OperationalCapability.CAN_USE_OFFLINE,
    },
    TempleOperationalState.DEACTIVATED: {
        # Graceful disable: mostly blocked, but allows admin reading for audit.
        OperationalCapability.CAN_READ,
    },
    TempleOperationalState.SUSPENDED: {
        # Emergency lock: block everything.
        OperationalCapability.CAN_READ, # Allow superadmin only view (handled in policy evaluator)
    },
    TempleOperationalState.READ_ONLY: {
        OperationalCapability.CAN_LOGIN,
        OperationalCapability.CAN_READ,
        OperationalCapability.CAN_SYNC, # Can pull, but pushes will be blocked by CAN_WRITE
    },
    TempleOperationalState.QUARANTINED: {
        OperationalCapability.CAN_LOGIN,
        OperationalCapability.CAN_READ,
        # Sync is locked/frozen
    },
    TempleOperationalState.INVESTIGATION: {
        OperationalCapability.CAN_LOGIN,
        OperationalCapability.CAN_READ,
    },
    TempleOperationalState.SYNC_LOCKED: {
        OperationalCapability.CAN_LOGIN,
        OperationalCapability.CAN_WRITE,
        OperationalCapability.CAN_READ,
        OperationalCapability.CAN_BOOK,
        OperationalCapability.CAN_ADMIN,
        # CAN_SYNC and CAN_RECONCILE removed
    },
    TempleOperationalState.OFFLINE_ONLY: {
        OperationalCapability.CAN_LOGIN,
        OperationalCapability.CAN_WRITE,
        OperationalCapability.CAN_READ,
        OperationalCapability.CAN_BOOK,
        OperationalCapability.CAN_ADMIN,
        OperationalCapability.CAN_USE_OFFLINE,
        # CAN_SYNC removed (blocks cloud sync)
    },
    TempleOperationalState.RECOVERY_MODE: {
        OperationalCapability.CAN_READ,
        OperationalCapability.CAN_ADMIN,
    },
}
