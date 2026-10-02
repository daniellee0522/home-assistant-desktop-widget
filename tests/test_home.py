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
        entities, _, rooms = home.build_home(states, self.areas, self.devices, registry,
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
                  state('input_boolean.h'), state('binary_sensor.b'), state('lock.front')]
        entities, _, _ = home.build_home(states, [], [], registry, {})
        self.assertEqual([e['entity_id'] for e in entities], ['lock.front'])

    def test_entities_without_a_registry_entry_are_kept(self):
        entities, _, rooms = home.build_home([state('switch.legacy')], [], [], [], {})
        self.assertEqual(entities[0]['area'], '')
        self.assertEqual(rooms, [])

    def test_order_is_by_kind_then_name(self):
        states = [state('switch.b', 'B'), state('light.z', 'Z'), state('light.a', 'A')]
        entities, _, _ = home.build_home(states, [], [], [], {})
        self.assertEqual([e['entity_id'] for e in entities],
                         ['light.a', 'light.z', 'switch.b'])

    def test_temperature_and_humidity_are_status_not_tiles(self):
        def sensor(entity_id, **attrs):
            return {'entity_id': entity_id, 'state': '21', 'attributes': attrs}
        states = [sensor('sensor.t', device_class='temperature'),
                  sensor('sensor.h', device_class='humidity', unit_of_measurement='%'),
                  sensor('sensor.homepod_mini_temperature', unit_of_measurement='°C'),
                  sensor('sensor.homepod_mini_humidity', unit_of_measurement='%'),
                  sensor('sensor.battery', device_class='battery', unit_of_measurement='%'),
                  sensor('sensor.cpu', unit_of_measurement='%')]
        registry = [{'entity_id': 'sensor.t', 'area_id': 'lr'}]
        entities, sensors, rooms = home.build_home(states, self.areas, [], registry, {})
        self.assertEqual(entities, [])
        self.assertEqual({s['entity_id']: s['kind'] for s in sensors},
                         {'sensor.t': 'temperature', 'sensor.h': 'humidity',
                          'sensor.homepod_mini_temperature': 'temperature',
                          'sensor.homepod_mini_humidity': 'humidity'})
        self.assertEqual(rooms, ['Living room'])

    def test_cameras_are_accessories(self):
        entities, _, _ = home.build_home([state('camera.door')], [], [], [], {})
        self.assertEqual([e['entity_id'] for e in entities], ['camera.door'])

    def test_unavailable_accessory_without_a_room_is_left_out(self):
        gone = state('switch.cam_setting'); gone['state'] = 'unavailable'
        placed = state('switch.cam_power'); placed['state'] = 'unavailable'
        entities, _, _ = home.build_home([gone, placed], self.areas, [],
                                         [{'entity_id': 'switch.cam_power', 'area_id': 'bd'}], {})
        self.assertEqual([e['entity_id'] for e in entities], ['switch.cam_power'])


class PanelConfig(unittest.TestCase):
    def test_clean_panel(self):
        keep = lambda tiles: list(tiles)
        panel = config.clean_panel({'mode': 'nonsense', 'tiles': None,
                                    'home_tiles': [{'entity': 'a'}],
                                    'room_overrides': {'light.a': ' Study ', 'b': '', 3: 'x'}}, keep)
        self.assertEqual(panel, {'mode': 'grid', 'tiles': None, 'home_tiles': [{'entity': 'a'}],
                                 'room_overrides': {'light.a': 'Study'}, 'hidden_rooms': [], 'custom_rooms': [], 'room_order': [],
                                 'bg_image': '', 'bg_blur': 28})
        self.assertEqual(config.clean_panel({'custom_rooms': [' Den ', 'Den', '', 4]}, keep)['custom_rooms'], ['Den'])
        loud = config.clean_panel({'hidden_rooms': ['Garage', 3], 'bg_image': 'x.jpg', 'bg_blur': 999}, keep)
        self.assertEqual((loud['hidden_rooms'], loud['bg_image'], loud['bg_blur']),
                         (['Garage'], 'x.jpg', 80))
        self.assertEqual(config.clean_panel({'mode': 'home', 'tiles': []}, keep)['mode'], 'home')


    def test_the_layout_survives_a_restart(self):
        # What is saved is read back by the loader, which once dropped the
        # layout fields along with the rest of a tile's unknown keys.
        saved = {'mode': 'home', 'home_tiles': [
            {'id': 'home:light.a', 'entity': 'light.a', 'w': 2, 'h': 2, 'order': 3, 'hidden': True},
            {'id': 'home:light.b', 'entity': 'light.b', 'w': 2}]}
        loaded = config.clean_panel(saved, lambda tiles: [config._migrate_tile(t) for t in tiles])
        a, b = loaded['home_tiles']
        self.assertEqual((a['w'], a['h'], a['order'], a['hidden']), (2, 2, 3.0, True))
        self.assertEqual(b['w'], 2)
        self.assertNotIn('h', b)


if __name__ == '__main__':
    unittest.main()
