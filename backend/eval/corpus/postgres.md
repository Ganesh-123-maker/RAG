# PostgreSQL: A Relational Database

PostgreSQL is a relational database that stores data in tables with
rows and columns. It is known for correctness: transactions follow
ACID properties, meaning they are atomic, consistent, isolated, and
durable. An atomic transaction either applies all of its changes or
none of them. Durability means that once a transaction is committed,
it survives a crash.

## Concurrency with MVCC

PostgreSQL uses multiversion concurrency control, shortened to MVCC.
Under MVCC, a writer creates a new version of a row instead of
overwriting it in place, so readers can continue reading the old
version without waiting for a lock. This is why read-heavy workloads
scale well on PostgreSQL even while writes are happening.

## Indexes and durability

The default index type is the B-tree, which supports equality and
range queries efficiently. An index speeds up lookups but slows down
writes slightly and uses disk space, so indexes should be created for
queried columns, not for every column. Durability is provided by the
write-ahead log, shortened to WAL: changes are written to the log
before they are applied to the main data files, so a crash can be
recovered by replaying the log.

## Practical facts used in this guide

PostgreSQL listens on port 5432 by default. Connections are
relatively expensive to create, so production applications use a
connection pool that reuses a fixed set of open connections instead
of opening a new one per request. Isolation levels control what one
transaction can observe of another: read committed is the default,
and serializable is the strictest level, which behaves as if
transactions ran one after another. Choosing the strictest level
everywhere is safe but can cause more transaction retries under
contention, so the level should match the workload.
