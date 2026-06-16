from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

DATABASE_URL = "sqlite:///./qa_checklist.db"

engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def ensure_indexes():
    indexes = [
        ("ix_audit_logs_created_at", "audit_logs", "created_at"),
        ("ix_audit_logs_username_created", "audit_logs", "username, created_at"),
        ("ix_audit_logs_action_created", "audit_logs", "action, created_at"),
        ("ix_audit_logs_resource_created", "audit_logs", "resource_type, resource_id, created_at"),
        ("ix_score_revisions_execution_created", "score_revisions", "execution_id, created_at"),
        ("ix_score_revisions_item_created", "score_revisions", "execution_item_id, created_at"),
        ("ix_executions_batch_no", "executions", "batch_no"),
        ("ix_executions_product_created", "executions", "product_line_id, created_at"),
        ("ix_executions_template_created", "executions", "template_id, created_at"),
        ("ix_nonconformances_execution", "nonconformances", "execution_id"),
        ("ix_nonconformances_status_created", "nonconformances", "status, created_at"),
        ("ix_rectifications_nc", "rectifications", "nonconformance_id"),
        ("ix_rectifications_assignee_created", "rectifications", "assignee, created_at"),
        ("ix_reviews_execution", "reviews", "execution_id"),
        ("ix_rbac_role_resource_action", "rbac_matrix", "role, resource, action"),
        ("ix_consensus_execution_voter", "arbitration_consensus", "execution_id, voter"),
        ("ix_transfers_rectification", "rectification_transfers", "rectification_id"),
        ("ix_transfer_approvals_transfer", "transfer_approvals", "transfer_id"),
        ("ix_nc_escalation_rule_level", "nc_escalation_rules", "severity_level"),
    ]
    with engine.connect() as conn:
        for name, table, columns in indexes:
            try:
                conn.execute(text(
                    f"CREATE INDEX IF NOT EXISTS {name} ON {table} ({columns})"
                ))
            except Exception:
                pass
        conn.commit()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
