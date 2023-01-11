import ast
import os
import pickle
import re
import time
import typing

import pytz
from datetime import datetime, timedelta

# Standard macOS tags colors
MACOS_TAGS_COLORS = {"NONE": 0,
                     "GRAY": 1,
                     "GREEN": 2,
                     "PURPLE": 3,
                     "BLUE": 4,
                     "YELLOW": 5,
                     "RED": 6,
                     "ORANGE": 7}


def timedelta_to_string(time_delta: timedelta) -> str:
    """
    Convert timedelta to the string
    :param time_delta:
    """
    td_sec = time_delta.total_seconds()
    sign = '' if td_sec > 0 else '-'
    hours, remainder = divmod(abs(td_sec), 3600)
    minutes, seconds = divmod(remainder, 60)
    return sign + '{:02}:{:02}:{:02}'.format(int(hours), int(minutes), int(seconds))


def string_to_datetime(dt_str: str, pattern: str) -> typing.Optional[datetime]:
    """
    Convert string date and time to the datetime format
    :param dt_str:
    :param pattern:
    :return:
    """
    try:
        date_time = datetime.strptime(dt_str, pattern)
        if date_time:
            return date_time
        else:
            return None
    except (ValueError, TypeError):
        return None


def save_struct_as_txt_file(txt_file_path: str,
                            struct_to_file: typing.Any,
                            file_type: str):
    with open(txt_file_path, 'w') as file:
        struct_str = str(struct_to_file)
        struct_str = re.sub(r'^\{', '{\n', struct_str)
        struct_str = re.sub(r'^\[', '[\n', struct_str)
        struct_str = re.sub(r'}$', '\n}', struct_str)
        struct_str = re.sub(r']$', '\n]', struct_str)

        if file_type == 'done_folders':
            struct_str = re.sub(r"', '", "',\n'", struct_str)

        struct_str = re.sub('True', 'true', struct_str)
        struct_str = re.sub('False', 'false', struct_str)

        file.write(struct_str)


def load_pickle_file_as_struct(pickle_file_path: str,
                               empty_struct: typing.Any) -> typing.Any:
    """
    Load data from pickle file. If something goes wrong, method  returns the value from the empty_struct parameter.
    :param pickle_file_path:
    :param empty_struct:
    :return: A data structure read from a file and recognized.
    """
    try:
        with open(pickle_file_path, 'rb') as file:
            file_struct = pickle.load(file)
    except (FileNotFoundError, SyntaxError, EOFError, AttributeError):
        file_struct = empty_struct
    return file_struct


def save_struct_as_pickle_file(pickle_file_path: str,
                               struct_to_file: typing.Any) -> typing.NoReturn:
    with open(pickle_file_path, 'wb') as file:
        pickle.dump(struct_to_file, file)


def load_txt_file_as_struct(txt_file_path: str, empty_struct: typing.Any) -> typing.Any:
    """
    Opens a file and creates a structure from its contents. In case of error it returns empty structure.
    Because the script is expected to only load JSON files, the script replaces true and false with True and False.
    param file_path: string
    param file_path: empty_struct
    :return: A data structure read from a file and recognized.
    """
    try:
        with open(txt_file_path) as file:
            body = file.read()
            body = re.sub('true', 'True', body)
            body = re.sub('false', 'False', body)
            file_struct = ast.literal_eval(body)
    except FileNotFoundError:
        file_struct = empty_struct
    except SyntaxError:
        file_struct = empty_struct
    return file_struct


def get_macos_tag_color_code(tag_color: str) -> MACOS_TAGS_COLORS:
    return MACOS_TAGS_COLORS[tag_color.upper()] if tag_color in MACOS_TAGS_COLORS else 0


def create_new_folder(new_folder_path: str) -> typing.NoReturn:
    try:
        os.mkdir(new_folder_path)
    except FileExistsError:
        pass


def coord_to_text(coord: typing.Tuple[float, float]) -> str:
    text = f"{coord[0]}, {coord[1]}"
    return text


def alt_to_text(alt: float) -> str:
    text = f"alt {alt}"
    return text


def get_next_element(source_list: list,
                     element: typing.Any,
                     non_element: typing.Any) -> typing.Any:
    """
    Get the next element in the list given the element. If there is no next element or the element is not in the list,
    the method returns value from non_element.
    """
    if element in source_list:
        el_ind = source_list.index(element)
        if el_ind + 2 > len(source_list):
            return non_element
        else:
            return source_list[el_ind + 1]
    else:
        return non_element


def step_time_print():
    """
    counter = func.step_time_print()
    next(counter)
    ...
    counter.send('bla bla 1')
    ...
    counter.send('bla bla 2')
    """
    step_time = time.time()
    while True:
        msg = yield
        time_now = time.time()
        print(msg, time_now - step_time)
        step_time = time_now


def text_to_alt(text: str) -> float:
    """
    Convert a special format string to a floating height value.
    'alt 103' -> 103
    """
    search = re.findall(r'\s*alt\s*[0-9]{1,3}\.?[0-9]+\s*$', text)
    if search:
        try:
            alt = float(search[0].replace('alt', ''))
        except ValueError:
            alt = 0.0
    else:
        alt = 0.0
    return alt


def text_to_coord(text: str) -> typing.Tuple[float, float]:
    """
    Convert the special format string to a coordinates - tuple of two float.
    40.772360 -73.9717 -> (40.772360, -73.9717)
    40°46'20.0"N 73°58'23.7"W -> (40.772222, -73.973250)
    """
    coord_str_lst = re.findall(r'^\s*-?[0-9]{1,2}\.?[0-9]+.{1,2}-?[0-9]{1,3}\.?[0-9]+\s*$', text)
    if coord_str_lst:
        coord_str = re.findall(r'-?[0-9]{1,3}\.?[0-9]+', coord_str_lst[0])
        try:
            coord = float(coord_str[0]), float(coord_str[1])
            if coord[0] <= -90 or 90 <= coord[0] or coord[1] <= -180 or 180 <= coord[1]:
                coord = ()
        except ValueError:
            coord = ()
    else:
        coord = ()

    if not coord:
        lat_dms = re.findall(r"""[0-9]{1,2}°\s*[0-9]{1,2}'\s*[0-9]{1,2}\.?[0-9]*"\s*[NS]""", text)
        lon_dms = re.findall(r"""[0-9]{1,3}°\s*[0-9]{1,2}'\s*[0-9]{1,2}\.?[0-9]*"\s*[WE]""", text)
        if lat_dms and lon_dms:
            lat_dms_lst = re.findall(r'[0-9]+\.?[0-9]*', lat_dms[0])
            lon_dms_lst = re.findall(r'[0-9]+\.?[0-9]*', lon_dms[0])
            lat_deg = float(lat_dms_lst[0])
            lat_min = float(lat_dms_lst[1])
            lat_sec = float(lat_dms_lst[2])
            lon_deg = float(lon_dms_lst[0])
            lon_min = float(lon_dms_lst[1])
            lon_sec = float(lon_dms_lst[2])

            if 0 <= lat_deg <= 90 and 0 <= lat_min < 60 and 0 <= lat_sec < 60 and \
                    0 <= lon_deg <= 180 and 0 <= lon_min < 60 and 0 <= lon_sec < 60:
                lat = lat_deg + lat_min / 60 + lat_sec / 3600
                lat = -lat if lat_dms[0][-1] == 'S' else lat
                lon = lon_deg + lon_min / 60 + lon_sec / 3600
                lon = -lon if lon_dms[0][-1] == 'W' else lon
                if lat and lon:
                    coord = (lat, lon)
            else:
                coord = ()
        else:
            coord = ()
    return coord


def get_utc_datetime(date_time: datetime,
                     *args: str) -> typing.Optional[datetime]:
    """
    Convert datetime to UTC datetime.
    :param date_time: date and time to convert to UTC
    :param args: timezone. If date_time does not contain t-zone information and args contains t-zone, date_time is
    assumed to be the local time in zone args[0]. Next, we get the UTC time.
    :return: UTC datetime or None
    """
    if date_time.tzinfo is pytz.timezone('UTC'):
        utc_date_time = date_time
    elif date_time.tzinfo:
        utc_date_time = date_time.astimezone(pytz.timezone('UTC'))
    elif args:
        zone_time = pytz.timezone(args[0]).localize(date_time)
        utc_date_time = zone_time.astimezone(pytz.timezone('UTC'))
    else:
        utc_date_time = None
    return utc_date_time


def diff_utc_and_stamp(utc_datetime: datetime,
                       stamp: int) -> int:
    """
    Get different in seconds between utc_datetime and timestamp.
    """
    return int(utc_datetime.timestamp() - stamp)


def set_script_data_and_coord_to_file_exif_tags(exif_tool,
                                                file_path_for_set_exif: str,
                                                coordinates: dict,
                                                script_data: dict,
                                                script_data_tag_name: str) -> str:
    """
    Use ExifTool to store the script data and geolocation in the file's metadata.
    """
    try:
        if script_data and coordinates:
            exif_tool.execute(b'-overwrite_original',
                              ('-GPSLatitude=' + coordinates['GPSLatitude']).encode("utf-8"),
                              ('-GPSLatitudeRef=' + coordinates['GPSLatitudeRef']).encode("utf-8"),
                              ('-GPSLongitude=' + coordinates['GPSLongitude']).encode("utf-8"),
                              ('-GPSLongitudeRef=' + coordinates['GPSLongitudeRef']).encode("utf-8"),
                              ('-GPSAltitudeRef=' + coordinates['GPSAltitudeRef']).encode("utf-8"),
                              ('-GPSAltitude=' + coordinates['GPSAltitude']).encode("utf-8"),
                              ('-' + script_data_tag_name + '=' + str(script_data)).encode("utf-8"),
                              file_path_for_set_exif.encode("utf-8"))
        elif script_data and not coordinates:
            exif_tool.execute(b'-overwrite_original',
                              ('-' + script_data_tag_name + '=' + str(script_data)).encode("utf-8"),
                              file_path_for_set_exif.encode("utf-8"))
        elif not script_data and coordinates:
            exif_tool.execute(b'-overwrite_original',
                              ('-GPSLatitude=' + coordinates['GPSLatitude']).encode("utf-8"),
                              ('-GPSLatitudeRef=' + coordinates['GPSLatitudeRef']).encode("utf-8"),
                              ('-GPSLongitude=' + coordinates['GPSLongitude']).encode("utf-8"),
                              ('-GPSLongitudeRef=' + coordinates['GPSLongitudeRef']).encode("utf-8"),
                              ('-GPSAltitudeRef=' + coordinates['GPSAltitudeRef']).encode("utf-8"),
                              ('-GPSAltitude=' + coordinates['GPSAltitude']).encode("utf-8"),
                              file_path_for_set_exif.encode("utf-8"))
    except Exception as ex:
        return str(ex)
    return ''


def set_tag_to_file_exif_tags(exif_tool, file_path_for_set_exif: str, new_tag: list) -> str:
    """
    For tools using ExifTool, store the custom tag in the file's metadata.
    """
    if len(new_tag) == 2:
        try:
            exif_tool.execute(b'-overwrite_original',
                              ('-' + new_tag[0] + '=' + new_tag[1]).encode("utf-8"),
                              file_path_for_set_exif.encode("utf-8"))
        except Exception as ex:
            return str(ex)
    return ''


def dir_path(path: typing.Any) -> bool:
    """
    If the path is a folder it returns True, if the path is not a folder it returns False.
    """
    if type(path) == str and os.path.isdir(path):
        return True
    else:
        print(f"The '{path}' parameter must be a folder path.")
        return False


def file_path(path: str) -> bool:
    """
    If the path is a file it returns True, if the path is not a file it returns False.
    """
    if type(path) == str and os.path.isfile(path):
        return True
    else:
        print(f"The '{path}' parameter must be a file path.")
        return False


def set_man_flag(parameter_settings: dict, param_name: str, *args) -> bool:
    """
    The mechanism is needed to overwrite the values of the settings parameters depending on the parameters specified
    when the script is run. Get a list of script command line options from args. There must be only one True parameter.
    If there is only one True value, the script places the value of the third parameter from the tuple into the
    settings_parameter dictionary.

    :param parameter_settings: a dictionary to be passed to the script
    :param param_name: string key for the parameter in parameter_parameters
    :param args: tuples (script_bool_parameter_value, script_bool_parameter_name, parameter_settings_result_value)
    For example: (scr_par.rec, '-rec', True), (scr_par.rec_all, '-rec_all', True), (scr_par.no_rec, '-no_rec', False)
    :return: True if everything is OK or False if several script keys from the given set are specified together
    """
    flags = [flag_data for flag_data in args if flag_data[0]]
    if len(flags) > 1:
        print(f"You cannot use {', '.join([flag_data[1] for flag_data in flags])} arguments together.")
        return False
    elif len(flags) == 1:
        parameter_settings[param_name] = flags[0][2]
    return True


def print_all_t_zones():
    t_zones = sorted([z for z in pytz.all_timezones_set])
    for zone in t_zones:
        print(zone)


def get_attr(data_source: typing.Any, key: str) -> typing.Any:
    """
    Get the attribute with the 'key' name from the data_source object
    :param data_source: One of two format options. A dictionary if the data is loaded from a pickle file, or an object
    of the PVFile class, if data was loaded from photo-video files.
    :param key: string name of the attribute
    :return: value of the attribute
    """
    return data_source[key] if type(data_source) is dict else getattr(data_source, key)


def add_to_list(main_list: list, new_element: typing.Any) -> typing.NoReturn:
    if type(new_element) is list:
        main_list += new_element
    else:
        main_list.append(new_element)


def get_dict(dict_str: str) -> dict:
    try:
        dict_ast = ast.literal_eval(dict_str)
        if type(dict_ast) is dict:
            return dict_ast
    except (ValueError, TypeError, SyntaxError):
        pass
    return {}


def sd_data(tag_string: str) -> dict:
    """
    Get script data from file's metadata tag
    :param tag_string: file's metadata tag
    :return: value of the script data or empty dictionary if there is no a script data in this tag
    """
    try:
        tag_structure = ast.literal_eval(tag_string)
        if type(tag_structure) is dict and 'pvs' in tag_structure:
            return tag_structure
    except (ValueError, TypeError, SyntaxError):
        pass
    return {}


def str_after_sing(checking_string: str, sub_str: str) -> str:
    """
    Checking for the presence of the sub_str substring at the beginning of the checking_string.
    If found, the rest of the string is returned. Else empty string is returned
    """
    res = ''
    if checking_string and len(checking_string) > len(sub_str) and checking_string[:len(sub_str)] == sub_str:
        res = checking_string[len(sub_str):]
    return res


def zone_offset(time_zone_name: str) -> timedelta:
    return datetime.now(pytz.timezone(time_zone_name)).utcoffset()
