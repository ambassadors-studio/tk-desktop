# Copyright (c) 2013 Shotgun Software Inc.
#
# CONFIDENTIAL AND PROPRIETARY
#
# This work is provided "AS IS" and subject to the Shotgun Pipeline Toolkit
# Source Code License included in this distribution package. See LICENSE.
# By accessing, using, copying or modifying this work you indicate your
# agreement to the Shotgun Pipeline Toolkit Source Code License. All rights
# not expressly granted therein are reserved by Shotgun Software Inc.

import re
import datetime

from PySide import QtGui
from PySide import QtCore

import sgtk

from .login import ShotgunLogin
from .grouping_model import GroupingModel
from .grouping_model import GroupingProxyModel


class ProjectCommandProxyModel(GroupingProxyModel):
    def __init__(self, parent=None):
        GroupingProxyModel.__init__(self, parent)
        self.setDynamicSortFilter(True)

    def lessThan(self, left, right):
        # Order recents then pass through to default grouping order
        src_model = self.sourceModel()

        if not src_model.is_content(left) or not src_model.is_content(right):
            # only sort content
            return GroupingProxyModel.lessThan(self, left, right)

        left_group = src_model.get_item_group_key(left)
        right_group = src_model.get_item_group_key(right)

        if left_group != ProjectCommandModel.RECENT_GROUP_NAME or \
           right_group != ProjectCommandModel.RECENT_GROUP_NAME:
            # only sort when both content are from the Recent group
            return GroupingProxyModel.lessThan(self, left, right)

        left_launch = left.data(ProjectCommandModel.LAST_LAUNCH_ROLE)
        right_launch = right.data(ProjectCommandModel.LAST_LAUNCH_ROLE)
        return left_launch > right_launch


class ProjectCommandModel(GroupingModel):
    APP_LAUNCH_EVENT_TYPE = "Toolkit_Desktop_AppLaunch"

    RECENT_GROUP_NAME = "RECENT"

    BUTTON_NAME_ROLE = QtCore.Qt.UserRole + 1
    MENU_NAME_ROLE = QtCore.Qt.UserRole + 2
    COMMAND_ROLE = QtCore.Qt.UserRole + 3
    LAST_LAUNCH_ROLE = QtCore.Qt.UserRole + 4

    # signal emitted when a command is triggered
    # arguments are the group and the command_name of the triggered command
    command_triggered = QtCore.Signal(str, str)

    def __init__(self, parent=None):
        GroupingModel.__init__(self, parent)

        self.__project = None
        self.__recents = {}

    def set_project(self, project, groups):
        self.clear()
        self.__project = project

        (header, _) = self.create_group(self.RECENT_GROUP_NAME)
        self.set_group_rank(self.RECENT_GROUP_NAME, 0)
        for (i, group) in enumerate(groups):
            group = group.upper()
            (header, _) = self.create_group(group)
            self.set_group_rank(group, i+1)

        self.__initialize_recents()

    def add_command(self, name, button_name, menu_name, icon, command_tooltip, groups):
        if name in self.__recents:
            item = QtGui.QStandardItem()
            item.setData(button_name, self.BUTTON_NAME_ROLE)
            item.setData(menu_name, self.MENU_NAME_ROLE)
            item.setData(name, self.COMMAND_ROLE)
            item.setToolTip(command_tooltip)
            item.setData(self.__recents[name]["timestamp"], self.LAST_LAUNCH_ROLE)
            if icon is not None:
                item.setIcon(icon)

            self.set_item_group(item, self.RECENT_GROUP_NAME)
            self.appendRow(item)

        for group in groups:
            group = group.upper()

            # Has this command already been added?
            start = self.index(0, 0)
            match_flags = QtCore.Qt.MatchExactly
            indexes_in_group = self.match(start, self.GROUP_ROLE, group, -1, match_flags)

            item = None
            for index in indexes_in_group:
                if index.data(self.BUTTON_NAME_ROLE) == button_name:
                    # button already exists in this group, reuse item
                    item = self.itemFromIndex(index)
                    break

            if item is None:
                item = QtGui.QStandardItem()
                item.setData(button_name, self.BUTTON_NAME_ROLE)
                item.setData(menu_name, self.MENU_NAME_ROLE)
                item.setData(name, self.COMMAND_ROLE)
                item.setToolTip(command_tooltip)

                if icon is not None:
                    item.setIcon(icon)
                self.set_item_group(item, group)
                self.appendRow(item)

            if menu_name is not None:
                menu_item = QtGui.QStandardItem()
                menu_item.setData(button_name, self.BUTTON_NAME_ROLE)
                menu_item.setData(menu_name, self.MENU_NAME_ROLE)
                menu_item.setData(name, self.COMMAND_ROLE)
                menu_item.setToolTip(command_tooltip)
                if icon is not None:
                    menu_item.setIcon(icon)
                item.appendRow(menu_item)

    def _handle_command_triggered(self, item, command_name=None, button_name=None,
                                  menu_name=None, icon=None, tooltip=None):
        # Create an event log entry to track app launches
        engine = sgtk.platform.current_engine()
        connection = engine.shotgun

        group_name = item.data(self.GROUP_ROLE)
        if command_name is None:
            command_name = item.data(self.COMMAND_ROLE)
        if button_name is None:
            button_name = item.data(self.BUTTON_NAME_ROLE)
        if menu_name is None:
            menu_name = item.data(self.MENU_NAME_ROLE)
        if icon is None:
            icon = item.data(QtCore.Qt.DecorationRole)
        if tooltip is None:
            tooltip = item.toolTip()

        login = ShotgunLogin.get_login()
        data = {
            # recent is populated by grouping on description, so it needs
            # to be the same for each event created for a given name, but
            # different for different names
            #
            # this is parsed when populating the recents menu
            "description": "App '%s' launched from tk-desktop-engine" % command_name,
            "event_type": self.APP_LAUNCH_EVENT_TYPE,
            "project": self.__project,
            "meta": {"name": command_name, "group": group_name},
            "user": login,
        }

        # use toolkit connection to get ApiUser permissions for event creation
        engine.log_debug("Registering app launch event: %s" % data)
        connection.create("EventLogEntry", data)

        # find the corresponding recent if it exists
        start = self.index(0, 0)
        match_flags = QtCore.Qt.MatchExactly
        indexes_in_recent = self.match(start, self.GROUP_ROLE, self.RECENT_GROUP_NAME, -1, match_flags)

        recent_item = None
        for index in indexes_in_recent:
            if index.data(self.COMMAND_ROLE) == command_name:
                recent_item = self.itemFromIndex(index)
                break

        # create it if it doesn't
        if recent_item is None:
            recent_item = QtGui.QStandardItem()
            recent_item.setData(button_name, self.BUTTON_NAME_ROLE)
            recent_item.setData(menu_name, self.MENU_NAME_ROLE)
            recent_item.setData(command_name, self.COMMAND_ROLE)
            recent_item.setToolTip(tooltip)
            if icon is not None:
                recent_item.setIcon(icon)

            self.set_item_group(recent_item, self.RECENT_GROUP_NAME)
            self.appendRow(recent_item)

        # update its timestamp, keep everything in utc which is what shotgun does
        recent_item.setData(datetime.datetime.utcnow(), self.LAST_LAUNCH_ROLE)

        # and notify that the command was triggered
        self.command_triggered.emit(group_name, command_name)

    def __initialize_recents(self):
        """
        Pull down the information from Shotgun for what the recent command
        launches have been.  Needed to track which ones are still registered.
        """
        # dictionary to keep track of the commands launched with recency information
        # each command name keeps track of a timestamp of when it was last launched
        # and a boolean saying whether the corresponding command has been registered
        self.__recents = {}

        # need to know what login to find events for
        login = ShotgunLogin.get_login()

        # pull down matching invents for the current project for the current user
        filters = [
            ["user", "is", login],
            ["project", "is", self.__project],
            ["event_type", "is", self.APP_LAUNCH_EVENT_TYPE],
        ]

        # execute the Shotgun summarize command
        # get one group per description with a summary of the latest created_at
        connection = sgtk.platform.current_engine().shotgun
        summary = connection.summarize(
            entity_type="EventLogEntry",
            filters=filters,
            summary_fields=[{"field": "created_at", "type": "latest"}],
            grouping=[{"field": "description", "type": "exact", "direction": "desc"}],
        )

        # parse the results
        for group in summary["groups"]:
            # convert the text representation of created_at to a datetime
            text_stamp = group["summaries"]["created_at"]
            time_stamp = datetime.datetime.strptime(text_stamp, "%Y-%m-%d %H:%M:%S %Z")

            # pull the command name from the description
            description = group["group_name"]
            match = re.search("'(?P<name>.+)'", description)
            if match is not None:
                name = match.group("name")

                # if multiple descriptions end up with the same name use the most recent one
                existing_info = self.__recents.setdefault(
                    name, {"timestamp": time_stamp})
                if existing_info["timestamp"] < time_stamp:
                    self.__recents[name]["timestamp"] = time_stamp