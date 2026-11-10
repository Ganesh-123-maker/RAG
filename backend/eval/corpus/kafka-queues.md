# Apache Kafka: Topics, Partitions, and Consumer Groups

Kafka is a distributed event log. Producers append records to topics, and consumers read them. A topic is split into partitions, and each partition is an ordered, append-only sequence of records. Ordering is guaranteed only within a single partition, never across partitions, so the choice of partition key decides which records stay ordered relative to each other. A record's position inside its partition is its offset, a monotonically increasing number that consumers use to track how far they have read.

Consumers read in consumer groups. Each partition is assigned to exactly one consumer inside a group, so a group with three consumers splits a six-partition topic two partitions each. Adding a consumer triggers a rebalance: partitions are reassigned across the group, and during the rebalance no one in the group consumes. Two different groups reading the same topic are independent -- each group tracks its own offsets, so the same record can be processed once by billing and once by analytics without either affecting the other.

Kafka retains records after they are consumed. The default retention is 7 days, after which old segments are deleted, though retention can also be set by total size. Because data stays available, a consumer can rewind its offsets and replay history, which is how a new consumer group backfills or a broken one recovers.

Delivery semantics are a trade-off. At-least-once delivery, the default, can redeliver after a crash, so consumers must be idempotent. Exactly-once delivery is possible with an idempotent producer plus transactions, but it costs throughput and only holds within Kafka itself. The common production choice is at-least-once with idempotent consumers.
