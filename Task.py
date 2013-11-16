# standard libraries
import copy
import gettext
import logging
import threading
import time

# third party libraries
# None

# local libraries
from nion.swift.Decorators import singleton
from nion.swift import Panel
from nion.swift import Storage

_ = gettext.gettext


"""
    Task modules can register task viewer factory with the task manager.

    Tasks will request a new task controller from the document model.
    
    A task section will get created and added to the task panel with some type of progress
    indicator and cancel button. The task section will display a task viewer if one is
    available for the task data.

    While the task is running, it is free to call task controller methods from
    a thread to update the data. The task controller will take care of getting the
    data to the task viewer on the UI thread.
    
    When the task finishes, it can optionally send final data. The last data available
    data will get permanently stored into the document.

    When the document loads, all tasks will be displayed in the task panel. The
    user has an option to copy, export, or delete finished tasks.

"""

class TaskPanel(Panel.Panel):

    def __init__(self, document_controller, panel_id, properties):
        super(TaskPanel, self).__init__(document_controller, panel_id, _("Tasks"))

        # connect to the document controller
        self.document_controller.add_listener(self)

        # the main column widget contains a stack group for each operation
        self.column = self.ui.create_column_widget(properties)  # TODO: put this in scroll area
        self.scroll_area = self.ui.create_scroll_area_widget()
        self.scroll_area.set_scrollbar_policies("off", "needed")
        self.task_column_container = self.ui.create_column_widget()
        self.task_column = self.ui.create_column_widget()
        self.task_column_container.add(self.task_column)
        self.task_column_container.add_stretch()
        self.scroll_area.content = self.task_column_container
        self.column.add(self.scroll_area)
        self.widget = self.column

        # map task to widgets
        self.__pending_tasks = list()
        self.__pending_tasks_mutex = threading.RLock()
        self.__task_needs_update = set()
        self.__task_needs_update_mutex = threading.RLock()
        self.__task_section_controller_list = list()

    def close(self):
        # disconnect to the document controller
        self.document_controller.remove_listener(self)
        # disconnect from tasks
        for task_section_controller in self.__task_section_controller_list:
            task_section_controller.task.remove_listener(self)
        # finish closing
        super(TaskPanel, self).close()

    def periodic(self):
        with self.__pending_tasks_mutex:
            pending_tasks = self.__pending_tasks
            self.__pending_tasks = list()
        for task in pending_tasks:
            task_section_controller = TaskSectionController(self.ui, task)
            self.task_column.insert(task_section_controller.widget, 0)
            self.scroll_area.scroll_to(0, 0)
            self.__task_section_controller_list.append(task_section_controller)
            with self.__task_needs_update_mutex:
                self.__task_needs_update.add(task)
            task.add_listener(self)
        # allow unfinished tasks to mark themselves as finished.
        for task_section_controller in self.__task_section_controller_list:
            task = task_section_controller.task
            if task in self.__task_needs_update:
                # remove from update list before updating to prevent a race
                with self.__task_needs_update_mutex:
                    self.__task_needs_update.remove(task)
                # update
                task_section_controller.update()

    # thread safe
    def task_created(self, task):
        with self.__pending_tasks_mutex:
            self.__pending_tasks.append(task)

    # thread safe
    def task_changed(self, task):
        with self.__task_needs_update_mutex:
            self.__task_needs_update.add(task)


# this is UI object, and not a thread safe
class TaskSectionController(object):

    def __init__(self, ui, task):
        self.ui = ui
        self.task = task

        widget = self.ui.create_column_widget()
        task_header = self.ui.create_row_widget()
        self.title_widget = self.ui.create_label_widget(properties={"stylesheet": "font-weight: bold"})
        task_header.add(self.title_widget)
        task_spacer_row = self.ui.create_row_widget()
        task_spacer_row_col = self.ui.create_column_widget()
        task_spacer_row.add_spacing(20)
        task_spacer_row.add(task_spacer_row_col)
        self.task_progress_row = self.ui.create_row_widget()
        self.task_progress_label = self.ui.create_label_widget()
        self.task_progress_row.add(self.task_progress_label)
        task_time_row = self.ui.create_row_widget()
        self.task_progress_state = self.ui.create_label_widget(properties={"stylesheet": "font: italic"})
        task_time_row.add(self.task_progress_state)
        task_spacer_row_col.add(self.task_progress_row)
        task_spacer_row_col.add(task_time_row)

        # add custom ui, if any
        self.task_ui_controller = TaskManager().build_task_ui(self.ui, task)
        if self.task_ui_controller:
            task_spacer_row_col.add(self.task_ui_controller.widget)

        widget.add(task_header)
        widget.add(task_spacer_row)

        self.widget = widget

        self.update()

    # only called on UI thread
    def update(self):

        # update the title
        self.title_widget.text = "{}".format(self.task.title)

        # update the progress label
        in_progress = self.task.in_progress
        if in_progress:
            self.task_progress_label.visible = True
            done_percentage_str = "{0:.0f}%".format(float(self.task.progress[0])/self.task.progress[1] * 100) if self.task.progress else "--"
            self.task_progress_label.text = "{0} {1}".format(done_percentage_str, self.task.progress_text)
        else:
            self.task_progress_label.visible = False

        # update the state text
        task_state_str = _("In Progress") if in_progress else _("Done")
        task_time_str = time.strftime("%c", time.localtime(self.task.start_time if in_progress else self.task.finish_time))
        self.task_progress_state.text = "{} {}".format(task_state_str, task_time_str)

        # update the custom builder, if any
        if self.task_ui_controller:
            self.task_ui_controller.update_task(self.task)


class Task(Storage.StorageBase):

    def __init__(self, title, task_type, task_data=None, start_time=None, finish_time=None):
        super(Task, self).__init__()
        self.storage_properties += ["title", "task_type", "task_data", "start_time", "finish_time"]
        self.storage_type = "task"
        self.__title = title
        self.__start_time = None
        self.__finish_time = None
        self.__task_type = task_type
        self.__task_data = None
        self.__task_data_mutex = threading.RLock()
        self.__progress = None
        self.__progress_text = str()

    @classmethod
    def build(cls, storage_reader, item_node, uuid_):
        title = storage_reader.get_property(item_node, "title", None)
        task_type = storage_reader.get_property(item_node, "task_type", None)
        task_data = storage_reader.get_property(item_node, "task_data", None)
        start_time = storage_reader.get_property(item_node, "start_time", None)
        finish_time = storage_reader.get_property(item_node, "finish_time", None)
        return cls(title, task_type, task_data=task_datam, start_time=start_time, finish_time=finish_time)

    def __deepcopy__(self, memo):
        task = Task(self.task_type, self.task_data)
        memo[id(self)] = task
        return task

    # title
    def __get_title(self):
        return self.__title
    def __set_title(self, value):
        self.__title = value
        self.notify_set_property("title", value)
        self.notify_listeners("task_changed", self)
    title = property(__get_title, __set_title)

    # start time
    def __get_start_time(self):
        return self.__start_time
    def __set_start_time(self, value):
        self.__start_time = value
        self.notify_set_property("start_time", value)
        self.notify_listeners("task_changed", self)
    start_time = property(__get_start_time, __set_start_time)

    # finish time
    def __get_finish_time(self):
        return self.__finish_time
    def __set_finish_time(self, value):
        self.__finish_time = value
        self.notify_set_property("finish_time", value)
        self.notify_listeners("task_changed", self)
    finish_time = property(__get_finish_time, __set_finish_time)

    # in progress
    def __get_in_progress(self):
        return self.finish_time is None
    in_progress = property(__get_in_progress)

    # progress
    def __get_progress(self):
        return self.__progress
    def __set_progress(self, progress):
        self.__progress = progress
        self.notify_listeners("task_changed", self)
    progress = property(__get_progress, __set_progress)

    # progress_text
    def __get_progress_text(self):
        return self.__progress_text
    def __set_progress_text(self, progress_text):
        self.__progress_text = progress_text
        self.notify_listeners("task_changed", self)
    progress_text = property(__get_progress_text, __set_progress_text)

    # task type
    def __get_task_type(self):
        return self.__task_type
    task_type = property(__get_task_type)

    # task data
    def __get_task_data(self):
        with self.__task_data_mutex:
            return copy.copy(self.__task_data)
    def __set_task_data(self, task_data):
        with self.__task_data_mutex:
            self.__task_data = copy.copy(task_data)
        self.notify_set_property("task_data", task_data)
        self.notify_listeners("task_changed", self)
    task_data = property(__get_task_data, __set_task_data)


# all public methods are thread safe
class TaskContextManager(object):

    def __init__(self, container, task):
        self.__container = container
        self.__task = task

    def __enter__(self):
        logging.debug("%s: started", self.__task.title)
        self.__task.start_time = time.time()
        return self

    def __exit__(self, type, value, traceback):
        self.__task.finish_time = time.time()
        logging.debug("%s: finished", self.__task.title)

    def update_progress(self, progress_text, progress=None, task_data=None):
        self.__task.progress_text = progress_text
        self.__task.progress = progress
        if task_data:
            self.__task.task_data = task_data
        logging.debug("%s: %s %s", self.__task.title, progress_text, progress if progress else "")


@singleton
class TaskManager(object):

    def __init__(self):
        self.__task_ui_builder_map = dict()

    def register_task_type_builder(self, task_type, fn):
        self.__task_ui_builder_map[task_type] = fn

    def unregister_task_type_builder(self, task_type):
        del self.__task_ui_builder_map[task_type]

    def build_task_ui(self, ui, task):
        if task.task_type in self.__task_ui_builder_map:
            return self.__task_ui_builder_map[task.task_type](ui)
        return None


class TableController(object):

    def __init__(self, ui):
        self.ui = ui
        self.widget = self.ui.create_row_widget()
        self.column_widgets = self.ui.create_row_widget()
        self.widget.add(self.column_widgets)

    def update_task(self, task):
        if task.task_data:
            column_count = len(task.task_data["headers"])
            while self.column_widgets.count() > column_count:
                self.column_widgets.remove(self.column_widgets.count() - 1)
            while self.column_widgets.count() < column_count:
                self.column_widgets.add(self.ui.create_column_widget())
            row_count = len(task.task_data["data"]) if "data" in task.task_data else 0
            for column_index, column_widget in enumerate(self.column_widgets.children):
                while column_widget.count() > row_count + 1:
                    column_widget.remove(column_widget.count() - 1)
                while column_widget.count() < row_count + 1:
                    # bold on first row. not working?
                    properties = {"stylesheet": "font-weight: bold"} if column_widget.count() == 0 else None
                    column_widget.add(self.ui.create_label_widget(properties))
                column_widget.children[0].text = task.task_data["headers"][column_index]
                for row_index in xrange(row_count):
                    column_widget.children[row_index + 1].text = str(task.task_data["data"][row_index][column_index])
        else:
            self.column_widgets.remove_all()


class StringListController(object):

    def __init__(self, ui):
        self.ui = ui
        self.widget = self.ui.create_label_widget("[]")

    def update_task(self, task):
        strings = task.task_data["strings"] if task.task_data else list()
        self.widget.text = "[" + ":".join(strings) + "]"

TaskManager().register_task_type_builder("string_list", lambda ui: StringListController(ui))
TaskManager().register_task_type_builder("table", lambda ui: TableController(ui))