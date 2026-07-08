# Mixtape — Submission

## Codebase Map

### Main files and what they do

| File | Responsibility |
|---|---|
| `app.py` | Application factory (`create_app`). Configures Flask, initializes the `SQLAlchemy` `db` instance, registers all blueprints under their URL prefixes, and creates the database tables on startup. Also holds the `db` object that every model and service imports from. |
| `models.py` | SQLAlchemy models for every entity: `User`, `Tag`, `Song`, `ListeningEvent`, `Rating`, `Playlist`, `Notification`. Also defines three association tables for many-to-many relationships: `friendships` (user↔user), `song_tags` (song↔tag), and `playlist_entries` (playlist↔song, with extra `position`, `added_by`, `added_at` columns). Every model has a `to_dict()` used to serialize it to JSON. |
| `routes/songs.py` | Blueprint `songs_bp`, mounted at `/songs`. Endpoints: search songs (`GET /songs/search`), get one song (`GET /songs/<id>`), rate a song (`POST /songs/<id>/rate`), and log a listen (`POST /songs/<id>/listen`). |
| `routes/playlists.py` | Blueprint `playlists_bp`, mounted at `/playlists`. Endpoints: create a playlist (`POST /playlists/`), get playlist metadata (`GET /playlists/<id>`), list a playlist's songs (`GET /playlists/<id>/songs`), and add a song to a playlist (`POST /playlists/<id>/songs`). |
| `routes/users.py` | Blueprint `users_bp`, mounted at `/users`. Endpoints: get a user profile (`GET /users/<id>`), get a user's streak (`GET /users/<id>/streak`), list a user's notifications (`GET /users/<id>/notifications`), and mark a notification read (`POST /users/notifications/<id>/read`). |
| `routes/feed.py` | Blueprint `feed_bp`, mounted at `/feed`. Endpoints: friends listening right now (`GET /feed/<id>/listening-now`) and a friends' activity feed (`GET /feed/<id>/activity`). |
| `services/streak_service.py` | Business logic for listening streaks: recording a listening event and incrementing/resetting `User.listening_streak` based on how many days have passed since `last_listened_at`. |
| `services/feed_service.py` | Builds the "friends listening now" feed (friends who listened today, deduplicated to one song per friend) and a general activity feed (most recent N events from friends, no recency filter). |
| `services/search_service.py` | Song search by title/artist substring match, and single-song lookup. |
| `services/notification_service.py` | Creates and retrieves `Notification` records, and contains the logic that decides *when* a notification should fire (e.g. when a song is added to a playlist) as well as rating logic (`rate_song`). |
| `services/playlist_service.py` | Playlist CRUD-ish logic: creating a playlist, fetching a playlist's songs in position order, fetching playlist metadata, and listing a user's playlists. |
| `seed_data.py` | Populates the database with 5 users (with friendships), 25 songs (with varying tag counts), 3 playlists, a spread of listening events (recent and old), pre-set streaks, and a sample notification. Run directly with `python seed_data.py`. |
| `tests/` | Pytest suites (`test_streaks.py`, `test_search.py`, `test_playlists.py`, `test_feed.py`) that exercise the service layer directly. |

### Data flow: adding a song to a playlist triggers a notification

This is the clearest end-to-end example of the request → route → service → model → DB chain in the app.

1. **Client** sends `POST /playlists/<playlist_id>/songs` with a JSON body `{"song_id": ..., "added_by": ...}`.
2. **`routes/playlists.py::add_song`** receives the request, pulls `song_id` and `added_by` out of the JSON body, validates that both are present (400 if not), and delegates to `services.notification_service.add_to_playlist(playlist_id, song_id, added_by)`.
3. **`services/notification_service.py::add_to_playlist`** does the actual work:
   - Looks up the `Song`, the adding `User`, and the `Playlist` by ID via `db.session.get(...)`, raising `ValueError` (→ 400 in the route) if any is missing.
   - If the song isn't already in `playlist.songs`, appends it (this writes a row into the `playlist_entries` association table) and commits.
   - Compares `song.shared_by` (the original sharer) to `added_by_user_id`. If they differ — i.e., someone other than the original sharer added the song — it calls `create_notification(...)`.
4. **`create_notification`** builds a `Notification` model instance (`user_id`, `notification_type="song_added_to_playlist"`, a human-readable `body`) and commits it to the database.
5. The route returns `{"message": "Song added to playlist"}` with status 201.
6. Later, the original sharer can retrieve this notification via `GET /users/<user_id>/notifications`, which routes to `routes/users.py::notifications` → `services/notification_service.py::get_notifications`, which queries `Notification` by `user_id` (optionally filtered to unread) ordered newest-first.

So the full chain for this feature is:
`HTTP POST` → `routes/playlists.py` (thin controller) → `services/notification_service.py` (business logic + DB writes via `models.py`) → `Notification` row in SQLite → later read back through `routes/users.py` → `services/notification_service.py`.

### Patterns observed in the app's organization

- **Layered architecture, one direction of dependency.** `routes/` → `services/` → `models.py`/`db`. Routes never touch the database directly (with one small exception: `routes/users.py::get_user` queries `User` directly instead of going through a service). Services never know about Flask/HTTP — they raise plain `ValueError`s, and it's the route's job to translate that into a JSON error response with the right status code.
- **Consistent error convention.** Every service raises `ValueError` for "not found" or "invalid input" cases, and every route wraps its service call in `try/except ValueError` to turn it into a `jsonify({"error": ...})` response (400 for bad input, 404 for missing resources).
- **Blueprints per resource, one prefix each.** `songs_bp`, `playlists_bp`, `users_bp`, `feed_bp` are each registered with a URL prefix in `app.py`, so there's no route for bare `/` — this is a pure JSON API, not a rendered-page app.
- **UUID string primary keys.** Every model uses `db.String(36)` with `generate_uuid()` as the default, rather than auto-incrementing integers.
- **Serialization lives on the model.** Every model defines its own `to_dict()`, so routes/services just call `.to_dict()` rather than hand-building response dicts (except for the composite feed/notification dicts, which are assembled in the service).
- **Association tables carry extra metadata where needed.** `playlist_entries` isn't a bare many-to-many join table — it also stores `position`, `added_by`, and `added_at`, which is what makes ordered playlists and "who added this" possible.
- **The app factory creates tables eagerly.** `create_app()` calls `db.create_all()` inside its own app context every time it's invoked, so both `flask run` and `seed_data.py` (which calls `create_app()` itself) will create the schema if it doesn't exist.
- **Bugs are confined to the service layer by design.** Per the README, the app's five known issues all live in `services/`, not in `routes/` or `models.py` — consistent with the layering above, since the services are where the actual business rules (streak math, recency windows, dedup, notification triggers, ordering) are implemented.

---

## Root Cause Analysis

4 of the 5 listed issues were fixed (Issues #1, #2, #3, #5). Issue #4 (missing notification when a friend rates a shared song) was not attempted.

### Issue #1: Listening streak keeps resetting

**Reproduction Steps:** Called `update_listening_streak` with two genuinely consecutive days that straddle a Saturday → Sunday boundary — `last_listened_at` on Saturday 2024-06-15, then `now` = Sunday 2024-06-16. `days_since_last` computes to 1 (a real consecutive day), but the streak reset to 1 instead of incrementing to 2. The pre-existing test `tests/test_streaks.py::test_streak_increments_on_sunday` encodes this exact scenario.

**Navigation Strategy:** The README maps Issue #1 directly to `streak_service.py`, so I went straight there rather than starting from the route. Before reading any code closely, I ran `pytest tests/test_streaks.py -v` to see the current state: 4 of 5 tests passed, only `test_streak_increments_on_sunday` failed. That immediately narrowed the search to "whatever is different about Sundays specifically," instead of reading the whole file blind. Opening `update_listening_streak`, the three-branch `if/elif/else` computing `days_since_last` was short enough to read end to end, and the `elif` branch stood out because it had a second condition (`and today.weekday() != 6`) that has nothing to do with counting days since the last listen — that mismatch between "this branch is about day deltas" and "this clause is about day-of-week" was the moment I was confident I'd found it.

**Root Cause Explanation:** `date.weekday()` returns Monday=0 … Sunday=6, so `today.weekday() != 6` means "today is not Sunday." The increment branch was `elif days_since_last == 1 and today.weekday() != 6: user.listening_streak += 1`. Because of the `and`, a user who listened on two truly consecutive days still fell through to the `else` (reset to 1) whenever the second day happened to be a Sunday — the correct behavior (increment on any consecutive day) requires that the day-of-week never enter the decision at all.

**Fix Description:** Removed the erroneous weekday clause so the branch depends only on `days_since_last == 1`, in `services/streak_service.py`:
```python
elif days_since_last == 1:
    user.listening_streak += 1
else:
    user.listening_streak = 1
```

**Side-Effect Check:** Grepped the whole codebase for other uses of `weekday(` to make sure this special-case logic wasn't a convention relied on elsewhere (e.g. in notifications or the feed) — the only production-code match was the test file itself (asserting the day-of-week of its fixture timestamps), confirming the clause was isolated to this one branch. Also re-ran the other 4 pre-existing streak tests (same-day dedup, skipped-day reset, new-user default) to confirm none of them changed behavior — they all still pass unmodified, showing the fix only affects the Sunday case and nothing else.

---

### Issue #2: Friends Listening Now shows people from yesterday

**Reproduction Steps:** Reproduced nova's exact report: a listening event at 11pm one night, then checked the feed at 9am the next morning (~10 hours later). Because 10 hours fell inside the old 24-hour rolling window, the friend still appeared as "listening now" even though he hadn't opened the app since the night before.

**Navigation Strategy:** Started at `routes/feed.py::listening_now`, which calls straight into `feed_service.get_friends_listening_now`. The first thing I read was the module-level `RECENT_THRESHOLD = timedelta(hours=24)` constant, since the bug report was specifically about a time window. I recognized it was used as `now - RECENT_THRESHOLD`, i.e. a rolling window, not a calendar-day cutoff. To confirm that the rolling-window *shape* (not just its length) was the actual problem, I compared it against `streak_service.py`, which solves an equivalent "is this still the same day" question using `.date()` comparisons rather than a rolling timedelta — seeing that the rest of the app already had a correct pattern for this exact kind of problem was what convinced me the fix was to change the mechanism, not just shorten 24 hours to something smaller.

**Root Cause Explanation:** The feed used a rolling 24-hour window to decide who counts as "listening now." A rolling window has no relationship to a calendar day: anything from the previous evening stays inside a 24-hour window well into the next morning. The ticket's expected behavior ("only friends who have listened today appear") requires a fixed cutoff at the start of the current calendar day, not a sliding duration.

**Fix Description:** Replaced the rolling-window cutoff with a start-of-today cutoff in `services/feed_service.py`, and added an optional `now` parameter (mirroring `update_listening_streak(user, now)` in `streak_service.py`) so the current time can be injected in tests instead of the function calling `datetime.now()` internally:
```python
def get_friends_listening_now(user_id: str, now: datetime | None = None) -> list[dict]:
    ...
    now = now or datetime.now(timezone.utc)
    start_of_today = datetime.combine(now.date(), time.min, tzinfo=timezone.utc)
    ...
    .filter(
        ListeningEvent.user_id.in_(friend_ids),
        ListeningEvent.listened_at >= start_of_today,
    )
```
The now-unused `RECENT_THRESHOLD` constant was removed.

**Side-Effect Check:** Grepped the codebase for other references to `RECENT_THRESHOLD` before deleting it, to make sure no other function imported it — none found, so removing it couldn't break another caller. Also specifically re-read `get_activity_feed` (the other function in the same file) to confirm it never used `RECENT_THRESHOLD` or the cutoff logic at all (it intentionally shows the most recent N events with no recency filter), so it needed no changes — confirmed by re-running the full suite, which shows both feed functions still working correctly together.

**Regression test:** Added `tests/test_feed.py`, covering both the negative case (11pm-previous-night listener excluded at 9am) and the positive case (2am-same-day listener still shown at 9am). I confirmed this is a genuine regression test, not one that just happens to pass: I temporarily restored the old `now - timedelta(hours=24)` cutoff logic (while keeping the new `now` parameter) and reran `pytest tests/test_feed.py -v` — `test_friend_from_last_night_not_shown_this_morning` failed with `assert feed == []` actually containing darius, reproducing nova's exact report. Restoring the real fix and rerunning the full suite (`pytest tests/ -v`) shows all 15 tests passing.

---

### Issue #3: Same song shows up twice in search

**Reproduction Steps:** `pytest tests/test_search.py -v` passed 5/5 even before touching any code, so the test suite alone didn't show a live failure. `seed_data.py`'s comments specifically flag "songs with 3+ tags" as the ones that expose this issue, so I built a targeted repro: a song with 3 tags, then called `db.session.execute(q.statement).fetchall()` on the raw query `search_songs` builds (bypassing the ORM's entity-loading return path). That returned **3 raw rows** for the one song — one row per matching tag from the join.

**Navigation Strategy:** The README maps Issue #3 to `search_service.py`, and the seed-data comment about multi-tag songs told me exactly what kind of input would trigger it, so I didn't need to guess. When the existing pytest suite passed cleanly despite that, instead of concluding there was no bug, I read `search_songs`'s actual query — an `outerjoin` against `song_tags` — and reasoned about what it should return at the raw-SQL level, independent of whatever the ORM does with the result afterward. Printing `q.statement` and executing it directly via `db.session.execute(...)` instead of `.all()` was the moment of confidence: 3 raw rows for one song proved the join really does fan out, even though the higher-level `Query.all()` call was quietly collapsing the duplicates.

**Root Cause Explanation:** `search_songs` joined `Song` to the `song_tags` association table purely to filter by title/artist — tags are never referenced in the `WHERE` clause, and `Song.to_dict()` already loads tags independently via the `Song.tags` relationship (`lazy="subquery"` in `models.py`). The join was unnecessary and produced one row per matching tag for any song with more than one tag. This didn't show up as a failing test because the installed SQLAlchemy version (2.0.51) automatically de-duplicates ORM entities returned by a legacy `Query.all()` call, silently absorbing the fan-out before it reaches calling code — on an older SQLAlchemy version, or via `session.execute(select(...))` without an explicit `.unique()`, the same query would return duplicate `Song` objects to the caller.

**Fix Description:** Removed the unnecessary join (and the now-unused `Tag`/`song_tags` imports) in `services/search_service.py`, so the query only touches the `song` table:
```python
results = (
    db.session.query(Song)
    .filter(db.or_(Song.title.ilike(f"%{query}%"), Song.artist.ilike(f"%{query}%")))
    .all()
)
```

**Side-Effect Check:** Re-ran the raw-SQL check from the reproduction step after the fix — it now returns exactly 1 row for the same 3-tag song, confirming the fan-out is gone at the SQL level, not just still being masked by ORM dedup. Also manually inspected a search result's `tags` field to confirm it was still fully populated (`['rap', 'hip-hop', 'boom bap']`) via the `Song.tags` relationship alone, proving the removed join wasn't secretly required for correctness. Finally, grepped for other usages of `song_tags`/`Tag` outside `search_service.py` — the only matches are `models.py` (the definition), `seed_data.py` (seeding), and the test fixture itself, confirming no other code depended on the removed join.

---

### Issue #5: The last song in a playlist never shows up

**Reproduction Steps:** Ran `pytest tests/test_playlists.py -v` before making any changes. The `seed_playlist` fixture creates a playlist with 5 songs at positions 1–5. `test_playlist_returns_all_songs` failed with `assert 4 == 5`, and `test_playlist_returns_songs_in_order` failed because `"Track 5"` was missing — confirming the last song by position specifically, not a random one, was being dropped.

**Navigation Strategy:** README maps Issue #5 to `playlist_service.py`, so I opened `get_playlist_songs` directly. Reading the SQLAlchemy query top to bottom — it joins `playlist_entries`, filters by `playlist_id`, and orders ascending by `position` — nothing there looked wrong; the query itself was correctly constructed and correctly ordered. That ruled out the query as the problem and narrowed my attention to whatever happened *after* the query executed, which is a single return line — `songs[:-1]` was the only place a song could still be silently dropped from an already-correct, fully-ordered result.

**Root Cause Explanation:** `return [song.to_dict() for song in songs[:-1]]` slices off the last element of the list before returning it. Since `songs` was already ordered ascending by position, this unconditionally dropped the highest-position (most recently added) song in every playlist, regardless of playlist length.

**Fix Description:** Removed the slice in `services/playlist_service.py` so every song in the ordered query result is included:
```python
return [song.to_dict() for song in songs]
```

**Side-Effect Check:** The existing tests only cover a 5-song playlist and an empty playlist, so I specifically tested the single-song playlist edge case by hand, since `[0:-1]` of a 1-item list returns an empty list — an even more severe failure mode than "N-1 of N" that wasn't covered by any existing fixture. Before the fix this would have returned 0 songs for a 1-song playlist; after the fix it correctly returns the 1 song, confirming the fix generalizes rather than only satisfying the specific 5-song fixture.

---

## AI Usage

I used Claude (via Claude Code) throughout this project to help me navigate the codebase, understand what each service function was actually doing, and figure out where each reported bug lived before I made changes. Two specific instances where it wasn't just "ask AI, get code":

1. **Search bug (Issue #3) — the AI's first assumption turned out to be incomplete.** Based on the issue description and the `seed_data.py` comment calling out multi-tag songs, both the AI and I expected `pytest tests/test_search.py` to show a clear failing test, the same way the streak and playlist bugs did. It didn't — all 5 search tests passed. Rather than accept that as "no bug here," we dug into the raw SQL the query actually generates by executing `q.statement` directly instead of going through `.all()`, which showed the join really does return 3 duplicate rows for a 3-tag song at the SQL level. The reason the test suite didn't catch it was that the installed SQLAlchemy version auto-deduplicates ORM query results — something neither of us knew going in. I made the call to still fix and document it as a latent, version-dependent bug rather than skip it, since the underlying query was genuinely wrong even though it wasn't currently observable through the test suite.

2. **Feed regression test verification — the AI's own verification step broke the fix, and it had to catch and correct itself.** While proving that the new `tests/test_feed.py` would have caught the original 24-hour-window bug, the AI first tried `git stash` to temporarily revert the fix and rerun the tests. That produced a confusing `TypeError` instead of a clean assertion failure, because the stash reverted both the logic fix and an unrelated function-signature change (the new `now` parameter) at once. The AI recognized that wasn't a fair demonstration and instead hand-patched just the old threshold logic back in while keeping the new parameter, which produced the real, meaningful failure (`assert feed == []` actually containing darius). Then, when restoring the fix afterward, `git checkout -- services/feed_service.py` reverted the file all the way back to the last *committed* version — which was the original buggy code, since the feed fix had never been committed yet — silently wiping out the fix. The AI caught this immediately by re-reading the file, told me plainly that the fix had been lost, and reapplied it by hand rather than leaving it broken or pretending nothing happened. I would not have known to check for that if it hadn't flagged it.

In both cases the takeaway for me was the same: I couldn't just trust that a test suite passing (or a git command completing) meant the underlying assumption was correct — I had to verify the actual behavior (raw SQL row counts, the file's contents on disk) myself before accepting either "it's fine" or "it's fixed."
