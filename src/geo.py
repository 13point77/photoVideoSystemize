from __future__ import annotations
import ast
import os.path
import re
import ssl
import statistics
import time
import typing
import certifi
import geopy
import gpxpy
import pytz
from datetime import datetime, timedelta
from os import listdir
from os.path import isfile, join
from bs4 import BeautifulSoup
from geopy import Nominatim
from geopy.distance import distance
from shapely.geometry import Polygon, Point, MultiPoint
from shapely.ops import nearest_points
from timezonefinder import TimezoneFinder
from src import func
from src.settings import Settings


class ManualData(Settings):

    def __init__(self):
        self.manual_data_file_name = self.get_par('', 'manual_data_file')
        self.split_sign = self.get_par('|', 'split_sign')
        self.t_zones = [z for z in pytz.all_timezones_set]
        self.folder_path = ''
        self.manual_data: typing.Dict[str, dict] = {}
        self.common_data = {}
        self.wrong_file_manual_data: typing.Dict[str, dict] = {}

    def add_manual_data(self, group_name: str, group_data: dict) -> typing.NoReturn:
        if group_name in self.manual_data:
            self.manual_data[group_name].update(group_data)
        else:
            self.manual_data[group_name] = group_data

    def set_common_data(self, line_data: dict) -> typing.NoReturn:
        self.common_data = line_data

    def set_wrong_data(self, pv_group_name: str, pv_group_data: dict) -> typing.NoReturn:
        self.wrong_file_manual_data[pv_group_name] = pv_group_data

    def remove_manual_file_data(self, group_name: str) -> typing.NoReturn:
        if group_name in self.manual_data:
            del self.manual_data[group_name]

    def load_folder_manual_data_file(self, folder_path: str) -> typing.NoReturn:
        self.folder_path = folder_path
        if self.manual_data_file_name and self.folder_path:
            manual_data_file_path = join(self.folder_path, self.manual_data_file_name)
            manual_date_time_format = self.get_par('', 'manual_date_time_format')
            file_lines = []
            try:
                with open(manual_data_file_path) as file:
                    body = file.read()
                    file_lines = body.split('\n')
            except FileNotFoundError:
                pass
            if file_lines:
                for line in file_lines:
                    if line:
                        words = line.split(self.split_sign)
                        if len(words) > 1:
                            line_data = {}
                            file_name = words[0].strip()
                            for word in words[1:]:
                                word = word.strip()
                                if re.findall(r'^\s*cam:', word):
                                    continue
                                coord = func.text_to_coord(word)
                                if coord:
                                    line_data['coord'] = coord
                                    continue
                                alt = func.text_to_alt(word)
                                if alt:
                                    line_data['alt'] = alt
                                    continue
                                t_zone = word if word in self.t_zones else ''
                                if t_zone:
                                    line_data['t_zone'] = t_zone
                                    continue
                                geo_object = GeoObjects.is_geo_object(word)
                                if geo_object:
                                    line_data['geo_object_name'] = geo_object
                                    continue
                                file_dt = func.string_to_datetime(word, manual_date_time_format)
                                if file_dt:
                                    line_data['file_dt'] = file_dt
                                    continue
                            if line_data:
                                if file_name.upper() == 'ALL':
                                    self.set_common_data(line_data)
                                else:
                                    self.add_manual_data(file_name, line_data)

    def save_folder_manual_data_file(self) -> typing.NoReturn:
        manual_data_file_path = join(self.folder_path, self.manual_data_file_name)
        manual_date_time_format = self.get_par('', 'manual_date_time_format')
        if self.manual_data and manual_data_file_path:
            with open(manual_data_file_path, 'w') as file:
                for group_name, group_data in self.manual_data.items():
                    line = self.save_ready_string(group_name, group_data, self.split_sign, manual_date_time_format)
                    if line:
                        print(line, file=file)

                if self.common_data:
                    line = self.save_ready_string('All', self.common_data, self.split_sign, manual_date_time_format)
                    if line:
                        print(line, file=file)

                for file_name, file_data in self.wrong_file_manual_data.items():
                    line = self.save_ready_string(file_name, file_data, self.split_sign, manual_date_time_format)
                    if line:
                        print(line, file=file)

    @staticmethod
    def save_ready_string(group_name: str,
                          group_data: dict,
                          split_sign: str,
                          manual_date_time_format: str) -> str:
        line_data = []
        if 'coord' in group_data:
            line_data.append(func.coord_to_text(group_data['coord']))
        if 'alt' in group_data:
            line_data.append(func.alt_to_text(group_data['alt']))
        if 'file_dt' in group_data:
            line_data.append(group_data['file_dt'].strftime(manual_date_time_format))
        if 'geo_object_name' in group_data:
            line_data.append(group_data['geo_object_name'])
        if 'camera' in group_data:
            line_data.append('cam: ' + group_data['camera'])
        if 't_zone' in group_data:
            line_data.append(group_data['t_zone'])
        return split_sign.join([group_name] + line_data)

    def check_and_rebuild(self,
                          group_name_by_file_name: typing.Dict[str, str],
                          pv_groups) -> typing.NoReturn:
        wrong_files = [file_name for
                       file_name in self.manual_data.keys() if
                       file_name not in group_name_by_file_name.keys()]
        if wrong_files:
            self.print_log('w', 'main', f"{self.folder_path}: Can't find files {wrong_files} from "
                                        f"manual data file {self.manual_data_file_name}")
            for file_name in wrong_files:
                self.set_wrong_data(file_name, self.manual_data[file_name])
                self.remove_manual_file_data(file_name)

        self.manual_data = {group_name_by_file_name[file_name]: file_data for
                            file_name, file_data in self.manual_data.items()}

        # Add cam info to manual data
        for name, man_data in self.manual_data.items():
            if pv_groups[name].camera_key and pv_groups[name].camera_found:
                man_data['camera'] = pv_groups[name].camera_key

    # Change names to new_names
    def rename_before_save_manual_data_file(self, new_name_by_name: typing.Dict[str, str]) -> typing.NoReturn:
        self.manual_data = {new_name_by_name[file_name]: file_data for
                            file_name, file_data in self.manual_data.items()}

    def sort_manual_data_file(self) -> typing.NoReturn:
        self.manual_data = {file_name: file_data for file_name, file_data in
                            sorted(self.manual_data.items(), key=lambda item: item[0])}


class GeoObjectPoint:
    def __init__(self,
                 name: str,
                 coord: typing.Tuple[float, float],
                 radius: float,
                 tags: typing.List[str]):
        self.name = name
        self.coord = coord
        self.radius = radius
        self.tags = tags


class GeoObjectPolygon:
    def __init__(self,
                 name: str,
                 pol_coord: typing.List[typing.Tuple[float, float]],
                 tags: typing.List[str]):
        self.center = ()
        self.name = name
        self.pol_coord = pol_coord
        self.tags = tags
        self.get_center()

    def get_center(self) -> typing.NoReturn:
        if self.pol_coord:
            polygon = Polygon(self.pol_coord)
            self.center = (polygon.centroid.xy[0][0], polygon.centroid.xy[1][0])
        else:
            self.center = ()


class GeoObjects:
    points = {}
    polygons = {}
    tag_by_hand_info_begin = ''

    @staticmethod
    def is_geo_object(name: str) -> str:
        name = name.strip()
        if name in GeoObjects.points or name in GeoObjects.polygons:
            return name
        else:
            return ''

    @staticmethod
    def load_google_earth_kml(geo_object_kml_file_path: str) -> typing.NoReturn:
        """
        Reading local 'Google Earth Pro' myplaces.kml file with information of named geo-objects
        :return: dictionary with usefully format information of named geo-objects from 'Google Earth Pro'
        """
        if geo_object_kml_file_path:
            try:
                kml_file = open(geo_object_kml_file_path, 'r')
                kml_xml = kml_file.read()
                kml_file.close()
            except FileNotFoundError:
                Settings.print_log('w', 'main', f"Can't load objects from Google Earth file {geo_object_kml_file_path}")
            else:
                soup_kml = BeautifulSoup(kml_xml, 'xml')
                for folder in soup_kml.select('Folder'):
                    folder_name = folder.select('name')[0].text
                    if folder_name == 'photo_objects':
                        kml_points = folder.select('Placemark')
                        for place in kml_points:
                            place_name_struct = place.select('name')
                            if place_name_struct:
                                place_name = place_name_struct[0].text.strip()
                                description = place.select('description')
                                desc_lst = description[0].text.split('\n') if description else []
                                if place.select('Polygon'):
                                    pol_coord_list_str = place.select('coordinates')[0].text.strip().split(' ')
                                    pol_coord_list = [(float(c[1]), float(c[0])) for c in
                                                      [point.split(',') for point in pol_coord_list_str]]
                                    tags_lst = [place_name] + desc_lst
                                    object_polygon = GeoObjectPolygon(place_name, pol_coord_list, tags_lst)
                                    GeoObjects.polygons[place_name] = object_polygon

                                else:
                                    lat = float(place.select('coordinates')[0].text.split(',')[1])
                                    lon = float(place.select('coordinates')[0].text.split(',')[0])
                                    try:
                                        radius = float(place.select('description')[0].text.split('\n')[0])
                                        tags_lst = [place_name] + desc_lst[1:] if len(desc_lst) > 1 else [place_name]
                                    except ValueError:
                                        radius = 0
                                        tags_lst = [place_name] + desc_lst
                                    object_point = GeoObjectPoint(place_name, (lat, lon), radius, tags_lst)
                                    GeoObjects.points[place_name] = object_point

    @staticmethod
    def get_object_tags(coord: typing.Union[typing.Tuple[float, float], typing.Tuple[()]]) -> typing.List[str]:
        """
        Find all Google objects by coordinates and collect all tags from them
        :param coord:
        :return:
        """
        if coord:
            tags = set()
            for point in GeoObjects.points.values():
                if point.radius > 0:
                    if distance(coord, point.coord).m < point.radius:
                        tags.update(set(point.tags))
            for polygon in GeoObjects.polygons.values():
                shap_point = Point(coord)
                shap_polygon = Polygon(polygon.pol_coord)
                if shap_polygon.contains(shap_point):
                    tags.update(set(polygon.tags))
        else:
            tags = []
        return list(tags)

    @staticmethod
    def get_coord_by_tag(tag: str) -> typing.Tuple[float, float]:
        coord = ()
        if tag in GeoObjects.points.keys():
            coord = GeoObjects.points[tag].coord
        elif tag in GeoObjects.polygons.keys():
            coord = GeoObjects.polygons[tag].center
        return coord


class Address(Settings):
    addr_cache = {}
    num_new_address = 0
    shapely_multipoint = None
    min_dist = 50
    pickle_file_path = ''
    osm_connection_num = 0
    last_osm_connection = time.time()
    ctx = None
    osm_geo_locator = None

    def __init__(self, *args: typing.Dict[str, str]):
        self.address = args[0] if args and args[0] else {}
        self.tags = []

    def set_address(self, new_address: dict) -> typing.NoReturn:
        if new_address:
            self.address = new_address
        self.get_address_tags()

    def clear_address(self) -> typing.NoReturn:
        self.address = {}
        self.tags = []

    def get_address_tags(self, *args) -> typing.NoReturn:
        if args and args[0]:
            addr_parts_types = args[0]
        else:
            addr_parts_types = self.get_par([], 'addr_parts_types')
        self.tags = [self.address[key] for key in addr_parts_types if key in self.address]

    def copy(self):
        new_address = Address(self.address)
        return new_address

    def get_address_by_coordinates(self,
                                   coord: typing.Union[typing.Tuple[float, float], typing.Tuple[()]],
                                   *args: str) -> typing.NoReturn:
        """
        Gets an address based on geographic coordinates.
        If the coordinates are (), then the method will return the value {}
        :param coord: the geographic coordinates of the point whose address is to be determined.
        tuple((float)latitude, (float)longitude)
        :return:  If the address is found, the address is returned as a dictionary of address element types and their
        values, plus a 'source' element is added to the dictionary with the source of the address value.
        """
        self.clear_address()
        address = {}
        if args:
            address_sources = args[0]
        else:
            address_sources = self.get_par([], 'address_source_ordered')

        if coord and address_sources:
            for addr_source in address_sources:
                if not address and addr_source == "cache":
                    address = Address.get_cache_addr_by_coord(coord)
                elif not address and addr_source == "osm":
                    address = Address.get_address_by_coord_osm(coord)
                    if address:
                        Address.add_cache_address(coord, address)
            if not address and self.check_par('use_geo_point'):
                # no address with coordinates -> address is 'geo_point': '{lat} {lon}'
                address = {'geo_point': str(coord[0]) + " " + str(coord[1])}
                Address.add_cache_address(coord, address)
        if address:
            self.set_address(address)

    @staticmethod
    def get_cache_addr_by_coord(coord: typing.Tuple[float, float]) -> dict:
        """
        Calculating the address of a point with coordinates using previously saved address calculations.
        :param coord:  points coordinates
        :return: address
        """
        if Address.shapely_multipoint:
            nearest_coord = nearest_points(Address.shapely_multipoint, Point(coord))[0].coords[0]
            step_dist = distance(nearest_coord, coord).m
            if step_dist < Address.min_dist:
                cache_address = Address.addr_cache[nearest_coord]
            else:
                cache_address = {}
        else:
            cache_address = {}
        return cache_address

    @staticmethod
    def update_address_cache(*args: str) -> typing.NoReturn:
        """
        The method updates the cache of addresses from available services with actual values.
        sources - an ordered list of address sources. when calculating the address, the sources are selected in
        accordance and in the order specified in the 'sources' parameter. Options: "cache", "osm", etc.
        From the list select all values except "cache"
        """
        start = time.time()
        if not Address.addr_cache:
            Address.load_address_cache()
        # Activate connection to the OpenStreetMaps  service
        if not Address.ctx:
            Address.activate_osm_connection()
        # From time to time we can update all cached points addresses.
        Address.print_log('i', 'main', f'Start update address cache.')
        # Get sources from *args or from parameter 'address_source_ordered'
        if args:
            address_sources = [source for source in args if source != 'cache']
        else:
            address_sources = Address.get_par([], 'address_source_ordered')
            address_sources = [source for source in address_sources if source != 'cache']

        if address_sources:
            p_num = 0
            for coord, item in Address.addr_cache.items():
                address = {}
                for addr_source in address_sources:
                    if not address and addr_source == "osm":
                        address = Address.get_address_by_coord_osm(coord)
                    # elif not address and addr_source == "some_new_source":
                    #     address = Address.get_address_by_coord_some_new_source(coord)
                if address:
                    Address.addr_cache[coord] = address
                p_num += 1
                Address.print_log('i', 'upd_addr_cache', f"Updated {p_num} address from {len(Address.addr_cache)}: "
                                                         f"{coord} - {Address.addr_cache[coord]}")
            # Save address cache to the file.
            Address.save_address_cache()

            Address.print_log('i', 'main', f'Address cache updated in {timedelta(seconds=int(time.time() - start))}')
        else:
            Address.print_log('i', 'main', f'Address cache skipped - no source for update!')

    @staticmethod
    def load_address_cache() -> typing.NoReturn:
        Address.min_dist = Address.get_par(50, 'address_cache_delta')
        Address.pickle_file_path = Address.get_par('', 'addr_cache_pickle_file_path')
        if Address.pickle_file_path:
            Address.addr_cache = func.load_pickle_file_as_struct(Address.pickle_file_path, {})
            if Address.addr_cache:
                Address.shapely_multipoint = MultiPoint(list(Address.addr_cache.keys()))
            else:
                Address.shapely_multipoint = MultiPoint(list(Address.addr_cache.keys()))
                Address.print_log('i', 'main', f"Address cache file loaded, but it is empty.")
        else:
            Address.print_log('i', 'main', f"Can't load address cache file. "
                                           f"Parameter 'addr_cache_pickle_file_path' is empty.")

    @staticmethod
    def add_cache_address(coord: typing.Tuple[float, float], address: dict) -> typing.NoReturn:
        Address.addr_cache[coord] = address
        Address.shapely_multipoint = Address.shapely_multipoint.union(Point(coord))
        Address.num_new_address += 1
        if Address.num_new_address > 100:
            Address.save_address_cache()
            Address.num_new_address = 0

    @staticmethod
    def save_address_cache() -> typing.NoReturn:
        func.save_struct_as_pickle_file(Address.pickle_file_path, Address.addr_cache)

    @staticmethod
    def activate_osm_connection() -> typing.NoReturn:
        Address.ctx = ssl.create_default_context(cafile=certifi.where())
        geopy.geocoders.options.default_ssl_context = Address.ctx
        osm_user_agent = Address.get_par('', 'osm_user_agent')
        if osm_user_agent:
            try:
                Address.osm_geo_locator = Nominatim(user_agent=osm_user_agent)
            except Exception as ex:
                Address.print_log('e', 'main', '(activate_osm_connection) ' + str(ex))

    @staticmethod
    def get_address_by_coord_osm(coord: typing.Tuple[float, float]) -> dict:
        """
        Using geographic coordinates, accesses the OSM service and tries to get a postal address.
        :param coord: tuple((float)latitude, (float) longitude) - geographic coordinates
        :return: dictionary { address element type: address element value}
                 if nothing is found, return an empty dictionary
        """
        osm_address = {}
        if coord:
            location = None
            i = 2
            while not location and i < 5:
                if time.time() - Address.last_osm_connection < i:
                    time.sleep(i)
                Address.last_osm_connection = time.time()
                Address.osm_connection_num += 1
                try:
                    location = Address.osm_geo_locator.reverse(str(coord[0]) + "," + str(coord[1]))
                except Exception as ex:
                    Address.print_log('e', 'main', '(get_address_by_coord_osm) reverse' + str(ex))
                i += 1

            if location:
                geo_address_str = str(location.raw['address'])
                try:
                    osm_address = ast.literal_eval(geo_address_str)
                    if osm_address:
                        osm_address['source'] = 'osm'
                except ValueError:
                    Address.print_log('e', 'main', '(get_address_by_coord_osm) ast.literal_eval ')
        return osm_address


class GeoTrackPoint:

    def __init__(self, **kwargs):
        self.coord = kwargs['coord'] if 'coord' in kwargs else ()
        self.elevation = kwargs['elevation'] if 'elevation' in kwargs else 0
        self.utc_dt = kwargs['utc_dt'] if 'utc_dt' in kwargs else None
        # self.t_zone = kwargs['t_zone'] if 't_zone' in kwargs else ''

    @property
    def lat(self) -> float:
        """Return latitude. """
        return self.coord[0]

    @property
    def lon(self) -> float:
        """Return longitude."""
        return self.coord[1]

    @property
    def elev(self) -> float:
        """Return longitude."""
        return self.elevation

    def distance(self, point: GeoTrackPoint) -> float:
        return distance(self.coord, point.coord).m

    def time_diff(self, point: GeoTrackPoint):
        if self.utc_dt and point.utc_dt:
            diff = (self.utc_dt - point.utc_dt).total_seconds()
        else:
            diff = None
        return diff


class GeoMultiTrack(Settings):
    tf = TimezoneFinder()

    def __init__(self):
        self.tracks = []

    def load_gpx_folder(self, folder_path: str) -> typing.NoReturn:
        self.print_log('i', 'stage', f"{folder_path}: Loading gpx files.")
        gpx_file_list = [join(folder_path, f) for f in listdir(folder_path) if isfile(join(folder_path, f)) and
                         f.split('.')[-1].upper() == 'GPX']
        for gpx_file_path in gpx_file_list:
            gpx_file_name = os.path.split(gpx_file_path)[1]
            if self.get_par('', 'exist_pv_gpx_track_file') == gpx_file_name:
                # Do not load track made from exist photo/video files.
                continue
            self.load_gpx_file(gpx_file_path)

    def load_gpx_file(self, file_path: str) -> typing.NoReturn:
        try:
            gpx_file = open(file_path, 'r')
            gpx = gpxpy.parse(gpx_file)
            gpx_file.close()
        except Exception as error:
            self.print_log('e', 'main', '(geo_load_gpx_file) ' + str(error))
            return
        else:
            folder_path = os.path.split(file_path)[0]
            self.print_log('i', 'stage', f"{folder_path}: Loading gpx file {file_path}.")
            for track in gpx.tracks:
                for segment in track.segments:
                    if not self.tracks or (self.tracks and self.tracks[-1].points):
                        self.add_track()
                    for p_gpx in segment.points:
                        if p_gpx.time:
                            point_utc_dt = func.get_utc_datetime(p_gpx.time)
                            if point_utc_dt:
                                point = GeoTrackPoint(coord=(p_gpx.latitude, p_gpx.longitude),
                                                      elevation=p_gpx.elevation,
                                                      utc_dt=point_utc_dt)
                                self.tracks[-1].add_point(point)

    def add_point(self, point: GeoTrackPoint) -> typing.NoReturn:
        self.tracks[-1].add_point(point)

    def add_track(self, *args: GeoTrack) -> GeoTrack:
        if args:
            geo_track = args[0]
        else:
            geo_track = GeoTrack()
        self.tracks.append(geo_track)
        return geo_track

    def save_multi_track(self, file_path: str) -> typing.NoReturn:
        if self.tracks:
            gpx = gpxpy.gpx.GPX()
            for track in self.tracks:
                gpx_track = gpxpy.gpx.GPXTrack()
                gpx.tracks.append(gpx_track)
                gpx_segment = gpxpy.gpx.GPXTrackSegment()
                gpx_track.segments.append(gpx_segment)
                for point in track.points:
                    gpx_point = gpxpy.gpx.GPXTrackPoint()
                    gpx_point.latitude = point.lat
                    gpx_point.longitude = point.lon
                    gpx_point.time = point.utc_dt
                    gpx_point.elevation = point.elevation
                    gpx_segment.points.append(gpx_point)

            with open(file_path, 'w') as f:
                f.write(gpx.to_xml())
                f.close()
                self.print_log('i', 'stage', f"Track with {len(self.tracks)} tracks saved to the file {file_path}")

    def __add__(self, other_multi_geo_tracks: GeoMultiTrack) -> GeoMultiTrack:
        new_multi_geo_tracks = GeoMultiTrack()
        new_multi_geo_tracks.tracks = self.tracks.copy() + other_multi_geo_tracks.tracks.copy()
        return new_multi_geo_tracks

    def __len__(self) -> int:
        return len(self.tracks)

    def add_multi_track(self, multi_track: GeoMultiTrack) -> typing.NoReturn:
        for track in multi_track.tracks:
            self.add_track(track)

    def get_coord_by_utc_dt(self, utc_dt: datetime) -> typing.Tuple[tuple, float]:
        for track in self.tracks:
            coord, elev = track.binary_coord_search(utc_dt)
            if coord:
                return coord, elev
        return (), 0

    def rebuild_multi_track(self,
                            distance_delta: float,
                            less_dist_time_delta: float,
                            merge_flag: bool) -> bool:
        self.print_log('i', 'tool', f"Start rebuilding  geo multi track with {len(self.tracks)} tracks.")

        if self.tracks:
            points_list = [point for p_list in self.tracks for point in p_list.points]
            # sorting points from all gpx files by time
            points_list = [p for p in sorted(points_list, key=lambda li: li.utc_dt)] if points_list else []
            first_no_print_flag = False
            if points_list:
                self.tracks.clear()
                old_time = func.string_to_datetime('1900:01:01 00:00:01', '%Y:%m:%d %H:%M:%S')
                step_time = pytz.timezone('UTC').localize(old_time)
                step_point = GeoTrackPoint(coord=(-90, 180), utc_dt=step_time)
                for point in points_list:
                    dist = point.distance(step_point)
                    time_delta = point.time_diff(step_point)
                    if time_delta == 0:
                        continue
                    if (not merge_flag or not first_no_print_flag) and \
                            (dist >= distance_delta or (time_delta > less_dist_time_delta and dist < distance_delta)):
                        msg = f"Split: dist = {int(dist)}, " \
                              f"time_delta = {int(time_delta)} s., " \
                              f"vel = {int(dist / time_delta)} m/s, " \
                              f"vel = {int(dist / time_delta * 3.6)} km/h, " \
                              f"utc_time_prev = {step_point.utc_dt}, " \
                              f"utc_time_next = {point.utc_dt}, " \
                              f"num_points {len(self.tracks[-1].points) if self.tracks else 0}"
                        if first_no_print_flag:
                            self.print_log('i', 'tool', msg)
                        first_no_print_flag = True
                        self.tracks.append(GeoTrack())
                        self.tracks[-1].add_point(point)
                    else:
                        self.tracks[-1].add_point(point)
                    step_point = point

        self.print_log('i', 'tool', f"Finished rebuilding  geo multi track with {len(self.tracks)} tracks.")
        return True


class GeoTrack:
    def __init__(self):
        self.points = []
        self.south_bound = 90.0
        self.north_bound = -90.0
        self.west_bound = 180.0
        self.east_bound = -180.0

    def add_point(self, geo_point: GeoTrackPoint) -> typing.NoReturn:
        self.points.append(geo_point)
        self.south_bound = min(self.south_bound, geo_point.lat)
        self.north_bound = max(self.north_bound, geo_point.lat)
        self.west_bound = min(self.west_bound, geo_point.lon)
        self.east_bound = max(self.east_bound, geo_point.lon)

    def sort_track(self) -> typing.NoReturn:
        self.points = [p for p in sorted(self.points, key=lambda pp: pp.utc_dt)]

    def binary_coord_search(self, date_time: datetime) -> typing.Tuple[tuple, float]:
        # start = time.time()
        if self.points[0].utc_dt > date_time or self.points[-1].utc_dt < date_time:
            return (), 0
        first = 0
        last = len(self.points) - 1
        while first < last:
            mid = (first + last) // 2
            if self.points[mid].utc_dt < date_time:
                first = mid + 1
            else:
                last = mid
        prev_p = first - 1 if first > 0 else first
        next_p = first + 1 if first < len(self.points) - 1 else first

        if self.points[prev_p].utc_dt < date_time < self.points[first].utc_dt:
            left = prev_p
            right = first
        elif date_time == self.points[first].utc_dt:
            return self.points[first].coord, self.points[first].elev
        elif self.points[first].utc_dt < date_time < self.points[next_p].utc_dt:
            left = first
            right = next_p
        else:
            return (), 0

        k = (date_time - self.points[left].utc_dt) / (self.points[right].utc_dt - self.points[left].utc_dt)
        lat = self.points[left].lat + k * (self.points[right].lat - self.points[left].lat)
        lon = self.points[left].lon + k * (self.points[right].lon - self.points[left].lon)
        coord = (lat, lon)
        elev = 0
        if self.points[right].elev - self.points[left].elev:
            elev = self.points[left].elev + k * (self.points[right].elev - self.points[left].elev)
        return coord, elev


class CalibrateCameraClocks(Settings):

    def __init__(self,
                 camera: str,
                 geo_tracks: GeoMultiTrack,
                 pv_groups):
        # Very, very, very, very, very approximate conversion factor from meters to degrees.
        # Will use "distances in degrees". In this case it will be much faster.
        self.dist_conv_factor = 11000
        self.camera = camera
        self.geo_tracks = geo_tracks
        self.pv_groups = pv_groups
        self.multipoint_by_group_coord = {}
        self.multipoint_by_group_coord_dist = {}
        self.multipoint_by_group_coord_init = {}
        # Best common median time shift. Possibly outside the target time spread.
        self.best_used_ref_pv_groups = None
        self.best_time_spread = None
        self.best_dist_delta = None
        self.best_time_shifts = None
        self.best_median_time_shift = None

        self.time_delta = self.get_par(60, 'utc_cal_by_multi_track', 'time_delta')
        self.min_dist_delta = self.get_par(5, 'utc_cal_by_multi_track', 'min_dist_delta')
        self.max_dist_delta = self.get_par(50, 'utc_cal_by_multi_track', 'max_dist_delta')
        self.distance_step = self.get_par(5, 'utc_cal_by_multi_track', 'distance_step')
        self.min_files_num = max(self.get_par(3, 'utc_cal_by_multi_track', 'min_files_num'), 1)
        self.max_files_num = self.get_par(10, 'utc_cal_by_multi_track', 'max_files_num')
        self.dist_delta = self.min_dist_delta
        self.max_time_spread = self.get_par(2, 'utc_cal_by_multi_track', 'num_time_delta_spread') * self.time_delta
        self.ref_groups_by_coord = {}
        self.track_geo_points = {}
        self.track_multi_point = None
        self.branch_num = 0
        self.intersections_num = 0
        self.intersections = []

    def filtrate_groups_time_shifts_multipoints(self) -> typing.NoReturn:
        # Filter by distance delta
        # dist_delta - distances in meters.But we use "distances in degrees". In this case it will be much faster.
        dist_delta_deg = self.dist_delta / self.dist_conv_factor
        self.multipoint_by_group_coord_dist = {
            group_coord: self.to_mp(group_mps.intersection(Point(group_coord).buffer(dist_delta_deg)))
            for group_coord, group_mps in self.multipoint_by_group_coord_init.items()}

        # Filter by time delta. Get intersections for all reference groups as a base.
        # Choose the intersection with the smallest time spread
        t_shift_mp_by_group_coord = {coord: MultiPoint([(p.z, 0) for p in self.to_mp(mp).geoms])
                                     for coord, mp in self.multipoint_by_group_coord_dist.items()}

        # Walking the tree recursively. When the intersection with neighboring leaves becomes zero, stop the branch.
        self.get_inter_list_mp_with_mps(t_shift_mp_by_group_coord, 0)

        if self.best_time_spread:
            # For each group left only points with common time shift result.
            intersection_ext_point = Point(self.best_median_time_shift, 0).buffer(self.time_delta)
            self.multipoint_by_group_coord = {coord: MultiPoint([(p.x, p.y, p.z)
                                                                 for p in self.to_mp(group_mp).geoms
                                                                 if intersection_ext_point.intersection(Point(p.z, 0))])
                                              for coord, group_mp in self.multipoint_by_group_coord_dist.items()}
            self.multipoint_by_group_coord = {coord: mp for
                                              coord, mp in self.multipoint_by_group_coord.items()
                                              if mp}
            self.best_used_ref_pv_groups = [self.ref_groups_by_coord[coord].name
                                            for coord
                                            in self.multipoint_by_group_coord.keys()]

    def add_suitable_intersection_to_results(self,
                                             time_shift_mp: MultiPoint,
                                             used_groups: int) -> typing.NoReturn:
        t_shifts = [p.x for p in self.to_mp(time_shift_mp).geoms]
        time_spread = max(t_shifts) - min(t_shifts)
        median_time_shift = statistics.median(t_shifts)
        used_groups += 1
        # Check result and keep it only if number of used groups more than self.min_files_num
        # and time spread less than 'num_time_delta_spread' * self.time_delta.
        if used_groups >= self.min_files_num and t_shifts:
            self.intersections_num += 1
            # self.intersections.append((used_groups, time_spread, median_time_shift, t_shifts))
            if not self.best_time_spread or time_spread < self.best_time_spread:
                self.best_time_spread = time_spread
                self.best_median_time_shift = median_time_shift
                self.best_time_shifts = t_shifts.copy()
                self.best_dist_delta = self.dist_delta

    def get_inter_list_mp_with_mps(self,
                                   t_shift_mp_by_group_coord: typing.Dict[typing.Tuple[float, float], MultiPoint],
                                   used_groups: int) -> typing.NoReturn:
        self.branch_num += 1
        self.print_counter(f'Branches number {self.branch_num}, '
                           f'found intersections {self.intersections_num}, '
                           f'minimum time spread {self.best_time_spread}')
        if len(t_shift_mp_by_group_coord) > 1:
            for coord_st, mp_st in t_shift_mp_by_group_coord.items():
                if self.best_time_spread and self.best_time_spread < self.max_time_spread:
                    return
                if mp_st:
                    step_t_shift_mp_by_group_coord = {coord: self.to_mp(mp_st.buffer(self.time_delta).intersection(mp))
                                                      for coord, mp
                                                      in t_shift_mp_by_group_coord.items()
                                                      if coord != coord_st and mp}
                    step_t_shift_mp_by_group_coord = {coord: mp
                                                      for coord, mp
                                                      in step_t_shift_mp_by_group_coord.items()
                                                      if mp}
                    if len(t_shift_mp_by_group_coord) > len(step_t_shift_mp_by_group_coord) + 1:
                        self.add_suitable_intersection_to_results(mp_st, used_groups)
                    if step_t_shift_mp_by_group_coord:
                        self.get_inter_list_mp_with_mps(step_t_shift_mp_by_group_coord, used_groups + 1)
        elif len(t_shift_mp_by_group_coord) == 1:
            time_shift_mp = list(t_shift_mp_by_group_coord.values())[0]
            self.add_suitable_intersection_to_results(time_shift_mp, used_groups)
        else:
            self.print_log('e', 'calibr', f"{self.camera}: An unexpected situation.")
        self.branch_num -= 1
        self.print_counter(f'Branches number {self.branch_num}, '
                           f'found intersections {self.intersections_num}, '
                           f'minimum time spread {self.best_time_spread}')

    def print_empty_results(self, gr_coord: typing.Tuple[float, float]) -> typing.NoReturn:
        mp_inside_dist_delta = self.multipoint_by_group_coord_dist[gr_coord]
        if mp_inside_dist_delta:
            gr_t_shifts = [p.z for p in self.to_mp(mp_inside_dist_delta).geoms]
            max_t_shift = max(gr_t_shifts)
            min_t_shift = min(gr_t_shifts)
            gr_time_spread = max_t_shift - min_t_shift
            median_t_shift = statistics.median(gr_t_shifts)
            msg = f"{self.camera}: NO  {self.ref_groups_by_coord[gr_coord].name}: time_delta = {self.time_delta} s., " \
                  f"dist_delta = {self.dist_delta} m., median time shift = {median_t_shift}, " \
                  f"{len(mp_inside_dist_delta.geoms)} closest points time spread = {gr_time_spread} " \
                  f"from {min_t_shift} to {max_t_shift}"
            self.print_log('i', 'calibr', msg)

            if self.check_par('log_mode', ['cal_w_p_log', 'cal_w_p_print']):
                for p in mp_inside_dist_delta.geoms:
                    msg = f"{self.camera}: {self.ref_groups_by_coord[gr_coord].name}: track point: {(p.x, p.y)} " \
                          f"time shift = {p.z}, point time shift spread = {int(abs(p.z - median_t_shift))}, " \
                          f"distance = {int(distance((p.x, p.y), gr_coord).m)} m."
                    self.print_log('i', 'cal_wrong_points', msg)
        else:
            msg = f"{self.camera}: NO  {self.ref_groups_by_coord[gr_coord].name}: time_delta = {self.time_delta} s., " \
                  f"dist_delta = {self.dist_delta} m. No track-points closer {self.dist_delta} m."
            self.print_log('i', 'calibr', msg)

    def print_intermediate_results(self) -> typing.NoReturn:
        # Empty groups without common time shifts
        no_common_shifts_coord = [coord for coord
                                  in self.multipoint_by_group_coord_dist.keys()
                                  if coord not in self.multipoint_by_group_coord.keys()]
        for gr_coord in no_common_shifts_coord:
            if self.check_par('log_mode', ['calibr_log', 'calibr_print',
                                           'cal_w_p_log', 'cal_w_p_print']):
                self.print_empty_results(gr_coord)

        # Groups with common time shifts
        mp_by_group_coord_not_empty = {gr_coord: group_mps for
                                       gr_coord, group_mps in self.multipoint_by_group_coord.items() if group_mps}
        for gr_coord, group_mps in mp_by_group_coord_not_empty.items():
            gr_t_shifts = [p.z for p in group_mps.geoms]
            time_spread = max(gr_t_shifts) - min(gr_t_shifts)
            median_time_shift = statistics.median(gr_t_shifts)
            if len(gr_t_shifts) > 2:
                str_gr_t_shifts_list = f"{str(gr_t_shifts[0])} .. {str(gr_t_shifts[-1])}"
            else:
                str_gr_t_shifts_list = ', '.join([str(gs) for gs in gr_t_shifts])
            msg = f"{self.camera}: YES {self.ref_groups_by_coord[gr_coord].name}: time_delta = {self.time_delta} s., " \
                  f"dist_delta = {self.dist_delta} m., time spread: {time_spread}, median time shift: " \
                  f"{median_time_shift},  {len(gr_t_shifts)} shifts: {str_gr_t_shifts_list}"
            self.print_log('i', 'calibr', msg)

        # Print/log step result
        if self.best_median_time_shift:
            msg = f"{self.camera}: Step results: median time shift: {self.best_median_time_shift}, time delta = " \
                  f"{self.time_delta} s., distance delta = {self.dist_delta} m., num time shifts: " \
                  f"{len(self.best_time_shifts)}, time spread: {self.best_time_spread}, " \
                  f"num reference files: {len(self.best_used_ref_pv_groups)}"
        else:
            msg = f"{self.camera}: Step results: no time shifts for time delta = {self.time_delta} s., " \
                  f"distance delta = {self.dist_delta} m."
        self.print_log('i', 'calibr', msg)

    def data_prepare(self) -> bool:
        # Get utc_relative_base_time for calibrate UTC time in each pv_group
        for pv_group in [gr for gr in self.pv_groups.values() if gr.camera_key == self.camera]:
            pv_group.get_utc_relative_base_time()

        if not self.geo_tracks or not self.geo_tracks.tracks:
            self.print_log('w', 'calibr', f"{self.camera}: No geo-tracks loaded calibrating stopped.")
            return False

        # Get reference files with geo-information from non-gps photo/video device 'camera'.
        max_files_num = self.get_par(10, 'utc_cal_by_multi_track', 'max_files_num')
        groups_coord_list = [pv_group.coord for pv_group in self.pv_groups.values()
                             if pv_group.coord
                             and pv_group.coord_source in ['by_hand']
                             and pv_group.camera_key == self.camera][:max_files_num]

        if not groups_coord_list:
            self.print_log('w', 'calibr', f"{self.camera}: No reference files for calibrate  - calibrating stopped.")
            return False
        self.ref_groups_by_coord = {pv_group.coord: pv_group
                                    for group_name, pv_group in self.pv_groups.items()
                                    if pv_group.coord in groups_coord_list}

        # Get one list of all geo-points
        self.track_geo_points = {point.coord: point for p_list in self.geo_tracks.tracks for point in p_list.points}
        # Create from all geo-points shapely MultiPoint structure for fast search intersections. As third coordinate
        # use time dump of UTC time of geo-point
        self.track_multi_point = MultiPoint([(point.lat, point.lon, point.utc_dt.timestamp())
                                             for point in self.track_geo_points.values()])

        # For each reference pv_group select all points from geo_tracks that are in dist_spread degrees from
        # the current reference pv_group or closer.
        # Create Dictionary {coordinates pv_group: shapely MultiPoint}  As third coordinate in that shapely points
        # use time difference between UTC datetime of geo-point and utc_relative_base_time from pv_group.
        self.multipoint_by_group_coord_init = {}
        max_d_s_deg = self.max_dist_delta / self.dist_conv_factor
        for pv_group in self.ref_groups_by_coord.values():
            # Get shapely MultiPoint that are in dist_spread degrees or closer.
            mp_max_dist_spread = self.track_multi_point.intersection(Point(pv_group.coord).buffer(max_d_s_deg))
            if mp_max_dist_spread:
                self.multipoint_by_group_coord_init[pv_group.coord] = MultiPoint(
                    [(p.x, p.y, func.diff_utc_and_stamp(pv_group.utc_relative_base_time, p.z))
                     for p in self.to_mp(mp_max_dist_spread).geoms])

        if self.multipoint_by_group_coord_init:
            msg = f"{self.camera}: Start getting time shift using {len(self.multipoint_by_group_coord_init)} of " \
                  f"{len(self.ref_groups_by_coord)} geolocated groups. Files close to the track are selected."
            self.print_log('i', 'calibr', msg)
            if self.check_par('log_mode', ['calibr_log', 'calibr_print']):
                for pv_group_coord in self.multipoint_by_group_coord_init.keys():
                    self.print_log('i', 'calibr', f"{self.camera}: {self.ref_groups_by_coord[pv_group_coord].name}")
        else:
            self.print_log('i', 'calibr', f"{self.camera}: No reference files closer {self.max_dist_delta} m. to the "
                                          f"track - calibrating stopped.")
            return False

        return True

    def get_camera_utc_dt_shift(self) -> typing.Optional[timedelta]:
        if not self.data_prepare():
            return None

        stop_flag = False
        if self.ref_groups_by_coord:
            while not stop_flag:
                self.filtrate_groups_time_shifts_multipoints()
                self.print_intermediate_results()

                stop_flag_over_dist = self.dist_delta > self.max_dist_delta
                stop_flag_time_spread = self.best_time_spread and self.best_time_spread < self.max_time_spread
                stop_flag = stop_flag_time_spread or stop_flag_over_dist
                if not stop_flag:
                    self.dist_delta += self.distance_step

            if self.best_time_spread:
                msg = f"{self.camera}: Got time shift: {self.best_median_time_shift}, " \
                      f"time spread: {self.best_time_spread}, distance delta = {self.best_dist_delta} m."
                if self.best_time_spread > self.max_time_spread:
                    msg += " Check time spread !!!!"
                msg += f" From {len(self.best_used_ref_pv_groups)} reference files:"
                self.print_log('i', 'calibr', msg)
                for pv_group_name in self.best_used_ref_pv_groups:
                    self.print_log('i', 'calibr', f"{self.camera}: {pv_group_name}")
                return self.best_median_time_shift
            else:
                msg = f"{self.camera}: Can't find common time shift at least for {self.min_files_num} files."
                self.print_log('i', 'calibr', msg)
                return None
        else:
            msg = f"{self.camera}: No reference files was found with manually set coordinates. Calibrating stopped."
            self.print_log('i', 'calibr', msg)
            return None

    @staticmethod
    def to_mp(any_obj: typing.Union[MultiPoint, Point]) -> MultiPoint:
        if any_obj.type == 'MultiPoint':
            multi_point_result = any_obj
        elif any_obj.type == 'Point' and any_obj:
            multi_point_result = MultiPoint([any_obj])
        else:
            multi_point_result = MultiPoint()
        return multi_point_result

    # @staticmethod
    # def mp_to_coord_list(multi_point):
    #     return [geom.coords[0] for geom in multi_point.geoms] if multi_point.type == 'MultiPoint' else \
    #         [multi_point.coords[0]] if multi_point and multi_point.type == 'Point' else []

    # @staticmethod
    # def mp_to_t_shift_list(multi_point):
    #     return [geom.z for geom in multi_point.geoms] if multi_point.type == 'MultiPoint' else \
    #         [multi_point.z] if multi_point and multi_point.type == 'Point' else []
