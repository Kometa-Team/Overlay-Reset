import logging, os, sys, util
from datetime import datetime
from xml.etree.ElementTree import ParseError
from urllib.parse import quote
from util import Failed

try:
    import cv2, numpy, plexapi, requests
    from PIL import Image, ImageFile
    from plexapi.exceptions import BadRequest, NotFound, Unauthorized
    from plexapi.server import PlexServer
    from plexapi.video import Movie, Show, Season, Episode
    from tmdbapis import TMDbAPIs, TMDbException
except (ModuleNotFoundError, ImportError):
    print("Requirements Error: Requirements are not installed")
    sys.exit(0)

if sys.version_info[0] != 3 or sys.version_info[1] < 7:
    print("Version Error: Version: %s.%s.%s incompatible please use Python 3.7+" % (sys.version_info[0], sys.version_info[1], sys.version_info[2]))
    sys.exit(0)

options = [
    {"arg": "u",  "key": "url",      "env": "PLEX_URL",     "type": "str",  "default": None,  "help": "Plex URL of the Server you want to connect to."},
    {"arg": "t",  "key": "token",    "env": "PLEX_TOKEN",   "type": "str",  "default": None,  "help": "Plex Token of the Server you want to connect to."},
    {"arg": "l",  "key": "library",  "env": "PLEX_LIBRARY", "type": "str",  "default": None,  "help": "Plex Library Name you want to reset."},
    {"arg": "a",  "key": "asset",    "env": "PMM_ASSET",    "type": "str",  "default": None,  "help": "PMM Asset Folder to Scan for restoring posters."},
    {"arg": "o",  "key": "original", "env": "PMM_ORIGINAL", "type": "str",  "default": None,  "help": "PMM Original Folder to Scan for restoring posters."},
    {"arg": "ta", "key": "tmdbapi",  "env": "TMDBAPI",      "type": "str",  "default": None,  "help": "TMDb V3 API Key for restoring posters from TMDb."},
    {"arg": "re", "key": "resume",   "env": "RESUME",       "type": "str",  "default": None,  "help": "Plex Item Title to Resume restoring posters from."},
    {"arg": "ti", "key": "timeout",  "env": "TIMEOUT",      "type": "int",  "default": 600,   "help": "Timeout can be any number greater then 0. (Default: 600)"},
    {"arg": "d",  "key": "dry",      "env": "DRY_RUN",      "type": "bool", "default": False, "help": "Run as a Dry Run without making changes in Plex."},
    {"arg": "f",  "key": "flat",     "env": "PMM_FLAT",     "type": "bool", "default": False, "help": "PMM Asset Folder uses Flat Assets Image Paths."},
    {"arg": "s",  "key": "season",   "env": "SEASON",       "type": "bool", "default": False, "help": "Restore Season posters during run."},
    {"arg": "e",  "key": "episode",  "env": "EPISODE",      "type": "bool", "default": False, "help": "Restore Episode posters during run."},
    {"arg": "tr", "key": "trace",    "env": "TRACE",        "type": "bool", "default": False, "help": "Run with every request logged."}
]

choices = util.init(options, "")
url_parsed = requests.utils.urlparse(choices["url"]).netloc
secrets = [choices["url"], choices["token"], choices["tmdbapi"], quote(str(choices["url"])), url_parsed]
util.init_logger("overlay_reset", secrets=secrets, trace=choices["trace"])
logger = util.logger
sys.excepthook = util.my_except_hook
requests.Session.send = util.update_send(requests.Session.send, choices["timeout"])
plexapi.BASE_HEADERS["X-Plex-Client-Identifier"] = util.get_uuid()
ImageFile.LOAD_TRUNCATED_IMAGES = True
util.header("Complete Overlay Reset")

try:
    if not choices["url"]:
        raise Failed("Error: No Plex URL Provided")
    if not choices["token"]:
        raise Failed("Error: No Plex Token Provided")
    if not choices["library"]:
        raise Failed("Error: No Plex Library Name Provided")
    try:
        server = PlexServer(choices["url"], choices["token"], timeout=choices["timeout"])
        plexapi.server.TIMEOUT = choices["timeout"]
        os.environ["PLEXAPI_PLEXAPI_TIMEOUT"] = str(choices["timeout"])
    except Unauthorized:
        raise Failed("Plex Error: Plex token is invalid")
    except (requests.exceptions.ConnectionError, ParseError):
        raise Failed("Plex Error: Plex url is invalid")
    lib = next((s for s in server.library.sections() if s.title == choices["library"]), None)
    if not lib:
        raise Failed(f"Plex Error: Library: {choices['library']} not found. Options: {', '.join([s.title for s in server.library.sections()])}")
    if lib.type not in ["movie", "show"]:
        raise Failed("Plex Error: Plex Library must be Movie or Show")

    tmdbapi = None
    if choices["tmdbapi"]:
        try:
            tmdbapi = TMDbAPIs(choices["tmdbapi"])
        except TMDbException as e:
            logger.error(e)

    overlay_directory = os.path.join(util.base_dir, "overlays")
    config_overlay_directory = os.path.join(util.config_dir, "overlays")
    if not os.path.exists(overlay_directory):
        raise Failed(f"Folder Error: overlays Folder not found {os.path.abspath(overlay_directory)}")
    if not os.path.exists(config_overlay_directory):
        os.makedirs(config_overlay_directory)
    overlay_images = util.glob_filter(os.path.join(overlay_directory, "*.png")) + util.glob_filter(os.path.join(config_overlay_directory, "*.png"))
    if not overlay_images:
        raise Failed(f"Images Error: overlays Folder Images not found {os.path.abspath(os.path.join(overlay_directory, '*.png'))}")

    def detect_overlay_in_image(poster_source, img_path=None, url_path=None):
        out_path = img_path
        if url_path:
            img_path = util.download_image(url_path)
            out_path = url_path
        with Image.open(img_path) as pil_image:
            exif_tags = pil_image.getexif()
        if 0x04bc in exif_tags and exif_tags[0x04bc] == "overlay":
            logger.debug(f"Overlay Detected: EXIF Overlay Tag Found ignoring {poster_source}: {out_path}")
            return True

        target = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE)
        if target is None:
            logger.error(f"Image Load Error: {poster_source}: {out_path}")
            return False
        if target.shape[0] < 500 or target.shape[1] < 500:
            logger.error(f"Image Error: {poster_source}: Dimensions {target.shape[0]}x{target.shape[1]} must be greater then 500x500: {out_path}")
            return False
        for overlay_image in overlay_images:
            overlay = cv2.imread(overlay_image, cv2.IMREAD_GRAYSCALE)
            if overlay is None:
                logger.error(f"Image Load Error: {overlay_image}")
                continue

            if overlay.shape[0] > target.shape[0] or overlay.shape[1] > target.shape[1]:
                logger.error(f"Image Error: {overlay_image} is larger than {poster_source}: {out_path}")
                continue

            template_result = cv2.matchTemplate(target, overlay, cv2.TM_CCOEFF_NORMED)
            loc = numpy.where(template_result >= 0.95)

            if len(loc[0]) == 0:
                continue
            logger.debug(f"Overlay Detected: {overlay_image} found in {poster_source}: {out_path} with score {template_result.max()}")
            return True
        return False

    assets_directory = os.path.join(util.base_dir, "assets")
    if os.path.exists(assets_directory) and os.listdir(assets_directory) and not choices["asset"]:
        choices["asset"] = assets_directory
    if choices["asset"]:
        choices["asset"] = os.path.abspath(choices["asset"])
        if not os.path.exists(choices["asset"]):
            raise Failed(f"Folder Error: Asset Folder Path Not Found: {os.path.abspath(choices['asset_folder'])}")

    originals_directory = os.path.join(util.base_dir, "originals")
    if os.path.exists(originals_directory) and os.listdir(originals_directory) and not choices["original"]:
        choices["original"] = originals_directory
    if choices["original"]:
        choices["original"] = os.path.abspath(choices["original"])
        if not os.path.exists(choices["original"]):
            raise Failed(f"Folder Error: Original Folder Path Not Found: {os.path.abspath(choices['original'])}")

    def reset_poster(plex_item, tmdb_poster_url, asset_directory, asset_file_name):
        poster_source = None
        poster_path = None

        # Check Assets
        if asset_directory:
            asset_matches = util.glob_filter(os.path.join(asset_directory, f"{asset_file_name}.*"))
            if len(asset_matches) > 0:
                poster_source = "asset"
                poster_path = asset_matches[0]
            else:
                logger.info("No Asset Found")

        # Check Original Folder
        if not poster_source and choices["original"]:
            png = os.path.join(choices["original"], f"{plex_item.ratingKey}.png")
            jpg = os.path.join(choices["original"], f"{plex_item.ratingKey}.jpg")
            if os.path.exists(png) and detect_overlay_in_image("Original Poster", img_path=png) is False:
                poster_source = "original"
                poster_path = png
            elif os.path.exists(jpg) and detect_overlay_in_image("Original Poster", img_path=jpg) is False:
                poster_source = "original"
                poster_path = jpg
            else:
                logger.info("No Original Found")

        # Check Plex
        if not poster_source:
            plex_image_url = None
            for p, plex_poster in enumerate(plex_item.posters(), 1):
                if plex_poster.key.startswith("/"):
                    plex_image_url = f"{choices['url']}{plex_poster.key}&X-Plex-Token={choices['token']}"
                    if plex_poster.ratingKey.startswith("upload"):
                        if detect_overlay_in_image(f"Plex Poster {p}", url_path=plex_image_url) is not False:
                            continue
                else:
                    plex_image_url = plex_poster.key
                break
            if plex_image_url:
                poster_source = "plex"
                poster_path = plex_image_url
            else:
                logger.into("No Clean Plex Image Found")

        # TMDb
        if not poster_source:
            if tmdb_poster_url:
                poster_source = "tmdb"
                poster_path = tmdb_poster_url
            else:
                logger.into("No TMDb Image Found")

        # Upload poster and Remove "Overlay" Label
        if poster_source:
            logger.info(f"Image Source: {poster_source}")
            logger.info(f"Image Path: {poster_path}")
            if not choices["dry"]:
                if poster_source == "plex":
                    plex_item.uploadPoster(url=poster_path)
                else:
                    plex_item.uploadPoster(filepath=poster_path)
            logger.info("Poster Successfully Reset")
            if "Overlay" in [la.tag for la in plex_item.labels]:
                if not choices["dry"]:
                    plex_item.removeLabel("Overlay")
                logger.info("Overlay Label Removed")
        else:
            logger.error("Image Error: No Image Found to Restore")

    def get_title(plex_item):
        if isinstance(plex_item, Movie):
            return f"Movie: {item.title}"
        elif isinstance(plex_item, Show):
            return f"Show: {item.title}"
        elif isinstance(plex_item, Season):
            if season.title == f"Season {season.seasonNumber}":
                return season.title
            return f"Season {season.seasonNumber}: {season.title}"
        elif isinstance(plex_item, Episode):
            return f"Episode {episode.seasonEpisode.upper()}: {episode.title}"
        else:
            return f"Item: {item.title}"

    def reload(plex_item):
        try:
            plex_item.reload(checkFiles=False, includeAllConcerts=False, includeBandwidths=False, includeChapters=False,
                             includeChildren=False, includeConcerts=False, includeExternalMedia=False, includeExtras=False,
                             includeFields=False, includeGeolocation=False, includeLoudnessRamps=False, includeMarkers=False,
                             includeOnDeck=False, includePopularLeaves=False, includeRelated=False, includeRelatedCount=0,
                             includeReviews=False, includeStations=False)
        except (BadRequest, NotFound) as e1:
            raise Failed(f"Plex Error: {get_title(plex_item)} Failed to Load: {e1}")

    if choices["resume"]:
        logger.info(f'Resume From "{choices["resume"]}"')
    items = lib.all()
    total_items = len(items)
    for i, item in enumerate(items):
        start_time = datetime.now()
        if choices["resume"] and item.title != choices["resume"]:
            logger.info(f"Skipping {i + 1}/{total_items} {item.title}")
            continue
        logger.info(util.separator())
        logger.info(f"Resetting {i + 1}/{total_items} {item.title}")
        try:
            reload(item)
        except Failed as e:
            logger.error(e)
            continue

        # Find Item's PMM Asset Directory
        item_asset_directory = None
        asset_name = None
        if choices["asset"]:
            if not item.locations:
                logger.error(f"Asset Error: No video filepath found fo {item.title}")
            else:
                file_name = "poster"
                path_test = str(item.locations[0])
                if not os.path.dirname(path_test):
                    path_test = path_test.replace("\\", "/")
                asset_name = util.validate_filename(os.path.basename(os.path.dirname(path_test) if isinstance(item, Movie) else path_test))
                if choices["flat"]:
                    item_asset_directory = choices["asset"]
                    file_name = asset_name
                elif os.path.isdir(os.path.join(choices["asset"], asset_name)):
                    item_asset_directory = os.path.join(choices["asset"], asset_name)
                else:
                    for n in range(1, 5):
                        new_path = choices["asset"]
                        for m in range(1, n + 1):
                            new_path = os.path.join(new_path, "*")
                        matches = util.glob_filter(os.path.join(new_path, asset_name))
                        if len(matches) > 0:
                            item_asset_directory = os.path.abspath(matches[0])
                            break
                if not item_asset_directory:
                    logger.warning(f"Asset Warning: No Asset Directory Found")

        tmdb_item = None
        if tmdbapi:
            guid = requests.utils.urlparse(item.guid)
            item_type = guid.scheme.split(".")[-1]
            check_id = guid.netloc
            tmdb_id = None
            tvdb_id = None
            imdb_id = None
            if item_type == "plex":
                for guid_tag in item.guids:
                    url_parsed = requests.utils.urlparse(guid_tag.id)
                    if url_parsed.scheme == "tvdb":
                        tvdb_id = int(url_parsed.netloc)
                    elif url_parsed.scheme == "imdb":
                        imdb_id = url_parsed.netloc
                    elif url_parsed.scheme == "tmdb":
                        tmdb_id = int(url_parsed.netloc)
                if not tvdb_id and not imdb_id and not tmdb_id:
                    item.refresh()
            elif item_type == "imdb":
                imdb_id = check_id
            elif item_type == "thetvdb":
                tvdb_id = int(check_id)
            elif item_type == "themoviedb":
                tmdb_id = int(check_id)
            elif item_type in ["xbmcnfo", "xbmcnfotv"]:
                if len(check_id) > 10:
                    logger.warning(f"XMBC NFO Local ID: {check_id}")
                try:
                    if item_type == "xbmcnfo":
                        tmdb_id = int(check_id)
                    else:
                        tvdb_id = int(check_id)
                except ValueError:
                    imdb_id = check_id
            if not tvdb_id and not imdb_id and not tmdb_id:
                logger.error("Plex Error: No External GUIDs found")
            if not tmdb_id and imdb_id:
                try:
                    results = tmdbapi.find_by_id(imdb_id=imdb_id)
                    if results.movie_results and isinstance(item, Movie):
                        tmdb_id = results.movie_results[0].id
                    elif results.tv_results and isinstance(item, Show):
                        tmdb_id = results.tv_results[0].id
                except TMDbException as e:
                    logger.error(e)
            if not tmdb_id and tvdb_id and isinstance(item, Show):
                try:
                    results = tmdbapi.find_by_id(tvdb_id=tvdb_id)
                    if results.tv_results:
                        tmdb_id = results.tv_results[0].id
                except TMDbException as e:
                    logger.error(e)
            if tmdb_id:
                tmdb_item = tmdbapi.movie(tmdb_id) if isinstance(item, Movie) else tmdbapi.tv_show(tmdb_id)
            else:
                logger.error("Plex Error: TMDb ID Not Found")

        reset_poster(item, tmdb_item.poster_url if tmdb_item else None, item_asset_directory, asset_name if choices["flat"] else "poster")

        logger.info(f"Run Time: {str(datetime.now() - start_time).split('.')[0]}")

        if isinstance(item, Show) and (choices["season"] or choices["episode"]):
            tmdb_seasons = {s.season_number: s for s in tmdb_item.seasons} if tmdb_item else {}
            for season in item.seasons():
                if choices["season"]:
                    start_time = datetime.now()
                    logger.info(util.separator())
                    logger.info(f"Resetting {item.title} Season {season.seasonNumber}: {season.title}")
                    try:
                        reload(season)
                    except Failed as e:
                        logger.error(e)
                        continue
                    tmdb_poster = tmdb_seasons[season.seasonNumber].poster_url if season.seasonNumber in tmdb_seasons else None
                    file_name = f"Season{'0' if not season.seasonNumber or season.seasonNumber < 10 else ''}{season.seasonNumber}"
                    reset_poster(season, tmdb_poster, item_asset_directory, f"{asset_name}_{file_name}" if choices["flat"] else file_name)

                    logger.info(f"Run Time: {str(datetime.now() - start_time).split('.')[0]}")

                if choices["episode"]:
                    if not choices["season"]:
                        try:
                            reload(season)
                        except Failed as e:
                            logger.error(e)
                            continue
                    tmdb_episodes = {}
                    if season.seasonNumber in tmdb_seasons:
                        for episode in tmdb_seasons[season.seasonNumber].episodes:
                            episode._partial = False
                            try:
                                tmdb_episodes[episode.episode_number] = episode
                            except TMDbException:
                                logger.error(f"TMDb Error: An Episode of Season {season.seasonNumber} was Not Found")

                    for episode in season.episodes():
                        start_time = datetime.now()
                        logger.info(util.separator())
                        logger.info(f"Resetting {item.title} Episode {episode.seasonEpisode.upper()}: {episode.title}")
                        try:
                            reload(episode)
                        except Failed as e:
                            logger.error(e)
                            continue
                        tmdb_poster = tmdb_episodes[episode.episodeNumber].still_url if episode.episodeNumber in tmdb_episodes else None
                        file_name = episode.seasonEpisode.upper()
                        reset_poster(episode, tmdb_poster, item_asset_directory, f"{asset_name}_{file_name}" if choices["flat"] else file_name)
                        logger.info(f"Run Time: {str(datetime.now() - start_time).split('.')[0]}")
except Failed as e:
    logger.info(util.separator())
    logger.critical(e)
    logger.info(util.separator())
