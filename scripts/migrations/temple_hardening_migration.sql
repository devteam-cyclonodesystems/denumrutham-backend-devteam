-- 1. Handle existing NULL values safely
UPDATE temples SET status = 'PENDING' WHERE status IS NULL;

-- 2. Enforce DB-level integrity
ALTER TABLE temples ALTER COLUMN status SET DEFAULT 'PENDING';
ALTER TABLE temples ALTER COLUMN status SET NOT NULL;

-- 3. Performance Optimization - Partial Index
CREATE INDEX IF NOT EXISTS idx_temples_visible 
ON temples (id) 
WHERE status = 'APPROVED' AND is_active = TRUE;

-- 4. Audit Trail Implementation
CREATE TABLE IF NOT EXISTS temple_status_audit (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    temple_id UUID NOT NULL REFERENCES temples(id) ON DELETE CASCADE,
    old_status TEXT NOT NULL,
    new_status TEXT NOT NULL,
    changed_by UUID REFERENCES users(id) ON DELETE SET NULL,
    changed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    reason TEXT
);

-- Index for querying audit history by temple
CREATE INDEX IF NOT EXISTS idx_temple_status_audit_temple_id ON temple_status_audit(temple_id);
