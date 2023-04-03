#!/usr/bin/env python
# -*- coding: utf-8 -*-

import unittest
import pcbnew
import logging
import sys
import os
from save_restore_layout import SaveLayout
from save_restore_layout import RestoreLayout


class TestSave(unittest.TestCase):

    def test_path(self):
        prj_dir = os.path.normpath(os.path.dirname(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                                                "SaveRestoreSourceProject_path_issue/")))
        source_file = os.path.join(prj_dir, 'save_restore_source_project.kicad_pcb')

        board = pcbnew.LoadBoard(source_file)
        src_anchor_fp_ref = 'L401'
        save_layout = SaveLayout(board, src_anchor_fp_ref)

        # get the level from user
        level = 1

        data_file = os.path.join(prj_dir, 'source_layout_test_shallow.pckl')
        save_layout.save_layout(save_layout.src_anchor_fp.sheet_id[0:level + 1], data_file,
                                True, True, True, True, True)

    @unittest.SkipTest
    def test_save_shallow(self):
        prj_dir = os.path.normpath(os.path.dirname(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                   "SaveRestoreSourceProject/")))
        source_file = os.path.join(prj_dir, 'save_restore_source_project.kicad_pcb')

        board = pcbnew.LoadBoard(source_file)
        src_anchor_fp_ref = 'L401'
        save_layout = SaveLayout(board, src_anchor_fp_ref)

        # get the level from user
        level = 1

        data_file = os.path.join(prj_dir, 'source_layout_test_shallow.pckl')
        save_layout.save_layout(save_layout.src_anchor_fp.sheet_id[0:level + 1], data_file,
                                True, True, True, True, True)

    @unittest.SkipTest
    def test_save_deep(self):
        prj_dir = os.path.normpath(os.path.dirname(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                   "SaveRestoreSourceProject/")))
        source_file = os.path.join(prj_dir, 'save_restore_source_project.kicad_pcb')

        board = pcbnew.LoadBoard(source_file)
        src_anchor_fp_ref = 'L401'
        save_layout = SaveLayout(board, src_anchor_fp_ref)

        # get the level from user
        level = 0

        data_file = os.path.join(prj_dir, 'source_layout_test_deep.pckl')
        save_layout.save_layout(save_layout.src_anchor_fp.sheet_id[0:level + 1], data_file,
                                True, True, True, True, True)

    @unittest.SkipTest
    def test_restore_shallow_different_level(self):
        prj_dir = os.path.normpath(os.path.dirname(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                   "SaveRestoreDestinationProject/")))
        src_prj_dir = os.path.normpath(os.path.dirname(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                                                    "SaveRestoreSourceProject/")))
        data_file = os.path.join(src_prj_dir, 'source_layout_test_shallow.pckl')
        destination_file = os.path.join(prj_dir, 'save_restore_destination_project.kicad_pcb')
        board = pcbnew.LoadBoard(destination_file)
        dst_anchor_fp_ref = 'L201'
        restore_layout = RestoreLayout(board, dst_anchor_fp_ref, "Shallow, different level")

        restore_layout.restore_layout(data_file)

        saved = pcbnew.SaveBoard(destination_file.replace(".kicad_pcb", "_shallow_different.kicad_pcb"), board)

    @unittest.SkipTest
    def test_restore_shallow_same_level(self):
        prj_dir = os.path.normpath(os.path.dirname(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                   "SaveRestoreDestinationProject/")))
        src_prj_dir = os.path.normpath(os.path.dirname(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                                                    "SaveRestoreSourceProject/")))
        data_file = os.path.join(src_prj_dir, 'source_layout_test_shallow.pckl')
        destination_file = os.path.join(prj_dir, 'save_restore_destination_project.kicad_pcb')
        board = pcbnew.LoadBoard(destination_file)
        dst_anchor_fp_ref = 'L401'
        restore_layout = RestoreLayout(board, dst_anchor_fp_ref, "Shallow_same_level")

        restore_layout.restore_layout(data_file)

        saved = pcbnew.SaveBoard(destination_file.replace(".kicad_pcb", "_shallow_same.kicad_pcb"), board)

    @unittest.SkipTest
    def test_restore_deep(self):
        prj_dir = os.path.normpath(os.path.dirname(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                   "SaveRestoreDestinationProject/")))
        src_prj_dir = os.path.normpath(os.path.dirname(os.path.join(os.path.dirname(os.path.realpath(__file__)),
                                                                    "SaveRestoreSourceProject/")))
        data_file = os.path.join(src_prj_dir, 'source_layout_test_deep.pckl')
        destination_file = os.path.join(prj_dir, 'save_restore_destination_project.kicad_pcb')
        board = pcbnew.LoadBoard(destination_file)
        dst_anchor_fp_ref = 'L401'
        restore_layout = RestoreLayout(board, dst_anchor_fp_ref, None)

        restore_layout.restore_layout(data_file)

        saved = pcbnew.SaveBoard(destination_file.replace(".kicad_pcb", "_deep.kicad_pcb"), board)


if __name__ == "__main__":
    file_handler = logging.FileHandler(filename='save_restore_layout.log', mode='w')
    stdout_handler = logging.StreamHandler(sys.stdout)
    handlers = [file_handler, stdout_handler]

    logging_level = logging.INFO

    logging.basicConfig(level=logging_level,
                        format='%(asctime)s %(name)s %(lineno)d:%(message)s',
                        datefmt='%m-%d %H:%M:%S',
                        handlers=handlers
                        )

    logger = logging.getLogger(__name__)
    logger.info("Plugin executed on: " + repr(sys.platform))
    logger.info("Plugin executed with python version: " + repr(sys.version))
    logger.info("KiCad build version: " + str(pcbnew.GetBuildVersion()))

    unittest.main()
