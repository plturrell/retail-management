"""SQL (TiDB Cloud / MySQL-compatible) data layer.

The Firestore client (`app.firestore`) remains the primary system of record
during the dual-write migration. Anything in this package is additive: callers
that import from here must tolerate `TIDB_DATABASE_URL` being unset and fall
back to a no-op so single-store deployments don't require a SQL cluster.
"""
