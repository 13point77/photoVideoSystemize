import logging
import typing
from logging.handlers import RotatingFileHandler
import os
import platform
import shutil
import sys
import pytz
import multiprocessing as mp
from datetime import datetime
from os.path import join
from pathlib import Path

from src import func


class Settings:
    settings = {}
    manual_settings = {}
    mode_preset_list = []
    app_folder = ''
    app_log = None

    @staticmethod
    def set_manual_settings(man_settings) -> typing.NoReturn:
        Settings.manual_settings = man_settings

    @staticmethod
    def set_mode_preset_list(mode_preset_list) -> typing.NoReturn:
        if mode_preset_list:
            Settings.mode_preset_list = mode_preset_list

    @staticmethod
    def transfer_manual_settings_to_settings() -> typing.NoReturn:
        # Overwrite settings by manual settings
        for param in Settings.manual_settings.keys():
            Settings.settings[param] = Settings.manual_settings[param]

    @staticmethod
    def get_par(none_value: typing.Any, *args: str) -> typing.Any:
        if not args:
            raise "Used method get_par without default value!"
        try:
            parameter = Settings.settings
            if args:
                for par in args:
                    if par in parameter:
                        parameter = parameter[par]
                    else:
                        parameter = none_value
            else:
                parameter = none_value
            return parameter
        except TypeError:
            return none_value

    @staticmethod
    def check_par(*args: typing.Union[str, list, tuple, dict]) -> bool:
        try:
            parameter = Settings.settings
            if args:
                for par in args[:-1]:
                    if par in parameter:
                        parameter = parameter[par]
                    else:
                        return False
                if type(parameter) in (list, tuple, dict):
                    if type(args[-1]) in (list, tuple):
                        return any(item in parameter for item in args[-1])
                    else:
                        return args[-1] in parameter
                else:
                    return args[-1] == parameter
        except TypeError:
            return False
        return False

    @staticmethod
    def no_empty_par(*args: str) -> bool:
        try:
            parameter = Settings.settings
            if args:
                for par in args[:-1]:
                    if par in parameter:
                        parameter = parameter[par]
                    else:
                        return False
                return bool(parameter[args[-1]]) or parameter[args[-1]] == 0
        except TypeError:
            return False
        except KeyError:
            return False
        return False

    @staticmethod
    def set_logger(log_file_path: str, size_mb: int) -> typing.NoReturn:
        log_formatter = logging.Formatter('%(levelname)s %(message)s')
        max_b_size = size_mb * 1024 * 1024
        if Settings.app_log and Settings.app_log.handlers:
            Settings.app_log.removeHandler(Settings.app_log.handlers[0])
        handler = RotatingFileHandler(log_file_path,
                                      maxBytes=max_b_size,
                                      backupCount=10)
        handler.setFormatter(log_formatter)
        handler.setLevel(logging.INFO)

        Settings.app_log = logging.getLogger('root')
        Settings.app_log.setLevel(logging.INFO)

        Settings.app_log.addHandler(handler)
        # logging.basicConfig(filename=log_file_path, level=logging.INFO)

    @staticmethod
    def load_settings(*args: str) -> bool:
        Settings.app_folder = os.path.split(sys.argv[0])[0] if sys.argv else ''

        # Load settings from file
        settings_file_path = join(Settings.app_folder, 'pvs_settings.json')
        Settings.settings = func.load_txt_file_as_struct(settings_file_path, {})
        if not Settings.settings:
            Settings.print_log('w', 'main', f"Can't get settings from file {settings_file_path}")
            return False

        # Checking if the settings are correct.
        if not Settings.check_settings('Settings',
                                       Settings.gen_settings_template(),
                                       Settings.settings):
            Settings.print_log('w', 'main', f'Process was interrupted because of incorrect settings.')
            return False

        # Check OS
        if not Settings.get_os_alias():
            return False

        # If some settings are empty, get default values
        Settings.get_default_settings_values()

        # If we have folder path, load folder settings and update main settings
        if Settings.mode_preset_list:
            mode_preset_file_path = join(Settings.app_folder, 'pvs_mode_preset.json')
            mode_presets: dict = func.load_txt_file_as_struct(mode_preset_file_path, {})
            if not mode_presets:
                Settings.print_log('w', 'main', f"Can't get mode settings from file {mode_preset_file_path}")
                return False
            for mode in Settings.mode_preset_list:
                if mode not in mode_presets.keys():
                    Settings.print_log('w', 'main', f"Can't find mode settings in file {mode_preset_file_path}")
                    return False
                if not Settings.load_additional_settings(mode_presets[mode], f"'{mode}' mode"):
                    return False

        # If we have folder path, load folder settings and update main settings
        if args:
            folder_settings_file_path = join(args[0], Settings.get_par('', 'folder_settings_file'))
            folder_settings = func.load_txt_file_as_struct(folder_settings_file_path, {})
            if not Settings.load_additional_settings(folder_settings, args[0]):
                return False

        # After all updates, apply the settings with manual settings from the script parameters
        Settings.transfer_manual_settings_to_settings()

        # Check if number of processes more than real number of cores
        Settings.check_real_core_num()
        return True

    @staticmethod
    def check_real_core_num() -> typing.NoReturn:
        num_multi_processes = Settings.get_par(0, 'num_multi_processes')
        if num_multi_processes > 1:
            real_core_num = mp.cpu_count()
            if num_multi_processes > real_core_num:
                Settings.print_log('w', 'main', f"Settings parameter 'num_multi_processes' was reduced to real number "
                                                f"of cores: {real_core_num}")
                real_core_num = 0 if real_core_num == 1 else real_core_num
                Settings.set_settings_parameter('num_multi_processes', real_core_num)

    @staticmethod
    def load_additional_settings(add_settings: dict, type_settings: str) -> bool:
        # Checking if the current settings are correct.
        if add_settings:
            if not Settings.check_settings(f"{type_settings} settings",
                                           Settings.gen_additional_settings_template(),
                                           add_settings):
                Settings.print_log('w', 'main', f'Process was interrupted - incorrect {type_settings} settings.')
                return False

            # Paste all settings into main settings
            for param in add_settings.keys():
                Settings.set_settings_parameter(param, add_settings[param])
        return True

    @staticmethod
    def set_settings_parameter(param: str, value: typing.Any) -> typing.NoReturn:
        Settings.settings[param] = value

    @staticmethod
    def get_os_alias() -> bool:
        osn = platform.system()
        os_dict_lower = {'darwin': 'macOS', 'windows': 'windows', 'linux': 'linux'}
        if osn.lower() in os_dict_lower:
            Settings.set_settings_parameter('os', os_dict_lower[osn.lower()])
        else:
            Settings.print_log("e", 'main', "(get_os_alias) Can't determine os: " + osn + '.')
            return False
        return True

    @staticmethod
    def get_default_settings_values() -> typing.NoReturn:
        def_sett = {"done_folders_txt_file_path": join(Settings.app_folder, 'data', 'pvs_done_folders_list.txt'),
                    "done_folders_pickle_file_path": join(Settings.app_folder, 'data', 'pvs_done_folders_list.pickle'),
                    "addr_cache_pickle_file_path": join(Settings.app_folder, 'data', 'pvs_address_cache.pickle'),
                    "files_data_pickle_file_path": join(Settings.app_folder, 'data', 'pvs_files_data.pickle'),
                    "all_types_folder_path": join(Settings.app_folder, 'data', 'pvs_all_file_types'),
                    "log_file_path": join(Settings.app_folder, 'data', 'pvs_report.log'),
                    "folder_settings_file": "_pvs_folder_settings.json",
                    "script_data_tag_name": "XMP:UserComment",
                    "manual_data_file": "_manual_data.txt",
                    "split_sign": "|",
                    "job_sing": "-_t_-",
                    "t_zone_naming": "local",
                    "manual_date_time_format": "%Y_%m_%d-%H_%M_%S",
                    "folder_dt_name_format": "%Y_%m",
                    "gogle_geo_object_kml_file_path": join(Path.home(),
                                                           "Library/Application Support/Google Earth/myplaces.kml")
                    }
        if Settings.settings and def_sett:
            for def_parameter, def_value in def_sett.items():
                if def_parameter in Settings.settings.keys():
                    if not str(Settings.settings[def_parameter]):
                        Settings.settings[def_parameter] = def_value
                else:
                    Settings.settings[def_parameter] = def_value

    @staticmethod
    def gen_settings_template() -> dict:
        # (type or 'val' , structure or None, boolean must be specified)
        mac_tag_template = ('val',
                            {"active": (bool, None, True),
                             "prefix": (str, None, True),
                             "color": (str, tuple(func.MACOS_TAGS_COLORS.keys()), True)},
                            True)
        file_type_pattern = ('val',
                             {"|str_from_settings|": ('val',
                                                      {"prefix": (str, None, True),
                                                       "suffix": (str, None, True),
                                                       "ext": (str, None, True)},
                                                      True)},
                             False)
        all_t_zones_plus = [z for z in pytz.all_timezones_set]
        all_t_zones_plus.append('local')

        return {
            "version": (str, ["1.01"], True),
            "new_job_reset": (bool, None, True),
            "recurrent": (bool, None, True),
            "num_multi_processes": (int, None, True),
            "folder_dt_name_format": (str, None, True),
            "name_core_format": (str, None, True),
            "new_name_order": (list, ("num", "prefix", "name_core", "suffix"), True),
            "t_zone_naming": (str, tuple(all_t_zones_plus), True),
            "new_name_case": (str, ["lower", "upper", "as_is"], True),
            "sort_files": (bool, None, True),
            "path_names_phrase_pattern": (str, None, True),
            "gogle_geo_object_kml_file_path": (str, None, True),
            "log_file_path": (str, None, True),
            "max_log_size_mb": (int, None, True),
            "done_folders_txt_file_path": (str, None, True),
            "done_folders_pickle_file_path": (str, None, True),
            "files_data_pickle_file_path": (str, None, True),
            "addr_cache_pickle_file_path": (str, None, True),
            "all_types_folder_path": (str, None, True),
            "exist_pv_gpx_track_file": (str, None, True),
            "create_exist_track": (bool, None, True),
            "split_exist_track_by_cameras": (bool, None, True),
            "folder_settings_file": (str, None, True),
            "manual_data_file": (str, None, True),
            "split_sign": (str, None, True),
            "manual_date_time_format": (str, None, True),
            "save_all_by_hand_file_data": (bool, None, True),
            "osm_user_agent": (str, None, True),
            "ignore_sing": (str, None, True),
            "media_types": (list, str, True),
            "add_types": (list, str, True),
            "masters": file_type_pattern,
            "slaves": file_type_pattern,
            "additions": file_type_pattern,
            "non_pair": ('val',
                         {"prefix": (str, None, True),
                          "suffix": (str, None, True)},
                         False),
            "group_pattern_case_sensitive": (bool, None, True),
            "job_sing": (str, None, True),
            "tag_by_hand_info_begin": (str, None, True),
            "mactag_keep_signs": (list, str, True),
            "mactag_coord_source": mac_tag_template,
            "mactag_no_coord": mac_tag_template,
            "mactag_address_source": mac_tag_template,
            "mactag_folder_dt_format": mac_tag_template,
            "mactag_path": mac_tag_template,
            "mactag_geo_object": mac_tag_template,
            "mactag_address": mac_tag_template,
            "mactag_camera_key": mac_tag_template,
            "mactag_no_address": mac_tag_template,
            "mactag_no_utc_datetime": mac_tag_template,
            "mactag_no_t_zone": mac_tag_template,
            "mactag_geo_point_address": mac_tag_template,
            "mactag_first_datetime": mac_tag_template,
            "mactag_creation_datetime": mac_tag_template,
            "mactag_utc_datetime": mac_tag_template,
            "mactag_naming_datetime": mac_tag_template,
            "mactag_naming_datetime_warning": mac_tag_template,
            "mactag_sort_key": mac_tag_template,
            "mactag_order": (list, [
                "mactag_address",
                "mactag_coord_source",
                "mactag_folder_dt_format",
                "mactag_path",
                "mactag_geo_object",
                "mactag_address_source",
                "mactag_no_address",
                "mactag_geo_point_address",
                "mactag_no_coord",
                "mactag_no_t_zone",
                "mactag_no_utc_datetime",
                "mactag_utc_datetime",
                "mactag_sort_key",
                "mactag_camera_key",
                "mactag_first_datetime",
                "mactag_creation_datetime",
                "mactag_no_exif_dt",
                "mactag_naming_datetime",
                "mactag_datetime_offset",
                "mactag_naming_datetime_warning"], True),

            "EXIF_create_dt_tag_name": (list, str, True),
            "script_data_tag_name": (str, None, True),
            "EXIF_camera_id_tags_names": (list, str, True),
            "cameras": ('val',
                        {"|str_from_settings|": ('val',
                                                 {"synthetic_ids": (list, str, True),
                                                  "geo_info": (str, ["own_geo", "no_geo", ""], True)},
                                                 True)},
                        False),
            "get": (list, ("get_coord_by_gpx_file",
                           "-get_coord_by_gpx_file",
                           "get_coord_by_neighbors",
                           "-get_coord_by_neighbors",
                           "get_begin_coord_by_first_neighbor",
                           "-get_begin_coord_by_first_neighbor",
                           "get_end_coord_by_last_neighbor",
                           "-get_end_coord_by_last_neighbor",
                           "get_median_coord",
                           "-get_median_coord",
                           "get_file_data_from_manual_file",
                           "-get_file_data_from_manual_file",
                           "get_common_data_from_manual_file",
                           "-get_common_data_from_manual_file",
                           "get_utc_calibrate_by_track",
                           "-get_utc_calibrate_by_track",
                           "get_t_zone_by_neighbors",
                           "-get_t_zone_by_neighbors",
                           "get_file_data_by_file_tags",
                           "-get_file_data_by_file_tags",
                           "get_coord_by_geo_object",
                           "-get_coord_by_geo_object",
                           "get_address",
                           "-get_address",
                           "get_unique_id",
                           "-get_unique_id"), True),
            "address_source_ordered": (list, ("cache",
                                              "-cache",
                                              "osm",
                                              "-osm"), True),
            "use_geo_point": (bool, None, True),
            "address_cache_delta": (int, None, True),
            "log_mode": (list, ("counter_print",
                                "-counter_print",
                                "rename_log",
                                "-rename_log",
                                "rename_print",
                                "-rename_print",
                                "address_log",
                                "-address_log",
                                "address_print",
                                "-address_print",
                                "coord_log",
                                "-coord_log",
                                "coord_print",
                                "-coord_print",
                                "t_zone_log",
                                "-t_zone_log",
                                "t_zone_print",
                                "-t_zone_print",
                                "datetime_log",
                                "-datetime_log",
                                "datetime_print",
                                "-datetime_print",
                                "upd_addr_cache_log",
                                "-upd_addr_cache_log",
                                "upd_addr_cache_print",
                                "-upd_addr_cache_print",
                                "stage_log",
                                "-stage_log",
                                "stage_print",
                                "-stage_print",
                                "main_log",
                                "-main_log",
                                "main_print",
                                "-main_print",
                                "result_log",
                                "-result_log",
                                "result_print",
                                "-result_print",
                                "calibr_log",
                                "-calibr_log",
                                "calibr_print",
                                "-calibr_print",
                                "cal_w_p_log",
                                "-cal_w_p_log",
                                "cal_w_p_print",
                                "-cal_w_p_print",
                                "tool_log",
                                "tool_print"), True),
            "set": (list, ("exif_set",
                           "-exif_set",
                           "mac_tags_set",
                           "-mac_tags_set",
                           "addr_if_obj_to_mac_tag",
                           "-addr_if_obj_to_mac_tag",
                           "rename_set",
                           "-rename_set"), True),
            "addr_parts_types": (list, str, True),
            "time_shift_by_settings": ('val',
                                       {"camera_key_shift": ('val',
                                                             {
                                                                 "|str_from_settings|": ('val',
                                                                                         {"days": (int, None, True),
                                                                                          "hours": (int, None, True),
                                                                                          "minutes": (int, None, True),
                                                                                          "seconds": (int, None, True)},
                                                                                         True)
                                                             },
                                                             False)},
                                       False),
            "utc_cal_by_multi_track": ('val',
                                       {"min_dist_delta": (int, None, True),
                                        "max_dist_delta": (int, None, True),
                                        "distance_step": (int, None, True),
                                        "min_files_num": (int, None, True),
                                        "max_files_num": (int, None, True),
                                        "time_delta": (int, None, True),
                                        "num_time_delta_spread": (int, None, True)},
                                       True),
            "results_check": (list, ("no_address_with_coordinates",
                                     "-no_address_with_coordinates",
                                     "no_utc_datetime",
                                     "-no_utc_datetime",
                                     "no_coord_with_utc_time",
                                     "-no_coord_with_utc_time"
                                     ), True),
            "gpx_track_rebuild": ('val',
                                  {"merge": (bool, None, True),
                                   "distance_delta": (int, None, True),
                                   "less_dist_time_delta": (int, None, True),
                                   "new_gpx_file_name": (str, None, True)},
                                  True)
        }

    @staticmethod
    def gen_additional_settings_template() -> dict:
        folder_settings_tmp = Settings.gen_settings_template()
        if folder_settings_tmp:
            for key, item in folder_settings_tmp.items():
                if key != 'version':
                    folder_settings_tmp[key] = (item[0], item[1], False)
            return folder_settings_tmp
        else:
            return {}

    @staticmethod
    def check_settings(el_name: str,
                       struct_tmp: dict,
                       struct: dict) -> bool:
        if type(struct) is not dict:
            Settings.print_log('w', 'main', f"Incorrect type of {el_name} - {type(struct)}. Should be 'dict'.")
            return False
        res = True
        if isinstance(struct_tmp, dict):
            res = True
            if '|str_from_settings|' in struct_tmp.keys():
                struct_tmp = {k: struct_tmp['|str_from_settings|'] for k in struct.keys()}
                for k in struct.keys():
                    if not isinstance(k, str):
                        Settings.print_log('w', 'main', f'{el_name} -> {k} should be a string, but it is: {type(k)}.')
                        res = False
            for key, item in struct_tmp.items():
                if key in struct:
                    if item[0] == 'val':
                        if isinstance(item[1], dict):
                            res &= Settings.check_settings(el_name, item[1], struct[key])
                        else:
                            Settings.print_log('w', 'main',
                                               f'Unknown "val" type in template {el_name} -> {key} : '
                                               f'{type(item[1])}.')
                            res = False
                    elif item[0] is str:
                        if item[1] is None:
                            if not isinstance(struct[key], str):
                                Settings.print_log('w', 'main',
                                                   f' {el_name} -> {key} should be a string, but it is: '
                                                   f'{type(struct[key])}.')
                                res = False
                        elif isinstance(item[1], tuple) or isinstance(item[1], list):
                            if struct[key] not in item[1]:
                                Settings.print_log('w', 'main',
                                                   f' {el_name} -> {key}: '
                                                   f'{struct[key]} should has one of these values: {item[1]}.')
                                res = False
                        else:
                            Settings.print_log('w', 'main',
                                               f'Unknown type of string in template {el_name} -> {key} : '
                                               f'{type(item[1])}.')
                            res = False
                    elif item[0] is list:
                        if item[1] is str:
                            for l_elem in struct[key]:
                                if not isinstance(l_elem, str):
                                    Settings.print_log('w', 'main',
                                                       f'{el_name} -> {key} all values should be a string: {l_elem}.')
                                    res = False
                        elif isinstance(item[1], tuple) or isinstance(item[1], list):
                            for l_elem in struct[key]:
                                if l_elem not in item[1]:
                                    Settings.print_log('w', 'main', f'{el_name} -> {key} : '
                                                                    f'{l_elem} should has one of these values: '
                                                                    f'{item[1]}')
                                    res = False
                        else:
                            Settings.print_log('w', 'main',
                                               f'Unknown type of list in template {el_name} -> {key}: {type(item[1])}.')
                            res = False
                    elif item[0] is int:
                        if item[1] is None:
                            if not isinstance(struct[key], int):
                                Settings.print_log('w', 'main', f' {el_name} -> {key} should be an integer, '
                                                                f'but it is: {type(struct[key])}.')
                                res = False
                        elif isinstance(item[1], tuple) or isinstance(item[1], list):
                            if struct[key] not in item[1]:
                                Settings.print_log('w', 'main',
                                                   f' {el_name} -> {key}: '
                                                   f'{struct[key]} should has one of these values: {item[1]}.')
                                res = False
                        else:
                            Settings.print_log('w', 'main',
                                               f'Unknown type of int in template {el_name} -> {key}: {type(item[1])}.')
                            res = False
                    elif item[0] is bool:
                        if item[1] is None:
                            if not isinstance(struct[key], bool):
                                Settings.print_log('w', 'main', f' {el_name} -> {key} should be a boolean, '
                                                                f'but it is: {type(struct[key])}.')
                                res = False
                        else:
                            Settings.print_log('w', 'main',
                                               f'Unknown type of bool in template {el_name} -> {key}: {type(item[1])}.')
                            res = False
                    else:
                        Settings.print_log('w', 'main', f'Unknown type of item for {el_name} -> {key}: {item[0]}.')
                        res = False
                elif item[2] or key == 'version':
                    Settings.print_log('w', 'main', f'Missing key {key} in {el_name}.')
                    res = False
        return res

    @staticmethod
    def print_counter(msg: str, *args: str) -> typing.NoReturn:
        if args:
            show_counter_flag = not Settings.check_par('log_mode', args[0] + '_print')
        else:
            show_counter_flag = True
        if show_counter_flag and Settings.check_par('log_mode', 'counter_print'):
            if msg:
                log_msg = 'INFO: count ' + datetime.now().strftime("%Y:%m:%d-%H:%M:%S") + ' ' + msg
                print('\r' + log_msg[:shutil.get_terminal_size().columns - 2] + '\x1b[K', end='\r', flush=True)
            else:
                print('')

    @staticmethod
    def print_log(m_type: str, proc: str, message: str) -> typing.NoReturn:
        """
        Printing messages to the log and terminal depends on the settings
        :param m_type:
        :param proc:
        :param message:
        :return:
        """
        if Settings.no_empty_par('log_mode'):
            log_flag = Settings.check_par('log_mode', (proc + '_log'))
            print_flag = Settings.check_par('log_mode', (proc + '_print'))
            if log_flag or print_flag:
                if m_type == 'i':
                    log_msg = ' ' + proc + ' ' + datetime.now().strftime("%Y:%m:%d-%H:%M:%S") + ' ' + message
                    if log_flag:
                        Settings.app_log.info(log_msg)
                    if print_flag:
                        print("\rINFO:" + log_msg)

                elif m_type == 'w':
                    log_msg = ' ' + proc + ' ' + datetime.now().strftime("%Y:%m:%d-%H:%M:%S") + ' ' + message
                    if log_flag:
                        Settings.app_log.warning(log_msg)
                    if print_flag:
                        print("\rWARNING:" + log_msg)

                elif m_type == 'e':
                    log_msg = ' ' + proc + ' ' + datetime.now().strftime("%Y:%m:%d-%H:%M:%S") + ' ' + \
                              str(sys.exc_info()[0]) + ' ' + str(sys.exc_info()[1]) + ' ' + message
                    if log_flag:
                        Settings.app_log.error(log_msg)
                    if print_flag:
                        print("\rERROR:" + log_msg)
        else:
            print("\r" + message)
