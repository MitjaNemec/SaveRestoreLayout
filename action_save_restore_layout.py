# -*- coding: utf-8 -*-
#  action_save_restore_layout.py
#
# Copyright (C) 2019 Mitja Nemec
#
#  This program is free software; you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation; either version 2 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program; if not, write to the Free Software
#  Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston,
#  MA 02110-1301, USA.
#
#
import wx
import pcbnew
import os
import logging
import sys

from .save_layout_dialog_GUI import SaveLayoutDialogGUI
from .initial_dialog_GUI import InitialDialogGUI


class InitialDialog(InitialDialogGUI):
    SAVE = 1025
    RESTORE = 1026

    # hack for new wxFormBuilder generating code incompatible with old wxPython
    # noinspection PyMethodOverriding
    def SetSizeHints(self, sz1, sz2):
        # DO NOTHING
        pass

    def __init__(self, parent):
        super(InitialDialog, self).__init__(parent)

    def on_save(self, event):
        event.Skip()
        self.EndModal(InitialDialog.SAVE)

    def on_restore(self, event):
        event.Skip()
        self.EndModal(InitialDialog.RESTORE)


class SaveRestoreDialog(SaveLayoutDialogGUI):
    def SetSizeHints(self, sz1, sz2):
        # DO NOTHING
        pass

    def __init__(self, parent, levels, layout_saver, src_anchor_fp, board, logger):
        super(SaveRestoreDialog, self).__init__(parent)

        self.logger = logger
        self.board = board
        self.brd_fps = self.board.GetFootprints()
        self.src_anchor_fp = src_anchor_fp
        self.save_layout = layout_saver
        self.scr_fps = []
        self.list_levels.Clear()
        self.list_levels.AppendItems(levels)

        self.src_footprints = []
        self.hl_fps = []
        self.hl_items = []

    def level_changed(self, event):
        # clear highlight on all footprints on selected level
        self.save_layout.highlight_clear_level(self.hl_fps, self.hl_items)
        self.hl_fps = []
        self.hl_items = []
        pcbnew.Refresh()

        # highlight all footprints on selected level
        (self.hl_fps, self.hl_items) = self.save_layout.highlight_set_level(self.src_anchor_fp.sheet_id[0:self.list_levels.GetSelection() + 1],
                                                                            True,
                                                                            True,
                                                                            True,
                                                                            True,
                                                                            False)
        pcbnew.Refresh()
        event.Skip()

    def on_ok(self, event):
        pass
        event.Skip()

    def on_cancel(self, event):
        pass
        event.Skip()


class SaveRestoreLayout(pcbnew.ActionPlugin):
    def __init__(self):
        super(SaveRestoreLayout, self).__init__()

        self.frame = None

        self.name = "Save/Restore Layout"
        self.category = "Save Restore Layout"
        self.description = "The plugin can save and restore partial layout of footprints from one hierarchical sheet."
        self.icon_file_name = os.path.join(
            os.path.dirname(__file__), 'save_restore_layout_light.png')
        self.dark_icon_file_name = os.path.join(
            os.path.dirname(__file__), 'save_restore_layout_dark.png')

        self.debug_level = logging.INFO

        # plugin paths
        self.plugin_folder = os.path.join(os.path.dirname(os.path.abspath(__file__)))
        self.version_file_path = os.path.join(self.plugin_folder, 'version.txt')

        # load the plugin version
        with open(self.version_file_path) as fp:
            self.version = fp.readline()

    def defaults(self):
        pass

    def Run(self):
        # grab PCB editor frame
        self.frame = wx.FindWindowByName("PcbFrame")

        # load board
        board = pcbnew.GetBoard()
        pass

        # go to the project folder - so that log will be in proper place
        os.chdir(os.path.dirname(os.path.abspath(board.GetFileName())))

        # Remove all handlers associated with the root logger object.
        for handler in logging.root.handlers[:]:
            logging.root.removeHandler(handler)

        file_handler = logging.FileHandler(filename='save_restore_layout.log', mode='w')
        handlers = [file_handler]

        # set up logger
        logging.basicConfig(level=logging.INFO,
                            format='%(asctime)s %(name)s %(lineno)d:%(message)s',
                            datefmt='%m-%d %H:%M:%S',
                            handlers=handlers)
        logger = logging.getLogger(__name__)
        logger.info("Plugin executed on: " + repr(sys.platform))
        logger.info("Plugin executed with python version: " + repr(sys.version))
        logger.info("KiCad build version: " + str(pcbnew.GetBuildVersion()))
        logger.info("Plugin version: " + self.version)
        logger.info("Frame repr: " + repr(self.frame))

        # check if there is exactly one footprints selected
        selected_footprints = [x.GetReference() for x in board.GetFootprints() if x.IsSelected()]

        # if more or less than one show only a message box
        if len(selected_footprints) != 1:
            caption = 'Save/Restore Layout'
            message = "More or less than 1 footprint selected. Please select exactly one footprint " \
                      "and run the plugin again"
            dlg = wx.MessageDialog(self.frame, message, caption, wx.OK | wx.ICON_INFORMATION)
            dlg.ShowModal()
            dlg.Destroy()
            return

        # this is the source anchor footprint reference
        anchor_fp_ref = selected_footprints[0]

        # show initial dialog
        dlg = InitialDialog(self.frame)
        res = dlg.ShowModal()
        dlg.Destroy()

        if res == InitialDialog.SAVE:
            src_anchor_fp_ref = anchor_fp_ref
            logger.info("Save layout chosen")
            # prepare the layout to save
            pass
        if res == InitialDialog.RESTORE:
            dst_anchor_fp_ref = anchor_fp_ref
            logger.info("Restore layout chosen")

            # ask the user to find the layout information file
            wildcard = "Saved Layout Files (*.pckl)|*.pckl"
            dlg = wx.FileDialog(self.frame, "Choose a file", os.getcwd(), "", wildcard, wx.FD_OPEN)
            res = dlg.ShowModal()
            if res != wx.ID_OK:
                logging.shutdown()
                return
            layout_file = dlg.GetPath()
            dlg.Destroy()

            try:
                restore_layout = save_restore_layout.RestoreLayout(board)
            except Exception:
                logger.exception("Fatal error when creating an instance of RestoreLayout")
                caption = 'Save/Restore Layout'
                message = "Fatal error when creating an instance of RestoreLayout.\n" \
                          + "You can raise an issue on GiHub page.\n" \
                          + "Please attach the save_restore_layout.log which you should find in the project folder."
                dlg = wx.MessageDialog(self.frame, message, caption, wx.OK | wx.ICON_ERROR)
                dlg.ShowModal()
                dlg.Destroy()
                logging.shutdown()
                return

            dst_anchor_fp = restore_layout.get_mod_by_ref(dst_anchor_fp_ref)

            try:
                restore_layout.restore_layout(dst_anchor_fp, layout_file)
            except (ValueError, LookupError) as error:
                caption = 'Save/Restore Layout'
                message = str(error)
                dlg = wx.MessageDialog(self.frame, message, caption, wx.OK | wx.ICON_EXCLAMATION)
                dlg.ShowModal()
                dlg.Destroy()
                logger.exception("Error when restoring layout")
                return
            except Exception:
                logger.exception("Fatal error when restoring layout")
                caption = 'Save/Restore Layout'
                message = "Fatal error when restoring layout.\n" \
                          + "You can raise an issue on GiHub page.\n" \
                          + "Please attach the save_restore_layout.log which you should find in the project folder."
                dlg = wx.MessageDialog(self.frame, message, caption, wx.OK | wx.ICON_ERROR)
                dlg.ShowModal()
                dlg.Destroy()
                logging.shutdown()
                return
