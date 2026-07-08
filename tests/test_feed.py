"""
tests/test_feed.py — Mixtape

Tests for the "Friends Listening Now" feed logic.
"""

import pytest
from datetime import datetime, timezone
from app import create_app, db
from models import User, Song, ListeningEvent, friendships
from services.feed_service import get_friends_listening_now


@pytest.fixture
def app():
    app = create_app({"TESTING": True, "SQLALCHEMY_DATABASE_URI": "sqlite:///:memory:"})
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()


@pytest.fixture
def nova_and_darius(app):
    """Two friends, nova and darius, with a song darius can listen to."""
    with app.app_context():
        nova = User(username="nova", email="nova@example.com")
        darius = User(username="darius", email="darius@example.com")
        db.session.add_all([nova, darius])
        db.session.flush()

        db.session.execute(friendships.insert().values(user_id=nova.id, friend_id=darius.id))
        db.session.execute(friendships.insert().values(user_id=darius.id, friend_id=nova.id))

        song = Song(title="Late Night Session", artist="Nova Blix", shared_by=nova.id)
        db.session.add(song)
        db.session.flush()

        db.session.commit()
        yield {"nova": nova, "darius": darius, "song": song}


def test_friend_from_last_night_not_shown_this_morning(app, nova_and_darius):
    """
    Regression test for Issue #2: "Friends Listening Now shows people from yesterday".

    Reproduces nova's exact report: darius listened at 11pm the previous night
    and didn't open the app again. Checking the feed at 9am the next morning
    should NOT show darius as currently listening, even though only ~10 hours
    have passed (well within the old 24-hour rolling window).
    """
    with app.app_context():
        nova = db.session.get(User, nova_and_darius["nova"].id)
        darius = nova_and_darius["darius"]
        song = nova_and_darius["song"]

        last_night = datetime(2024, 6, 16, 23, 0, 0, tzinfo=timezone.utc)  # 11pm
        this_morning = datetime(2024, 6, 17, 9, 0, 0, tzinfo=timezone.utc)  # 9am next day

        event = ListeningEvent(user_id=darius.id, song_id=song.id, listened_at=last_night)
        db.session.add(event)
        db.session.commit()

        feed = get_friends_listening_now(nova.id, now=this_morning)

        assert feed == []


def test_friend_from_earlier_today_is_shown(app, nova_and_darius):
    """A friend who listened earlier today (calendar day) should still appear."""
    with app.app_context():
        nova = db.session.get(User, nova_and_darius["nova"].id)
        darius = nova_and_darius["darius"]
        song = nova_and_darius["song"]

        early_this_morning = datetime(2024, 6, 17, 2, 0, 0, tzinfo=timezone.utc)  # 2am
        later_this_morning = datetime(2024, 6, 17, 9, 0, 0, tzinfo=timezone.utc)  # 9am

        event = ListeningEvent(user_id=darius.id, song_id=song.id, listened_at=early_this_morning)
        db.session.add(event)
        db.session.commit()

        feed = get_friends_listening_now(nova.id, now=later_this_morning)

        assert len(feed) == 1
        assert feed[0]["friend"]["username"] == "darius"
