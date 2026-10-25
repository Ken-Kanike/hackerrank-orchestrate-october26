"""Single source of truth for resource-id families, systems and observation-kind -> data-category mapping."""
from __future__ import annotations

import re
from functools import lru_cache

SYS_OF_PREFIX = {"account": "account_service", "search": "search_service", "analytics": "analytics_platform",
                 "support": "support_platform", "export": "export_service", "data_flow": "integration_service",
                 "backup": "backup_service", "audit_record": "security_service", "tombstone": "identity_service",
                 "legal_hold": "legal_service", "marketing": "marketing_platform", "object": "object_storage"}

# State shown by a screenshot/PDF whose row we could not read (state is then *unverified*; see evidence.catalog_obs).
PREFIX_STATE = {"account": "PRESENT", "search": "PRESENT", "analytics": "PII", "support": "PII", "export": "PRESENT",
                "data_flow": "ACTIVE", "backup": "RESTORABLE", "audit_record": "RETAINED", "tombstone": "CLEAN",
                "marketing": "PRESENT", "object": "PRESENT", "legal_hold": "RETAINED"}

# Observation kind (collection / record_type / log event) -> deletion_rules.csv data_category.
CATEGORY_OF = {
    "customer_profiles": "USER_PROFILE", "USER_PROFILE": "USER_PROFILE", "profile_lookup_completed": "USER_PROFILE",
    "profile_lookups": "USER_PROFILE",
    "customer_search_documents": "SEARCH_INDEX_ENTRY", "search_documents_primary": "SEARCH_INDEX_ENTRY",
    "SEARCH_INDEX_ENTRY": "SEARCH_INDEX_ENTRY", "index_queries": "SEARCH_INDEX_ENTRY", "index_query_completed": "SEARCH_INDEX_ENTRY",
    "support_conversations": "SUPPORT_MESSAGE", "support_records": "SUPPORT_MESSAGE", "tickets": "SUPPORT_MESSAGE",
    "SUPPORT_MESSAGE": "SUPPORT_MESSAGE", "message_pii_scan": "SUPPORT_MESSAGE", "message_read": "SUPPORT_MESSAGE",
    "support_ticket_read_completed": "SUPPORT_MESSAGE",
    "ticket_attachments": "SUPPORT_ATTACHMENT", "SUPPORT_ATTACHMENT": "SUPPORT_ATTACHMENT", "attachment_pii_scan": "SUPPORT_ATTACHMENT",
    "customer_analytics_reports": "ANALYTICS_PROFILE", "customer_analytics_profiles": "ANALYTICS_PROFILE", "profiles": "ANALYTICS_PROFILE",
    "ANALYTICS_PROFILE": "ANALYTICS_PROFILE", "analytics_profile_read": "ANALYTICS_PROFILE",
    "analytics_profile_read_completed": "ANALYTICS_PROFILE", "analytics_identity_scan": "ANALYTICS_PROFILE",
    # a *contact* lookup (analytics or support replica) finds a secondary identifier, not the profile itself
    "contact_lookup_completed": "SECONDARY_IDENTIFIER", "contact_query_completed": "SECONDARY_IDENTIFIER",
    "customer_export_jobs": "USER_EXPORT", "customer_exports": "USER_EXPORT", "exports": "USER_EXPORT", "USER_EXPORT": "USER_EXPORT",
    "export_download_check_completed": "USER_EXPORT", "export_metadata_read_completed": "USER_EXPORT",
    "security_audit_events": "SECURITY_AUDIT_LOG", "security_audit_records": "SECURITY_AUDIT_LOG", "audit_records": "SECURITY_AUDIT_LOG",
    "SECURITY_AUDIT_LOG": "SECURITY_AUDIT_LOG", "audit_record_read_completed": "SECURITY_AUDIT_LOG",
    "retained_order_records": "LEGAL_HOLD_RECORD", "LEGAL_HOLD_RECORD": "LEGAL_HOLD_RECORD", "retained_order_loaded": "LEGAL_HOLD_RECORD",
    "backup_catalog": "BACKUP_ARCHIVE", "backup_restore_entries": "BACKUP_ARCHIVE", "restore_entries": "BACKUP_ARCHIVE",
    "BACKUP_ARCHIVE": "BACKUP_ARCHIVE", "restore_policy_read_completed": "BACKUP_ARCHIVE",
    "restore_candidate_evaluated": "BACKUP_ARCHIVE", "restore_authorization_completed": "BACKUP_ARCHIVE",
    "deleted_customer_references": "ACCOUNT_TOMBSTONE",
    "connector_configurations": "DATA_FLOW", "connector_subscriptions": "DATA_FLOW", "connectors": "DATA_FLOW", "DATA_FLOW": "DATA_FLOW",
    "connector_config_read_completed": "DATA_FLOW", "connector_config_loaded": "DATA_FLOW", "connector_heartbeat": "DATA_FLOW",
}
# Fallback when the kind is unknown (screenshots / PDFs / resources with no observation): decided by the resource-id family.
CATEGORY_OF_PREFIX = {"account": "USER_PROFILE", "search": "SEARCH_INDEX_ENTRY", "analytics": "ANALYTICS_PROFILE",
                      "support": "SUPPORT_MESSAGE", "export": "USER_EXPORT", "data_flow": "DATA_FLOW", "backup": "BACKUP_ARCHIVE",
                      "audit_record": "SECURITY_AUDIT_LOG", "legal_hold": "LEGAL_HOLD_RECORD", "tombstone": "ACCOUNT_TOMBSTONE",
                      "marketing": "MARKETING_PROFILE", "object": "SUPPORT_ATTACHMENT", "cache": "CACHE_ENTRY",
                      "email_delivery": "EMAIL_DELIVERY_LOG"}


@lru_cache(maxsize=None)
def prefix(rid: str) -> str:
    return re.sub(r"_\d+$", "", rid)
