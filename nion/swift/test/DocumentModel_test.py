# standard libraries
import contextlib
import copy
import gc
import random
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import Facade
from nion.swift.model import Cache
from nion.swift.model import DataGroup
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.swift.model import Symbolic
from nion.ui import TestUI
from nion.utils import Recorder


Facade.initialize()


class TestDocumentModelClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(TestUI.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    def test_remove_data_items_on_document_model(self):
        cache_name = ":memory:"
        storage_cache = Cache.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(storage_cache=storage_cache)
        with contextlib.closing(document_model):
            data_item1 = DataItem.DataItem()
            data_item1.title = 'title'
            data_item2 = DataItem.DataItem()
            data_item2.title = 'title'
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            self.assertEqual(len(document_model.data_items), 2)
            self.assertTrue(data_item1 in document_model.data_items)
            self.assertTrue(data_item2 in document_model.data_items)
            document_model.remove_data_item(data_item1)
            self.assertFalse(data_item1 in document_model.data_items)
            self.assertTrue(data_item2 in document_model.data_items)

    def test_removing_data_item_should_remove_from_groups_too(self):
        cache_name = ":memory:"
        storage_cache = Cache.DbStorageCache(cache_name)
        document_model = DocumentModel.DocumentModel(storage_cache=storage_cache)
        with contextlib.closing(document_model):
            data_item1 = DataItem.DataItem()
            data_item1.title = 'title'
            data_item2 = DataItem.DataItem()
            data_item2.title = 'title'
            document_model.append_data_item(data_item1)
            document_model.append_data_item(data_item2)
            data_group = DataGroup.DataGroup()
            document_model.append_data_group(data_group)
            data_group.append_data_item(data_item1)
            data_group.append_data_item(data_item2)
            self.assertEqual(data_group.counted_data_items[data_item1], 1)
            self.assertEqual(data_group.counted_data_items[data_item2], 1)
            document_model.remove_data_item(data_item1)
            self.assertEqual(data_group.counted_data_items[data_item1], 0)
            self.assertEqual(data_group.counted_data_items[data_item2], 1)

    def test_loading_document_with_duplicated_data_items_ignores_earlier_ones(self):
        memory_persistent_storage_system = DocumentModel.MemoryStorageSystem()
        document_model = DocumentModel.DocumentModel(persistent_storage_systems=[memory_persistent_storage_system])
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(numpy.ones((2, 2), numpy.uint32))
            document_model.append_data_item(data_item)
        # modify data reference to have duplicate
        old_data_key = list(memory_persistent_storage_system.data.keys())[0]
        new_data_key = "2000" + old_data_key[4:]
        old_properties_key = list(memory_persistent_storage_system.properties.keys())[0]
        new_properties_key = "2000" + old_properties_key[4:]
        memory_persistent_storage_system.data[new_data_key] = copy.deepcopy(memory_persistent_storage_system.data[old_data_key])
        memory_persistent_storage_system.properties[new_properties_key] = copy.deepcopy(memory_persistent_storage_system.properties[old_properties_key])
        # reload and verify
        document_model = DocumentModel.DocumentModel(persistent_storage_systems=[memory_persistent_storage_system], log_migrations=False)
        with contextlib.closing(document_model):
            self.assertEqual(len(document_model.data_items), len(set([d.uuid for d in document_model.data_items])))
            self.assertEqual(len(document_model.data_items), 1)

    def test_document_model_releases_data_item(self):
        # test memory usage
        document_model = DocumentModel.DocumentModel()
        import weakref
        with contextlib.closing(document_model):
            data_item = DataItem.DataItem(data=numpy.zeros((2, 2)))
            data_item_weak_ref = weakref.ref(data_item)
            document_model.append_data_item(data_item)
            data_item = None
        document_model = None
        gc.collect()
        self.assertIsNone(data_item_weak_ref())

    def test_processing_line_profile_configures_intervals_connection(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = numpy.zeros((8, 8), dtype=numpy.float)
            d[:] = random.randint(1, 100)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            line_profile_data_item = document_model.get_line_profile_new(data_item)
            self.assertEqual(len(data_item.displays[0].graphics[0].interval_descriptors), 0)
            interval = Graphics.IntervalGraphic()
            interval.interval = 0.3, 0.6
            line_profile_data_item.displays[0].add_graphic(interval)
            self.assertEqual(len(data_item.displays[0].graphics[0].interval_descriptors), 1)
            self.assertEqual(data_item.displays[0].graphics[0].interval_descriptors[0]["interval"], interval.interval)

    def test_processing_pick_configures_in_and_out_regions_and_connection(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = (100 * numpy.random.randn(8, 8, 64)).astype(numpy.int)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            pick_data_item = document_model.get_pick_new(data_item)
            self.assertEqual(len(data_item.displays[0].graphics), 1)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(pick_data_item.data, d[4, 4, :]))
            data_item.displays[0].graphics[0].position = 0, 0
            document_model.recompute_all()
            self.assertFalse(numpy.array_equal(pick_data_item.data, d[4, 4, :]))
            self.assertTrue(numpy.array_equal(pick_data_item.data, d[0, 0, :]))
            self.assertEqual(pick_data_item.displays[0].graphics[0].interval, data_item.displays[0].slice_interval)
            interval1 = 5 / d.shape[-1], 8 / d.shape[-1]
            pick_data_item.displays[0].graphics[0].interval = interval1
            self.assertEqual(pick_data_item.displays[0].graphics[0].interval, data_item.displays[0].slice_interval)
            self.assertEqual(pick_data_item.displays[0].graphics[0].interval, interval1)
            interval2 = 10 / d.shape[-1], 15 / d.shape[-1]
            data_item.displays[0].slice_interval = interval2
            self.assertEqual(pick_data_item.displays[0].graphics[0].interval, data_item.displays[0].slice_interval)
            self.assertEqual(pick_data_item.displays[0].graphics[0].interval, interval2)

    def test_recompute_after_data_item_deleted_does_not_update_data_on_deleted_data_item(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = (100 * numpy.random.randn(4, 4)).astype(numpy.int)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            inverted_data_item = document_model.get_invert_new(data_item)
            document_model.remove_data_item(inverted_data_item)
            document_model.recompute_all()

    def test_recompute_after_computation_cleared_does_not_update_data(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = (100 * numpy.random.randn(4, 4)).astype(numpy.int)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            inverted_data_item = document_model.get_invert_new(data_item)
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(inverted_data_item.data, -d))
            data_item.set_data((100 * numpy.random.randn(4, 4)).astype(numpy.int))
            document_model.set_data_item_computation(inverted_data_item, None)
            self.assertTrue(numpy.array_equal(inverted_data_item.data, -d))
            document_model.recompute_all()
            self.assertTrue(numpy.array_equal(inverted_data_item.data, -d))

    def test_recompute_twice_before_periodic_uses_final_data(self):
        document_model = DocumentModel.DocumentModel()
        with contextlib.closing(document_model):
            d = numpy.zeros((2, 2), numpy.int)
            data_item = DataItem.DataItem(d)
            document_model.append_data_item(data_item)
            computation = document_model.create_computation(Symbolic.xdata_expression("a.xdata + x"))
            computation.create_object("a", document_model.get_object_specifier(data_item))
            x = computation.create_variable("x", value_type="integral", value=5)
            computed_data_item = DataItem.DataItem(d)
            document_model.append_data_item(computed_data_item)
            document_model.set_data_item_computation(computed_data_item, computation)
            document_model.recompute_all(merge=False)
            x.value = 10
            document_model.recompute_all(merge=False)
            document_model.perform_data_item_merges()
            self.assertTrue(numpy.array_equal(computed_data_item.data, d + 10))

    def test_data_item_recording(self):
        data_item = DataItem.DataItem(numpy.zeros((16, 16)))
        data_item_recorder = Recorder.Recorder(data_item)
        data_item.displays[0].display_type = "line_plot"
        point_graphic = Graphics.PointGraphic()
        point_graphic.position = 0.2, 0.3
        data_item.displays[0].add_graphic(point_graphic)
        point_graphic.position = 0.21, 0.31
        new_data_item = DataItem.DataItem(numpy.zeros((16, 16)))
        self.assertNotEqual(data_item.displays[0].display_type, new_data_item.displays[0].display_type)
        data_item_recorder.apply(new_data_item)
        self.assertEqual(data_item.displays[0].display_type, new_data_item.displays[0].display_type)
        self.assertEqual(new_data_item.displays[0].graphics[0].position, point_graphic.position)


if __name__ == '__main__':
    unittest.main()
