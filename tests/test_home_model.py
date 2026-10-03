"""The Home panel's rules with no window (nativeui/homemodel.py): where tiles stand and who makes way."""
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from nativeui.homemodel import HomeModel, home_layout, OTHER_ROOM   # noqa: E402


def t(id, w, h, order, x=None, y=None):
    return {"id": id, "w": w, "h": h, "order": order, "x": x, "y": y}


def L(items, pin=None):
    return {k: [v["x"], v["y"], v["w"], v["h"]] for k, v in home_layout(items, pin).items()}


class Layout(unittest.TestCase):
    def test_first_free_cell_in_order(self):
        self.assertEqual(L([t("a", 1, 1, 0), t("b", 2, 1, 1), t("c", 1, 1, 2), t("d", 2, 2, 3)]),
                         {"a": [0, 0, 1, 1], "b": [1, 0, 2, 1], "c": [3, 0, 1, 1], "d": [0, 1, 2, 2]})

    def test_a_held_tile_pushes_down_and_the_rest_moves_up(self):
        self.assertEqual(L([t("a", 1, 1, 0, 0, 0), t("b", 1, 1, 1, 1, 0)], {"id": "c", "x": 0, "y": 0, "w": 1, "h": 1}),
                         {"c": [0, 0, 1, 1], "a": [0, 1, 1, 1], "b": [1, 0, 1, 1]})

    def test_a_large_square_pushes_a_row_down(self):
        self.assertEqual(L([t("a", 1, 1, 0, 0, 0), t("b", 1, 1, 1, 1, 0), t("c", 1, 1, 2, 0, 1)],
                           {"id": "big", "x": 0, "y": 0, "w": 2, "h": 2}),
                         {"big": [0, 0, 2, 2], "a": [0, 2, 1, 1], "b": [1, 2, 1, 1], "c": [0, 3, 1, 1]})

    def test_gap_above_closed_gap_beside_kept(self):
        self.assertEqual(L([t("a", 1, 1, 0, 0, 3), t("b", 1, 1, 1, 3, 5)]), {"a": [0, 0, 1, 1], "b": [3, 0, 1, 1]})

    def test_past_the_right_edge_is_brought_back(self):
        self.assertEqual(L([], {"id": "bar", "x": 3, "y": 0, "w": 2, "h": 1}), {"bar": [2, 0, 2, 1]})

    def test_nothing_overlaps(self):
        crowd = [t("a", 2, 2, 0, 0, 0), t("b", 2, 1, 1, 1, 1), t("c", 1, 1, 2, 0, 0), t("d", 2, 2, 3, 2, 0)]
        spots = list(home_layout(crowd).values())
        for p in spots:
            for q in spots:
                if p is not q:
                    self.assertTrue(p["x"] + p["w"] <= q["x"] or q["x"] + q["w"] <= p["x"]
                                    or p["y"] + p["h"] <= q["y"] or q["y"] + q["h"] <= p["y"])

    def test_dragged_left_they_make_way_to_the_right(self):
        row = [t("a", 1, 1, 0, 0, 0), t("b", 1, 1, 1, 1, 0), t("c", 1, 1, 2, 2, 0)]
        self.assertEqual(L(row, {"id": "p", "x": 1, "y": 0, "w": 1, "h": 1, "dir": {"x": 1, "y": 0}}),
                         {"p": [1, 0, 1, 1], "a": [0, 0, 1, 1], "b": [2, 0, 1, 1], "c": [3, 0, 1, 1]})
        self.assertEqual(L([t("b", 1, 1, 0, 1, 0), t("c", 1, 1, 1, 2, 0)],
                           {"id": "p", "x": 2, "y": 0, "w": 1, "h": 1, "dir": {"x": -1, "y": 0}}),
                         {"p": [2, 0, 1, 1], "c": [1, 0, 1, 1], "b": [0, 0, 1, 1]})

    def test_no_room_that_way_they_go_down(self):
        crowded = [t("a", 1, 1, 0, 0, 0), t("b", 1, 1, 1, 1, 0), t("c", 1, 1, 2, 2, 0), t("d", 1, 1, 3, 3, 0)]
        full = L(crowded, {"id": "p", "x": 0, "y": 0, "w": 1, "h": 1, "dir": {"x": 1, "y": 0}})
        self.assertEqual(full["p"], [0, 0, 1, 1])
        self.assertGreater(full["d"][1], 0)
        for i in "abc":
            self.assertEqual(full[i][1], 0)


class Model(unittest.TestCase):
    def setUp(self):
        self.m = HomeModel()
        self.m.entities = [{"entity_id": "light.a", "domain": "light", "name": "A", "area": "客廳", "state": {}},
                           {"entity_id": "light.b", "domain": "light", "name": "B", "area": "", "state": {}},
                           {"entity_id": "lock.d", "domain": "lock", "name": "D", "area": "玄關", "state": {}}]
        self.m.sensors = [{"entity_id": "sensor.t", "kind": "temperature", "name": "T", "area": "客廳"},
                          {"entity_id": "sensor.h", "kind": "humidity", "name": "H", "area": "客廳"}]
        self.m.rooms = ["客廳", "玄關"]
        self.m.states = {"light.a": {"state": "on"}, "sensor.t": {"state": "26.3"}, "sensor.h": {"state": "45"},
                         "lock.d": {"state": "unlocked"}}

    def test_rooms_and_other(self):
        self.assertEqual(self.m.room_names()[-1], OTHER_ROOM)
        self.m.panel["custom_rooms"] = ["書房"]
        self.assertIn("書房", self.m.room_names())
        self.m.panel["room_order"] = ["玄關", "客廳"]
        self.assertEqual(self.m.room_names()[:2], ["玄關", "客廳"])

    def test_hidden_room_and_device(self):
        self.m.panel["hidden_rooms"] = ["客廳"]
        self.m.panel["show_other"] = True
        self.assertEqual([k for k, _, _ in self.m.groups()], ["玄關", OTHER_ROOM])
        self.m.editing = True
        stubs = {k: stub for k, _, stub in self.m.groups()}
        self.assertTrue(stubs["客廳"])
        self.m.editing = False
        self.m.ensure_record("lock.d")["hidden"] = True
        self.assertEqual([k for k, _, _ in self.m.groups()], [OTHER_ROOM])

    def test_uncategorised_is_off_the_main_screen_unless_chosen(self):
        self.assertEqual(self.m.room_label(OTHER_ROOM), "未分類")
        self.assertNotIn(OTHER_ROOM, [k for k, _, _ in self.m.groups()])
        self.m.room = OTHER_ROOM                         # its button still shows it
        self.assertEqual([k for k, _, _ in self.m.groups()], [OTHER_ROOM])
        self.m.room = ""
        self.m.editing = True                            # and editing offers to put it back
        self.assertTrue({k: stub for k, _, stub in self.m.groups()}[OTHER_ROOM])
        self.m.editing = False
        self.m.panel["show_other"] = True
        self.assertIn(OTHER_ROOM, [k for k, _, _ in self.m.groups()])

    def test_capsules(self):
        pills = {c["id"]: p["sub"] for c, _, p in self.m.visible_categories()}
        self.assertEqual(pills["env"], "26.3° · 45%")
        self.assertEqual(pills["light"], "1 個開著")
        self.assertEqual(pills["security"], "1 個未鎖上")
        self.assertNotIn("media", pills)

    def test_capsule_member_left_out(self):
        self.m.ensure_record("light.a")["cat_hidden"] = True
        light = [c for c, _, _ in self.m.visible_categories() if c["id"] == "light"][0]
        self.assertEqual([e["entity_id"] for e in self.m.category_members(light)], ["light.b"])

    def test_saved_layout_round_trips(self):
        layout = home_layout(self.m.items([e for e in self.m.entities if e["area"] == "客廳"]))
        self.m.save_layout(layout)
        rec = self.m.record("light.a")
        self.assertEqual((rec["x"], rec["y"], rec["w"], rec["h"]), (0, 0, 1, 1))


class CapsuleSizes(unittest.TestCase):
    def test_capsule_shape_is_apart_from_the_room_shape(self):
        import config
        rec = {"id": "home:light.a", "w": 2, "h": 2, "cat_w": 2}
        self.assertEqual(HomeModel.span(rec), (2, 2))
        self.assertEqual(HomeModel.cat_span(rec), (2, 1))
        self.assertEqual(HomeModel.cat_span({"w": 2, "h": 2}), (1, 1))
        kept = config.tile_layout(rec)
        self.assertEqual((kept.get("cat_w"), kept.get("cat_h")), (2, None))


if __name__ == "__main__":
    unittest.main()
