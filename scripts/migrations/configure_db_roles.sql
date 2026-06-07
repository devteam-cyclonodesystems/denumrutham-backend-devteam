-- Database Role Segregation for Audit Chain Integrity Compliance
--
-- This script configures two distinct database roles to enforce Single Writer architecture:
-- 1. tms_api_user: Used by the web application for operational CRUD. Revokes direct writes to audit logs/registries.
-- 2. tms_worker_user: Used by background processors/workers for executing outbox processing.

-- Revoke write privileges on audit tables from the standard API user
REVOKE INSERT, UPDATE, DELETE ON TABLE immutable_activity_logs FROM tms_api_user;
REVOKE INSERT, UPDATE, DELETE ON TABLE audit_chain_index_registry FROM tms_api_user;
REVOKE INSERT, UPDATE, DELETE ON TABLE audit_chain_versions FROM tms_api_user;
REVOKE INSERT, UPDATE, DELETE ON TABLE audit_chain_incidents FROM tms_api_user;

-- Ensure API user can only SELECT from audit tables
GRANT SELECT ON TABLE immutable_activity_logs TO tms_api_user;
GRANT SELECT ON TABLE audit_chain_index_registry TO tms_api_user;
GRANT SELECT ON TABLE audit_chain_versions TO tms_api_user;
GRANT SELECT ON TABLE audit_chain_incidents TO tms_api_user;

-- Grant full operational privileges to the worker user
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE activity_outbox TO tms_worker_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE immutable_activity_logs TO tms_worker_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE audit_chain_index_registry TO tms_worker_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE audit_chain_versions TO tms_worker_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE audit_chain_incidents TO tms_worker_user;
