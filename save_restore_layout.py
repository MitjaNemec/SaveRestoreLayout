# -*- coding: utf-8 -*-
#  save_restore_layout.py
#
# Copyright (C) 2022 Mitja Nemec
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

import pcbnew
from collections import namedtuple
import logging
import math
import os
import tempfile
import hashlib
import pickle
import json

with open(os.path.join(os.path.join(os.path.dirname(os.path.abspath(__file__))), 'version.txt')) as fp:
    VERSION = fp.readline()

Footprint = namedtuple('Footprint', ['ref', 'fp', 'fp_id', 'sheet_id', 'filename'])
LayoutData = namedtuple('LayoutData', ['version', 'layout', 'hash', 'dict_of_sheets', 'list_of_local_nets',
                                       'level', 'level_filename', 'layer_count'])
logger = logging.getLogger(__name__)


def rotate_around_center(coordinates, angle):
    """ rotate coordinates for a defined angle in degrees around coordinate center"""
    new_x = coordinates[0] * math.cos(2 * math.pi * angle / 360) \
            - coordinates[1] * math.sin(2 * math.pi * angle / 360)
    new_y = coordinates[0] * math.sin(2 * math.pi * angle / 360) \
            + coordinates[1] * math.cos(2 * math.pi * angle / 360)
    return new_x, new_y


def rotate_around_point(old_position, point, angle):
    """ rotate coordinates for a defined angle in degrees around a point """
    # get relative position to point
    rel_x = old_position[0] - point[0]
    rel_y = old_position[1] - point[1]
    # rotate around
    new_rel_x, new_rel_y = rotate_around_center((rel_x, rel_y), angle)
    # get absolute position
    new_position = (new_rel_x + point[0], new_rel_y + point[1])
    return new_position


def find_all(string, substring):
    indices = [index for index in range(len(string)) if string.startswith(substring, index)]
    return indices


def get_sch_hash(sch_file, md5hash):

    # load sch file
    with open(sch_file, 'rb') as f:
        file_contents = f.read().decode('utf-8').replace("\r", "")

    # remove all "(property "Reference" "R201"" lines as they might differ in reference number
    contents_by_line = file_contents.split("\n")
    contents_by_line_removed = []
    for c in contents_by_line:
        if "(property \"Reference\"" not in c:
            contents_by_line_removed.append(c)
    file_contents_without_references = "\n".join(contents_by_line_removed)

    # remove all instances
    filtered_contents = ""
    instances_start = find_all(file_contents_without_references, "(instances")
    instances_stop = []
    instance_end_old = 0
    for instance_start in instances_start:
        current_index = instance_start + 1
        number_of_parentheses = 1
        # find termination

        while number_of_parentheses != 0:
            a = file_contents_without_references[current_index]
            if file_contents_without_references[current_index] == "(":
                number_of_parentheses = number_of_parentheses + 1
            if file_contents_without_references[current_index] == ")":
                number_of_parentheses = number_of_parentheses - 1
            current_index = current_index + 1
        instance_end = current_index
        instances_stop.append(instance_end)

        # concatenated everything between
        filtered_contents = filtered_contents + file_contents_without_references[instance_end_old:instance_start]
        instance_end_old = instance_end
    # add last part
    filtered_contents = filtered_contents + file_contents_without_references[instance_end_old:-1]

    # calculate the hash - disregard the empty lines
    hash_lines = [hashlib.md5(line.encode('utf-8')).hexdigest() for line in filtered_contents.split('\n') if line.strip()]

    # sort hashes - so that summed has is more robust to positional changes of schematics
    hash_lines.sort()

    # get hash of hashes
    for h in hash_lines:
        md5hash.update(h.encode('utf-8'))

    return md5hash


def get_index_of_tuple(list_of_tuples, index, value):
    for pos, t in enumerate(list_of_tuples):
        if t[index] == value:
            return pos


def flipped_angle(angle):
    if angle > 0:
        return 180 - angle
    else:
        return -180 - angle


def get_footprint_text_items(footprint):
    """ get all text item belonging to a footprint """
    list_of_items = [footprint.fp.Reference(), footprint.fp.Value()]

    footprint_items = footprint.fp.GraphicalItems()
    for item in footprint_items:
        if type(item) is pcbnew.PCB_TEXT:
            list_of_items.append(item)
    return list_of_items


def semver_compare(ver_1, ver_2):
    ver_1_list = [int(x) for x in ver_1.split(".")]
    ver_2_list = [int(x) for x in ver_2.split(".")]
    for i in range(min(len(ver_1_list), len(ver_2_list))):
        if ver_2_list[i] > ver_1_list[i]:
            return False
        if ver_2_list[i] < ver_1_list[i]:
            return True
    return True


class PrjData:
    def __init__(self, board, dict_of_sheets=None):
        self.board = board

        self.level = None
        self.src_anchor_fp = None
        self.src_sheet = None
        self.src_footprints = []
        self.src_local_nets = []
        self.src_bounding_box = None
        self.src_tracks = []
        self.src_zones = []
        self.src_text = []
        self.src_drawings = []

        self.pcb_filename = os.path.abspath(board.GetFileName())
        self.sch_filename = self.pcb_filename.replace(".kicad_pcb", ".kicad_sch")
        self.project_folder = os.path.dirname(self.pcb_filename)

        # construct a list of footprints with all pertinent data
        logger.info('getting a list of all footprints on board')
        footprints = board.GetFootprints()
        self.footprints = []

        # get dict_of_sheets from layout data only (through footprint Sheetfile and Sheetname properties)
        if dict_of_sheets is None:
            self.dict_of_sheets = {}
            unique_sheet_ids = set()
            for fp in footprints:
                # construct a set of unique sheets from footprint properties
                path = fp.GetPath().AsString().upper().replace('00000000-0000-0000-0000-0000', '').split("/")
                sheet_path = path[0:-1]
                for x in sheet_path:
                    unique_sheet_ids.add(x)

                sheet_id = self.get_sheet_id(fp)
                try:
                    sheet_file = fp.GetSheetfile()
                    sheet_name = fp.GetSheetname()
                except KeyError:
                    logger.info("Footprint " + fp.GetReference() +
                                " does not have Sheetfile property, it will not be considered for placement."
                                " Most likely it is only in layout")
                    continue
                # footprint is in the schematics and has Sheetfile property
                if sheet_file and sheet_id:
                    self.dict_of_sheets[sheet_id] = [sheet_name, sheet_file]
                # footprint is in the schematics but has no Sheetfile properties
                elif sheet_id:
                    logger.info("Footprint " + fp.GetReference() + " does not have Sheetfile property")
                    raise LookupError("Footprint " + str(
                        fp.GetReference()) + " doesn't have Sheetfile and Sheetname properties. "
                                             "You need to update the layout from schematics")
                # footprint is only in the layout
                else:
                    logger.debug("Footprint " + fp.GetReference() + " is only in layout")

            # catch corner cases with nested hierarchy, where some hierarchical pages don't have any footprints
            unique_sheet_ids.remove("")
            if len(unique_sheet_ids) > len(self.dict_of_sheets):
                # open root schematics file and parse for other schematics files
                # This might be prone to errors regarding path discovery
                # thus it is used only in corner cases
                schematic_found = {}
                self.parse_schematic_files(self.sch_filename, schematic_found)
                # make all paths relative
                self.dict_of_sheets = {}
                for item in schematic_found.items():
                    sheet_name = item[1][0]
                    sheet_path = item[1][1]
                    rel_sheet_path = sheet_path
                    self.dict_of_sheets[item[0]] = [sheet_name, rel_sheet_path]
        else:
            self.dict_of_sheets = dict_of_sheets

        # test if all filenames exist, if not, try finding one in a subfolder if avaialble
        other_folders = []
        for k, i in self.dict_of_sheets.items():
            d = os.path.dirname(i[1])
            if d:
                other_folders.append(d)
        # test and correct
        for k, i in self.dict_of_sheets.items():
            f = i[1]
            if not os.path.exists(os.path.join(self.project_folder, f)):
                for d in other_folders:
                    if os.path.exists(os.path.join(self.project_folder, d, f)):
                        self.dict_of_sheets[k] = [i[0], os.path.join(d, f)]

        # construct a list of all the footprints
        for fp in footprints:
            fp_ref = fp.GetReference()
            fp_tuple = Footprint(fp=fp,
                                 fp_id=self.get_footprint_id(fp),
                                 sheet_id=self.get_sheet_path(fp)[0],
                                 filename=self.get_sheet_path(fp)[1],
                                 ref=fp.GetReference())
            self.footprints.append(fp_tuple)
        pass
        # TODO check if there is any other footprint fit same ID as anchor footprint

    def parse_schematic_files(self, filename, dict_of_sheets):
        filename_dir = os.path.dirname(filename)

        with open(filename, encoding='utf-8') as f:
            contents = f.read()

        indexes = []
        level = []
        sheet_definitions = []
        new_lines = []
        lvl = 0
        # get the nesting levels at index
        for idx in range(len(contents) - 20):
            if contents[idx] == "(":
                lvl = lvl + 1
                level.append(lvl)
                indexes.append(idx)
            if contents[idx] == ")":
                lvl = lvl - 1
                level.append(lvl)
                indexes.append(idx)
            if contents[idx] == "\n":
                new_lines.append(idx)
            a = contents[idx:idx + 20]
            if a.startswith("(sheet\n") or a.startswith("(sheet "):
                sheet_definitions.append(idx)

        start_idx = sheet_definitions
        end_idx = sheet_definitions[1:]
        end_idx.append(len(contents))
        braces = list(zip(indexes, level))
        # parse individual sheet definitions (if any)
        for start, end in zip(start_idx, end_idx):
            def next_bigger(l, v):
                for m in l:
                    if m > v:
                        return m

            uuid_loc = contents[start:end].find('(uuid') + start
            uuid_loc_end = next_bigger(new_lines, uuid_loc)
            uuid_complete_string = contents[uuid_loc:uuid_loc_end]
            uuid = uuid_complete_string.strip("(uuid").strip(")").replace("\"", '').upper().lstrip()

            v8encoding = contents[start:end].find('(property "Sheetname\"')
            v7encoding = contents[start:end].find('(property "Sheet name\"')
            if v8encoding != -1:
                offset = v8encoding
            elif v7encoding != -1:
                offset = v7encoding
            else:
                logger.info(f'Did not found sheetname properties in the schematic file '
                            f'in {filename} line:{str(i)}')
                raise LookupError(f'Did not found sheetname properties in the schematic file '
                                  f'in {filename} line:{str(i)}. Unsupported schematics file format')
            sheetname_loc = offset + start
            sheetname_loc_end = next_bigger(new_lines, sheetname_loc)
            sheetname_complete_string = contents[sheetname_loc:sheetname_loc_end]
            sheetname = sheetname_complete_string.strip("(property").split('"')[1::2][1]

            v8encoding = contents[start:end].find('(property "Sheetfile\"')
            v7encoding = contents[start:end].find('(property "Sheet file\"')
            if v8encoding != -1:
                offset = v8encoding
            elif v7encoding != -1:
                offset = v7encoding
            else:
                logger.info(f'Did not found sheetfile properties in the schematic file '
                            f'in {filename}.')
                raise LookupError(f'Did not found sheetfile properties in the schematic file '
                                  f'in {filename}. Unsupported schematics file format')
            sheetfile_loc = offset + start
            sheetfile_loc_end = next_bigger(new_lines, sheetfile_loc)
            sheetfile_complete_string = contents[sheetfile_loc:sheetfile_loc_end]
            sheetfile = sheetfile_complete_string.strip("(property").split('"')[1::2][1]

            sheetfilepath = os.path.join(filename_dir, sheetfile)
            dict_of_sheets[uuid] = [sheetname, sheetfile]

            # test if newfound file can be opened
            if not os.path.exists(sheetfilepath):
                raise LookupError(f'File {sheetfilepath} does not exists. This is either due to error in parsing'
                                  f' schematics files, missing schematics file or an error within the schematics')
            # open a newfound file and look for nested sheets
            self.parse_schematic_files(sheetfilepath, dict_of_sheets)
            pass
        return

    def get_fp_by_ref(self, ref):
        for fp in self.footprints:
            if fp.ref == ref:
                return fp
        return None

    @staticmethod
    def get_footprint_id(footprint):
        path = footprint.GetPath().AsString().upper().replace('00000000-0000-0000-0000-0000', '').split("/")
        if len(path) != 1:
            fp_id = path[-1]
        # if path is empty, then footprint is not part of schematics
        else:
            fp_id = None
        return fp_id

    @staticmethod
    def get_sheet_id(footprint):
        path = footprint.GetPath().AsString().upper().replace('00000000-0000-0000-0000-0000', '').split("/")
        if len(path) != 1:
            sheet_id = path[-2]
        # if path is empty, then footprint is not part of schematics
        else:
            sheet_id = None
        return sheet_id

    def get_sheet_path(self, footprint):
        """ get sheet id """
        path = footprint.GetPath().AsString().upper().replace('00000000-0000-0000-0000-0000', '').split("/")
        if len(path) != 1:
            sheet_path = path[0:-1]
            sheet_names = [self.dict_of_sheets[x][0] for x in sheet_path if x in self.dict_of_sheets]
            sheet_files = [self.dict_of_sheets[x][1] for x in sheet_path if x in self.dict_of_sheets]
            sheet_path = [sheet_names, sheet_files]
        else:
            sheet_path = ["", ""]
        return sheet_path

    def get_footprints_on_sheet(self, level):
        footprints_on_sheet = []
        level_depth = len(level)
        for fp in self.footprints:
            if level == fp.sheet_id[0:level_depth]:
                footprints_on_sheet.append(fp)
        return footprints_on_sheet

    def get_footprints_not_on_sheet(self, level):
        footprints_not_on_sheet = []
        level_depth = len(level)
        for fp in self.footprints:
            if level != fp.sheet_id[0:level_depth]:
                footprints_not_on_sheet.append(fp)
        return footprints_not_on_sheet

    @staticmethod
    def get_nets_from_footprints(footprints):
        # go through all footprints and their pads and get the nets they are connected to
        nets = []
        for fp in footprints:
            # get their pads
            pads = fp.fp.Pads()
            # get net
            for pad in pads:
                nets.append(pad.GetNetname())

        # remove duplicates
        nets_clean = []
        for i in nets:
            if i not in nets_clean:
                nets_clean.append(i)
        return nets_clean

    def get_local_nets(self, src_footprints, other_footprints):
        # get nets other footprints are connected to
        other_nets = self.get_nets_from_footprints(other_footprints)
        # get nets only source footprints are connected to
        nets_on_sheet = self.get_nets_from_footprints(src_footprints)

        src_local_nets = []
        for net in nets_on_sheet:
            if net not in other_nets:
                src_local_nets.append(net)

        return src_local_nets

    @staticmethod
    def get_footprints_bounding_box(footprints):
        # get first footprint bounding box
        bounding_box = footprints[0].fp.GetBoundingBox(False, False)
        top = bounding_box.GetTop()
        bottom = bounding_box.GetBottom()
        left = bounding_box.GetLeft()
        right = bounding_box.GetRight()
        # iterate through the rest of the footprints and resize bounding box accordingly
        for fp in footprints:
            fp_box = fp.fp.GetBoundingBox(False, False)
            top = min(top, fp_box.GetTop())
            bottom = max(bottom, fp_box.GetBottom())
            left = min(left, fp_box.GetLeft())
            right = max(right, fp_box.GetRight())

        position = pcbnew.VECTOR2I(left, top)
        size = pcbnew.VECTOR2I(right - left, bottom - top)
        bounding_box = pcbnew.BOX2I(position, size)
        return bounding_box


class SaveLayout:
    def __init__(self, board, src_anchor_fp_ref):
        logger.info(f'Working on {board.GetFileName()}')

        # get the source board data
        self.src_prjdata = PrjData(board)

        logger.info("Saving the current board temporary in order to leave current layout intact")
        # generate new temporary file
        tempdir = tempfile.gettempdir()
        self.temp_filename = os.path.join(tempdir, 'temp_board_file_for_save.kicad_pcb')
        if os.path.isfile(self.temp_filename):
            os.remove(self.temp_filename)
        logger.info(f'Saving board as tempfile: {self.temp_filename}')
        pcbnew.PCB_IO_MGR.Save(pcbnew.PCB_IO_MGR.KICAD_SEXP, self.temp_filename, board)

        self.board = pcbnew.PCB_IO_MGR.Load(pcbnew.PCB_IO_MGR.KICAD_SEXP, self.temp_filename)

        logger.info(f'Loaded temp boardfile: {self.board.GetFileName()}')
        logger.info("Get project schematics and layout data")
        self.save_prjdata = PrjData(self.board, dict_of_sheets=self.src_prjdata.dict_of_sheets)
        self.save_prjdata.dict_of_sheets = self.src_prjdata.dict_of_sheets
        # override project paths
        self.save_prjdata.pcb_filename = os.path.abspath(board.GetFileName())
        self.save_prjdata.sch_filename = self.save_prjdata.pcb_filename.replace(".kicad_pcb", ".kicad_sch")
        self.save_prjdata.project_folder = os.path.dirname(self.save_prjdata.pcb_filename)

        self.src_anchor_fp = self.save_prjdata.get_fp_by_ref(src_anchor_fp_ref)
        self.nets_exclusively_on_sheet = None

    def save_layout(self, level, data_file,
                    tracks, zones, text, drawings, intersecting):
        logger.info("Saving layout for level: " + repr(level))
        logger.info("Calculating hash of the layout schematics")
        # load schematics and calculate hash of schematics (you have to support nested hierarchy)
        list_of_sheet_files = self.src_anchor_fp.filename[len(level) - 1:]

        logger.info("Saving hash for files: " + repr(list_of_sheet_files))

        md5hash = hashlib.md5()
        for sch_file in list_of_sheet_files:
            file_path = os.path.join(self.save_prjdata.project_folder, sch_file)
            md5hash = get_sch_hash(file_path, md5hash)

        hex_hash = md5hash.hexdigest()

        # get footprints on a sheet
        src_fps = self.save_prjdata.get_footprints_on_sheet(level)
        logging.info("Source footprints are: " + repr([x.ref for x in src_fps]))

        # get other footprints
        other_fps = self.save_prjdata.get_footprints_not_on_sheet(level)

        # get nets local to source footprints
        self.nets_exclusively_on_sheet = self.save_prjdata.get_local_nets(src_fps, other_fps)

        # get source bounding box
        bounding_box = self.save_prjdata.get_footprints_bounding_box(src_fps)

        logger.info("Removing everything else from the layout")

        # remove text items
        self.remove_text(bounding_box, not intersecting, not text)

        # remove drawings
        self.remove_drawings(bounding_box, not intersecting, not drawings)

        # remove zones
        self.remove_zones(bounding_box, not intersecting, not zones)

        # remove tracks
        self.remove_tracks(bounding_box, not intersecting, not tracks)

        # remove footprints
        self.remove_footprints(other_fps)

        # save the layout
        logger.info("Saving layout in temporary file")
        pcbnew.PCB_IO_MGR.Save(pcbnew.PCB_IO_MGR.KICAD_SEXP, self.temp_filename, self.board)

        # load as text
        logger.info("Reading layout as text")
        with open(self.temp_filename, 'rb') as f:
            layout_file_as_text = f.read().decode('utf-8')

        # remove the file
        os.remove(self.temp_filename)

        logger.info("Saving layout data")

        # save all data
        level_filename = [self.src_anchor_fp.filename[self.src_anchor_fp.sheet_id.index(x)] for x in level]
        level_saved = level_filename[len(level)-1]
        copper_layer_count = self.save_prjdata.board.GetCopperLayerCount()
        data_to_save = LayoutData(VERSION,
                                  layout_file_as_text,
                                  hex_hash,
                                  self.save_prjdata.dict_of_sheets,
                                  self.nets_exclusively_on_sheet, level_saved, level_filename,
                                  copper_layer_count)
        if data_file.endswith('.pckl'):
            with open(data_file, 'wb') as f:
                pickle.dump(data_to_save, f, 0)
        if data_file.endswith('.json'):
            with open(data_file, 'w') as f:
                json.dump(data_to_save, f)
        logger.info("Successfully saved the layout")

    def remove_drawings(self, bounding_box, containing, remove_all=False):
        logger.info("Removing drawing")
        # remove all drawings outside of bounding box
        drawings_to_delete = []
        all_drawings = self.board.GetDrawings()
        for drawing in all_drawings:
            if isinstance(drawing, pcbnew.PCB_TEXT):
                continue
            drawing_bb = drawing.GetBoundingBox()
            if remove_all:
                drawings_to_delete.append(drawing)
            else:
                if containing:
                    if not bounding_box.Contains(drawing_bb):
                        if drawing.IsConnected():
                            if drawing.GetNetname() not in self.nets_exclusively_on_sheet:
                                drawings_to_delete.append(drawing)
                else:
                    if not bounding_box.Intersects(drawing_bb):
                        if drawing.IsConnected():
                            if drawing.GetNetname() not in self.nets_exclusively_on_sheet:
                                drawings_to_delete.append(drawing)
        for dwg in drawings_to_delete:
            self.board.RemoveNative(dwg)

    def remove_text(self, bounding_box, containing, remove_all=False):
        logger.info("Removing text")
        # remove all text outside of bounding box
        text_to_delete = []
        all_text_items = self.board.GetDrawings()
        for text in all_text_items:
            if not isinstance(text, pcbnew.PCB_TEXT):
                continue
            text_bb = text.GetBoundingBox()
            if remove_all:
                text_to_delete.append(text)
            else:
                if containing:
                    if not bounding_box.Contains(text_bb):
                        text_to_delete.append(text)
                else:
                    if not bounding_box.Intersects(text_bb):
                        text_to_delete.append(text)
        for txt in text_to_delete:
            self.board.RemoveNative(txt)

    def remove_zones(self, bounding_box, containing, remove_all=False):
        logger.info("Removing zones")
        # remove all zones outisde of bounding box
        all_zones = []
        for zoneid in range(self.board.GetAreaCount()):
            all_zones.append(self.board.GetArea(zoneid))
        # find all zones which are outside the source bounding box
        for zone in all_zones:
            zone_bb = zone.GetBoundingBox()
            if remove_all:
                self.board.RemoveNative(zone)
            else:
                if containing:
                    if not bounding_box.Contains(zone_bb):
                        if zone.GetNetname() not in self.nets_exclusively_on_sheet:
                            self.board.RemoveNative(zone)
                else:
                    if not bounding_box.Intersects(zone_bb):
                        if zone.GetNetname() not in self.nets_exclusively_on_sheet:
                            self.board.RemoveNative(zone)

    def remove_tracks(self, bounding_box, containing, remove_all=False):
        logger.info("Removing tracks")

        logger.info("Bounding box points: "
                    + repr((bounding_box.GetTop(), bounding_box.GetBottom(), bounding_box.GetLeft(), bounding_box.GetRight())))
        # find all tracks within the source bounding box
        tracks_to_delete = []
        # get all the tracks for replication
        for track in self.board.GetTracks():
            track_bb = track.GetBoundingBox()
            # if track is contained or intersecting the bounding box
            if remove_all:
                tracks_to_delete.append(track)
            else:
                if containing:
                    if not bounding_box.Contains(track_bb):
                        if track.GetNetname() not in self.nets_exclusively_on_sheet:
                            tracks_to_delete.append(track)
                else:
                    if not bounding_box.Intersects(track_bb):
                        if track.GetNetname() not in self.nets_exclusively_on_sheet:
                            tracks_to_delete.append(track)
        for trk in tracks_to_delete:
            self.board.RemoveNative(trk)

    def remove_footprints(self, footprints):
        logger.info("Removing footprints")
        for fp in footprints:
            self.board.RemoveNative(fp.fp)

    def highlight_set_level(self, level, tracks, zones, text, drawings, intersecting):
        # find level bounding box
        src_fps = self.src_prjdata.get_footprints_on_sheet(level)
        fps_bb = self.src_prjdata.get_footprints_bounding_box(src_fps)

        fps = []
        # set highlight on all the footprints
        for fp in src_fps:
            self.fp_set_highlight(fp.fp)
            fps.append(fp)

        # set highlight on other items
        items = []
        if tracks:
            tracks = self.get_tracks(fps_bb, not intersecting)
            for t in tracks:
                t.SetBrightened()
                items.append(t)
        if zones:
            zones = self.get_zones(fps_bb, not intersecting)
            for zone in zones:
                zone.SetBrightened()
                items.append(zone)
        if text:
            text_items = self.get_text_items(fps_bb, not intersecting)
            for t_i in text_items:
                t_i.SetBrightened()
                items.append(t_i)
        if drawings:
            dwgs = self.get_drawings(fps_bb, not intersecting)
            for dw in dwgs:
                dw.SetBrightened()
                items.append(dw)

        return fps, items

    def highlight_clear_level(self, fps, items):
        # set highlight on all the footprints
        for fp in fps:
            self.fp_clear_highlight(fp.fp)

        # set highlight on other items
        for item in items:
            item.ClearBrightened()

    def get_tracks(self, bounding_box, containing, exclusive_nets=None):
        # get_all tracks
        if exclusive_nets is None:
            exclusive_nets = []
        all_tracks = self.src_prjdata.board.GetTracks()
        tracks = []
        # keep only tracks that are within our bounding box
        for track in all_tracks:
            track_bb = track.GetBoundingBox()
            # if track is contained or intersecting the bounding box
            if (containing and bounding_box.Contains(track_bb)) or \
                    (not containing and bounding_box.Intersects(track_bb)):
                tracks.append(track)
            # even if track is not within the bounding box, but is on the completely local net
            else:
                # check if it on a local net
                if track.GetNetname() in exclusive_nets:
                    # and add it to the
                    tracks.append(track)
        return tracks

    def get_zones(self, bounding_box, containing):
        # get all zones
        all_zones = []
        for zone_id in range(self.src_prjdata.board.GetAreaCount()):
            all_zones.append(self.src_prjdata.board.GetArea(zone_id))
        # find all zones which are within the bounding box
        zones = []
        for zone in all_zones:
            zone_bb = zone.GetBoundingBox()
            if (containing and bounding_box.Contains(zone_bb)) or \
                    (not containing and bounding_box.Intersects(zone_bb)):
                zones.append(zone)
        return zones

    def get_text_items(self, bounding_box, containing):
        # get all text objects in bounding box
        all_text = []
        for drawing in self.src_prjdata.board.GetDrawings():
            if not isinstance(drawing, pcbnew.PCB_TEXT):
                continue
            text_bb = drawing.GetBoundingBox()
            if containing:
                if bounding_box.Contains(text_bb):
                    all_text.append(drawing)
            else:
                if bounding_box.Intersects(text_bb):
                    all_text.append(drawing)
        return all_text

    def get_drawings(self, bounding_box, containing):
        # get all drawings in source bounding box
        all_drawings = []
        for drawing in self.src_prjdata.board.GetDrawings():
            if isinstance(drawing, pcbnew.PCB_TEXT):
                # text items are handled separately
                continue
            dwg_bb = drawing.GetBoundingBox()
            if containing:
                if bounding_box.Contains(dwg_bb):
                    all_drawings.append(drawing)
            else:
                if bounding_box.Intersects(dwg_bb):
                    all_drawings.append(drawing)
        return all_drawings

    @staticmethod
    def fp_set_highlight(fp):
        pads_list = fp.Pads()
        for pad in pads_list:
            pad.SetBrightened()
        drawings = fp.GraphicalItems()
        for item in drawings:
            item.SetBrightened()

    @staticmethod
    def fp_clear_highlight(fp):
        pads_list = fp.Pads()
        for pad in pads_list:
            pad.ClearBrightened()
        drawings = fp.GraphicalItems()
        for item in drawings:
            item.ClearBrightened()


class RestoreLayout:
    def __init__(self, board, dst_anchor_fp_ref, group_name):
        logger.info("Getting board info")
        self.board = board
        self.group_name = group_name
        logger.info("Get project schematics and layout data")
        self.prj_data = PrjData(self.board)

        self.dst_anchor_fp = self.prj_data.get_fp_by_ref(dst_anchor_fp_ref)

        # check if there are more footprints with same ID
        for fp in self.prj_data.footprints:
            if fp.ref != self.dst_anchor_fp.ref:
                if fp.fp_id == self.dst_anchor_fp.fp_id:
                    logger.info("There is more than one footprint with same ID in the target layout."
                                "This is due the multiple hierarchical sheets. The plugin can not resolve this issue")


    def restore_layout(self, layout_file):
        logger.info("Loading saved design")
        # load saved design
        if layout_file.endswith('.pckl'):
            with open(layout_file, 'rb') as f:
                data_saved = pickle.load(f)
        if layout_file.endswith('.json'):
            with open(layout_file, 'r') as f:
                json_load = json.load(f)
                data_saved = LayoutData(json_load[0], json_load[1], json_load[2], json_load[3],
                                        json_load[4], json_load[5], json_load[6], json_load[7])

        # check if version matches
        if semver_compare(VERSION, data_saved.version) is False:
            raise LookupError("Layout was saved with newer version of the plugin. This is not supported.")

        # check layer count
        if hasattr(data_saved, 'layer_count'):
            if data_saved.layer_count < self.prj_data.board.GetCopperLayerCount():
                raise LookupError("Target board has less layers than layers saved. This is not supported.")
        else:
            logger.info("Saved layout does not have copper layer count saved. Might result in unhandled issues.")

        # get saved hierarchy
        source_level_filename = data_saved.level_filename
        source_level = data_saved.level
        logger.info("Source level is:" + repr(source_level_filename))

        # find the corresponding hierarchy in the target layout
        # this is tricky as target design might be shallower or deeper than source design

        logger.info("Destination footprint is:" + repr(self.dst_anchor_fp.ref))
        logger.info("Destination levels available are:" + repr(self.dst_anchor_fp.filename))

        # check if saved (source) level is available in destination
        if source_level not in self.dst_anchor_fp.filename:
            raise LookupError("Destination hierarchy: " + repr(self.dst_anchor_fp.filename) + "\n"
                              + "does not match source level: " + repr(source_level))

        level_index = self.dst_anchor_fp.filename.index(source_level)
        level = self.dst_anchor_fp.sheet_id[0:level_index + 1]

        destination_level_filename = self.dst_anchor_fp.filename[0:level_index + 1]
        logger.info("Destination level is:" + repr(destination_level_filename))

        # load schematics and calculate hash of schematics (you have to support nested hierarchy)
        list_of_sheet_files = self.dst_anchor_fp.filename[len(destination_level_filename) - 1:]

        logger.info("All sch files required are: " + repr(list_of_sheet_files))

        logger.info("Getting current schematics hash")
        md5hash = hashlib.md5()
        for sch_file in list_of_sheet_files:
            file_path = os.path.join(self.prj_data.project_folder, sch_file)
            md5hash = get_sch_hash(file_path, md5hash)

        hex_hash = md5hash.hexdigest()

        # check the hash
        saved_hash = data_saved.hash

        logger.info("Source hash is:" + repr(saved_hash))
        logger.info("Destination hash is: " + repr(hex_hash))

        if not saved_hash == hex_hash:
            raise ValueError("Source and destination schematics don't match!")

        # save board from the saved layout only temporary
        tempdir = tempfile.gettempdir()
        temp_filename = os.path.join(tempdir, 'temp_layout_for_restore.kicad_pcb')
        with open(temp_filename, 'wb') as f:
            f.write(data_saved.layout.encode('utf-8'))

        # restore layout data
        saved_board = pcbnew.PCB_IO_MGR.Load(pcbnew.PCB_IO_MGR.KICAD_SEXP, temp_filename)
        # delete temporary file
        os.remove(temp_filename)

        # get layout data from saved board
        logger.info("Get layout data from saved board")
        saved_layout = PrjData(saved_board, dict_of_sheets=data_saved.dict_of_sheets)

        saved_fps = saved_layout.footprints

        footprints_to_place = self.prj_data.get_footprints_on_sheet(level)

        # check if source layout and destination layout to be restored match at least in footprint count
        if len(footprints_to_place) != len(saved_fps):
            raise ValueError("Source and destination footprint count don't match!")

        # sort by ID - I am counting that source and destination sheet have been
        # annotated by KiCad in their final form (reset annotation and then re-annotate)
        footprints_to_place = sorted(footprints_to_place, key=lambda x: (x.fp_id, x.sheet_id))
        saved_fps = sorted(saved_fps, key=lambda x: (x.fp_id, x.sheet_id))

        # get the saved layout ID numbers and try to figure out a match (at least the same depth, ...)
        # find net pairs
        net_pairs = self.get_net_pairs(footprints_to_place, saved_fps)

        # Create Group for placed components
        if self.group_name:
            self.layout_group = pcbnew.PCB_GROUP(self.board)
            self.layout_group.SetName(self.group_name)
            self.board.Add(self.layout_group)
        else:
            self.layout_group = None

        src_anchor_fp = saved_fps[footprints_to_place.index(self.dst_anchor_fp)]
        # find matching source anchor footprint
        list_of_possible_anchor_footprints = []
        for fp in saved_fps:
            if fp.fp_id == self.dst_anchor_fp.fp_id:
                list_of_possible_anchor_footprints.append(fp)

        # if there is only one
        if len(list_of_possible_anchor_footprints) == 1:
            src_anchor_fp = list_of_possible_anchor_footprints[0]
        # if there are more then one, we're dealing with multiple hierarchy
        # the correct one is the one who's path is the best match to the sheet path
        else:
            list_of_matches = []
            for fp in list_of_possible_anchor_footprints:
                index = list_of_possible_anchor_footprints.index(fp)
                matches = 0
                for item in self.dst_anchor_fp.sheet_id:
                    if item in fp.sheet_id:
                        matches = matches + 1
                list_of_matches.append((index, matches))
            # select the one with most matches
            index, _ = max(list_of_matches, key=lambda x: x[1])
            src_anchor_fp = list_of_possible_anchor_footprints[index]

        # replicate footprints
        self.replicate_footprints(src_anchor_fp, saved_fps, self.dst_anchor_fp, footprints_to_place, self.layout_group)

        # replicate tracks
        self.replicate_tracks(src_anchor_fp, saved_board.GetTracks(), self.dst_anchor_fp, net_pairs, self.layout_group)

        # replicate zones
        src_zones = [saved_board.GetArea(zone_id) for zone_id in range(saved_board.GetAreaCount()) ]
        self.replicate_zones(src_anchor_fp, src_zones, self.dst_anchor_fp, net_pairs, self.layout_group)

        # replicate text
        src_text = [item for item in saved_board.GetDrawings() if isinstance(item, pcbnew.PCB_TEXT)]
        self.replicate_text(src_anchor_fp, src_text, self.dst_anchor_fp, self.layout_group)

        # replicate drawings
        source_dwgs = [item for item in saved_board.GetDrawings() if not isinstance(item, pcbnew.PCB_TEXT)]
        self.replicate_drawings(src_anchor_fp, source_dwgs, self.dst_anchor_fp, net_pairs, self.layout_group)

        return self.board

    @staticmethod
    def get_net_pairs(dst_fps, src_fps):
        """ find all net pairs between source sheet and current sheet"""
        # find all net pairs via same footprint pads,
        net_pairs = []
        net_dict = {}
        # construct footprint pairs
        fp_matches = []
        for s_fp in src_fps:
            fp_matches.append([s_fp.fp, s_fp.fp_id, s_fp.sheet_id])

        for d_fp in dst_fps:
            for fp in fp_matches:
                if fp[1] == d_fp.fp_id:
                    index = fp_matches.index(fp)
                    fp_matches[index].append(d_fp.fp)
                    fp_matches[index].append(d_fp.fp_id)
                    fp_matches[index].append(d_fp.sheet_id)
        # find closest match
        fp_pairs = []
        fp_pairs_by_reference = []
        for index in range(len(fp_matches)):
            fp = fp_matches[index]
            # get number of matches
            matches = (len(fp) - 3) // 3
            # if more than one match, get the most likely one
            # this is when replicating a sheet which consist of two or more identical subsheets (multiple hierachy)
            if matches > 1:
                match_len = []
                for index in range(0, matches):
                    match_len.append(len(set(fp[2]) & set(fp[2 + 3 * (index + 1)])))
                index = match_len.index(max(match_len))
                fp_pairs.append((fp[0], fp[3 * (index + 1)]))
                fp_pairs_by_reference.append((fp[0].GetReference(), fp[3 * (index + 1)].GetReference()))
            # if only one match
            elif matches == 1:
                fp_pairs.append((fp[0], fp[3]))
                fp_pairs_by_reference.append((fp[0].GetReference(), fp[3].GetReference()))
            # can not find at least one matching footprint
            elif matches == 0:
                raise LookupError("Could not find at least one matching footprint for: " + fp[0].GetReference() +
                                  ".\nPlease make sure that schematics and layout are in sync.")

        # prepare the list of pad pairs
        pad_pairs = []
        for x in range(len(fp_pairs)):
            pad_pairs.append([])

        for pair in fp_pairs:
            index = fp_pairs.index(pair)
            # get all footprint pads
            src_fp_pads = pair[0].Pads()
            dst_fp_pads = pair[1].Pads()
            # create a list of pads names and pads
            s_pads = []
            d_pads = []
            for pad in src_fp_pads:
                s_pads.append((pad.GetName(), pad))
            for pad in dst_fp_pads:
                d_pads.append((pad.GetName(), pad))
            # sort by pad names
            s_pads.sort(key=lambda tup: tup[0])
            d_pads.sort(key=lambda tup: tup[0])
            # extract pads and append them to pad pairs list
            pad_pairs[index].append([x[1] for x in s_pads])
            pad_pairs[index].append([x[1] for x in d_pads])

        for pair in fp_pairs:
            index = fp_pairs.index(pair)
            # get their pads
            src_fp_pads = pad_pairs[index][0]
            dst_fp_pads = pad_pairs[index][1]
            # I am going to assume pads are in the same order
            s_nets = []
            d_nets = []
            # get netlists for each pad
            for p_pad in src_fp_pads:
                pad_name = p_pad.GetName()
                s_nets.append((pad_name, p_pad.GetNetname()))
            for s_pad in dst_fp_pads:
                pad_name = s_pad.GetName()
                d_nets.append((pad_name, s_pad.GetNetname()))
                net_dict[s_pad.GetNetname()] = s_pad.GetNet()
            # sort both lists by pad name
            # so that they have the same order - needed in some cases
            # as the iterator through the pads list does not return pads always in the proper order
            s_nets.sort(key=lambda tup: tup[0])
            d_nets.sort(key=lambda tup: tup[0])
            # build list of net tuples
            for net in s_nets:
                index = get_index_of_tuple(s_nets, 1, net[1])
                net_pairs.append((s_nets[index][1], d_nets[index][1]))

        # remove duplicates
        net_pairs_clean = list(set(net_pairs))

        return net_pairs_clean, net_dict

    @staticmethod
    def replicate_footprints(src_anchor_fp, src_fps, dst_anchor_fp, dst_fps, layout_group):
        logger.info("Replicating footprints")

        dst_anchor_fp_angle = dst_anchor_fp.fp.GetOrientationDegrees()
        dst_anchor_fp_position = dst_anchor_fp.fp.GetPosition()

        src_anchor_fp_angle = src_anchor_fp.fp.GetOrientationDegrees()

        anchor_delta_angle = src_anchor_fp_angle - dst_anchor_fp_angle

        # go through all footprints
        src_footprints = src_fps
        dst_footprints = dst_fps

        nr_footprints = len(src_footprints)
        for fp_index in range(nr_footprints):
            src_fp = src_footprints[fp_index]

            # find proper match in source footprints
            list_of_possible_dst_footprints = []
            for d_fp in dst_footprints:
                if d_fp.fp_id == src_fp.fp_id:
                    list_of_possible_dst_footprints.append(d_fp)

            # if there is more than one possible anchor, select the correct one
            if len(list_of_possible_dst_footprints) == 1:
                dst_fp = list_of_possible_dst_footprints[0]
            else:
                list_of_matches = []
                for fp in list_of_possible_dst_footprints:
                    index = list_of_possible_dst_footprints.index(fp)
                    matches = 0
                    for item in src_fp.sheet_id:
                        if item in fp.sheet_id:
                            matches = matches + 1
                    list_of_matches.append((index, matches))
                # check if list is empty, if it is, then it is highly likely that schematics and pcb are not in sync
                if not list_of_matches:
                    raise LookupError("Can not find destination footprint for source footprint: " + repr(src_fp.ref)
                                      + "\n" + "Most likely, schematics and PCB are not in sync")
                # select the one with most matches
                index, _ = max(list_of_matches, key=lambda item: item[1])
                dst_fp = list_of_possible_dst_footprints[index]

            # skip locked footprints
            # TODO
            #if dst_fp.fp.IsLocked() is True and self.replicate_locked_items is False:
            #    continue

            # get footprint to clone position
            src_fp_orientation = src_fp.fp.GetOrientationDegrees()
            src_fp_pos = src_fp.fp.GetPosition()
            # get relative position with respect to source anchor
            src_anchor_pos = src_anchor_fp.fp.GetPosition()
            src_fp_flipped = src_fp.fp.IsFlipped()
            src_fp_delta_pos = src_fp_pos - src_anchor_pos

            # new orientation is simple
            new_orientation = src_fp_orientation - anchor_delta_angle
            old_pos = src_fp_delta_pos + dst_anchor_fp_position
            new_pos = rotate_around_point(old_pos, dst_anchor_fp_position, anchor_delta_angle)

            # convert to tuple of integers
            new_pos = [int(x) for x in new_pos]
            # place current footprint - only if current footprint is not also the anchor
            if dst_fp.ref != dst_anchor_fp.ref:
                dst_fp.fp.SetPosition(pcbnew.VECTOR2I(*new_pos))

                if dst_fp.fp.IsFlipped() != src_fp_flipped:
                    dst_fp.fp.Flip(dst_fp.fp.GetPosition(), False)
                dst_fp.fp.SetOrientationDegrees(new_orientation)

            # Copy local settings.
            dst_fp.fp.SetLocalClearance(src_fp.fp.GetLocalClearance())
            dst_fp.fp.SetLocalSolderMaskMargin(src_fp.fp.GetLocalSolderMaskMargin())
            dst_fp.fp.SetLocalSolderPasteMargin(src_fp.fp.GetLocalSolderPasteMargin())
            dst_fp.fp.SetLocalSolderPasteMarginRatio(src_fp.fp.GetLocalSolderPasteMarginRatio())
            dst_fp.fp.SetZoneConnection(src_fp.fp.GetZoneConnection())

            # flip if dst anchor is flipped with regards to src anchor
            if src_anchor_fp.fp.IsFlipped() != dst_anchor_fp.fp.IsFlipped():
                # ignore anchor fp
                if dst_anchor_fp != dst_fp:
                    dst_fp.fp.Flip(dst_anchor_fp_position, False)
                    #
                    src_fp_rel_pos = src_anchor_pos - src_fp_pos
                    delta_angle = dst_anchor_fp_angle + src_anchor_fp_angle
                    dst_fp_rel_pos_rot = rotate_around_center([-src_fp_rel_pos[0], src_fp_rel_pos[1]],
                                                              -delta_angle)
                    dst_fp_rel_pos = dst_anchor_fp_position + pcbnew.VECTOR2I(dst_fp_rel_pos_rot[0],
                                                                             dst_fp_rel_pos_rot[1])
                    # also need to change the angle
                    dst_fp.fp.SetPosition(dst_fp_rel_pos)
                    src_fp_flipped_orientation = flipped_angle(src_fp_orientation)
                    flipped_delta = flipped_angle(src_anchor_fp_angle)-dst_anchor_fp_angle
                    new_orientation = src_fp_flipped_orientation - flipped_delta
                    dst_fp.fp.SetOrientationDegrees(new_orientation)

            dst_fp_orientation = dst_fp.fp.GetOrientationDegrees()
            dst_fp_flipped = dst_fp.fp.IsFlipped()

            # replicate also text layout - also for anchor footprint. I am counting that the user is lazy and will
            # just position the destination anchors and will not edit them
            # get footprint text
            src_fp_text_items = get_footprint_text_items(src_fp)
            dst_fp_text_items = get_footprint_text_items(dst_fp)
            # check if both footprints (source and the one for replication) have the same number of text items
            if len(src_fp_text_items) != len(dst_fp_text_items):
                raise LookupError(
                    "Source footprint: " + src_fp.ref + " has different number of text items (" + repr(
                        len(src_fp_text_items))
                    + ")\nthan footprint for replication: " + dst_fp.ref + " (" + repr(
                        len(dst_fp_text_items)) + ")")

            # replicate each text item
            src_text: pcbnew.PCB_TEXT
            dst_text: pcbnew.PCB_TEXT
            for src_text in src_fp_text_items:
                txt_index = src_fp_text_items.index(src_text)
                src_txt_pos = src_text.GetPosition()
                src_txt_rel_pos = src_txt_pos - src_fp.fp.GetBoundingBox(False, False).Centre()
                src_txt_orientation = src_text.GetTextAngleDegrees()
                delta_angle = dst_fp_orientation - src_fp_orientation

                dst_fp_pos = dst_fp.fp.GetBoundingBox(False, False).Centre()
                dst_text = dst_fp_text_items[txt_index]

                dst_text.SetLayer(src_text.GetLayer())
                # set text parameters
                dst_text.SetAttributes(src_text.GetAttributes())
                # properly set position
                if src_fp_flipped != dst_fp_flipped:
                    dst_text.Flip(dst_anchor_fp_position, False)
                    dst_txt_rel_pos = [-src_txt_rel_pos[0], src_txt_rel_pos[1]]
                    delta_angle = flipped_angle(src_anchor_fp_angle) - dst_anchor_fp_angle
                    dst_txt_rel_pos_rot = rotate_around_center(dst_txt_rel_pos, delta_angle)
                    dst_txt_pos = dst_fp_pos + pcbnew.VECTOR2I(dst_txt_rel_pos_rot[0], dst_txt_rel_pos_rot[1])
                    dst_text.SetPosition(dst_txt_pos)
                    dst_text.SetTextAngleDegrees(-src_txt_orientation - anchor_delta_angle)
                    dst_text.SetMirrored(not src_text.IsMirrored())
                else:
                    dst_txt_rel_pos = rotate_around_center(src_txt_rel_pos, -delta_angle)
                    dst_txt_pos = dst_fp_pos + pcbnew.VECTOR2I(int(dst_txt_rel_pos[0]), int(dst_txt_rel_pos[1]))
                    dst_text.SetPosition(dst_txt_pos)
                    dst_text.SetTextAngleDegrees(src_txt_orientation - anchor_delta_angle)
                    dst_text.SetMirrored(src_text.IsMirrored())

            # Add Footprint to group
            if layout_group:
                layout_group.AddItem(dst_fp.fp)

    def replicate_tracks(self, src_anchor_fp, src_tracks, dst_anchor_fp, net_pairs, layout_group):
        logger.info("Replicating tracks")

        # get anchor footprint
        dst_anchor_fp_angle = dst_anchor_fp.fp.GetOrientation()
        dst_anchor_fp_position = dst_anchor_fp.fp.GetPosition()

        src_anchor_fp_angle = src_anchor_fp.fp.GetOrientation()
        src_anchor_fp_position = src_anchor_fp.fp.GetPosition()

        move_vector = dst_anchor_fp_position - src_anchor_fp_position
        delta_orientation = dst_anchor_fp_angle - src_anchor_fp_angle

        net_pairs, net_dict = net_pairs
        logger.info(f'Net pairs are: {repr(net_pairs)}')

        # go through all the tracks
        nr_tracks = len(src_tracks)
        for track_index in range(nr_tracks):
            track = src_tracks[track_index]
            # get from which net we are cloning
            from_net_name = track.GetNetname()
            # find to net
            tup = [item for item in net_pairs if item[0] == from_net_name]
            # if net was not found, then the track is not part of this sheet and should not be cloned
            if not tup:
                pass
            else:
                to_net_name = tup[0][1]
                to_net_code = net_dict[to_net_name].GetNetCode()
                to_net_item = net_dict[to_net_name]

                # make a duplicate, move it, rotate it, select proper net and add it to the board
                new_track = track.Duplicate().Cast()
                new_track.SetNetCode(to_net_code, True)
                new_track.SetNet(to_net_item)
                new_track.Move(move_vector)
                if src_anchor_fp.fp.IsFlipped() != dst_anchor_fp.fp.IsFlipped():
                    new_track.Flip(dst_anchor_fp_position, False)
                    src_anchor_fp_flipped_angle = flipped_angle(src_anchor_fp_angle / 10)
                    delta_angle = src_anchor_fp_flipped_angle * 10 - dst_anchor_fp_angle
                    rot_angle = delta_angle - 1800
                    new_track.Rotate(dst_anchor_fp_position, -rot_angle)
                else:
                    new_track.Rotate(dst_anchor_fp_position, delta_orientation)
                    pass

                self.board.Add(new_track)

                # Add track in Group
                if layout_group:
                    layout_group.AddItem(new_track)

    def replicate_zones(self, src_anchor_fp, src_zones, dst_anchor_fp, net_pairs, layout_group):
        """ method which replicates zones"""
        logger.info("Replicating zones")

        # get anchor footprint
        dst_anchor_fp_angle = dst_anchor_fp.fp.GetOrientation()
        dst_anchor_fp_position = dst_anchor_fp.fp.GetPosition()

        src_anchor_fp_angle = src_anchor_fp.fp.GetOrientation()
        src_anchor_fp_position = src_anchor_fp.fp.GetPosition()

        move_vector = dst_anchor_fp_position - src_anchor_fp_position
        delta_orientation = dst_anchor_fp_angle - src_anchor_fp_angle

        net_pairs, net_dict = net_pairs
        logger.info(f'Net pairs are: {repr(net_pairs)}')
        # go through all the zones
        nr_zones = len(src_zones)
        for zone_index in range(nr_zones):
            zone = src_zones[zone_index]

            # get from which net we are cloning
            from_net_name = zone.GetNetname()
            logger.info(f'Handlilng zone connected to: {repr(from_net_name)}')

            # if zone is not on copper layer it does not matter on which net it is
            if not zone.IsOnCopperLayer():
                tup = [('', '')]
            else:
                if from_net_name:
                    tup = [item for item in net_pairs if item[0] == from_net_name]
                    logger.info(f'Zone list of net tuples: {repr(tup)}')
                    # TODO - what if the designed is restored in a project where some net does not exist?
                else:
                    tup = [('', '')]

            # there is no net
            if not tup:
                # Allow keepout zones to be cloned.
                if not zone.IsOnCopperLayer():
                    tup = [('', '')]
                # TODO should probably need to cover the else case
                else:
                    logger.info(f'unhandled net pair case with zone. The zone has a name: {repr(zone.GetZoneName())}\n'
                                f'is connected: {repr(zone.IsConnected())}\n'
                                f'is on net: {repr(zone.GetNetname())}\n'
                                f'has flags: {repr(zone.GetFlags())}\n'
                                f'is of class: {repr(zone.GetClass())}\n'
                                f'is of type: {repr(zone.GetTypeDesc())}\n'
                                f'has center at: {repr(zone.GetCenter())}\n')

            # start the clone
            to_net_name = tup[0][1]
            if to_net_name == u'':
                to_net_code = 0
                to_net_item = self.board.FindNet(0)
            else:
                to_net_code = net_dict[to_net_name].GetNetCode()
                to_net_item = net_dict[to_net_name]

            # make a duplicate, move it, rotate it, select proper net and add it to the board
            new_zone = zone.Duplicate().Cast()
            new_zone.Move(move_vector)
            new_zone.SetNetCode(to_net_code, True)
            new_zone.SetNet(to_net_item)
            if src_anchor_fp.fp.IsFlipped() != dst_anchor_fp.fp.IsFlipped():
                new_zone.Flip(dst_anchor_fp_position, False)
                src_anchor_fp_flipped_angle = flipped_angle(src_anchor_fp_angle / 10)
                delta_angle = src_anchor_fp_flipped_angle * 10 - dst_anchor_fp_angle
                rot_angle = delta_angle - 1800
                new_zone.Rotate(dst_anchor_fp_position, -rot_angle)
            else:
                new_zone.Rotate(dst_anchor_fp_position, delta_orientation)
            self.board.Add(new_zone)

            # Add Zone to Group
            if layout_group:
                layout_group.AddItem(new_zone)

    def replicate_text(self, src_anchor_fp, src_text, dst_anchor_fp, layout_group):
        logger.info("Replicating text")

        # get anchor footprint
        dst_anchor_fp_position = dst_anchor_fp.fp.GetPosition()
        dst_anchor_fp_angle = dst_anchor_fp.fp.GetOrientation()

        src_anchor_fp_angle = src_anchor_fp.fp.GetOrientation()
        src_anchor_fp_position = src_anchor_fp.fp.GetPosition()

        move_vector = dst_anchor_fp_position - src_anchor_fp_position
        delta_orientation = dst_anchor_fp_angle - src_anchor_fp_angle

        nr_text = len(src_text)
        for text_index in range(nr_text):
            text = src_text[text_index]

            new_text = text.Duplicate().Cast()
            new_text.Move(move_vector)
            if src_anchor_fp.fp.IsFlipped() != dst_anchor_fp.fp.IsFlipped():
                new_text.Flip(dst_anchor_fp_position, False)
                src_anchor_fp_flipped_angle = flipped_angle(src_anchor_fp_angle / 10)
                delta_angle = src_anchor_fp_flipped_angle * 10 - dst_anchor_fp_angle
                rot_angle = delta_angle - 1800
                new_text.Rotate(dst_anchor_fp_position, -rot_angle)
            else:
                new_text.Rotate(dst_anchor_fp_position, delta_orientation)

            self.board.Add(new_text)

            # Add text to group
            if layout_group:
                pass
                #layout_group.AddItem(layout_group)

    def replicate_drawings(self, src_anchor_fp, src_drawings, dst_anchor_fp, net_pairs, layout_group):
        logger.info("Replicating drawings")

        # get anchor footprint
        dst_anchor_fp_position = dst_anchor_fp.fp.GetPosition()
        dst_anchor_fp_angle = dst_anchor_fp.fp.GetOrientation()

        src_anchor_fp_angle = src_anchor_fp.fp.GetOrientation()
        src_anchor_fp_position = src_anchor_fp.fp.GetPosition()

        move_vector = dst_anchor_fp_position - src_anchor_fp_position
        delta_orientation = dst_anchor_fp_angle - src_anchor_fp_angle

        net_pairs, net_dict = net_pairs
        logger.info(f'Net pairs are: {repr(net_pairs)}')

        # go through all the drawings
        nr_drawings = len(src_drawings)
        for dw_index in range(nr_drawings):
            drawing = src_drawings[dw_index]

            new_drawing = drawing.Duplicate().Cast()
            new_drawing.Move(move_vector)

            if src_anchor_fp.fp.IsFlipped() != dst_anchor_fp.fp.IsFlipped():

                new_drawing.Flip(dst_anchor_fp_position, False)
                src_anchor_fp_flipped_angle = flipped_angle(src_anchor_fp_angle / 10)
                delta_angle = src_anchor_fp_flipped_angle * 10 - dst_anchor_fp_angle
                rot_angle = delta_angle - 1800
                new_drawing.Rotate(dst_anchor_fp_position, -rot_angle)
            else:
                new_drawing.Rotate(dst_anchor_fp_position, delta_orientation)

            # handle connectivity
            if drawing.IsConnected():
                from_net_name = drawing.GetNetname()
                tup = [item for item in net_pairs if item[0] == from_net_name]
                to_net_name = tup[0][1]
                to_net_item = net_dict[to_net_name]
                new_drawing.SetNet(to_net_item)

            self.board.Add(new_drawing)

            # Add drawing to Group
            if layout_group:
                layout_group.AddItem(new_drawing)
