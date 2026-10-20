# Agent Hub 0.1.10

A fix for `agent-hub reorder --apply`, which could not finish on a large project. No archived record, identity or normalized text changes.

**Foreign-key child columns are indexed.** Rebuilding the tree deletes every node of the project, and SQLite checks each deleted node for children through `tree_nodes.left_id` and `right_id`. Neither column had its own index, so every deletion scanned the whole project: the work grew with the square of the tree size. On a home archive of about 497,000 records (993,502 tree nodes) the reorder spent 40 minutes in that first delete, reading over 1.3 TB from cache while holding the write lock that capture uploads wait for. It was stopped; the uncommitted transaction rolled back and nothing changed.

Indexes now cover `tree_nodes(left_id, project)`, `(right_id, project)` and `(event_id, project)`, and the same gap in `memories` (`supersedes`, `superseded_by`), `memory_sources(event_id)`, `memory_keys(memory_id)` and `memory_reviews` (`memory_id`, `related_memory_id`), which affected forgetting and review on large projects. They are created with `IF NOT EXISTS` when the database opens, so an existing archive gains them on the first start of 0.1.10; the schema version is unchanged and 0.1.9 can still open the database. A test checks every foreign key in the schema has a usable index.

The 0.1.9 instructions apply unchanged: back up, run `agent-hub reorder --project P` to read the report, then `--apply`.
