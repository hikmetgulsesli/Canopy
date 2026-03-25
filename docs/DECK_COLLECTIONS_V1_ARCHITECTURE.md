# Deck Collections V1 Architecture

## Objective

Allow a human or agent to organize favorite deck-targeted sources in a private `Decks` page without copying the underlying source payloads or widening access to them.

## Recommended Narrow V1

Build deck collections as an extension of bookmarks, not as a separate copied-content system.

That means:
- each collection entry stores a source reference, not a duplicated deck or post payload;
- each collection entry can preserve a preferred deck target, reopen link, and return-context hint;
- reopening from a collection reuses the same access checks that apply to the original source; and
- collections remain actor-scoped and local-first by default.

## Suggested data model

### 1. Collection record

- `deck_collection_id`
- `actor_id`
- `collection_title`
- `created_at`
- `updated_at`

### 2. Collection entry

- `entry_id`
- `deck_collection_id`
- `saved_source_type`
- `saved_source_id`
- `preferred_deck_ref`
- `reopen_url`
- `saved_return_context`
- `sort_order`
- `notes`
- `tags`
- `saved_at`
- `last_opened_at`

## Load and reopen path

Recommended runtime sequence:
1. actor opens `Decks`
2. host loads actor-scoped collection records
3. actor selects a saved source entry
4. host revalidates access to the underlying source
5. if access is still valid, host reopens the source through the saved deep link and preferred deck target
6. if access is no longer valid, host shows an unavailable entry state rather than exposing copied content

## Security and privacy constraints

Do not allow:
- copied deck payloads stored independently of the source
- default mesh broadcast of a user's private deck collections
- bypass of current source access rules when reopening from a collection
- collection entries that expose source content after the source becomes unavailable

Collections should remain private and actor-scoped unless later explicit sharing is added as a separate feature.

## UX recommendation

Visible collection actions:
- `Save to Decks`
- `Open`
- `Reorder`
- `Tag`
- `Add note`
- `Remove`

This should feel like a private library of source-bound operational items, not a generic playlist view.

## Implementation difficulty

Moderate.

Main work:
- collection records layered on top of bookmarks
- reorder/tag/note metadata
- access revalidation on reopen
- unavailable-entry handling
- a dedicated `Decks` page

## Recommendation

If this is built, start with:
- actor-scoped private collections
- source references only
- preferred deck target preservation
- reopen path reuse from bookmarks

Do not build copied deck payloads, collaborative sharing, or social playlist behavior first.
