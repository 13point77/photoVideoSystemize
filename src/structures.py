from __future__ import annotations
import ast
import json
import os
import re
import statistics
import typing
import uuid
import pytz
import multiprocessing as mp
from time import time
from math import log10
from os import listdir
from os.path import isfile, isdir, join
from datetime import datetime, timedelta
from exiftool import exiftool
from multipledispatch import dispatch
from timezonefinder import TimezoneFinder
from src.geo import ManualData, GeoMultiTrack, GeoTrackPoint, Address, GeoObjects, CalibrateCameraClocks
from src import func
from src.settings import Settings

try:
    import macos_tags
except (ImportError, RuntimeError):
    import math


class PVFile(Settings):
    # Tool to read and update exif-tags
    exif_tool = exiftool.ExifTool()
    tf = TimezoneFinder()

    def __init__(self,
                 pv_group: typing.Optional[PVGroup],
                 file_path: str,
                 **kwargs: str):
        self.prev_sd_value = ''
        self.f_id = ''
        self.gr_id = ''
        self.pv_group = pv_group
        self.file_path = file_path
        self.file_name = os.path.split(file_path)[1]
        self.new_file_name = ''
        self.new_file_path = ''
        self.new_name_parts = {'prefix': kwargs['name_prefix'] if 'name_prefix' in kwargs else '',
                               'suffix': kwargs['name_suffix'] if 'name_suffix' in kwargs else '',
                               'ext': kwargs['name_ext'] if 'name_ext' in kwargs else ''}
        self.exif_tags = {}
        self.coord_source = ''
        self.coord = ()
        self.alt = 0
        self.prev_alt = 0
        self.prev_coord = ()
        self.script_data = {}
        self.new_script_data = {}
        self.new_coord = {}
        self.utc_datetime = None
        self.file_datetime = None
        self.first_datetime = None
        self.file_naming_datetime = None
        self.dt_source = ''
        self.camera_key = ''
        self.camera_full_key = ''
        self.camera_found = False
        self.mac_tags_names = []

        if not PVFile.exif_tool.running:
            PVFile.exif_tool.run()
        self.get_file_info()

    def get_file_exif_tags(self) -> typing.NoReturn:
        exif_info = None
        exif_tags = {}
        # Use the exif_tool to read and wright file statistic in EXIF:
        if PVFile.exif_tool.running:
            try:
                exif_info = PVFile.exif_tool.execute('-j', self.file_path)
            except Exception as ex:
                self.print_log('e', 'main', '(get_file_exif_tags) exif_tool.execute ' + str(ex) + ' ' + self.file_path)
                exif_info = None

        if exif_info:
            try:
                exif_tags = ast.literal_eval(exif_info)[0]
            except ValueError:
                try:
                    exif_tags = json.loads(exif_info)[0]
                except ValueError:
                    self.print_log('e', 'main', '(get_file_exif_tags) exif_tags_error ' + self.file_path)

        self.exif_tags = exif_tags

    def get_exif_script_data(self) -> typing.NoReturn:
        # Get previous calculation.
        self.script_data = {}
        script_data_str = self.exif_tags.get(self.get_par('', 'script_data_tag_name'), '')
        if script_data_str:
            self.prev_sd_value = script_data_str.strip()
            try:
                self.script_data = ast.literal_eval(script_data_str)
                if type(self.script_data) is dict and 'pvs' in self.script_data:
                    self.coord_source = self.script_data.get('coord_source', '')
                    self.first_datetime = func.string_to_datetime(self.script_data['first_dt'], '%Y:%m:%d %H:%M:%S') \
                        if 'first_dt' in self.script_data else None
                    self.gr_id = self.script_data.get('gr_id', '')
                    self.f_id = self.script_data.get('f_id', '')
                    self.prev_sd_value = self.script_data.get('prev_value', '')
                else:
                    self.script_data = {}
            except (ValueError, TypeError, SyntaxError):
                pass

    @staticmethod
    def get_file_camera_key(exif_camera_id_tags_names: typing.List[str],
                            cameras: typing.Dict[str, dict],
                            exif_tags: typing.Dict[str, str]) -> typing.Tuple[bool, str, str]:
        # Get camera, lens information to identify each photo/video device.
        cam_keys = []
        short_keys = []
        camera_found = False
        camera_key = ''
        for camera_key_tag_name in exif_camera_id_tags_names:
            tag_val = ' '.join(str(exif_tags.get(camera_key_tag_name, '')).split())
            if tag_val:
                cam_keys.append(camera_key_tag_name + '=' + tag_val)
                short_keys.append(tag_val)
        if not cam_keys:
            camera_key = camera_full_key = 'no_cam'
        else:
            camera_full_key = '_'.join(cam_keys)
            for cam, cam_info in cameras.items():
                if all([cam_id in camera_full_key for cam_id in cam_info['synthetic_ids']]):
                    camera_key = cam
                    camera_found = True
                    break
            camera_key = camera_key if camera_key else ('_'.join(short_keys))[:50]
        return camera_found, camera_key, camera_full_key

    def get_file_info(self) -> typing.NoReturn:
        # Read EXIF tags from file
        self.get_file_exif_tags()
        # Get previous results. First of all 'coord_source'.
        self.get_exif_script_data()

        cam_info = self.get_file_camera_key(self.get_par([], 'EXIF_camera_id_tags_names'),
                                            self.get_par({}, 'cameras'),
                                            self.exif_tags)
        self.camera_found, self.camera_key, self.camera_full_key = cam_info

        # Get creation date and time from EXIF from fields in descending order of precedence.
        for t_name in self.get_par([], 'EXIF_create_dt_tag_name'):
            if t_name in self.exif_tags:
                # self.file_datetime = func.exif_gpx_string_to_datetime(self.exif_tags[t_name])
                self.file_datetime = func.string_to_datetime(self.exif_tags[t_name], '%Y:%m:%d %H:%M:%S')
                if self.file_datetime:
                    self.dt_source = 'exif'
                    self.first_datetime = self.first_datetime if self.first_datetime else self.file_datetime
                    break

        # Get coordinates from EXIF.
        if 'Composite:GPSLatitude' in self.exif_tags and self.exif_tags['Composite:GPSLatitude'] and \
                'Composite:GPSLongitude' in self.exif_tags and self.exif_tags['Composite:GPSLongitude']:
            try:
                self.prev_coord = self.coord = (float(self.exif_tags['Composite:GPSLatitude']),
                                                float(self.exif_tags['Composite:GPSLongitude']))
            except ValueError:
                self.print_log('e', 'main', '(get_pv_info) GPSPosition ' + self.file_path)
        # Get altitude from EXIF.
        if 'Composite:GPSAltitude' in self.exif_tags and self.exif_tags['Composite:GPSAltitude']:
            try:
                self.prev_alt = self.alt = float(self.exif_tags['Composite:GPSAltitude'])
            except ValueError:
                self.print_log('e', 'main', '(get_pv_info) GPSAltitude ' + self.file_path)

        # If there is still not datetime value, we get it from the operating system statistics.
        if not self.file_datetime:
            file_stat = os.stat(self.file_path)
            birthtime = file_stat.st_birthtime
            if birthtime and birthtime != '':
                self.dt_source = 'st_birthtime'
                self.file_datetime = datetime.fromtimestamp(int(birthtime))
            else:
                self.dt_source = 'st_mtime'
                self.file_datetime = datetime.fromtimestamp(int(file_stat.st_mtime))

        if self.check_par('os', 'macOS'):
            self.mac_tags_names = [str(tag.name) for tag in macos_tags.get_all(file=self.file_path) if len(tag.name)]

    def move_file_to_folder(self, new_folder_path: str) -> bool:
        new_file_path = join(new_folder_path, self.file_name)
        try:
            with open(new_file_path, "r") as _:
                self.print_log('w', 'main', f"Can't move file: {self.file_path} to {new_file_path} - file exist.")
            return False
        except FileNotFoundError:
            os.rename(self.file_path, new_file_path)
            self.print_log('i', 'main', f"{self.file_path} moved to {new_file_path}")
            self.file_path = new_file_path
            return True

    def get_new_file_name(self, name_core: str, num: str, naming_datetime: datetime) -> str:
        if self.no_empty_par('new_name_order'):
            self.file_naming_datetime = naming_datetime
            self.new_name_parts['num'] = num
            self.new_name_parts['name_core'] = name_core
            file_ext = os.path.splitext(self.file_name)[1]
            self.new_name_parts['ext'] = self.new_name_parts['ext'] if self.new_name_parts['ext'] else file_ext
            self.new_file_name = ''
            for name_part in self.get_par([], 'new_name_order'):
                self.new_file_name += self.new_name_parts[name_part]
            self.new_file_name += self.new_name_parts['ext']

            new_name_case = self.get_par('as_is', 'new_name_case')
            if new_name_case == 'lower':
                self.new_file_name = self.new_file_name.lower()
            elif new_name_case == 'upper':
                self.new_file_name = self.new_file_name.upper()

            folder_path = os.path.split(self.file_path)[0]
            self.new_file_path = join(folder_path, self.new_file_name)
        else:
            self.new_file_path = ''
        return self.new_file_name

    def set_new_sd_and_coord_from_group(self) -> typing.NoReturn:
        gr: PVGroup = self.pv_group
        # Build new value of UserComment tag
        new_sd = {'pvs': '1.01'}
        if gr.file_datetime:
            new_sd['dt'] = gr.local_datetime.strftime("%Y:%m:%d %H:%M:%S")
        if gr.local_datetime_type:
            new_sd['dt_type'] = gr.local_datetime_type
        if self.dt_source:
            new_sd['dt_source'] = gr.dt_source
        if gr.t_zone:
            new_sd['t_zone'] = gr.t_zone
        if gr.utc_datetime:
            new_sd['utc_dt'] = gr.utc_datetime.strftime("%Y:%m:%d %H:%M:%S")
        if gr.coord_source:
            new_sd['coord_source'] = gr.coord_source
        if gr.address.address:
            new_sd['address'] = gr.address.address
        if self.first_datetime:
            new_sd['first_dt'] = self.first_datetime.strftime("%Y:%m:%d %H:%M:%S")
        if gr.camera_key:
            new_sd['camera'] = gr.camera_key
        if gr.gr_id:
            new_sd['gr_id'] = gr.gr_id
        if self.f_id:
            new_sd['f_id'] = self.f_id
        if self.prev_sd_value:
            new_sd['prev_value'] = self.prev_sd_value
        if gr.dt_offset:
            new_sd['dt_offset'] = gr.dt_offset

        # If the file data has been changed, then fill in self.new_script_data.
        if self.script_data != new_sd:
            self.set_new_script_data(new_sd)

        # Update GPS coordinates ONLY if gr.coord_source is non-empty!!!!!!!!!
        loc_changed_flag = self.prev_coord != gr.coord or self.prev_alt != gr.alt
        new_location_flag = gr.coord and gr.coord_source and 'coord_source' in new_sd and new_sd['coord_source']
        erase_location_flag = not gr.coord and not gr.coord_source and self.coord_source and self.coord
        keep_origin_coord = self.coord_source or not self.coord
        if loc_changed_flag and (new_location_flag or erase_location_flag) and keep_origin_coord:
            if gr.coord:
                self.set_new_coord_for_exif({'GPSLatitude': str(abs(gr.coord[0])),
                                             'GPSLatitudeRef': 'N' if gr.coord[0] > 0 else 'S',
                                             'GPSLongitude': str(abs(gr.coord[1])),
                                             'GPSLongitudeRef': 'E' if gr.coord[1] > 0 else 'W',
                                             'GPSAltitudeRef': '0' if gr.alt > 0 else '1',
                                             'GPSAltitude': str(abs(gr.alt))})
            else:
                self.set_new_coord_for_exif({'GPSLatitude': '',
                                             'GPSLatitudeRef': '',
                                             'GPSLongitude': '',
                                             'GPSLongitudeRef': '',
                                             'GPSAltitudeRef': '',
                                             'GPSAltitude': ''})

    def set_new_sd_and_coord_for_erase_coord(self) -> typing.NoReturn:
        script_data = self.script_data
        if 'coord_source' in script_data:
            del script_data['coord_source']
        if 'coord_type' in script_data:
            del script_data['coord_type']
        self.set_new_script_data(script_data)

        self.set_new_coord_for_exif({'GPSLatitude': '',
                                     'GPSLatitudeRef': '',
                                     'GPSLongitude': '',
                                     'GPSLongitudeRef': '',
                                     'GPSAltitudeRef': '',
                                     'GPSAltitude': ''})

    def set_file_macos_tags(self) -> bool:
        """
        Depending on the results of the calculations and the parameters specified in the settings, write macOS tags
        to the macOS file
        :return:
        """
        gr = self.pv_group
        # At first keep only macOS tags with one of signs from par['keep_mac_tag'] in the beginning of tag.
        macos_tag_list = []
        for tag in macos_tags.get_all(file=self.file_path):
            for keep_sing in self.get_par([], 'mactag_keep_signs'):
                if func.str_after_sing(tag.name, keep_sing):
                    macos_tag_list.append(tag)
        try:
            macos_tags.remove_all(file=self.file_path)
        except Exception as ex:
            self.print_log('e', 'main', '(set_file_macos_tags) exif_tool.execute ' + str(ex) + ' ' + self.file_path)
            return False

        for macos_tag in macos_tag_list:
            macos_tags.add(macos_tag, file=self.file_path)

        for step_tag in self.get_par([], 'mactag_order'):
            # If the addr_if_obj_to_mac_tag not set, then address tags are not saved if there are calculated
            # object tags.
            if step_tag == 'mactag_address' and gr.address.tags and \
                    (not gr.object_tags or self.check_par('set', 'addr_if_obj_to_mac_tag')):
                for address_tag in gr.address.tags:
                    self.set_macos_tag('mactag_address', address_tag)

            # Source of geolocation information - GPS coordinates. Empty means original.
            if step_tag == 'mactag_coord_source' and gr.coord_source:
                self.set_macos_tag('mactag_coord_source', gr.coord_source)

            # folder_dt_name_format.
            if step_tag == 'mactag_folder_dt_format' and gr.folder_dt_name:
                self.set_macos_tag('mactag_folder_dt_format', gr.folder_dt_name)

            # Special phrases from full file path in accord of settings
            path_phrases_tags = gr.pv_folder.path_phrases_tags
            if step_tag == 'mactag_path' and path_phrases_tags:
                for phrase in path_phrases_tags:
                    self.set_macos_tag('mactag_path', phrase)

            # Tags from geo objects
            if step_tag == 'mactag_geo_object' and gr.object_tags:
                for object_tag in gr.object_tags:
                    self.set_macos_tag('mactag_geo_object', object_tag)

            # Source of address.
            if step_tag == 'mactag_address_source' and gr.address.address and \
                    'source' in gr.address.address:
                self.set_macos_tag('mactag_address_source', gr.address.address['source'])

            # File with coordinates but without address.
            if step_tag == 'mactag_no_address' and gr.coord and not gr.address.address:
                self.set_macos_tag('mactag_no_address')

            # File with coordinates, without address, but with 'geo_point' in address
            if step_tag == 'mactag_geo_point_address' and gr.coord and \
                    'geo_point' in gr.address.address:
                self.set_macos_tag('mactag_geo_point_address')

            # No GPS coordinates.
            if step_tag == 'mactag_no_coord' and not gr.coord:
                self.set_macos_tag('mactag_no_coord')

            # No information about t_zone.
            if step_tag == 'mactag_no_t_zone' and not gr.t_zone:
                self.set_macos_tag('mactag_no_t_zone')

            # No utc_datetime.
            if step_tag == 'mactag_no_utc_datetime' and not gr.utc_datetime:
                self.set_macos_tag('mactag_no_utc_datetime')

            # Camera_key.
            if step_tag == 'mactag_camera_key' and self.camera_key:
                self.set_macos_tag('mactag_camera_key', self.camera_key)

            # First original datetime.
            if step_tag == 'mactag_first_datetime' and self.first_datetime:
                self.set_macos_tag('mactag_first_datetime', str(self.first_datetime))

            # Time offset after correction.
            if step_tag == 'mactag_datetime_offset' and gr.dt_offset:
                self.set_macos_tag('mactag_datetime_offset', str(gr.dt_offset))

            # creation_datetime.
            if step_tag == 'mactag_creation_datetime' and gr.file_datetime:
                self.set_macos_tag('mactag_creation_datetime', str(gr.file_datetime))

            # creation_datetime.
            if step_tag == 'mactag_utc_datetime' and gr.utc_datetime:
                self.set_macos_tag('mactag_utc_datetime', str(gr.utc_datetime))

            # Sign of Date and time of creation from os file statistic - not from EXIF.
            if step_tag == 'mactag_no_exif_dt' and self.dt_source in ['st_birthtime', 'st_mtime']:
                self.set_macos_tag('mactag_no_exif_dt', self.dt_source)

            # Calculated datetime for naming.
            if step_tag == 'mactag_naming_datetime' and gr.naming_datetime:
                self.set_macos_tag('mactag_naming_datetime', str(gr.naming_datetime))

            # Sing of calculation datetime for naming without UTC datetime or t-zone.
            if step_tag == 'mactag_naming_datetime_warning' and gr.naming_warning:
                self.set_macos_tag('mactag_naming_datetime_warning', gr.naming_warning)

            # Sorting key.
            if step_tag == 'mactag_sort_key' and gr.sort_key:
                self.set_macos_tag('mactag_sort_key', gr.sort_key)

        return True

    def set_macos_tag(self, tag_settings_name: str, *args: str) -> typing.NoReturn:
        if self.get_par(False, tag_settings_name, 'active'):
            text = args[0] if args and args[0] else ''
            tag = macos_tags.Tag(name=self.get_par('', tag_settings_name, 'prefix') + text,
                                 color=func.get_macos_tag_color_code(self.get_par('NONE', tag_settings_name, 'color')))
            macos_tags.add(tag, file=self.file_path)

    def file_rename(self, *args: str) -> typing.NoReturn:
        new_file_p = args[0] if args and args[0] else self.new_file_path
        if self.file_path != new_file_p:
            os.rename(self.file_path, new_file_p + self.get_par('-_t_-', 'job_sing'))
            self.print_log('i', 'rename', f"{self.file_path} -> {new_file_p}")
        else:
            self.print_log('i', 'rename', f"{self.file_path} File name has not been changed")

    def clear_all_file_exif_tags(self) -> typing.NoReturn:
        b_file_path = self.file_path.encode("utf-8")
        PVFile.exif_tool.execute(b"-overwrite_original",
                                 b"-TAG=",
                                 b_file_path)

    def clear_file_coord(self) -> typing.NoReturn:
        self.coord = ()
        self.coord_source = ''

    def set_new_coord_for_exif(self, new_coord: typing.Dict[str, str]) -> typing.NoReturn:
        self.new_coord = new_coord

    def set_new_script_data(self, new_script_data: dict) -> typing.NoReturn:
        self.new_script_data = new_script_data

    def get_new_f_id(self) -> typing.NoReturn:
        if not self.f_id:
            self.f_id = str(uuid.uuid4())


class PVFolder(Settings):
    def __init__(self, folder_path: str):
        self.folder_path = folder_path
        self.folder_name = os.path.split(folder_path)[1]
        self.pv_groups = {}
        self.folder_files = {}
        self.pv_group_name_by_file_name = {}
        self.pv_groups_by_name_key = {}
        # Manual data for update photo/video files
        self.manual_data = ManualData()
        self.manual_data.load_folder_manual_data_file(folder_path)
        self.path_phrases_tags = self.get_path_phrases_tags()
        self.cameras = {}
        self.multi_track = GeoMultiTrack()

    def run_process_folder(self) -> bool:
        """
        Method of the main process when processing a folder. All systematization steps are run from this method.
        """

        # Check that this folder has not been worked on yet.
        done_folders_list = func.load_pickle_file_as_struct(PVFolder.get_par('', 'done_folders_pickle_file_path'), [])
        if self.folder_path in done_folders_list:
            self.print_log('i', 'main', f'Skipped done: {self.folder_path}')
            self.run_subfolders_process()
            return False

        self.print_log('i', 'main', f'=== Start working on ===: {self.folder_path}')

        # Load folder settings file from current folder
        if not self.load_settings(self.folder_path):
            return False

        # Clean up after previous interrupted job.
        self.file_names_clean_up()

        # Load address cache
        if self.check_par('get', 'get_address') and not Address.addr_cache:
            Address.load_address_cache()

        # tmp_data_file_path = ''
        # if self.get_par(False, 'tech_load_pv_groups'):
        #     tmp_data_file_path = join(self.folder_path, '_files_data.pickle')
        #     self.pv_groups, self.pv_group_name_by_file_name = func.load_pickle_file_as_struct(tmp_data_file_path,
        #                                                                                       ({}, {}))

        if not self.pv_groups:
            # Create structure for work with photo/video files.
            if not self.build_main_data_structures():
                return False

        # if self.get_par(False, 'tech_load_pv_groups') and self.pv_groups:
        #     func.save_struct_as_pickle_file(tmp_data_file_path, (self.pv_groups, self.pv_group_name_by_file_name))

        if not self.pv_groups:
            self.print_log('i', 'main', f'Skipped empty: {self.folder_path}')
            self.run_subfolders_process()
            return False

        # Get all cameras keys
        self.get_all_folder_cameras()

        # Replace file names to group names in ManualFileData
        self.manual_data.check_and_rebuild(self.pv_group_name_by_file_name, self.pv_groups)

        #  ----------------- photo/video files loaded and ready to work--------------------

        # Shift files datetime according folder manual settings.
        self.shift_file_datetime_by_folder_settings()

        # Get data from file with name from 'manual_data_file' in current folder
        if self.check_par('get', 'get_file_data_from_manual_file'):
            self.print_log('i', 'stage', f"{self.folder_path}: Start getting of manual data from file.")
            for pv_group_name, group_data in self.manual_data.manual_data.items():
                self.pv_groups[pv_group_name].set_group_data(group_data, 'by_hand', 'manual data file')
            self.print_log('i', 'stage', f"{self.folder_path}: Finished getting of manual data from file.")

        # Get data from files tags
        if self.check_par('get', 'get_file_data_by_file_tags'):
            self.get_file_data_by_manual_file_tags()

        # Load all .gpx files from current folder
        if self.check_par('get', 'get_coord_by_gpx_file'):
            gpx_multi_track = GeoMultiTrack()
            gpx_multi_track.load_gpx_folder(self.folder_path)
            self.multi_track.add_multi_track(gpx_multi_track)

        if self.check_par('get', 'get_utc_calibrate_by_track') and self.multi_track:
            # Based on several frames, determine the clock shift of the non-navigation camera relative to the gpx track.
            # Separately for each camera.
            utc_dt_shift = self.get_utc_dt_shift_from_multitrack(self.multi_track)
            if utc_dt_shift:
                self.print_log('i', 'stage', f"{self.folder_path}: {utc_dt_shift}")
            else:
                self.print_log('i', 'stage', f"{self.folder_path}: No shifts found.")
            self.get_fixed_utc_dt_from_delta(utc_dt_shift)

        # For all pv_groups with no UTC datetime get it from t_zone and local creation datetime
        for pv_group in self.pv_groups.values():
            pv_group.get_utc_dt_if_empty()

        # Create destination subfolders and move all relevant files there. If after sorting and moving the files, the
        # current folder is empty, stop working in the current one and start the recurrent process for child folders.
        self.get_folder_dt_name_in_groups()
        if self.get_par(False, 'sort_files'):
            if not self.separate_files_to_sub_folders():
                return False
        if not self.pv_groups:
            self.print_log('i', 'main', f'Skipped devastated: {self.folder_path}')
            self.run_subfolders_process()
            return False

        # For each file group without coordinates gt coordinates by utc datetime
        if self.check_par('get', 'get_coord_by_gpx_file'):
            self.get_coord_from_multi_tracks_by_utc_dt(self.multi_track, 'geo_track')

        #  --------------------relative calculations----------------------------

        # Sorting pv_dict by key: 'sort_key'
        self.sort()

        # Get t_zone by neighbors
        if self.check_par('get', 'get_t_zone_by_neighbors'):
            self.get_t_zone_by_neighbors_borders()

        # For each file group without coordinates get coordinates by utc datetime
        self.get_coord_from_multi_tracks_by_utc_dt(self.multi_track, 'geo_track')

        # get coordinates from previous and next neighbors of file in current folder
        if self.check_par('get', 'get_coord_by_neighbors'):
            # Get synthetic track from photo/video files in current folder.
            exist_tracks = self.get_tracks_exist_pv()
            self.get_coord_from_multi_tracks_by_utc_dt(exist_tracks, 'geo_neighbors')

        # get coordinates in the beginning and in the end of folder by first group with coordinates and from last one
        if self.check_par('get', 'get_begin_coord_by_first_neighbor'):
            self.get_begin_coord_by_first_with_coord(list(self.pv_groups.values()))

        # get coordinates in the beginning and in the end of folder by first group with coordinates and from last one
        if self.check_par('get', 'get_end_coord_by_last_neighbor'):
            self.get_begin_coord_by_first_with_coord(list(self.pv_groups.values())[::-1])

        # get coordinates by median of all files with coordinates in current folder
        if self.check_par('get', 'get_median_coord'):
            self.get_median_coord_in_folder()

        # get common coordinates for non coordinate groups from 'manual_data_file' in current folder
        if self.check_par('get', 'get_common_data_from_manual_file'):
            self.get_common_data_from_manual_file()

        # Sorting pv_dict by key: 'sort_key'
        self.sort()

        # Numbering files
        self.get_name_number()

        # Get address by coordinates.
        if self.check_par('get', 'get_address'):
            self.get_folder_addresses_by_coordinates()

        # Get address by coordinates.
        self.get_local_dt()

        self.get_new_files_names()

        self.get_folder_object_tags_by_coord()

        # Get new unique_id if empty
        if self.check_par('set', 'exif_set') and self.check_par('get', 'get_unique_id'):
            for pv_group in self.pv_groups.values():
                pv_group.get_new_id()

        # According to the settings and previous calculations set macOS tags.
        if self.check_par('set', 'mac_tags_set') and self.check_par('os', 'macOS'):
            if not self.set_macos_tags():
                return False

        # According to the settings and previous calculations set EXIF data.
        if self.check_par('set', 'exif_set'):
            self.get_new_sd_and_coord()
            self.set_folder_exif_tags()

        # If something went wrong, and we got duplicate new filenames, don't start the renaming process.
        if not self.final_check_files_names_before_rename():
            return False

        # Renaming file plus adding a technological rename sign 'job_sing'
        # 1 of 2 step renaming to temporary names
        if self.check_par('set', 'rename_set'):
            self.final_rename()

        # Clean up after current rename job - remove technological rename sign from files names.
        self.file_names_clean_up()

        # Save by hand coordinates to file settings['manual_data_file'] in current folder
        if self.check_par('set', 'rename_set'):
            # Modify information about by hand coordinates in photo/video files.
            self.manual_data.rename_before_save_manual_data_file({pv_group.name: pv_group.new_name for
                                                                  pv_group in self.pv_groups.values()})
        self.manual_data.sort_manual_data_file()
        self.manual_data.save_folder_manual_data_file()

        # Write the current folder to the list of processed ones.
        done_folders_list.append(self.folder_path)
        func.save_struct_as_txt_file(self.get_par('', 'done_folders_txt_file_path'),
                                     done_folders_list, 'done_folders')
        func.save_struct_as_pickle_file(self.get_par('', 'done_folders_pickle_file_path'), done_folders_list)
        # Save address cache to the file.
        if self.check_par('get', 'get_address') and Address.addr_cache:
            Address.save_address_cache()

        # Save coordinates of photo/video files in current folder to the .gpx file
        if self.no_empty_par('exist_pv_gpx_track_file') and self.get_par(False, 'create_exist_track'):
            exist_tracks = self.get_tracks_exist_pv()
            exist_pv_gpx_track_file_path = join(self.folder_path, self.get_par('', 'exist_pv_gpx_track_file'))
            exist_tracks.save_multi_track(exist_pv_gpx_track_file_path)

        if self.check_par('log_mode', ('result_log', 'result_print')):
            self.check_folder_proc_results()

        self.print_log('i', 'main', f'Processed: {self.folder_path}')

        self.run_subfolders_process()

    def add_group_to_folder(self, pv_group_name: str, pv_group: PVGroup) -> typing.NoReturn:
        self.pv_groups[pv_group_name] = pv_group

    def get_path_phrases_tags(self, *args: str) -> typing.List[str]:
        """
        Get a list of tags from full_path. Do a search for phrases for tags based on a regular expression -
        'path_names_phrase_pattern'
        :return:
        """
        full_path = args[0] if args and args[0] else self.folder_path
        # Get name tags from the full folder path.
        pattern = self.get_par('', 'path_names_phrase_pattern')
        return re.findall(pattern, full_path)

    # Sorting of the main data structure of photo/video files.
    def sort(self) -> typing.NoReturn:
        self.pv_groups = {s_n: pv_g for s_n, pv_g in sorted(self.pv_groups.items(), key=lambda li: li[1].sort_key)}

    def file_names_clean_up(self) -> typing.NoReturn:
        """
        Remove 'job_sing' from file names after renaming job
        :return:
        """
        job_sing = PVFolder.get_par('-_t_-', 'job_sing')
        self.print_log('i', 'stage', f"{self.folder_path}: Start cleanup after rename.")
        job_list = [f for f in listdir(self.folder_path) if
                    isfile(join(self.folder_path, f)) and job_sing in f]
        for file in job_list:
            os.rename(join(self.folder_path, file), join(self.folder_path, file.replace(job_sing, '')))
        self.print_log('i', 'stage', f"{self.folder_path}: Finished cleanup after rename.")

    def run_subfolders_process(self) -> typing.NoReturn:
        """
        Starting recurrent process on all subfolders.
        Process ignore folders which name started by 'ignore' and all their subfolders.
        :return:
        """
        if self.get_par(True, 'recurrent'):
            ignore_sing = self.get_par('', 'ignore_sing')
            ignor_sign_len = len(ignore_sing)
            for folder in [folder for folder in listdir(self.folder_path) if isdir(join(self.folder_path, folder))]:
                if len(folder) >= ignor_sign_len and folder[:ignor_sign_len] != ignore_sing:
                    folder_path = join(self.folder_path, folder)
                    rec_folder = PVFolder(folder_path)
                    rec_folder.run_process_folder()

    def add_masters_to_main_data_structures(self, file_list: typing.List[str]) -> bool:
        case_sens = self.get_par(False, 'group_pattern_case_sensitive')
        # Creating groups by master files settings. 'masters'
        files_count = 0
        for file in file_list:
            files_count += 1
            for pattern, scheme in self.get_par({}, 'masters').items():
                name_key_re = re.findall(pattern, file) if case_sens else re.findall(pattern.upper(), file.upper())
                if name_key_re:
                    name_key = name_key_re[0]
                    if file in self.pv_groups:
                        self.print_log('w', 'main', f"According to the settings, {file} is included in more than "
                                                    f"one group as the master one. Probably incorrect 'masters' "
                                                    f"setting.")
                        return False
                    pv_group = PVGroup(self, file, self.folder_path)
                    pv_group.add_file_to_group(join(self.folder_path, file),
                                               name_prefix=scheme['prefix'],
                                               name_suffix=scheme['suffix'],
                                               name_ext=scheme['ext'])
                    self.add_group_to_folder(file, pv_group)
                    self.pv_groups_by_name_key[name_key] = pv_group
                    self.pv_group_name_by_file_name[file] = file
            self.print_counter(f"{self.folder_path}: Creating main data structure - masters. {files_count} file "
                               f"from {len(file_list)} files. Created {len(self.pv_groups)} groups.")
        if file_list:
            self.print_counter('')
        return True

    def add_pair_to_main_data_structures(self, file_list: typing.List[str], pair_type: str) -> bool:
        case_sens = self.get_par(False, 'group_pattern_case_sensitive')
        files_count = 0
        added_count = 0
        for file in file_list:
            files_count += 1
            for pattern, scheme in self.get_par({}, pair_type).items():
                name_key_re = re.findall(pattern, file) if case_sens else re.findall(pattern.upper(), file.upper())
                if name_key_re:
                    name_key = name_key_re[0]
                    # Add file to the pv_group
                    if name_key in self.pv_groups_by_name_key.keys() and \
                            file not in self.pv_group_name_by_file_name.keys():
                        self.pv_groups_by_name_key[name_key].add_file_to_group(join(self.folder_path, file),
                                                                               name_prefix=scheme['prefix'],
                                                                               name_suffix=scheme['suffix'],
                                                                               name_ext=scheme['ext'])
                        self.pv_group_name_by_file_name[file] = self.pv_groups_by_name_key[name_key].name
                        added_count += 1
                    # Found another pv_group for the file. This situation is not true in the current data model.
                    elif name_key in self.pv_groups_by_name_key.keys() and \
                            file in self.pv_group_name_by_file_name.keys():
                        self.print_log('w', 'main', f"According to the settings, {file} is included in more than "
                                                    f"one group as the paired one: "
                                                    f"{self.pv_group_name_by_file_name[file]}  and "
                                                    f"{self.pv_groups_by_name_key[name_key].name}. Probably incorrect "
                                                    f"'slave' setting.")
                        return False
                self.print_counter(f"{self.folder_path}: Creating main data structure - {pair_type}. "
                                   f"{files_count} file from {len(file_list)} files. Added {added_count} "
                                   f"{pair_type} files to the {len(self.pv_groups)} groups.")
        if file_list:
            self.print_counter('')
        return True

    def add_non_pair_to_main_data_structures(self, file_list: typing.List[str]) -> typing.NoReturn:
        files_count = 0
        non_pair_scheme = self.get_par({"prefix": "", "suffix": ""}, 'non_pair')
        for file in file_list:
            pv_group = PVGroup(self, file, self.folder_path)
            pv_group.add_file_to_group(join(self.folder_path, file),
                                       name_prefix=non_pair_scheme['prefix'],
                                       name_suffix=non_pair_scheme['suffix'])
            self.add_group_to_folder(file, pv_group)
            self.pv_group_name_by_file_name[file] = file
            name_key = os.path.splitext(file)[0].upper()
            self.pv_groups_by_name_key[name_key] = pv_group
            files_count += 1

            self.print_counter(f"{self.folder_path}: Creating main data structure - non pair. {files_count} file "
                               f"from {len(file_list)} files. Added {files_count} non pair files and groups. "
                               f"Total groups: {len(self.pv_groups)}.")
        if file_list:
            self.print_counter('')

    def build_main_data_structures(self) -> typing.NoReturn:

        self.print_log('i', 'stage', f"{self.folder_path}: Start creating main folder data structure.")
        start = time()
        # getting a file list of expected types from current folder
        media_types_list = [file_type.upper() for file_type in self.get_par([], 'media_types')]
        file_list = [f for f in listdir(self.folder_path) if
                     isfile(join(self.folder_path, f)) and f.split('.')[-1].upper() in media_types_list]
        if not file_list:
            return True
        # ------------masters------------------
        if self.no_empty_par('masters'):
            if not self.add_masters_to_main_data_structures(file_list):
                return False
            # ------------slaves------------------
            file_list = [file for file in file_list if file not in self.pv_group_name_by_file_name.keys()]
            if file_list and self.pv_groups and self.no_empty_par('slaves'):
                if not self.add_pair_to_main_data_structures(file_list, 'slaves'):
                    return False

        # ------------all non pair media------------------
        # Adding pv_group and non pair file.
        file_list = [file for file in file_list if file not in self.pv_group_name_by_file_name.keys()]
        if file_list:
            self.add_non_pair_to_main_data_structures(file_list)

        # ------------- all additional files ---------------
        # Adding additional files to the pv_groups. For example .XMP
        add_types_list = [file_type.upper() for file_type in self.get_par([], 'add_types')]
        file_list = [f for f in listdir(self.folder_path) if
                     isfile(join(self.folder_path, f)) and f.split('.')[-1].upper() in add_types_list]
        if file_list and self.pv_groups and self.no_empty_par('additions'):
            if not self.add_pair_to_main_data_structures(file_list, 'additions'):
                return False

        self.rebuild_folder_files()

        self.print_log('i', 'stage', f"{self.folder_path}: Finished creating main folder data structure in "
                                     f"{timedelta(seconds=int(time() - start))}. ")
        return True

    def shift_file_datetime_by_folder_settings(self) -> typing.NoReturn:
        # If current folder settings has information about the time difference for a particular photo-device
        # by the value from the time_shift_by_settings -> camera_key parameter or for all files , apply that.
        if self.check_par('time_shift_by_settings', 'camera_key_shift'):
            self.print_log('i', 'stage', f"{self.folder_path}: Start manually shifting datetime.")
            cam_keys = self.get_par({}, 'time_shift_by_settings', 'camera_key_shift')
            cam_keys_upper = {cam.upper(): time_shift for cam, time_shift in cam_keys.items()}
            if cam_keys:
                if 'ALL' in cam_keys_upper.keys():
                    time_shift = cam_keys_upper['ALL']
                    for group_name, pv_group in self.pv_groups.items():
                        pv_group.manual_shift_group_time(time_shift)
                else:
                    for cam_key, time_shift in cam_keys.items():
                        for pv_group in [pv_gr for pv_gr in self.pv_groups.values() if pv_gr.camera_key == cam_key]:
                            pv_group.manual_shift_group_time(time_shift)
            self.print_log('i', 'stage', f"{self.folder_path}: Finished manually shifting datetime.")

    def separate_files_to_sub_folders(self) -> bool:
        # Separate to subfolders by settings['folder_dt_name_format']
        subfolders = []
        groups_to_move = {}
        # Select files to move to subfolders and create subfolders
        self.print_log('i', 'stage', f"{self.folder_path}: Start separating files to subfolders by settings.")
        for group_name, pv_group in self.pv_groups.items():
            if pv_group.folder_dt_name not in self.folder_name:
                sub_folder_path = join(self.folder_path, pv_group.folder_dt_name)
                if sub_folder_path not in subfolders:
                    func.create_new_folder(sub_folder_path)
                    subfolders.append(sub_folder_path)
                groups_to_move[group_name] = sub_folder_path

        # Moving selected files
        if groups_to_move:
            for group_name, new_folder_path in groups_to_move.items():
                if not self.pv_groups[group_name].move_group_to_folder(new_folder_path):
                    self.print_log('w', 'main', f'Skipped {self.folder_path} and all subfolders.')
                    return False
                del self.pv_groups[group_name]

        self.rebuild_pv_group_name_by_file_name()
        self.rebuild_folder_files()

        self.print_log('i', 'stage', f"{self.folder_path}: Finished separating files to subfolders by settings.")

        return True

    def rebuild_pv_group_name_by_file_name(self) -> typing.NoReturn:
        self.pv_group_name_by_file_name.clear()
        for group_name, pv_group in self.pv_groups.items():
            self.pv_group_name_by_file_name.update({file.file_name: group_name for file in pv_group.group_files})

    def rebuild_folder_files(self) -> typing.NoReturn:
        self.folder_files.clear()
        for group_name, pv_group in self.pv_groups.items():
            self.folder_files.update({file.file_name: file for file in pv_group.group_files})

    def get_folder_object_tags_by_coord(self) -> typing.NoReturn:
        for pv_group in self.pv_groups.values():
            pv_group.get_group_object_tags_by_coord()

    def get_file_data_by_tag(self, tags: typing.List[str]) -> dict:
        group_data_by_tag = {}
        t_zones = [z for z in pytz.all_timezones_set]
        manual_date_time_format = self.get_par('', 'manual_date_time_format')
        tag_by_hand_info_begin = self.get_par('', 'tag_by_hand_info_begin')

        tag_num = 0
        for tag in tags:
            tag_num += 1
            group_data = {}
            self.print_counter(f'Getting of manual data file tags. Processed {tag_num} tags from {len(tags)}')

            # In case '*' in tag_by_hand_info_begin this will not work
            # by_hand_pattern = r'^' + tag_by_hand_info_begin
            # by_hand_tag = re.sub(by_hand_pattern, '', tag) if re.findall(by_hand_pattern, tag) else ''

            by_hand_tag = func.str_after_sing(tag, tag_by_hand_info_begin)

            if by_hand_tag:
                coord = func.text_to_coord(by_hand_tag)
                if coord:
                    group_data['coord'] = coord
                alt = func.text_to_alt(by_hand_tag)
                if alt:
                    group_data['alt'] = alt
                t_zone = by_hand_tag if by_hand_tag in t_zones else ''
                if t_zone:
                    group_data['t_zone'] = t_zone
                geo_object_name = GeoObjects.is_geo_object(by_hand_tag)
                if geo_object_name:
                    group_data['geo_object_name'] = geo_object_name
                file_dt = func.string_to_datetime(by_hand_tag, manual_date_time_format)
                if file_dt:
                    group_data['file_dt'] = file_dt
                if group_data:
                    group_data_by_tag[tag] = group_data
        if tag_num: self.print_counter('')
        return group_data_by_tag

    def get_file_data_by_manual_file_tags(self) -> typing.NoReturn:
        self.print_log('i', 'stage', f"{self.folder_path}: Start getting of manual data from file tags.")
        start = time()

        # Get all macOS tags list
        list_tags_lists = [pv_group.mac_tags_names for pv_group in self.pv_groups.values()]
        # add new tag type here
        # list_tags_lists += new tags list

        all_tags = [tag for tags in list_tags_lists for tag in tags]
        tags = list(set(all_tags))

        self.print_log('i', 'stage', f"{self.folder_path}: From all {len(all_tags)} file tags, "
                                     f"get {len(tags)} unique tags.")

        group_data_by_tag = self.get_file_data_by_tag(tags)

        if group_data_by_tag:
            for pv_group_name, pv_group in self.pv_groups.items():
                pv_group.get_group_data_by_manual_file_tags(group_data_by_tag)

        self.print_log('i', 'stage', f"{self.folder_path}: Finished getting of manual data from file tags in "
                                     f"{timedelta(seconds=int(time() - start))}")

    def get_tracks_exist_pv(self) -> GeoMultiTrack:
        self.print_log('i', 'stage', f"{self.folder_path}: Start getting geo track from exist files.")
        exist_pv_tracks = GeoMultiTrack()

        if self.get_par(False, 'split_exist_track_by_cameras'):
            cams_tracks = {cam: exist_pv_tracks.add_track() for cam in self.cameras.keys()}
        else:
            cams_tracks = {}

        cams_tracks['_-no_cam-_'] = exist_pv_tracks.add_track()
        for group_name, pv_group in self.pv_groups.items():
            if pv_group.coord and pv_group.utc_datetime:
                group_cam = pv_group.camera_key if pv_group.camera_key in cams_tracks.keys() else '_-no_cam-_'
                geo_point = GeoTrackPoint(coord=(pv_group.lat, pv_group.lon),
                                          elevation=pv_group.alt,
                                          utc_dt=pv_group.utc_datetime)
                cams_tracks[group_cam].add_point(geo_point)
        for track in cams_tracks.values():
            track.sort_track()

        self.print_log('i', 'stage', f"{self.folder_path}: Finished getting geo information from exist files.")
        return exist_pv_tracks

    def get_utc_dt_shift_from_multitrack(self, geo_tracks: GeoMultiTrack) -> typing.Union[typing.Dict[str, float],
                                                                                          typing.Dict[{}]]:
        if self.check_par('utc_cal_by_multi_track'):
            utc_dt_shift = {}
            cameras_to_calibrate = {cam: geo for cam, geo in self.cameras.items() if geo == 'no_geo'}
            self.print_log('i', 'stage',
                           f"{self.folder_path}: Start getting datetime shift for {len(cameras_to_calibrate.keys())} "
                           f"camera(s) without own geodata by geo tracks: "
                           f"{', '.join(list(cameras_to_calibrate.keys()))}")

            for camera in cameras_to_calibrate.keys():
                calibrate = CalibrateCameraClocks(camera, geo_tracks, self.pv_groups)
                time_shift = calibrate.get_camera_utc_dt_shift()

                if time_shift:
                    utc_dt_shift[camera] = time_shift

            self.print_log('i', 'stage', f"{self.folder_path}: Finished getting datetime shift for all cameras.")
        else:
            self.print_log('w', 'main', f"No utc_cal_by_multi_track in settings calibrating stopped.")
            utc_dt_shift = {}
        return utc_dt_shift

    def get_fixed_utc_dt_from_delta(self, utc_dt_shift: typing.Dict[str, float]) -> typing.NoReturn:
        self.print_log('i', 'stage', f"{self.folder_path}: Start applying the found time shift to files sets.")
        for group_name, pv_group in self.pv_groups.items():
            if pv_group.camera_key and pv_group.camera_key in utc_dt_shift and utc_dt_shift[pv_group.camera_key] and \
                    (not pv_group.coord or (pv_group.coord and pv_group.coord_source)):
                t_delta = timedelta(seconds=utc_dt_shift[pv_group.camera_key])
                pv_group.set_group_utc_datetime(pv_group.utc_relative_base_time - t_delta, 'shifted UTC datetime')
        self.print_log('i', 'stage', f"{self.folder_path}: Finished applying the found time shift to files sets.")

    def get_coord_from_multi_tracks_by_utc_dt(self, tracks: GeoMultiTrack, geo_type: str) -> typing.NoReturn:
        self.print_log('i', 'stage', f"{self.folder_path}: Start getting coordinates from {geo_type} multi track "
                                     f"by UTC time.")
        for group_name, pv_group in self.pv_groups.items():
            if not pv_group.coord and pv_group.utc_datetime:
                coord, elev = tracks.get_coord_by_utc_dt(pv_group.utc_datetime)
                if coord:
                    pv_group.set_group_data({'coord': coord, 'alt': elev}, geo_type, 'multi tracks by UTC datetime')
        self.print_log('i', 'stage', f"{self.folder_path}: Finished getting coordinates from {geo_type} multi track "
                                     f"by UTC time.")

    def get_t_zone_by_neighbors_borders(self) -> typing.NoReturn:
        self.print_log('i', 'stage', f"{self.folder_path}: Start getting t-zone from sorted neighbors files.")
        to_get_t_zone_group_list = []
        step_group = None
        for group_name, pv_group in self.pv_groups.items():
            if pv_group.t_zone:
                if to_get_t_zone_group_list:
                    if step_group is None:
                        step_group = pv_group
                        self.print_log('w', 't_zone',
                                       f"{self.folder_path}: Can't get t_zone by neighbors. Check files "
                                       f"{to_get_t_zone_group_list[0].name} to {to_get_t_zone_group_list[-1].name} "
                                       f"which are at the top of the file list. To fix this, you can manually set the "
                                       f"t-zone to the first file.")
                        to_get_t_zone_group_list.clear()
                    elif pv_group.t_zone == step_group.t_zone or \
                            func.zone_offset(pv_group.t_zone) == func.zone_offset(step_group.t_zone):
                        for work_group in to_get_t_zone_group_list:
                            work_group.set_group_data({'t_zone': step_group.t_zone}, '', 'neighbors t_zones')
                            work_group.get_utc_dt_if_empty()
                        to_get_t_zone_group_list.clear()
                        step_group = pv_group
                    else:
                        step_group = pv_group
                        self.print_log('w', 't_zone',
                                       f"{self.folder_path}: {group_name} Can't get t_zone by neighbors. Check files "
                                       f"from {to_get_t_zone_group_list[0].name} to {to_get_t_zone_group_list[-1].name}"
                                       f" - the t-zone has changed. To fix this, you can manually set the t-zone to the"
                                       f" border files between t-zones.")
                        to_get_t_zone_group_list.clear()
                else:
                    step_group = pv_group
            else:
                to_get_t_zone_group_list.append(pv_group)
        if to_get_t_zone_group_list:
            self.print_log('w', 't_zone',
                           f"{self.folder_path}: Can't get t_zone by neighbors. Check files "
                           f"{to_get_t_zone_group_list[0].name} to {to_get_t_zone_group_list[-1].name} which are at the"
                           f" bottom of the file list. To fix this, you can manually set the t-zone to the last file.")
        self.print_log('i', 'stage', f"{self.folder_path}: Finished getting t-zone from sorted neighbors files.")

    def get_median_coord_in_folder(self) -> typing.NoReturn:
        """
        Collect coordinates from all files with geodata. Calculate and set the median value to files group without
        geolocation
        :return:
        for group_name, pv_group in self.pv_groups.items():
        """
        self.print_log('i', 'stage', f"{self.folder_path}: Start getting coordinates by median.")
        lat = statistics.median([pv_group.lat for pv_group in self.pv_groups.values() if pv_group.coord])
        lon = statistics.median([pv_group.lat for pv_group in self.pv_groups.values() if pv_group.coord])
        alt = statistics.median([pv_group.alt for pv_group in self.pv_groups.values() if pv_group.coord])
        if lat and lon:
            for pv_group in [pv_group for pv_group in self.pv_groups.values() if not pv_group.coord]:
                pv_group.set_group_data({'coord': (lat, lon), 'alt': alt}, 'geo_median', 'median values in folder')
        self.print_log('i', 'stage', f"{self.folder_path}: Finished getting coordinates by median.")

    def get_common_data_from_manual_file(self) -> typing.NoReturn:
        if self.manual_data.common_data:
            coord = self.manual_data.common_data['coord'] if 'coord' in self.manual_data.common_data else ()
            alt = self.manual_data.common_data['alt'] if 'alt' in self.manual_data.common_data else 0
            t_zone = self.manual_data.common_data['t_zone'] if 't_zone' in self.manual_data.common_data else ''
            if coord:
                for pv_group in [pv_group for pv_group in self.pv_groups.values() if not pv_group.coord]:
                    pv_group.set_group_data({'coord': coord, 'alt': alt}, 'geo_common', 'common values in folder')
                    pv_group.get_utc_dt_if_empty()
            elif t_zone:
                for pv_group in [pv_group for pv_group in self.pv_groups.values() if not pv_group.t_zone]:
                    pv_group.set_group_data({'t_zone': t_zone}, 'geo_common', 'common values in folder')
                    pv_group.get_utc_dt_if_empty()

    def get_name_number(self) -> typing.NoReturn:
        self.print_log('i', 'stage', f"{self.folder_path}: Start numbering.")
        dig = int(log10(len(self.pv_groups) * 2)) + 1
        pat = r'{:0' + str(dig) + r'd}'
        step_num = 0
        for pv_group in self.pv_groups.values():
            # Numbering starts from the beginning in each folder.
            # Keep number for RAW pairs images.
            str_num = pat.format(step_num)
            pv_group.set_group_num(str_num)
            step_num += 1
        self.print_log('i', 'stage', f"{self.folder_path}: Finished numbering.")

    def get_folder_addresses_by_coordinates(self) -> typing.NoReturn:
        start = time()
        self.print_log('i', 'stage', f"{self.folder_path}: Start getting addresses by coordinates in one process.")
        # Load address cache from local file
        Address.load_address_cache()
        # Activate connection to the OpenStreetMaps service
        Address.activate_osm_connection()

        num_group = 0
        for pv_group in self.pv_groups.values():
            num_group += 1
            self.print_counter(f'Getting address for {num_group} of {len(self.pv_groups)} groups, '
                               f'{Address.osm_connection_num} connections to OSM completed.', 'address')
            pv_group.get_group_address_by_coordinates()
        self.print_counter('', 'address')
        self.print_log('i', 'stage', f"{self.folder_path}: Finished getting address by coordinates in "
                                     f"{timedelta(seconds=int(time() - start))}. {Address.osm_connection_num} "
                                     f"connections made to OSM service.")

    def get_new_files_names(self) -> typing.NoReturn:
        # Calculation of new names
        self.print_log('i', 'stage', f"{self.folder_path}: Start getting new files names cores.")
        for pv_group in self.pv_groups.values():
            pv_group.get_new_group_name()
        self.print_log('i', 'stage', f"{self.folder_path}: Finished getting new files names cores.")

    def get_local_dt(self) -> typing.NoReturn:
        # Calculation of local datetime and result time offset
        for pv_group in self.pv_groups.values():
            pv_group.get_local_naming_offset_time()

    def get_new_sd_and_coord(self) -> typing.NoReturn:
        self.print_log('i', 'stage', f"{self.folder_path}: Start getting new data for exif tags in files.")
        for pv_file in self.folder_files.values():
            pv_file.set_new_sd_and_coord_from_group()
        self.print_log('i', 'stage', f"{self.folder_path}: Finished getting new data for exif tags in files.")

    def set_folder_exif_tags_one_proc(self) -> typing.NoReturn:
        script_data_tag_name = self.get_par('script_data_tag_name')
        num_file = 0
        for pv_file in self.folder_files.values():
            num_file += 1
            self.print_counter(f'Setting exif tags to {num_file} of {len(self.folder_files.values())} files.')
            exif_error = func.set_script_data_and_coord_to_file_exif_tags(PVFile.exif_tool,
                                                                          pv_file.file_path,
                                                                          pv_file.new_coord,
                                                                          pv_file.new_script_data,
                                                                          script_data_tag_name)
            if exif_error:
                self.print_log('e', 'main', exif_error)
        self.print_counter('')

    def set_folder_exif_tags_multi_proc(self, num_proc: int) -> typing.NoReturn:
        mp.get_context('spawn')
        exif_data_q = mp.Queue()
        exif_errors_q = mp.Queue()
        exif_answer_q = mp.Queue()
        script_data_tag_name = self.get_par('XMP:UserComment', 'script_data_tag_name')
        # Start process
        processes = []
        for _ in range(num_proc):
            p = mp.Process(target=self.execute_exif_tool_mp,
                           args=(exif_data_q, exif_errors_q, exif_answer_q, script_data_tag_name,))
            p.start()
            processes.append(p)

        # Send data
        for pv_file in self.folder_files.values():
            exif_data = {'file_path': pv_file.file_path,
                         'new_script_data': pv_file.new_script_data,
                         'new_coord': pv_file.new_coord}
            exif_data_q.put(exif_data)
        for _ in range(num_proc):
            exif_data_q.put(None)

        # Receive answers
        answers_nones = num_proc
        num_file = 0
        while answers_nones:
            exif_answer = exif_answer_q.get()
            if exif_answer:
                num_file += 1
                self.print_counter(f'{num_proc} process: Setting exif tags to {num_file} of '
                                   f'{len(self.folder_files.values())} files.')
            elif exif_answer is None:
                answers_nones -= 1
        self.print_counter('')

        # Receive errors
        exif_errors_nones = num_proc
        while exif_errors_nones:
            exif_error = exif_errors_q.get()
            if exif_error:
                self.print_log('e', 'main', exif_error)
            elif exif_error is None:
                exif_errors_nones -= 1

        for p in processes:
            p.join()

    def set_folder_exif_tags(self) -> typing.NoReturn:
        self.print_log('i', 'stage', f"{self.folder_path}: Start setting exif tags in files.")
        start = time()
        if self.pv_groups:
            num_proc = self.get_par(0, 'num_multi_processes')
            # Setting exif tags to files through one process
            if num_proc == 0:
                self.set_folder_exif_tags_one_proc()
            # Setting exif tags to files through many processes
            elif num_proc > 0:
                self.set_folder_exif_tags_multi_proc(num_proc)

        self.print_log('i', 'stage', f"{self.folder_path}: Finished setting exif tags in files in "
                                     f"{timedelta(seconds=int(time() - start))}")

    @staticmethod
    def execute_exif_tool_mp(exif_data_q: mp.Queue,
                             exif_errors_q: mp.Queue,
                             exif_answer_q: mp.Queue,
                             script_data_tag_name: str) -> typing.NoReturn:
        mp_exif_tool = exiftool.ExifTool()
        mp_exif_tool.run()

        exif_data = True
        while exif_data is not None:
            exif_data = exif_data_q.get()
            if exif_data:

                error = func.set_script_data_and_coord_to_file_exif_tags(mp_exif_tool,
                                                                         exif_data['file_path'],
                                                                         exif_data['new_coord'],
                                                                         exif_data['new_script_data'],
                                                                         script_data_tag_name)
                if error:
                    exif_errors_q.put(f"{exif_data['file_path']}: Multiprocess setting exif tags error: {error}")
                exif_answer_q.put(1)
        exif_answer_q.put(None)
        exif_errors_q.put(None)
        mp_exif_tool.terminate()

    # Set macOS tags in to the files
    def set_macos_tags(self) -> bool:
        self.print_log('i', 'stage', f"{self.folder_path}: Start setting macOS tags in files.")
        for pv_file in self.folder_files.values():
            if not pv_file.set_file_macos_tags():
                return False
        self.print_log('i', 'stage', f"{self.folder_path}: Finished setting macOS tags in files.")
        return True

    def final_check_files_names_before_rename(self) -> bool:
        uniq_set = set()
        repeat_list = []
        for new_name in [pv_file.new_file_name for pv_file in self.folder_files.values()]:
            if new_name in uniq_set:
                repeat_list.append(new_name)
            else:
                uniq_set.add(new_name)
        if repeat_list:
            repeat_dict = {pv_file.file_name: pv_file.new_file_name for
                           pv_file in self.folder_files.values() if
                           pv_file.new_file_name in repeat_list}
            self.print_log('e', 'main', f"{self.folder_path}: Not all new file names are unique: {repeat_dict}")
            return False
        else:
            return True

    # Rename file by adding a technological rename sign self.settings['job_sing']
    def final_rename(self) -> typing.NoReturn:
        self.print_log('i', 'stage', f"{self.folder_path}: Start renaming files. First step.")
        for pv_file in self.folder_files.values():
            pv_file.file_rename()
        self.print_log('i', 'stage', f"{self.folder_path}: Finished renaming files. First step.")

    def print_folder_results(self, results_list: typing.List[PVFile], message: str) -> typing.NoReturn:
        if results_list:
            self.print_log('w', 'result', f"{self.folder_path}: {message} {len(results_list)} files")
            for pv_file in results_list:
                file_name = pv_file.new_file_name if self.check_par('set', 'rename_set') else pv_file.file_name
                self.print_log('w', 'result', f"{self.folder_path}: {message} {file_name}")

    def check_folder_proc_results(self) -> typing.NoReturn:
        """
        Check process result after all actions in folder
        :return:
        """
        self.print_log('i', 'result', f'--- Result checking ---: {self.folder_path}')

        # All files with no address and with coordinates
        if self.check_par('results_check', 'no_address_with_coord'):
            check_list = [pv_file for pv_file in self.folder_files.values() if
                          pv_file.pv_group.coord and not pv_file.pv_group.address.address]
            if check_list:
                self.print_folder_results(check_list, 'No address with coordinates')

        # All files with no UTC datetime
        if self.check_par('results_check', 'no_utc_datetime'):
            check_list = [pv_file for pv_file in self.folder_files.values() if not pv_file.pv_group.utc_datetime]
            if check_list:
                self.print_folder_results(check_list, 'No UTC datetime')

        # All files with no coordinates and with UTC datetime
        if self.check_par('results_check', 'no_coord_with_utc_time'):
            check_list = [pv_file for pv_file in self.folder_files.values() if
                          pv_file.pv_group.utc_datetime and not pv_file.pv_group.coord]
            if check_list:
                self.print_folder_results(check_list, 'No coord with UTC time')

    def get_folder_dt_name_in_groups(self) -> typing.NoReturn:
        for pv_group in self.pv_groups.values():
            pv_group.get_folder_dt_name()

    def get_all_folder_cameras(self) -> typing.NoReturn:
        cams = set([pv_group.camera_key for pv_group in self.pv_groups.values()])
        self.cameras = {c: 'own_geo' if any([pv_group.coord and
                                             not pv_group.coord_source and
                                             pv_group.camera_key == c for pv_group in
                                             self.pv_groups.values()]) else 'no_geo' for c in cams}

        cameras_settings = self.get_par({}, 'cameras')
        if self.cameras and cameras_settings:
            for camera_key in self.cameras.keys():
                if camera_key in cameras_settings.keys() and cameras_settings[camera_key]['geo_info']:
                    self.cameras[camera_key] = cameras_settings[camera_key]['geo_info']
        for camera_key, geo_info in self.cameras.items():
            self.print_log('i', 'stage', f"{self.folder_path}: Found camera: {camera_key} - {geo_info}")

    @staticmethod
    def get_begin_coord_by_first_with_coord(pv_groups: typing.List[PVGroup]) -> typing.NoReturn:
        beginning_groups: typing.List[PVGroup] = []
        for pv_gr in pv_groups:
            if pv_gr.coord:
                if beginning_groups:
                    for group in beginning_groups:
                        group.set_group_data({'coord': pv_gr.coord, 'alt': pv_gr.alt}, 'geo_begin_end',
                                             'first and last groups')
                break
            else:
                beginning_groups.append(pv_gr)


class PVGroup(Settings):
    tf = TimezoneFinder()
    time_get_data_from_file = 0

    def __init__(self,
                 pv_folder: PVFolder,
                 name: str,
                 folder_path: str):

        self.gr_id = ''
        self.pv_folder = pv_folder
        self.name = name
        self.new_name = ''
        self.folder_path = folder_path
        self.folder_dt_name = ''
        self.group_files = []
        self.file_datetime = None
        self.utc_datetime = None
        self.utc_relative_base_time = None
        self.naming_datetime = None
        self.local_datetime = None
        self.local_datetime_type = ''
        self.dt_offset = ''
        self.naming_warning = ''
        self.camera_key = ''
        self.camera_found = False
        self.t_zone = ''
        self.coord = ()
        self.coord_source = ''
        self.alt = 0
        self.dt_source = ''
        self.address = Address()
        self.sort_key = ''
        self.mac_tags_names = []
        self.num = ''
        self.object_tags = []
        self.new_f_name_core = ''

    def add_file_to_group(self, file_path: str, **kwargs: str) -> typing.NoReturn:
        pv_file = PVFile(self, file_path, **kwargs)
        self.group_files.append(pv_file)
        self.get_data_from_file(pv_file)

    def get_data_from_file(self, pv_file: PVFile) -> typing.NoReturn:
        if (not self.file_datetime and pv_file.file_datetime) or \
                (self.file_datetime and self.dt_source != 'exif' and
                 pv_file.file_datetime and self.dt_source == 'exif'):
            self.file_datetime = pv_file.file_datetime
            self.dt_source = pv_file.dt_source

        if not self.camera_key and pv_file.camera_key:
            self.camera_key = pv_file.camera_key
            self.camera_found = pv_file.camera_found

        if not self.coord and pv_file.coord and not pv_file.coord_source:
            self.coord = pv_file.coord
            # self.coord_source = pv_file.coord_source
            self.alt = pv_file.alt

        if self.coord and not self.t_zone:
            self.t_zone = PVGroup.tf.timezone_at(lat=self.coord[0], lng=self.coord[1])

        if pv_file.mac_tags_names:
            self.mac_tags_names = list(set(self.mac_tags_names + pv_file.mac_tags_names))

        if not self.sort_key:
            self.set_group_sort_key()

        if self.gr_id and pv_file.gr_id and self.gr_id != pv_file.gr_id:
            self.print_log('e', 'main', f'Files in the same group have different unique group IDs! {self.name}')
        elif not self.gr_id and pv_file.gr_id:
            self.set_gr_id(pv_file.gr_id)

    def get_folder_dt_name(self) -> typing.NoReturn:
        if self.utc_datetime:
            self.folder_dt_name = self.utc_datetime.strftime(self.get_par('%Y_%m', 'folder_dt_name_format'))
        else:
            self.folder_dt_name = self.file_datetime.strftime(self.get_par('%Y_%m', 'folder_dt_name_format'))

    def manual_shift_group_time(self, time_shift: typing.Dict[str, float]) -> typing.NoReturn:
        # If current folder settings has information about the time difference for a particular photo-device
        # by the value from the time_shift_by_settings -> camera_key parameter or for all files , apply that.
        if 'days' in time_shift and 'hours' in time_shift and 'minutes' in time_shift and 'seconds' in time_shift:
            dt_delta = timedelta(days=time_shift['days'],
                                 hours=time_shift['hours'],
                                 minutes=time_shift['minutes'],
                                 seconds=time_shift['seconds'])
            self.set_group_datetime(self.file_datetime + dt_delta, 'by_hand', 'the folder settings')

    def set_group_coordinates(self,
                              new_coord: typing.Tuple[float, float],
                              alt: float,
                              coord_source: str,
                              source: str) -> typing.NoReturn:
        if coord_source and new_coord:
            self.coord = new_coord
            self.coord_source = coord_source
            self.address.clear_address()
            self.alt = alt
            alt_msg = str(alt) + ' ' if alt else ''
            self.print_log('i', 'coord',
                           f"{self.folder_path}: {self.name} got coordinates {new_coord} {alt_msg}from {source}.")

    def set_group_address(self, new_address: typing.Dict[str, str]) -> typing.NoReturn:
        self.address.set_address(new_address)

    def get_utc_relative_base_time(self) -> typing.NoReturn:
        # Wrong UTC time, but it is needed to create a relative time array to calibrate the time of the pv files.
        self.utc_relative_base_time = pytz.timezone('UTC').localize(self.file_datetime)

    def get_utc_dt_if_empty(self) -> typing.NoReturn:
        if self.t_zone and self.file_datetime and not self.utc_datetime:
            file_datetime_t_zone = pytz.timezone(self.t_zone).localize(self.file_datetime)
            self.set_group_utc_datetime(file_datetime_t_zone.astimezone(pytz.timezone('UTC')),
                                        't_zone and local creation datetime')

    @property
    def lat(self) -> float:
        """Return latitude. """
        return self.coord[0]

    @property
    def lon(self) -> float:
        """Return longitude."""
        return self.coord[1]

    def set_group_datetime(self,
                           new_date_time: datetime,
                           data_type: str,
                           source: str) -> typing.NoReturn:
        dt = self.file_datetime
        self.file_datetime = new_date_time
        self.dt_source = data_type
        self.print_log('i', 'datetime',
                       f"{self.folder_path}: {self.name} got file datetime {dt} -> {new_date_time} from {source}.")

    @dispatch(tuple, str)
    def set_group_t_zone(self,
                         new_coord: typing.Tuple[float, float],
                         source: str) -> str:
        self.t_zone = PVGroup.tf.timezone_at(lat=new_coord[0], lng=new_coord[1])
        self.print_log('i', 't_zone',
                       f"{self.folder_path}: {self.name} got t_zone {self.t_zone} through coordinates from {source}.")
        return self.t_zone

    @dispatch(str, str)
    def set_group_t_zone(self, new_t_zone: str, source: str) -> str:
        self.t_zone = new_t_zone
        self.print_log('i', 't_zone',
                       f"{self.folder_path}: {self.name} got t_zone {self.t_zone} from {source}.")
        return new_t_zone

    def move_group_to_folder(self, new_folder_path: str) -> bool:
        res = True
        for pv_file in self.group_files:
            res &= pv_file.move_file_to_folder(new_folder_path)
        return res

    def clear_group_coord(self) -> typing.NoReturn:
        self.coord = ()
        self.alt = 0
        self.coord_source = ''
        self.address.clear_address()

    def set_group_utc_datetime(self, utc_datetime: datetime, source: str) -> typing.NoReturn:
        utc_dt = self.utc_datetime
        self.utc_datetime = utc_datetime
        self.sort_key = str(utc_datetime)
        self.print_log('i', 'datetime',
                       f"{self.folder_path}: {self.name} got UTC time {utc_dt} -> {self.utc_datetime} from {source}.")

    def set_group_num(self, str_num: str) -> typing.NoReturn:
        self.num = str_num

    def get_new_group_name(self) -> typing.NoReturn:
        name_core_format = self.get_par('', 'name_core_format')
        self.new_f_name_core = self.naming_datetime.strftime(name_core_format)

        for file in self.group_files:
            new_file_name = file.get_new_file_name(self.new_f_name_core, self.num, self.naming_datetime)
            self.new_name = new_file_name if self.name == file.file_name else self.new_name

    def set_group_data(self, group_data, data_type, source) -> typing.NoReturn:
        # coord, file_dt, geo_object, t_zone
        if 'coord' not in group_data and 'geo_object_name' in group_data and self.check_par('get',
                                                                                            'get_coord_by_geo_object'):
            group_data['coord'] = GeoObjects.get_coord_by_tag(group_data['geo_object_name'])
        if 'coord' in group_data and data_type and (not self.coord or self.coord and self.coord_source):
            alt = group_data['alt'] if 'alt' in group_data else 0
            self.set_group_coordinates(group_data['coord'], alt, data_type, source)
            self.set_group_t_zone(group_data['coord'], source)
        elif 'coord' in group_data and self.coord and not self.coord_source:
            self.print_log('w', 'coord', f"{self.folder_path}: {self.name} can't replace original coordinates "
                                         f"{self.coord}")
        elif 't_zone' in group_data and not self.coord:
            self.set_group_t_zone(group_data['t_zone'], source)
        elif 't_zone' in group_data and self.coord:
            self.print_log('w', 't_zone', f"{self.folder_path}: {self.name} can't get t_zone {group_data['t_zone']} "
                                          f"from {source} because of group already has coordinates.")
        if 'file_dt' in group_data:
            self.set_group_datetime(group_data['file_dt'], data_type, source)

        if data_type == 'by_hand' and self.check_par('save_all_by_hand_file_data') and self.pv_folder:
            group_data['camera'] = self.camera_key
            self.pv_folder.manual_data.add_manual_data(self.name, group_data)

    def get_group_data_by_manual_file_tags(self, group_data_by_tag: typing.Dict[str, dict]) -> typing.NoReturn:
        group_data = {}
        for tag in self.mac_tags_names:
            if tag in group_data_by_tag:
                group_data.update(group_data_by_tag[tag])
        if group_data:
            self.set_group_data(group_data, 'by_hand', 'file tags')

    def get_group_object_tags_by_coord(self) -> typing.NoReturn:
        if self.coord and not self.object_tags:
            self.object_tags = GeoObjects.get_object_tags(self.coord)

    def get_group_address_by_coordinates(self) -> typing.NoReturn:
        if self.coord:
            self.address.get_address_by_coordinates(self.coord)
            if self.address.address:
                if 'geo_point' in self.address.address:
                    self.print_log('i', 'address', f"{self.folder_path}: {self.name} No address for coordinates: "
                                                   f"{str(self.coord)}. Use 'geo_point' as address: "
                                                   f"{str(self.address.address)}.")
                else:
                    self.print_log('i', 'address', f"{self.folder_path}: {self.name} Got address: "
                                                   f"{str(self.address.address)}")
            else:
                self.print_log('i', 'address', f"{self.folder_path}: {self.name} No address for coordinates: "
                                               f"{str(self.coord)}")
        else:
            self.address.clear_address()
            self.print_log('i', 'address', f"{self.folder_path}: {self.name} No coordinates - address cleared.")

    def set_group_sort_key(self) -> typing.NoReturn:
        self.sort_key = str(self.utc_datetime) if self.utc_datetime else str(self.file_datetime)

    def set_gr_id(self, gr_id: str) -> typing.NoReturn:
        self.gr_id = gr_id

    def get_new_gr_id(self) -> typing.NoReturn:
        if not self.gr_id:
            self.gr_id = str(uuid.uuid4())

    def get_new_id(self) -> typing.NoReturn:
        self.get_new_gr_id()
        for pv_file in self.group_files:
            pv_file.get_new_f_id()

    def get_local_naming_offset_time(self):
        t_zone_naming = self.get_par('local', 't_zone_naming')
        if self.utc_datetime:
            if self.t_zone:
                self.local_datetime = self.utc_datetime.astimezone(pytz.timezone(self.t_zone)).replace(tzinfo=None)
                self.local_datetime_type = 'utc'
            else:
                self.local_datetime = self.file_datetime
                self.local_datetime_type = 'asis_no_tz'

            if t_zone_naming == 'local':
                self.naming_datetime = self.local_datetime
                if self.local_datetime_type != 'utc':
                    self.print_log('w', 'rename', f"{self.folder_path}: {self.name}  Can't get file name from UTC "
                                                  f"datetime - no t-zone. Named as is.")
                    self.naming_warning = 'name_no_t_zone'
            else:
                self.naming_datetime = self.utc_datetime.astimezone(pytz.timezone(t_zone_naming)).replace(tzinfo=None)
        else:
            self.local_datetime = self.naming_datetime = self.file_datetime
            self.local_datetime_type = 'asis_no_utc'
            self.naming_warning = 'name_no_utc_dt'
            self.print_log('w', 'rename', f"{self.folder_path}: {self.name}  Can't get file name from UTC "
                                          f"datetime - no UTC-time. Named as is.")

        offset = self.local_datetime - self.file_datetime
        if offset:
            self.dt_offset = func.timedelta_to_string(offset)
