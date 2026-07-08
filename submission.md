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