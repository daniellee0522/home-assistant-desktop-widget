"""This computer's player (local_media.py) and how the Api routes to it."""
import ast
import datetime
import json
import os
import sys
import threading
import unittest
from pathlib import Path
from unittest.mock import Mock

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
