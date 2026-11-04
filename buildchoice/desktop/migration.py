"""Backup-aware migration and offline rollback for the active decision ledger."""
import uuid
import sqlite3
from contextlib import closing
from pathlib import Path


def migrate_decision_database(workspace):
    """Add independent V3 tables, backing up before first migration."""
    from .decision_store import DecisionStore
    store=DecisionStore(workspace)
    return {'migration_version':1,'database':str(store.database),'audit_v1_semantics_changed':False,
            'backup':str(store.database.with_name(store.database.name+'.before-v3.bak'))}


def rollback_decision_database(workspace):
    """Explicit offline rollback. Preserve current audit.v1 rows and back up all V3 data."""
    from .audit import Ledger
    ledger=Ledger(workspace)
    backup=ledger.database.with_name(ledger.database.name+'.before-v3-rollback-'+uuid.uuid4().hex+'.bak')
    with ledger.connect() as db:
        with closing(sqlite3.connect(backup)) as out:db.backup(out)
        tables=[r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 'decision_v3_%'")]
        allowed={'decision_v3_migrations','decision_v3_tasks','decision_v3_items','decision_v3_confirmations',
                 'decision_v3_contexts','decision_v3_active','decision_v3_operations','decision_v3_events'}
        if not set(tables)<=allowed:raise ValueError('Unknown V3 table, refusing rollback')
        db.execute('BEGIN IMMEDIATE')
        for name in ('decision_v3_confirmations','decision_v3_items','decision_v3_contexts','decision_v3_active',
                     'decision_v3_operations','decision_v3_events','decision_v3_tasks','decision_v3_migrations'):
            db.execute('DROP TABLE IF EXISTS '+name)
    return {'rolled_back':True,'full_backup':str(backup),'audit_v1_preserved':True}
