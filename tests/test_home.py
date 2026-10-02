"""The Home-style panel: devices grouped by Home Assistant area."""
import unittest

import config
import home


def state(entity_id, name=None):
    return {'entity_id': entity_id, 'state': 'on',
            'attributes': {'friendly_name': name or entity_id}}


class BuildHome(unittest.TestCase):
    areas = [{'area_id': 'lr', 'name': 'Living room'}, {'area_id': 'bd', 'name': 'Bedroom'}]
    devices = [{'id': 'd1', 'area_id': 'lr'}, {'id': 'd2', 'area_id': None}]

    def test_entity_area_beats_device_area_and_overrides_beat_both(self):
        registry = [
            {'entity_id': 'light.a', 'device_id': 'd1'},                       # device's area
            {'entity_id': 'light.b', 'device_id': 'd1', 'area_id': 'bd'},      # its own area
            {'entity_id': 'light.c', 'device_id': 'd1'},
            {'entity_id': 'light.d', 'device_id': 'd2'},                       # nowhere
        ]
        states = [state('light.a'), state('light.b'), state('light.c'), state('light.d')]
        entities, rooms = home.build_home(states, self.areas, self.devices, registry,
                                          {'light.c': 'Garden'})
        area = {e['entity_id']: e['area'] for e in entities}
        self.assertEqual(area, {'light.a': 'Living room', 'light.b': 'Bedroom',
                                'light.c': 'Garden', 'light.d': ''})
        self.assertEqual(rooms, ['Bedroom', 'Garden', 'Living room'])

    def test_hidden_disabled_diagnostic_and_unsupported_are_left_out(self):
        registry = [
            {'entity_id': 'light.hidden', 'hidden_by': 'user'},
            {'entity_id': 'light.off', 'disabled_by': 'integration'},
            {'entity_id': 'sensor.rssi', 'entity_category': 'diagnostic'},
        ]
        states = [state('light.hidden'), state('light.off'), state('sensor.rssi'),
                  state('automation.x'), state('script.y'), state('scene.z'),
                  state('lock.front')]
        entities, _ = home.build_home(states, [], [], registry, {})
        self.assertEqual([e['entity_id'] for e in entities], ['lock.front'])

    def test_entities_without_a_registry_entry_are_kept(self):
        entities, rooms = home.build_home([state('switch.legacy')], [], [], [], {})
        self.assertEqual(entities[0]['area'], '')
        self.assertEqual(rooms, [])

    def test_order_is_by_kind_then_name(self):
        states = [state('sensor.b', 'B'), state('light.z', 'Z'), state('light.a', 'A')]
        entities, _ = home.build_home(states, [], [], [], {})
        self.assertEqual([e['entity_id'] for e in entities],
                         ['light.a', 'light.z', 'sensor.b'])


class PanelConfig(unittest.TestCase):
    def test_clean_panel(self):
        keep = lambda tiles: list(tiles)
        panel = config.clean_panel({'mode': 'nonsense', 'tiles': None,
                                    'home_tiles': [{'entity': 'a'}],
                                    'room_overrides': {'light.a': ' Study ', 'b': '', 3: 'x'}}, keep)
        self.assertEqual(panel, {'mode': 'grid', 'tiles': None, 'home_tiles': [{'entity': 'a'}],
                                 'room_overrides': {'light.a': 'Study'}})
        self.assertEqual(config.clean_panel({'mode': 'home', 'tiles': []}, keep)['mode'], 'home')


if __name__ == '__main__':
    unittest.main()
