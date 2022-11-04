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
from .error_dialog_GUI import ErrorDialogGUI

from .save_restore_layout import SaveLayout
from .save_restore_layout import RestoreLayout


class ErrorDialog(ErrorDialogGUI):
    def SetSizeHints(self, sz1, sz2):
        # DO NOTHING
        pass

    def __init__(self, parent):
        super(ErrorDialog, self).__init__(parent)


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

    def __init__(self, parent, layout_saver, logger):
        super(SaveRestoreDialog, self).__init__(parent)

        self.logger = logger
        self.save_layout = layout_saver
        self.list_levels.Clear()
        self.list_levels.AppendItems(layout_saver.src_anchor_fp.filename)

        self.hl_fps = []
        self.hl_items = []

    def level_changed(self, event):
        # clear highlight on all footprints on selected level
        self.save_layout.highlight_clear_level(self.hl_fps, self.hl_items)
        self.hl_fps = []
        self.hl_items = []
        pcbnew.Refresh()

        # highlight all footprints on selected level
        (self.hl_fps, self.hl_items) = self.save_layout.highlight_set_level(self.save_layout.src_anchor_fp.sheet_id[0:self.list_levels.GetSelection() + 1],
                                                                            self.cb_tracks.GetValue(),
                                                                            self.cb_zones.GetValue(),
                                                                            self.cb_text.GetValue(),
                                                                            self.cb_drawings.GetValue(),
                                                                            self.cb_intersecting.GetValue())
        pcbnew.Refresh()
        event.Skip()

    def __del__(self):
        # clear highlight on all footprints on selected level
        self.save_layout.highlight_clear_level(self.hl_fps, self.hl_items)
        self.hl_fps = []
        self.hl_items = []
        pcbnew.Refresh()


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
            logger.info("Plugin failed to run as more or less then 1 footprint selected")
            caption = 'Save/Restore Layout'
            message = "More or less than 1 footprint selected. Please select exactly one footprint " \
                      "and run the plugin again"
            dlg = wx.MessageDialog(self.frame, message, caption, wx.OK | wx.ICON_INFORMATION)
            dlg.ShowModal()
            dlg.Destroy()
            return

        # this is the source anchor footprint reference
        anchor_fp_ref = selected_footprints[0]
        logger.info("Anchor footprint reference is " + repr(anchor_fp_ref))

        # show initial dialog
        dlg = InitialDialog(self.frame)
        res = dlg.ShowModal()
        dlg.Destroy()

        if res == InitialDialog.SAVE:
            src_anchor_fp_ref = anchor_fp_ref
            logger.info("Save layout chosen")
            # prepare the layout to save
            try:
                save_layout = SaveLayout(board, src_anchor_fp_ref)
            except Exception:
                logger.exception("Fatal error when creating an instance of SaveLayout")
                e_dlg = ErrorDialog(self.frame)
                e_dlg.ShowModal()
                e_dlg.Destroy()
                logging.shutdown()
                return

            # show the level GUI
            main_dlg = SaveRestoreDialog(self.frame, save_layout, logger)
            main_dlg.CenterOnParent()
            action = main_dlg.ShowModal()
            if action == wx.ID_OK:
                # get the selected level
                selected_level = main_dlg.list_levels.GetSelection()
                # if user did not select any level available cancel
                if selected_level < 0:
                    logger.info("User failed to select hierarchy level to save")
                    caption = 'Save/Restore Layout'
                    message = "One hierarchical level has to be chosen"
                    dlg = wx.MessageDialog(self.frame, message, caption, wx.OK | wx.ICON_INFORMATION)
                    dlg.ShowModal()
                    dlg.Destroy()
                    logging.shutdown()
                    main_dlg.Destroy()
                    return

                # Ask the user top specify file
                wildcard = "Saved Layout Files (*.pckl)|*.pckl"
                dlg = wx.FileDialog(self.frame, "Select a file", os.getcwd(),
                                    save_layout.src_anchor_fp.filename[selected_level].strip(".kicad_sch"), wildcard,
                                    wx.FD_SAVE)
                res = dlg.ShowModal()
                if res != wx.ID_OK:
                    logger.info("No filename given. User canceled the plugin during file save selection")
                    logging.shutdown()
                    dlg.Destroy()
                    main_dlg.Destroy()
                    return
                data_file = dlg.GetPath()
                dlg.Destroy()

                # run the plugin
                logger.info("Saving the layout in " + repr(data_file) + " for level " + repr(selected_level))
                try:
                    save_layout.save_layout(save_layout.src_anchor_fp.sheet_id[0:selected_level + 1], data_file,
                                            main_dlg.cb_tracks.GetValue(),
                                            main_dlg.cb_zones.GetValue(),
                                            main_dlg.cb_text.GetValue(),
                                            main_dlg.cb_drawings.GetValue(),
                                            main_dlg.cb_intersecting.GetValue())
                except Exception:
                    logger.exception("Fatal error running SaveLayout")
                    e_dlg = ErrorDialog(self.frame)
                    e_dlg.ShowModal()
                    e_dlg.Destroy()
                    logging.shutdown()
                    return

                pass

            main_dlg.Destroy()
            logging.shutdown()
            return

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

            # create an instance
            try:
                restore_layout = RestoreLayout(board, dst_anchor_fp_ref)
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

            # run the main backend
            try:
                restore_layout.restore_layout(layout_file)
            except (ValueError, LookupError) as error:
                caption = 'Save/Restore Layout'
                message = str(error)
                dlg = wx.MessageDialog(self.frame, message, caption, wx.OK | wx.ICON_EXCLAMATION)
                dlg.ShowModal()
                dlg.Destroy()
                logger.exception("Error when restoring layout")
                logging.shutdown()
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
            logging.shutdown()
            return
