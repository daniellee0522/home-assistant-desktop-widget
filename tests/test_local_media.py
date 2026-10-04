"""This computer's player (local_media.py) and how the Api routes to it."""
import ast
import asyncio
import datetime
import json
import os
import sys
import threading
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config  # noqa: E402
import local_media  # noqa: E402


def api_with(*names):
    tree = ast.parse(Path('main.py').read_text(encoding='utf-8'))
    api = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == 'Api')
    api.body = [n for n in api.body if isinstance(n, ast.FunctionDef) and n.name in names]
    scope = {'json': json, 'threading': threading, 'cfgmod': config, 'local_media': local_media, 'os': os}
    exec(compile(ast.Module(body=[api], type_ignores=[]), 'main.py', 'exec'), scope)
    return scope['Api']()


def at(seconds_ago):
    return (datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=seconds_ago)).isoformat()


class Changes(unittest.TestCase):
    def setUp(self):
        self.lm = local_media.LocalMedia.__new__(local_media.LocalMedia)
        self.lm._last = {"state": "playing", "attributes": {"media_title": "A", "media_position": 10,
                                                            "media_position_updated_at": at(5)}}

    def test_the_song_moving_on_as_it_should_is_not_news(self):
        self.assertFalse(self.lm._changed({"state": "playing", "attributes": {
            "media_title": "A", "media_position": 15, "media_position_updated_at": at(0)}}))

    def test_a_jump_a_new_song_or_a_pause_is(self):
        self.assertTrue(self.lm._changed({"state": "playing", "attributes": {
            "media_title": "A", "media_position": 90, "media_position_updated_at": at(0)}}))
        self.assertTrue(self.lm._changed({"state": "playing", "attributes": {
            "media_title": "B", "media_position": 15, "media_position_updated_at": at(0)}}))
        self.assertTrue(self.lm._changed({"state": "paused", "attributes": {
            "media_title": "A", "media_position": 15, "media_position_updated_at": at(0)}}))


class Transitions(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        with patch.object(local_media, 'AVAILABLE', False):
            self.lm = local_media.LocalMedia(Mock())
        self.clock = Mock(return_value=10.0)
        clock_patch = patch.object(local_media, 'time', SimpleNamespace(monotonic=self.clock))
        clock_patch.start()
        self.addCleanup(clock_patch.stop)
        states_patch = patch.dict(local_media._STATES, {'playing': 'playing', 'paused': 'paused', 'idle': 'idle'})
        states_patch.start()
        self.addCleanup(states_patch.stop)
        self.lm._thumbnail = AsyncMock(return_value=b'new cover')
        self.session = Mock()
        self.session.source_app_user_model_id = 'chrome.exe'
        self.props = Mock(title='Short A', artist='Channel', thumbnail=Mock())
        self.session.try_get_media_properties_async = AsyncMock(return_value=self.props)
        self.session.get_playback_info.return_value.playback_status = 'playing'
        self.session.get_timeline_properties.return_value = Mock(
            end_time=datetime.timedelta(seconds=30), start_time=datetime.timedelta(),
            position=datetime.timedelta(seconds=2), last_updated_time=datetime.datetime.now(datetime.timezone.utc))
        self.lm._session = AsyncMock(return_value=self.session)

    async def test_short_switch_keeps_track_and_cover_until_next_track(self):
        await self.lm._read()
        first = self.lm._last
        self.lm.on_state.reset_mock()
        self.props.title = ''
        self.session.get_playback_info.return_value.playback_status = 'idle'
        self.lm._props_dirty = True
        self.lm._thumbnail.reset_mock()
        await self.lm._read()
        self.clock.return_value = 10.15
        self.lm._session.return_value = None
        await self.lm._read()
        self.assertIs(self.lm._last, first)
        self.assertEqual(self.lm.art, b'new cover')
        self.lm._thumbnail.assert_not_awaited()
        self.lm.on_state.assert_not_called()
        self.lm._session.return_value = self.session
        self.props.title = 'Short B'
        self.session.get_playback_info.return_value.playback_status = 'playing'
        await self.lm._read()
        self.assertEqual(self.lm._last['attributes']['media_title'], 'Short B')
        self.lm.on_state.assert_called_once()
        self.assertIsNone(self.lm._transition_until)

    async def test_real_stop_expires_even_when_gap_changes_shape(self):
        await self.lm._read()
        self.lm.on_state.reset_mock()
        self.props.title = ''
        await self.lm._read()
        deadline = self.lm._transition_until
        self.lm._session.return_value = None
        self.clock.return_value = deadline - 0.01
        await self.lm._read()
        self.lm.on_state.assert_not_called()
        self.clock.return_value = deadline
        await self.lm._read()
        self.assertEqual(self.lm._last['state'], 'off')
        self.assertIsNone(self.lm.art)
        self.lm.on_state.assert_called_once()

    async def test_pause_and_initial_empty_state_are_immediate(self):
        self.lm._session.return_value = None
        await self.lm._read()
        self.assertEqual(self.lm._last['state'], 'off')
        self.lm._session.return_value = self.session
        await self.lm._read()
        self.lm.on_state.reset_mock()
        self.session.get_playback_info.return_value.playback_status = 'paused'
        await self.lm._read()
        self.assertEqual(self.lm._last['state'], 'paused')
        self.lm.on_state.assert_called_once()

    async def test_empty_metadata_while_playing_is_bounded_and_next_gap_gets_new_deadline(self):
        await self.lm._read()
        self.props.title = ''
        await self.lm._read()
        self.clock.return_value = 10.3
        await self.lm._read()
        self.assertEqual(self.lm._last['attributes']['media_title'], '')
        self.props.title = 'Short B'
        await self.lm._read()
        self.props.title = ''
        self.clock.return_value = 12.0
        await self.lm._read()
        self.assertEqual(self.lm._transition_until, 12.3)
        self.assertEqual(self.lm._last['attributes']['media_title'], 'Short B')

    async def test_transition_retries_promptly_and_keeps_events_arriving_during_read(self):
        self.lm.active = True

        async def read():
            self.lm._transition_until = 10.3
            self.lm._wake_event.set()  # Windows posts another change while reading properties.

        async def wait(awaitable, timeout):
            self.assertEqual(timeout, local_media.TRANSITION_POLL_S)
            self.assertTrue(self.lm._wake_event.is_set())
            await awaitable
            raise asyncio.CancelledError

        self.lm._read = read
        with patch.object(local_media.asyncio, 'wait_for', side_effect=wait):
            with self.assertRaises(asyncio.CancelledError):
                await self.lm._main()


class Routing(unittest.TestCase):
    def test_this_computers_player_is_controlled_here_and_its_cover_comes_from_here(self):
        api = api_with('call_service', 'get_picture')
        api._local_media = Mock()
        api._local_media.control.return_value = True
        api._local_media.get_art.return_value = b"png"
        api._client = Mock()
        self.assertEqual(api.call_service("media_player", "media_next_track", local_media.ENTITY, {}), {"ok": True})
        api._local_media.control.assert_called_once_with("media_next_track", {})
        api._client.call_service.assert_not_called()
        self.assertEqual(api.get_picture("local:art/3"), b"png")
        api._client.get_bytes.assert_not_called()

    def test_a_player_widget_is_set_to_another_source(self):
        api = api_with('set_widget_source', 'get_media_sources', '_widget_cfg', '_clean_tiles')
        api._local_media = Mock()
        api._cfg = {"ha_token": "t", "widgets": [{"id": "p", "kind": "media", "tiles": []}]}
        api._client = Mock()
        api._client.get_states.return_value = [
            {"entity_id": "media_player.study", "attributes": {"friendly_name": "書房"}},
            {"entity_id": "light.x", "attributes": {}}]
        api._tiles_changed = Mock()
        sources = api.get_media_sources()
        self.assertEqual([s["entity_id"] for s in sources], [local_media.ENTITY, "media_player.study"])
        self.assertTrue(api.set_widget_source("p", "media_player.study"))
        tile = api._cfg["widgets"][0]["tiles"][0]
        self.assertEqual((tile["entity"], tile["domain"], tile["room"]), ("media_player.study", "media_player", "書房"))


if __name__ == "__main__":
    unittest.main()
