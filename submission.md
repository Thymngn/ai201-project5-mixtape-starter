## Bug Fixes — Root Cause Analysis

### Bug 1: Listening streak keeps resetting

**Symptom:** Users reported that their listening streak would randomly drop back to 1 even though they had listened on consecutive days.

**How I reproduced it:** In `services/streak_service.py::update_listening_streak`, I called the function with two consecutive days that straddled a Saturday → Sunday boundary — e.g. `last_listened_at` on Saturday 2024-06-15, then `now` = Sunday 2024-06-16. `days_since_last` correctly computed as 1 (a consecutive day), but the streak still reset to 1 instead of incrementing to 2. This is exactly what the pre-existing test `tests/test_streaks.py::test_streak_increments_on_sunday` exercises — running `pytest tests/test_streaks.py -v` before the fix showed that test failing (`assert 1 == 2`) while the other 4 streak tests passed, isolating the bug to behavior specific to Sundays.

**Root cause:** The increment condition was:
```python
elif days_since_last == 1 and today.weekday() != 6:
    user.listening_streak += 1
else:
    user.listening_streak = 1
```
`date.weekday()` returns Monday=0 … Sunday=6, so `today.weekday() != 6` means "today is not Sunday." That clause has no legitimate connection to a consecutive-day streak calculation — it caused the streak to fall through to the `else` branch (reset to 1) any time the current day happened to be a Sunday, even when the user had listened on truly consecutive days.

**Fix:** Removed the erroneous weekday check so the branch depends only on `days_since_last == 1`:
```python
elif days_since_last == 1:
    user.listening_streak += 1
else:
    user.listening_streak = 1
```
File: `services/streak_service.py`, line 73.

**Verification:** Ran `pytest tests/test_streaks.py -v` after the fix — all 5 tests pass, including `test_streak_increments_on_sunday`, which failed before the fix.

### Bug 2: Last song in a playlist never shows up

**Symptom:** `GET /playlists/<id>/songs` (and anything built on `get_playlist_songs`) always returns one fewer song than the playlist actually contains — the last song by position is missing.

**How I reproduced it:** Ran the existing test suite `pytest tests/test_playlists.py -v` before making any changes. The fixture `seed_playlist` creates a playlist with 5 songs at positions 1–5. `test_playlist_returns_all_songs` failed with `assert 4 == 5` (only 4 of 5 songs returned), and `test_playlist_returns_songs_in_order` failed because `"Track 5"` was missing from the result — confirming the last song by position is the one being dropped, not a random one.

**Root cause:** In `services/playlist_service.py::get_playlist_songs`, after querying songs in position order, the return line sliced the list:
```python
return [song.to_dict() for song in songs[:-1]]
```
`songs[:-1]` excludes the last element of the list. Since `songs` was already ordered ascending by position, this always dropped the highest-position (i.e. last-added) song in the playlist, regardless of playlist length.

**Fix:** Removed the slice so every song in the ordered query result is included:
```python
return [song.to_dict() for song in songs]
```
File: `services/playlist_service.py`, in `get_playlist_songs`.

**Verification:** Ran `pytest tests/test_playlists.py -v` after the fix — all 3 tests pass, including the two that failed beforehand.

### Bug 3: Same song shows up twice (or more) in search

**Symptom:** Per the project brief, a song with multiple tags could appear multiple times in a single search result (once per tag).

**How I reproduced it:** `pytest tests/test_search.py -v` passed 5/5 even before any change, so the test suite alone didn't show a live failure. To check whether the underlying query was actually safe, I ran the raw SQL that `search_songs` built by hand against a song seeded with 3 tags (via `song_tags.insert()`, mirroring `seed_data.py`'s "3+ tag" songs). Fetching the statement directly with `db.session.execute(q.statement).fetchall()` returned **3 raw rows** for that one song — one per matching tag row from the `LEFT OUTER JOIN` against `song_tags`. So the query itself does fan out at the SQL level; the reason the Python-level test didn't catch it is that the installed SQLAlchemy version (2.0.51) automatically de-duplicates ORM entities returned by a legacy `Query.all()` call, silently absorbing the fan-out before it reaches calling code. On an older SQLAlchemy version (or via `.session.execute(select(...))` without `.unique()`), this same query would return duplicate `Song` objects.

**Root cause:** In `services/search_service.py::search_songs`, the query joined `Song` to the `song_tags` association table purely to filter by title/artist — but tags aren't used in the `WHERE` clause at all, and `Song.to_dict()` already loads tags independently via the `Song.tags` relationship (`lazy="subquery"` in `models.py`). The join was unnecessary and caused a one-row-per-tag fan-out for any song with more than one tag:
```python
results = (
    db.session.query(Song)
    .outerjoin(song_tags, Song.id == song_tags.c.song_id)
    .filter(db.or_(Song.title.ilike(f"%{query}%"), Song.artist.ilike(f"%{query}%")))
    .all()
)
```

**Fix:** Removed the unnecessary join (and the now-unused `Tag`/`song_tags` imports) so the query only touches the `song` table and can no longer fan out:
```python
results = (
    db.session.query(Song)
    .filter(db.or_(Song.title.ilike(f"%{query}%"), Song.artist.ilike(f"%{query}%")))
    .all()
)
```
File: `services/search_service.py`.

**Verification:** Re-ran the raw-SQL check from the reproduction step — it now returns exactly 1 row for the same 3-tag song, confirming the fan-out is gone at the SQL level (not just masked by ORM dedup). Also ran the full suite, `pytest tests/ -v` — all 13 tests pass with no regressions.