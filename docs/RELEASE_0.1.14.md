# Agent Hub 0.1.14

Notes can be deleted and filtered in the browser. No archived record, identity or normalized text changes, and the schema is unchanged.

**Delete a note permanently.** A rejected note now has a **Delete…** action for administrators; an active note is retired first. After a confirmation, the note's statement, search entry, source links, idempotency keys and review history are erased, including the review of a note it replaced. That note keeps its status and loses the link. The chats the note came from stay in memory: forgetting a chat is still the way to remove its records. Nothing remembers a deleted statement, so an agent could propose it again; a rejected note, by contrast, absorbs a repeat proposal. The REST call is `DELETE /v1/projects/{project}/memories/{id}`, administrator only. Agents have no tool for it.

**Filter notes.** The Notes page has a filter box for each status. It runs on the server, so it also finds notes beyond the newest 200, and it keeps notes whose statement contains every word typed (ASCII letters case-insensitive). Search leaves out rejected and superseded notes, so the filter is how to find one to delete. The filter stays in the address, so it follows the status tabs and survives a reload. `GET /v1/projects/{project}/memories` takes the same filter as `query`.

**Context preview at the startup size.** The Agent context page said the startup hook requests 8,000 characters; since 0.1.12 it requests 9,500. The page now says so, and its size menu offers and defaults to 9,500.

Upgrade: install and restart the server. Clients are unchanged.
