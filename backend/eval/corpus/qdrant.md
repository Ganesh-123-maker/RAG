# Qdrant: A Vector Database

Qdrant is an open-source vector database. Each stored item is called a
point. A point has an identifier, a vector, and an optional payload of
metadata such as a document name, a chunk index, and an owner
identifier. Searches return points ordered by a similarity score.

## Collections and distance

Points live in collections. When a collection is created, the caller
chooses a vector size and a distance metric. Cosine similarity is the
usual choice for text embeddings, because it measures the angle between
two vectors rather than their length. Dot product and Euclidean
distance are also available, but mixing metrics inside one collection
is not allowed.

## Filtering

Qdrant supports payload filtering with conditions on payload fields.
A filter can require that `owner_id` equals a given user, or that
`document_id` equals a given document, or both. Filters are applied
during the search, so a user only ever sees their own points even
when many users share one collection.

## Deployment facts used in this guide

The example cluster in this guide uses a replication factor of 2 and
4 shards. The REST API listens on port 6333 and the gRPC API listens
on port 6334. Qdrant can run in memory for tests, on a single server
with a data directory for small deployments, or as a managed cloud
cluster. Scalar quantization can shrink stored vectors to roughly a
quarter of their original size at a small recall cost, which is useful
when memory is the limiting resource.

## Why Qdrant fits retrieval-augmented generation

Retrieval-augmented generation needs fast, filtered, ranked retrieval
over chunk embeddings, plus the ability to delete all points for one
document when that document is removed. Qdrant provides both: filtered
search by payload and deletion by a filter selector. A collection
whose vector size does not match the embedding model must not be used
silently; the size mismatch should be reported as an error, because
searching or upserting against the wrong size produces failures that
are hard to diagnose later.
