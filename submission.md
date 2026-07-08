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