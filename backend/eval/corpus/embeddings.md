# Text Embeddings

A text embedding is a vector of numbers produced by an embedding
model from a piece of text. Texts with similar meanings produce
vectors that are close together under a similarity measure, usually
cosine similarity. Embeddings let a system search by meaning rather
than by exact keyword match: a question about "canine behaviour"
can retrieve a document about dogs even though the two texts share
no keyword.

## A concrete model

The embedding model used as the example in this guide is
text-embedding-3-large. It produces vectors with 3072 dimensions by
default. The same model can produce shorter vectors on request, for
example 256 dimensions, by passing a dimensions parameter. Shorter
vectors use less storage and are faster to search, at some cost to
quality on fine-grained distinctions.

## Properties that matter for retrieval

Embedding vectors for retrieval are normally compared with cosine
similarity, which is insensitive to vector length. Some pipelines
also normalise vectors to unit length before storing them, which
makes cosine similarity equivalent to a dot product. Normalisation
must be consistent between indexing and querying: if indexed vectors
are normalised but query vectors are not, scores are still comparable
under cosine, but any code that assumes unit length will be wrong.

Batching matters for cost and speed. Embedding APIs accept a list of
inputs in one request, and this guide caps each request at 100
inputs. A document with more chunks than that is split into several
requests. Sending one chunk per request would multiply the number of
round trips and usually the cost as well.

## Failure behaviour

An embedding failure must not be hidden. If an embedding request
fails and the system substitutes a random or hash-derived vector,
that vector will be indexed as if it were real. Later searches will
return it with a meaningless score, and nothing in the stored data
marks it as fake. The correct behaviour is to raise an error, mark
the document as failed, and let the user retry. A failed embedding
is an operational problem; a fake embedding is a data-corruption
problem, and the two must never be confused.
