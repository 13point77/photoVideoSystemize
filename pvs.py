import argparse
import os
import shutil
import sys
import typing
from os import listdir
from time import time
from collections import Counter
from datetime import timedelta
from os.path import isdir, join, isfile
from exiftool import exiftool
from src import func
from src.geo import GeoObjects, Address, GeoMultiTrack
from src.settings import Settings
from src.structures import PVFolder, PVFile


class PVS(Settings):
    """
    Main class for work with folders with photo / video files or single file.
    """

    def __init__(self, **kwargs: dict):
        if 'manual_settings' in kwargs:
            Settings.set_manual_settings(kwargs['manual_settings'])
        if 'mode_preset_list' in kwargs:
            Settings.set_mode_preset_list(kwargs['mode_preset_list'])

    def new_job_reset(self) -> typing.NoReturn:
        """
        The names of all processed folders are placed in the done_folders_list.txt file.
        If the process is interrupted, we can restart it and parse the unfinished folders.
        """
        done_folders_pickle_file_path = self.get_par('', 'done_folders_pickle_file_path')
        done_folders_txt_file_path = self.get_par('', 'done_folders_txt_file_path')
        if self.get_par(True, 'new_job_reset'):
            func.save_struct_as_pickle_file(done_folders_pickle_file_path, [])
            func.save_struct_as_txt_file(done_folders_txt_file_path, [], 'done_folders')
        else:
            try:
                func.load_pickle_file_as_struct(done_folders_pickle_file_path, [])
            except FileNotFoundError:
                func.save_struct_as_pickle_file(done_folders_pickle_file_path, [])
                func.save_struct_as_txt_file(done_folders_txt_file_path, [], 'done_folders')

    def run_systemize(self, folder_path: str) -> bool:
        """
        Main method which starts the process of systematisation
        :param folder_path: full path of current folder, string
        """
        func.create_new_folder(join(Settings.app_folder, 'data'))
        start_time = time()

        # Activate
        if not self.activate():
            return False

        self.print_log('i', 'main', f'PVS process started.')

        # Depending on the script launch parameter, whether we clear the done_folders_pickle_file_path list or not.
        self.new_job_reset()

        # Load all objects from the local google file.
        GeoObjects.load_google_earth_kml(self.get_par('', 'gogle_geo_object_kml_file_path'))

        # Create object for first folder and start main process
        pv_folder = PVFolder(folder_path)
        pv_folder.run_process_folder()

        timedelta(seconds=int(time() - start_time))
        if PVFile.exif_tool.running:
            PVFile.exif_tool.terminate()
        self.print_log('i', 'main', f'PVS process finished in {timedelta(seconds=int(time() - start_time))}')
        if Address.osm_connection_num:
            self.print_log('i', 'main', f'Made {Address.osm_connection_num} OSM connections')
        return True

    def activate(self) -> bool:
        """
        Loading basic settings, check settings, activate logging. Checking if ExifTools is installed
        """
        log_file_path = join(Settings.app_folder, 'data', 'pvs_report.log')
        Settings.set_logger(log_file_path, 500)

        # Load settings
        if not self.load_settings():
            return False

        if shutil.which('exiftool') is None:
            self.print_log('e', 'main', f'Exiftool is not installed. Visit https://exiftool.org/install.html')
            return False

        settings_log_file_path = str(Settings.get_par('', 'log_file_path'))
        if settings_log_file_path:
            max_log_size_mb = Settings.get_par(100, 'max_log_size_mb')
            Settings.set_logger(settings_log_file_path, max_log_size_mb)
        return True

    def erase_folder_coord_rec(self, folder_path: str, cameras: typing.List[str]) -> typing.NoReturn:
        pv_folder = PVFolder(folder_path)
        pv_folder.build_main_data_structures()
        cameras = [camera.upper() for camera in cameras]
        for pv_file in pv_folder.folder_files.values():
            if pv_file.camera_key.upper() in cameras or 'ALL' in cameras:
                pv_file.set_new_sd_and_coord_for_erase_coord()
        pv_folder.set_folder_exif_tags()
        if self.get_par(True, 'recurrent'):
            self.recurrent_run(self.erase_folder_coord_rec, folder_path, cameras)

    def erase_file_coord(self, file_path: str) -> typing.NoReturn:
        pv_file = PVFile(None, file_path)
        pv_file.set_new_sd_and_coord_for_erase_coord()
        func.set_script_data_and_coord_to_file_exif_tags(PVFile.exif_tool,
                                                         pv_file.file_path,
                                                         pv_file.new_coord,
                                                         pv_file.new_script_data,
                                                         self.get_par('XMP:UserComment', 'script_data_tag_name'))
        PVFile.exif_tool.terminate()

    @staticmethod
    def erase_exif(file_path: str) -> typing.NoReturn:
        pv_file = PVFile(None, file_path)
        pv_file.clear_all_file_exif_tags()
        PVFile.exif_tool.terminate()

    def erase_folder_exif_rec(self, folder_path: str, cameras: typing.List[str]) -> typing.NoReturn:
        pv_folder = PVFolder(folder_path)
        pv_folder.build_main_data_structures()
        cameras = [camera.upper() for camera in cameras]
        for pv_file in pv_folder.folder_files.values():
            if pv_file.camera_key.upper() in cameras or 'ALL' in cameras:
                pv_file.clear_all_file_exif_tags()
        if self.get_par(True, 'recurrent'):
            self.recurrent_run(self.erase_folder_exif_rec, folder_path, cameras)

    def print_exif_tags_file(self, file_path: str, pickle_file_path: str) -> typing.NoReturn:
        pickle_data = {}
        if pickle_file_path:
            if pickle_file_path.upper() in ['D', 'DEFAULT']:
                pickle_file_path = pvs_tool.get_par('', 'files_data_pickle_file_path')
            pickle_data = func.load_pickle_file_as_struct(pickle_file_path, {}) if pickle_file_path else {}

        if pickle_data:
            exif_tags = pickle_data.get(file_path, {}).get('exif_tags', {})
            sd_data = func.get_dict(str(exif_tags.get(PVS.get_par('', 'script_data_tag_name'), {})))
        else:
            if func.file_path(scr_par.path):
                pv_file = PVFile(None, file_path)
                sd_data = pv_file.script_data
                exif_tags = pv_file.exif_tags
            else:
                return

        if sd_data:
            self.print_log('i', 'tool', '-------script data-------')
            for key, item in sd_data.items():
                self.print_log('i', 'tool', f" {key} = {item}")
        if exif_tags:
            self.print_log('i', 'tool', '-------exif-------')
            for key, item in exif_tags.items():
                self.print_log('i', 'tool', f" {key} = {item}")
        else:
            self.print_log('w', 'tool', ' No EXIF information.')
        PVFile.exif_tool.terminate()

    def files_data2pickle(self, folder_path: str, pickle_file_path: str) -> typing.NoReturn:
        if not pickle_file_path or pickle_file_path.upper() in ['D', 'DEFAULT']:
            pickle_file_path = pvs_tool.get_par('', 'files_data_pickle_file_path')
        files_data = {}
        self.files_data2pickle_rec(folder_path, files_data)
        func.save_struct_as_pickle_file(pickle_file_path, files_data)

    def files_data2pickle_rec(self,
                              folder_path: str,
                              files_data: typing.Dict[str, dict]) -> typing.NoReturn:
        pv_folder = PVFolder(folder_path)
        pv_folder.build_main_data_structures()
        for pv_file in pv_folder.folder_files.values():
            files_data[pv_file.file_path] = {"group_name": pv_file.pv_group.name,
                                             "file_path": pv_file.file_path,
                                             "script_data": pv_file.script_data,
                                             "coord": pv_file.coord,
                                             "exif_tags": pv_file.exif_tags}
        if self.get_par(True, 'recurrent'):
            self.recurrent_run(self.files_data2pickle_rec, folder_path, files_data)

    # Get unique values of datasets about files. Can be done recursively for all subfolders.
    # The function for getting data from a file is data_func, which returns the required data.
    def get_files_report(self,
                         folder_path: str,
                         data_func: typing.Callable,
                         pickle_file_path: str,
                         report_type: str,
                         *args: typing.Any) -> typing.NoReturn:
        stat_data = []
        pickle_data = {}
        if pickle_file_path:
            if pickle_file_path.upper() in ['D', 'DEFAULT']:
                pickle_file_path = pvs_tool.get_par('', 'files_data_pickle_file_path')
            pickle_data = func.load_pickle_file_as_struct(pickle_file_path, {}) if pickle_file_path else {}

        if pickle_data:
            for file_path, file_data in pickle_data.items():
                func.add_to_list(stat_data, data_func(file_data, *args))
        else:
            if func.dir_path(folder_path):
                self.get_files_data_rec(folder_path, data_func, stat_data, *args)
            else:
                return

        if stat_data:
            if report_type.upper() in ['U', 'UNIQUE']:
                stat_data_lists = [data[1] for data in stat_data if data]
                stat = Counter(stat_data_lists)
                stat = {st: num for st, num in sorted(stat.items(), key=lambda li: li[0].split(' ')[0])}
                for st, num in stat.items():
                    self.print_log('i', 'tool', str(num) + ': ' + st)
            elif report_type.upper() in ['ALL', 'A']:
                stat_data = [data for data in stat_data if data]
                stat_data = sorted(stat_data, key=lambda li: li[1])
                for f_data in stat_data:
                    self.print_log('i', 'tool', f'{f_data[1]}: {f_data[0]}')
        else:
            self.print_log('i', 'tool', 'No data for report.')

    def get_files_data_rec(self,
                           folder_path: str,
                           data_func: typing.Callable,
                           stat_data: typing.List[typing.Tuple[str, str]],
                           *args: typing.Any) -> typing.NoReturn:
        pv_folder = PVFolder(folder_path)
        pv_folder.build_main_data_structures()
        for pv_file in pv_folder.folder_files.values():
            func.add_to_list(stat_data, data_func(pv_file, *args))
        if self.get_par(True, 'recurrent'):
            self.recurrent_run(self.get_files_data_rec, folder_path, data_func, stat_data, *args)

    @staticmethod
    def data_func_get_sd_all_tags(data_source: typing.Union[dict, PVFile]) -> \
            typing.Union[typing.List[typing.Tuple[str, str]],
                         typing.Tuple[str, str]]:
        exif_tags = func.get_attr(data_source, 'exif_tags')
        sd_tag_val = []
        if exif_tags:
            sd_data = func.get_dict(str(exif_tags.get(PVS.get_par('', 'script_data_tag_name'), {})))
            if sd_data:
                file_path = func.get_attr(data_source, 'file_path')
                for sd_tag, sd_val in sd_data.items():
                    if not PVS.get_sd_tag_val(sd_tag, 'datetime', sd_val, file_path, sd_tag_val) and \
                            not PVS.get_sd_tag_val(sd_tag, 'address', sd_val, file_path, sd_tag_val) and \
                            not PVS.get_sd_tag_val(sd_tag, 'first_dt', sd_val, file_path, sd_tag_val) and \
                            not PVS.get_sd_tag_val(sd_tag, 'utc_dt', sd_val, file_path, sd_tag_val) and \
                            not PVS.get_sd_tag_val(sd_tag, 't_zone', sd_val, file_path, sd_tag_val) and \
                            not PVS.get_sd_tag_val(sd_tag, 'g_album_id', sd_val, file_path, sd_tag_val) and \
                            not PVS.get_sd_tag_val(sd_tag, 'g_media_id', sd_val, file_path, sd_tag_val) and \
                            not PVS.get_sd_tag_val(sd_tag, 'camera', sd_val, file_path, sd_tag_val) and \
                            not PVS.get_sd_tag_val(sd_tag, 'dt', sd_val, file_path, sd_tag_val):
                        sd_tag_val.append((file_path, str(sd_tag + '=' + str(sd_val))))
            if sd_tag_val:
                return sd_tag_val
            else:
                return [(func.get_attr(data_source, 'file_path'), 'no_sd_data')]
        else:
            return [(func.get_attr(data_source, 'file_path'), 'no_exif_data')]

    @staticmethod
    def get_sd_tag_val(sd_tag, ref_tag, sd_val, file_path, sd_tag_val):
        if sd_tag == ref_tag and sd_val:
            sd_tag_val.append((file_path, ref_tag + '=val'))
            return True
        elif sd_tag == ref_tag and sd_val is None:
            sd_tag_val.append((file_path, ref_tag + '=None'))
            return True
        return False

    @staticmethod
    def data_func_get_cam_data(data_source: typing.Union[dict, PVFile]) -> \
            typing.Union[typing.List[typing.Tuple[str, str]],
                         typing.Tuple[str, str]]:
        exif_tags = func.get_attr(data_source, 'exif_tags')
        cam_info = PVFile.get_file_camera_key(PVS.get_par([], 'EXIF_camera_id_tags_names'),
                                              PVS.get_par({}, 'cameras'),
                                              exif_tags)
        camera_found, camera_key, camera_full_key = cam_info
        return [(func.get_attr(data_source, 'file_path'), camera_full_key)]

    @staticmethod
    def data_func_get_cam_not(data_source: typing.Union[dict, PVFile]) -> \
            typing.Union[typing.List[typing.Tuple[str, str]],
                         typing.Tuple[str, str]]:
        exif_tags = func.get_attr(data_source, 'exif_tags')
        cam_info = PVFile.get_file_camera_key(PVS.get_par([], 'EXIF_camera_id_tags_names'),
                                              PVS.get_par({}, 'cameras'),
                                              exif_tags)
        camera_found, camera_key, camera_full_key = cam_info
        if camera_found:
            return [(func.get_attr(data_source, 'file_path'), 'camera_found')]
        else:
            return [(func.get_attr(data_source, 'file_path'), camera_full_key)]

    @staticmethod
    def data_func_get_cam_ok(data_source: typing.Union[dict, PVFile]) -> \
            typing.Union[typing.List[typing.Tuple[str, str]],
                         typing.Tuple[str, str]]:
        exif_tags = func.get_attr(data_source, 'exif_tags')
        cam_info = PVFile.get_file_camera_key(PVS.get_par([], 'EXIF_camera_id_tags_names'),
                                              PVS.get_par({}, 'cameras'),
                                              exif_tags)
        camera_found, camera_key, camera_full_key = cam_info
        if camera_found:
            return [(func.get_attr(data_source, 'file_path'), camera_key)]
        else:
            return [(func.get_attr(data_source, 'file_path'), 'camera_not_found')]

    @staticmethod
    def data_func_get_exif_by_smpl(data_source: typing.Union[dict, PVFile], samples: list):
        tags = []
        exif_tags = func.get_attr(data_source, 'exif_tags')
        for sample in samples:
            for tag in exif_tags:
                if sample in tag:
                    tags.append((func.get_attr(data_source, 'file_path'), tag))
        tags = tags if tags else [(func.get_attr(data_source, 'file_path'), 'empty')]
        return tags

    def rebuild_gpx(self, obj_path, new_gpx_file_name, distance_delta, less_dist_time_delta, merge_flag):
        distance_delta = self.get_par(1000, 'gpx_track_rebuild', 'distance_delta') \
            if distance_delta is None else distance_delta
        less_dist_time_delta = self.get_par(21600, 'gpx_track_rebuild', 'less_dist_time_delta') \
            if less_dist_time_delta is None else less_dist_time_delta
        merge_flag = self.get_par(False, 'gpx_track_rebuild', 'merge') if merge_flag is None else merge_flag
        gpx_multi_track = GeoMultiTrack()
        if os.path.isdir(obj_path):
            new_gpx_file_name = self.get_par('_track.gpx', 'gpx_track_rebuild', 'new_gpx_file_name') \
                if new_gpx_file_name is None else new_gpx_file_name
            new_gpx_file_path = join(obj_path, new_gpx_file_name)
            gpx_multi_track.load_gpx_folder(obj_path)

        else:  # os.path.isfile(obj_path)
            new_gpx_file_name = '_re_' + os.path.split(obj_path)[1] if new_gpx_file_name is None else new_gpx_file_name
            new_gpx_file_path = join(os.path.split(obj_path)[0], new_gpx_file_name)
            gpx_multi_track.load_gpx_file(obj_path)

        gpx_multi_track.rebuild_multi_track(distance_delta, less_dist_time_delta, merge_flag)
        gpx_multi_track.save_multi_track(new_gpx_file_path)

    @staticmethod
    def update_address_cache():
        Address.update_address_cache()

    def all_file_types(self, folder_path, target_folder_path):
        target_folder_path = target_folder_path if target_folder_path else pvs_tool.get_par('', 'all_types_folder_path')
        if target_folder_path:
            media_types_folder_path = join(target_folder_path, 'media_files')
            add_types_folder_path = join(target_folder_path, 'add_files')
            not_settings_types_folder_path = join(target_folder_path, 'not_in_settings')
            func.create_new_folder(target_folder_path)
            func.create_new_folder(media_types_folder_path)
            func.create_new_folder(add_types_folder_path)
            func.create_new_folder(not_settings_types_folder_path)
            file_types = {}
            self.all_file_types_rec(folder_path, file_types)
            self.print_counter('')
            if file_types:
                media_types = self.get_par([], 'media_types')
                add_types = self.get_par([], 'add_types')
                for ft, file_path in file_types.items():
                    if ft in media_types:
                        self.print_counter(f'Copying {file_path} to the {media_types_folder_path} folder.')
                        shutil.copy2(file_path, media_types_folder_path)
                    elif ft in add_types:
                        self.print_counter(f'Copying {file_path} to the {add_types_folder_path} folder.')
                        shutil.copy2(file_path, add_types_folder_path)
                    else:
                        self.print_counter(f'Copying {file_path} to the {not_settings_types_folder_path} folder.')
                        shutil.copy2(file_path, not_settings_types_folder_path)
                self.print_counter('')

    def all_file_types_rec(self, folder_path, file_types):
        self.print_counter(f'Searching all file types. Folder: {folder_path}')
        for file in [file for file in listdir(folder_path) if isfile(join(folder_path, file))]:
            ext = file.split('.')[-1].upper()
            if ext not in file_types.keys():
                file_types[ext] = join(folder_path, file)
        if self.get_par(True, 'recurrent'):
            self.recurrent_run(self.all_file_types_rec, folder_path, file_types)

    def recurrent_run(self, method, folder_path, *args):
        ignore_sing = self.get_par('', 'ignore_sing')
        ignor_sign_len = len(ignore_sing)
        for step_folder in [folder for folder in listdir(folder_path) if isdir(join(folder_path, folder))]:
            if (len(step_folder) >= ignor_sign_len and step_folder[:ignor_sign_len] != ignore_sing) or not ignore_sing:
                method(join(folder_path, step_folder), *args)


def create_parser():
    parser = argparse.ArgumentParser()
    subparsers = parser.add_subparsers(dest='command')

    parser.add_argument('-version', '-v', action='store_true')  # tool

    # Systematization command parser.
    sys_parser = subparsers.add_parser('sys')
    sys_parser.add_argument('path')
    sys_parser.add_argument('-new', action='store_true')
    sys_parser.add_argument('-con', action='store_true')
    sys_parser.add_argument('-rec', action='store_true')
    sys_parser.add_argument('-rec_all', action='store_true')
    sys_parser.add_argument('-no_rec', action='store_true')
    sys_parser.add_argument('-mode', nargs='+', type=str, default='')

    # Tool command parser.
    # Common settings
    tool_parser = subparsers.add_parser('tool')
    tool_parser.add_argument('path', nargs='?')  # parameter
    tool_parser.add_argument('-rec', action='store_true')  # parameter
    tool_parser.add_argument('-rec_all', action='store_true')  # parameter
    tool_parser.add_argument('-no_rec', action='store_true')  # parameter
    tool_parser.add_argument('-cameras', '-cams', nargs='+', default=['All'])  # parameter
    tool_parser.add_argument('-mode', nargs='+', type=str, default='')

    # Tools
    tool_parser.add_argument('-exif', action='store_true')  # tool

    tool_parser.add_argument('-add_exif_tag', '-aet', nargs=2)  # tool

    tool_parser.add_argument('-del_coord', action='store_true')  # tool

    tool_parser.add_argument('-erase_exif', action='store_true')  # tool

    tool_parser.add_argument('-gpx_rebuild', '-gpx_re', action='store_true')  # tool
    tool_parser.add_argument('-gpx_d', type=int)  # parameter
    tool_parser.add_argument('-gpx_t_less', type=int)  # parameter
    tool_parser.add_argument('-gpx_f', type=str)  # parameter
    tool_parser.add_argument('-gpx_merge', action='store_true', default=None)  # parameter

    tool_parser.add_argument('-update_address_cache', '-upd_cache', action='store_true')  # tool

    tool_parser.add_argument('-tzones', action='store_true')  # tool

    tool_parser.add_argument('-data2pickle', '-d2p', action='store_true')  # tool
    tool_parser.add_argument('-pickle_file_path', '-pf', type=str, nargs='?')  # parameter

    tool_parser.add_argument('-all_file_types', '-at', action='store_true')  # tool

    # Tools. Reports.
    # Common reports settings
    tool_parser.add_argument('-report_type', '-rt', choices=['all', 'a', 'unique', 'u'], default='u')  # parameter
    tool_parser.add_argument('-target_folder_path', '-t_folder', type=str)  # parameter

    # Reports
    tool_parser.add_argument('-sd_all_tags', action='store_true')  # tool
    tool_parser.add_argument('-cam_data', action='store_true')  # tool
    tool_parser.add_argument('-cam_not', action='store_true')  # tool
    tool_parser.add_argument('-cam_ok', action='store_true')  # tool
    tool_parser.add_argument('-exif_tags', nargs='+', type=str, default='')  # tool

    return parser


if __name__ == '__main__':
    # Script parameters
    parameter_parser = create_parser()
    scr_par = parameter_parser.parse_args(sys.argv[1:])
    # Manual settings
    params = {}

    if scr_par.version:
        print('photoVideoSystemize Version 1.01')

    if scr_par.command == 'sys':
        run_flag = func.set_man_flag(params, 'new_job_reset',
                                     (scr_par.new, '-new', True),
                                     (scr_par.con, '-con', False))
        run_flag &= func.set_man_flag(params, 'recurrent',
                                      (scr_par.rec, '-rec', True),
                                      (scr_par.rec_all, '-rec_all', True),
                                      (scr_par.no_rec, '-no_rec', False))
        if run_flag and func.dir_path(scr_par.path):
            app = PVS(manual_settings=params, mode_preset_list=scr_par.mode)
            app.run_systemize(scr_par.path)

    elif scr_par.command == 'tool':
        run_flag = func.set_man_flag(params, 'recurrent',
                                     (scr_par.rec, '-rec', True),
                                     (scr_par.rec_all, '-rec_all', True),
                                     (scr_par.no_rec, '-no_rec', False))
        run_flag &= func.set_man_flag(params, 'ignore_sing',
                                      (scr_par.rec_all, '-rec_all', ''))

        # Print file EXIF tags
        if scr_par.exif:
            pvs_tool = PVS()
            if pvs_tool.activate():
                pvs_tool.print_exif_tags_file(scr_par.path, scr_par.pickle_file_path)

        # rebuild GPX track files
        elif scr_par.gpx_rebuild:
            pvs_tool = PVS()
            if pvs_tool.activate():
                pvs_tool.rebuild_gpx(scr_par.path, scr_par.gpx_f, scr_par.gpx_d, scr_par.gpx_t_less, scr_par.gpx_merge)

        # Manual update address cache
        elif scr_par.update_address_cache:
            pvs_tool = PVS()
            if pvs_tool.activate():
                pvs_tool.update_address_cache()

        # Print all available t-zones
        elif scr_par.tzones:
            func.print_all_t_zones()

        # Manual add EXIF tag
        elif scr_par.add_exif_tag:
            if func.file_path(scr_par.path):
                mp_exif_tool = exiftool.ExifTool()
                mp_exif_tool.run()
                func.set_tag_to_file_exif_tags(mp_exif_tool, scr_par.path, scr_par.add_exif_tag)
                mp_exif_tool.terminate()

        # Erase coordinates from file or from folder by camera
        elif run_flag and scr_par.del_coord:
            pvs_tool = PVS(manual_settings=params)
            if pvs_tool.activate():
                if os.path.isfile(scr_par.path):
                    pvs_tool.erase_file_coord(scr_par.path)
                elif os.path.isdir(scr_par.path):
                    pvs_tool.erase_folder_coord_rec(scr_par.path, scr_par.cameras)

        # Erase coordinates from file or from folder by camera
        elif run_flag and scr_par.erase_exif:
            pvs_tool = PVS(manual_settings=params)
            if pvs_tool.activate():
                if os.path.isfile(scr_par.path):
                    pvs_tool.erase_exif(scr_par.path)
                elif os.path.isdir(scr_par.path):
                    pvs_tool.erase_folder_exif_rec(scr_par.path, scr_par.cameras)

        # Get info from files in folder and save in pickle file. This pickle file can be used in another tools.
        elif run_flag and scr_par.data2pickle:
            if func.dir_path(scr_par.path):
                pvs_tool = PVS(manual_settings=params, mode_preset_list=scr_par.mode)
                if pvs_tool.activate():
                    pvs_tool.files_data2pickle(scr_par.path, scr_par.pickle_file_path)

        # Print script data statistic
        elif run_flag and scr_par.sd_all_tags:
            pvs_tool = PVS(manual_settings=params, mode_preset_list=scr_par.mode)
            if pvs_tool.activate():
                pvs_tool.get_files_report(scr_par.path,
                                          pvs_tool.data_func_get_sd_all_tags,
                                          scr_par.pickle_file_path,
                                          scr_par.report_type)

        # Print camera_key statistic
        elif run_flag and scr_par.cam_data:
            pvs_tool = PVS(manual_settings=params)
            if pvs_tool.activate():
                pvs_tool.get_files_report(scr_par.path,
                                          pvs_tool.data_func_get_cam_data,
                                          scr_par.pickle_file_path,
                                          scr_par.report_type)

        # Print all unknown cameras
        elif run_flag and scr_par.cam_not:
            pvs_tool = PVS(manual_settings=params)
            if pvs_tool.activate():
                pvs_tool.get_files_report(scr_par.path,
                                          pvs_tool.data_func_get_cam_not,
                                          scr_par.pickle_file_path,
                                          scr_par.report_type)

        # Print all unknown cameras
        elif run_flag and scr_par.cam_ok:
            pvs_tool = PVS(manual_settings=params)
            if pvs_tool.activate():
                pvs_tool.get_files_report(scr_par.path,
                                          pvs_tool.data_func_get_cam_ok,
                                          scr_par.pickle_file_path,
                                          scr_par.report_type)

        # Print EXIF tags by sample statistic
        elif run_flag and scr_par.exif_tags:
            pvs_tool = PVS(manual_settings=params)
            if pvs_tool.activate():
                pvs_tool.get_files_report(scr_par.path,
                                          pvs_tool.data_func_get_exif_by_smpl,
                                          scr_par.pickle_file_path,
                                          scr_par.report_type,
                                          scr_par.exif_tags)

        # Copy one file for each file type to the folder
        elif run_flag and scr_par.all_file_types:
            if func.dir_path(scr_par.path):
                pvs_tool = PVS(manual_settings=params)
                if pvs_tool.activate():
                    pvs_tool.all_file_types(scr_par.path, scr_par.target_folder_path)
