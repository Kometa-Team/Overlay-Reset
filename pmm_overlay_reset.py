import os, sys
from xml.etree.ElementTree import ParseError
from urllib.parse import quote

if sys.version_info[0] != 3 or sys.version_info[1] < 11:
    print("Version Error: Version: %s.%s.%s incompatible please use Python 3.11+" % (sys.version_info[0], sys.version_info[1], sys.version_info[2]))
    sys.exit(0)

try:
    import cv2, numpy, plexapi, requests
    from pmmutils import logging, util
    from PIL import Image, ImageFile, UnidentifiedImageError
    from plexapi.exceptions import BadRequest, NotFound, Unauthorized
    from plexapi.server import PlexServer
    from plexapi.video import Movie, Show, Season, Episode
    from pmmutils.args import PMMArgs
    from pmmutils.exceptions import Failed
    from tmdbapis import TMDbAPIs, TMDbException
except (ModuleNotFoundError, ImportError) as e:
    print(e)
    print("Requirements Error: Requirements are not installed")
    sys.exit(0)

options = [
    {"arg": "u",  "key": "url",           "env": "PLEX_URL",      "type": "str",  "default": None,  "help": "Plex URL of the Server you want to connect to."},
    {"arg": "t",  "key": "token",         "env": "PLEX_TOKEN",    "type": "str",  "default": None,  "help": "Plex Token of the Server you want to connect to."},
    {"arg": "l",  "key": "library",       "env": "PLEX_LIBRARY",  "type": "str",  "default": None,  "help": "Plex Library Name you want to reset."},
    {"arg": "a",  "key": "asset",         "env": "PMM_ASSET",     "type": "str",  "default": None,  "help": "PMM Asset Folder to Scan for restoring posters."},
    {"arg": "o",  "key": "original",      "env": "PMM_ORIGINAL",  "type": "str",  "default": None,  "help": "PMM Original Folder to Scan for restoring posters."},
    {"arg": "ta", "key": "tmdbapi",       "env": "TMDBAPI",       "type": "str",  "default": None,  "help": "TMDb V3 API Key for restoring posters from TMDb."},
    {"arg": "st", "key": "start",         "env": "START",         "type": "str",  "default": None,  "help": "Plex Item Title to Start restoring posters from."},
    {"arg": "it", "key": "items",         "env": "ITEMS",         "type": "str",  "default": None,  "help": "Restore specific Plex Items by Title. Can use a bar-separated (|) list."},
    {"arg": "lb", "key": "labels",        "env": "LABELS",        "type": "str",  "default": None,  "help": "Additional labels to remove. Can use a bar-separated (|) list."},
    {"arg": "di", "key": "discord",       "env": "DISCORD",       "type": "str",  "default": None,  "help": "Webhook URL to channel for Notifications."},
    {"arg": "ti", "key": "timeout",       "env": "TIMEOUT",       "type": "int",  "default": 600,   "help": "Timeout can be any number greater then 0. (Default: 600)"},
    {"arg": "d",  "key": "dry",           "env": "DRY_RUN",       "type": "bool", "default": False, "help": "Run as a Dry Run without making changes in Plex."},
    {"arg": "f",  "key": "flat",          "env": "PMM_FLAT",      "type": "bool", "default": False, "help": "PMM Asset Folder uses Flat Assets Image Paths."},
    {"arg": "nm", "key": "no-main",       "env": "NO_MAIN",       "type": "bool", "default": False, "help": "Do not restore the Main Movie/Show posters during run."},
    {"arg": "s",  "key": "season",        "env": "SEASON",        "type": "bool", "default": False, "help": "Restore Season posters during run."},
    {"arg": "e",  "key": "episode",       "env": "EPISODE",       "type": "bool", "default": False, "help": "Restore Episode posters during run."},
    {"arg": "ir", "key": "ignore-resume", "env": "IGNORE_RESUME", "type": "bool", "default": None,  "help": "Ignores the automatic resume."},
    {"arg": "tr", "key": "trace",         "env": "TRACE",         "type": "bool", "default": False, "help": "Run with extra trace logs."},
    {"arg": "lr", "key": "log-requests",  "env": "LOG_REQUESTS",  "type": "bool", "default": False, "help": "Run with every request logged."}
]
script_name = "PMM Overlay Reset"
base_dir = os.path.dirname(os.path.abspath(__file__))
config_dir = os.path.join(base_dir, "config")
resume_file = os.path.join(config_dir, "resume.por")

pmmargs = PMMArgs("meisnate12/PMM-Overlay-Reset", base_dir, options, use_nightly=False)
logger = logging.PMMLogger(script_name, "overlay_reset", os.path.join(config_dir, "logs"), discord_url=pmmargs["discord"], is_trace=pmmargs["trace"], log_requests=pmmargs["log-requests"])
logger.secret([pmmargs["url"], pmmargs["discord"], pmmargs["tmdbapi"], pmmargs["token"], quote(str(pmmargs["url"])), requests.utils.urlparse(pmmargs["url"]).netloc])
requests.Session.send = util.update_send(requests.Session.send, pmmargs["timeout"])
plexapi.BASE_HEADERS["X-Plex-Client-Identifier"] = pmmargs.uuid
ImageFile.LOAD_TRUNCATED_IMAGES = True

logger.header(pmmargs, sub=True, discord_update=True)
logger.separator("Validating Options", space=False, border=False)
try:
    logger.info("Script Started", log=False, discord=True, start="script")
except Failed as e:
    logger.error(f"Discord URL Error: {e}")
report = []
current_rk = None
run_type = ""
try:
    # Connect to Plex
    if not pmmargs["url"]:
        raise Failed("Error: No Plex URL Provided")
    if not pmmargs["token"]:
        raise Failed("Error: No Plex Token Provided")
    if not pmmargs["library"]:
        raise Failed("Error: No Plex Library Name Provided")
    try:
        server = PlexServer(pmmargs["url"], pmmargs["token"], timeout=pmmargs["timeout"])
        plexapi.server.TIMEOUT = pmmargs["timeout"]
        os.environ["PLEXAPI_PLEXAPI_TIMEOUT"] = str(pmmargs["timeout"])
        logger.info("Plex Connection Successful")
    except Unauthorized:
        raise Failed("Plex Error: Plex token is invalid")
    except (requests.exceptions.ConnectionError, ParseError):
        raise Failed("Plex Error: Plex url is invalid")
    lib = next((s for s in server.library.sections() if s.title == pmmargs["library"]), None)
    if not lib:
        raise Failed(f"Plex Error: Library: {pmmargs['library']} not found. Options: {', '.join([s.title for s in server.library.sections()])}")
    if lib.type not in ["movie", "show"]:
        raise Failed("Plex Error: Plex Library must be Movie or Show")

    # Connect to TMDb
    tmdbapi = None
    if pmmargs["tmdbapi"]:
        try:
            tmdbapi = TMDbAPIs(pmmargs["tmdbapi"])
            logger.info("TMDb Connection Successful")
        except TMDbException as e:
            logger.error(e)

    # Check Labels
    labels = ["Overlay"]
    if pmmargs["labels"]:
        labels.extend(pmmargs["labels"].split("|"))
    logger.info(f"Labels to be Removed: {', '.join(labels)}")

    # Check for Overlay Files
    overlay_directory = os.path.join(base_dir, "overlays")
    config_overlay_directory = os.path.join(config_dir, "overlays")
    if not os.path.exists(overlay_directory):
        raise Failed(f"Folder Error: overlays Folder not found {os.path.abspath(overlay_directory)}")
    if not os.path.exists(config_overlay_directory):
        os.makedirs(config_overlay_directory)
    overlay_images = util.glob_filter(os.path.join(overlay_directory, "*.png")) + util.glob_filter(os.path.join(config_overlay_directory, "*.png"))
    if not overlay_images:
        raise Failed(f"Images Error: overlays Folder Images not found {os.path.abspath(os.path.join(overlay_directory, '*.png'))}")
    logger.info("overlays Folder Images Loaded Successfully ")

    # Check for Assets Folder
    assets_directory = os.path.join(base_dir, "assets")

    if os.path.exists(assets_directory) and os.listdir(assets_directory) and not pmmargs["asset"]:
        pmmargs["asset"] = assets_directory
    if pmmargs["asset"]:
        pmmargs["asset"] = os.path.abspath(pmmargs["asset"])
        if not os.path.exists(pmmargs["asset"]):
            raise Failed(f"Folder Error: Asset Folder Path Not Found: {pmmargs['asset']}")
        logger.info(f"Asset Folder Loaded: {pmmargs['asset']}")
    else:
        logger.warning("No Asset Folder Found")

    # Check for Originals Folder
    originals_directory = os.path.join(base_dir, "originals")
    if os.path.exists(originals_directory) and os.listdir(originals_directory) and not pmmargs["original"]:
        pmmargs["original"] = originals_directory
    if pmmargs["original"]:
        pmmargs["original"] = os.path.abspath(pmmargs["original"])
        if not os.path.exists(pmmargs["original"]):
            raise Failed(f"Folder Error: Original Folder Path Not Found: {os.path.abspath(pmmargs['original'])}")
        logger.info(f"Originals Folder Loaded: {pmmargs['original']}")
    else:
        logger.warning("No Originals Folder Found")

    def detect_overlay_in_image(item_title, poster_source, shape, img_path=None, url_path=None):
        out_path = img_path
        if url_path:
            img_path = util.download_image(url_path, config_dir)
            out_path = url_path

        try:
            with Image.open(img_path) as pil_image:
                exif_tags = pil_image.getexif()
                if 0x04bc in exif_tags and exif_tags[0x04bc] == "overlay":
                    logger.debug(f"Overlay Detected: EXIF Overlay Tag Found ignoring {poster_source}: {out_path}")
                    return True
                if (shape == "portrait" and pil_image.size != (1000, 1500)) or (shape == "landscape" and pil_image.size != (1920, 1080)):
                    logger.debug("No Overlay: Image not standard overlay size")
                    return False
        except UnidentifiedImageError:
            logger.error(f"Image Load Error: {poster_source}: {out_path}", group=item_title)
            return None

        target = cv2.imread(img_path, cv2.IMREAD_GRAYSCALE) # noqa
        if target is None:
            logger.error(f"Image Load Error: {poster_source}: {out_path}", group=item_title)
            return None
        if target.shape[0] < 500 or target.shape[1] < 500:
            logger.info(f"Image Error: {poster_source}: Dimensions {target.shape[0]}x{target.shape[1]} must be greater then 500x500: {out_path}")
            return False
        for overlay_image in overlay_images:
            overlay = cv2.imread(overlay_image, cv2.IMREAD_GRAYSCALE) # noqa
            if overlay is None:
                logger.error(f"Image Load Error: {overlay_image}", group=item_title)
                continue

            if overlay.shape[0] > target.shape[0] or overlay.shape[1] > target.shape[1]:
                logger.error(f"Image Error: {overlay_image} is larger than {poster_source}: {out_path}", group=item_title)
                continue

            template_result = cv2.matchTemplate(target, overlay, cv2.TM_CCOEFF_NORMED) # noqa
            loc = numpy.where(template_result >= 0.95)

            if len(loc[0]) == 0:
                continue
            logger.debug(f"Overlay Detected: {overlay_image} found in {poster_source}: {out_path} with score {template_result.max()}")
            return True
        return False

    def reset_from_plex(item_title, item_with_posters, shape, ignore=0):
        for p, plex_poster in enumerate(item_with_posters.posters(), 1):
            logger.trace(plex_poster.key)
            reset_url = None
            if plex_poster.key.startswith("/"):
                temp_url = f"{pmmargs['url']}{plex_poster.key}&X-Plex-Token={pmmargs['token']}"
                user = plex_poster.ratingKey.startswith("upload")
                if not user or (user and detect_overlay_in_image(item_title, f"Plex Poster {p}", shape, url_path=temp_url) is False):
                    reset_url = temp_url
            else:
                reset_url = plex_poster.key
            if reset_url:
                if ignore < 1:
                    return reset_url
                else:
                    ignore -= 1

    def reset_poster(item_title, plex_item, tmdb_poster_url, asset_directory, asset_file_name, parent=None, shape="portrait"):
        poster_source = None
        poster_path = None

        # Check Assets
        if asset_directory:
            asset_matches = util.glob_filter(os.path.join(asset_directory, f"{asset_file_name}.*"))
            if len(asset_matches) > 0:
                poster_source = "Assets Folder"
                poster_path = asset_matches[0]
            else:
                logger.info("No Asset Found")

        # Check Original Folder
        if not poster_source and pmmargs["original"]:
            png = os.path.join(pmmargs["original"], f"{plex_item.ratingKey}.png")
            jpg = os.path.join(pmmargs["original"], f"{plex_item.ratingKey}.jpg")
            if os.path.exists(png) and detect_overlay_in_image(item_title, "Original Poster", shape, img_path=png) is False:
                poster_source = "Originals Folder"
                poster_path = png
            elif os.path.exists(jpg) and detect_overlay_in_image(item_title, "Original Poster", shape, img_path=jpg) is False:
                poster_source = "Originals Folder"
                poster_path = jpg
            else:
                logger.info("No Original Found")

        # Check Plex
        if not poster_source:
            poster_path = reset_from_plex(item_title, plex_item, shape)
            if poster_path:
                poster_source = "Plex"
            else:
                logger.info("No Clean Plex Image Found")

        # TMDb
        if not poster_source:
            if tmdb_poster_url:
                poster_source = "TMDb"
                poster_path = tmdb_poster_url
            else:
                logger.info("No TMDb Image Found")

        # Check Item's Show
        if not poster_source and parent:
            poster_path = reset_from_plex(item_title, parent, shape)
            if poster_path:
                poster_source = "Plex's Show"
            else:
                logger.info("No Clean Plex Show Image Found")

        def upload(attempt=0):
            nonlocal poster_path
            is_url = poster_source in ["TMDb", "Plex", "Plex's Show"]
            try:
                if pmmargs["dry"]:
                    logger.info(f"Poster will be Reset by {'URL' if is_url else 'File'} from {poster_source}")
                else:
                    logger.info(f"Reset From {poster_source}")
                    logger.info(f"{'URL' if is_url else 'File'} Path: {poster_path}")
                    if is_url:
                        plex_item.uploadPoster(url=poster_path)
                    else:
                        plex_item.uploadPoster(filepath=poster_path)
            except BadRequest as eb:
                logger.error(eb, group=item_title)
                if poster_source in ["Plex", "Plex's Show"]:
                    attempt += 1
                    logger.info(f"Trying next poster #{attempt + 1}")
                    if poster_source == "Plex":
                        poster_path = reset_from_plex(item_title, plex_item, shape, ignore=attempt)
                        if not poster_path:
                            logger.info("No Clean Plex Image Found")
                    if poster_source == "Plex's Show":
                        poster_path = reset_from_plex(item_title, parent, shape, ignore=attempt)
                        if not poster_path:
                            logger.info("No Clean Plex Show Image Found")
                    if poster_path:
                        upload(attempt=attempt)
            else:
                item_labels = [la.tag for la in plex_item.labels]
                remove_labels = [la for la in labels if la in item_labels]
                if not pmmargs["dry"]:
                    for label in remove_labels:
                        plex_item.removeLabel(label)
                    logger.info(f"Labels Removed: {', '.join(remove_labels)}")
                else:
                    logger.info(f"Labels To Be Removed: {', '.join(remove_labels)}")

        # Upload poster and Remove "Overlay" Label
        if poster_source:
            upload()
        else:
            logger.error("Image Error: No Image Found to Restore", group=item_title)

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
            plex_item._autoReload = False
        except (BadRequest, NotFound) as e1:
            raise Failed(f"Plex Error: {get_title(plex_item)} Failed to Load: {e1}")

    start_from = None
    run_items = []
    resume_rk = None
    if pmmargs["items"]:
        run_items = [rs for r in pmmargs["items"].split("|") if (rs := r.strip())]
        if len(run_items) > 1:
            str_items = ""
            current = ""
            for r in run_items[:-1]:
                current += f"{r}, "
                if len(current) > 75:
                    str_items += f"{current}\n"
                    current = ""
            str_items += f"and {run_items[-1]}"
        else:
            str_items = run_items[0]
        logger.separator(f"Resetting Specific Posters\n{str_items}")
        run_type = "of Specific Items "
    elif pmmargs["start"]:
        start_from = pmmargs["start"]
        logger.separator(f'Resetting Posters\nStarting From "{start_from}"')
        run_type = f'Starting From "{start_from}" '
    elif not pmmargs["ignore-resume"] and os.path.exists(resume_file):
        with open(resume_file) as handle:
            for line in handle.readlines():
                line = line.strip()
                if len(line) > 0:
                    resume_rk = str(line).strip()
                    break
        os.remove(resume_file)
        if resume_rk:
            logger.separator(f'Resetting Posters\nStarting From Rating Key "{resume_rk}"')
            run_type = f'Starting From Rating Key "{resume_rk}" '
    if not run_items and not start_from and not resume_rk:
        logger.separator("Resetting All Posters")

    items = lib.all()
    total_items = len(items)
    for i, item in enumerate(items):
        if run_items or start_from or resume_rk:
            if (run_items and item.title not in run_items) or \
                    (start_from and item.title != start_from) or \
                    (resume_rk and str(item.ratingKey) != resume_rk):
                logger.info(f"Skipping {i + 1}/{total_items} {item.title}")
                continue
            elif start_from:
                start_from = None
            elif resume_rk:
                resume_rk = None
        title = item.title
        current_rk = item.ratingKey
        logger.separator(f"Resetting {i + 1}/{total_items} {title}", start="reset")
        try:
            reload(item)
        except Failed as e:
            logger.error(e, group=title)
            continue

        # Find Item's PMM Asset Directory
        item_asset_directory = None
        asset_name = None
        if pmmargs["asset"]:
            if not item.locations:
                logger.error(f"Asset Error: No video filepath found fo {title}", group=title)
            else:
                file_name = "poster"
                path_test = str(item.locations[0])
                if not os.path.dirname(path_test):
                    path_test = path_test.replace("\\", "/")
                asset_name = util.validate_filename(os.path.basename(os.path.dirname(path_test) if isinstance(item, Movie) else path_test))
                if pmmargs["flat"]:
                    item_asset_directory = pmmargs["asset"]
                    file_name = asset_name
                elif os.path.isdir(os.path.join(pmmargs["asset"], asset_name)):
                    item_asset_directory = os.path.join(pmmargs["asset"], asset_name)
                else:
                    for n in range(1, 5):
                        new_path = pmmargs["asset"]
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
            guid = requests.utils.urlparse(item.guid) # noqa
            item_type = guid.scheme.split(".")[-1]
            check_id = guid.netloc
            tmdb_id = None
            tvdb_id = None
            imdb_id = None
            if item_type == "plex":
                for guid_tag in item.guids:
                    url_parsed = requests.utils.urlparse(guid_tag.id) # noqa
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
                logger.error("Plex Error: No External GUIDs found", group=title)
            if not tmdb_id and imdb_id:
                try:
                    results = tmdbapi.find_by_id(imdb_id=imdb_id)
                    if results.movie_results and isinstance(item, Movie):
                        tmdb_id = results.movie_results[0].id
                    elif results.tv_results and isinstance(item, Show):
                        tmdb_id = results.tv_results[0].id
                except TMDbException as e:
                    logger.warning(e, group=title)
            if not tmdb_id and tvdb_id and isinstance(item, Show):
                try:
                    results = tmdbapi.find_by_id(tvdb_id=tvdb_id)
                    if results.tv_results:
                        tmdb_id = results.tv_results[0].id
                except TMDbException as e:
                    logger.warning(e, group=title)
            if tmdb_id:
                try:
                    tmdb_item = tmdbapi.movie(tmdb_id) if isinstance(item, Movie) else tmdbapi.tv_show(tmdb_id)
                except TMDbException as e:
                    logger.error(f"TMDb Error: {e}", group=title)
            else:
                logger.error("Plex Error: TMDb ID Not Found", group=title)

        if not pmmargs["no-main"]:
            reset_poster(title, item, tmdb_item.poster_url if tmdb_item else None, item_asset_directory, asset_name if pmmargs["flat"] else "poster")

        logger.info(f"Runtime: {logger.runtime('reset')}")

        if isinstance(item, Show) and (pmmargs["season"] or pmmargs["episode"]):
            tmdb_seasons = {s.season_number: s for s in tmdb_item.seasons} if tmdb_item else {}
            for season in item.seasons():
                title = f"Season {season.seasonNumber}"
                title = title if title == season.title else f"{title}: {season.title}"
                title = f"{item.title}\n {title}"
                if pmmargs["season"]:
                    logger.separator(f"Resetting {title}", start="reset")
                    try:
                        reload(season)
                    except Failed as e:
                        logger.error(e, group=title)
                        continue
                    tmdb_poster = tmdb_seasons[season.seasonNumber].poster_url if season.seasonNumber in tmdb_seasons else None
                    file_name = f"Season{'0' if not season.seasonNumber or season.seasonNumber < 10 else ''}{season.seasonNumber}"
                    reset_poster(title, season, tmdb_poster, item_asset_directory, f"{asset_name}_{file_name}" if pmmargs["flat"] else file_name, parent=item)

                    logger.info(f"Runtime: {logger.runtime('reset')}")

                if pmmargs["episode"]:
                    if not pmmargs["season"]:
                        try:
                            reload(season)
                        except Failed as e:
                            logger.error(e, group=title)
                            continue
                    tmdb_episodes = {}
                    if season.seasonNumber in tmdb_seasons:
                        for episode in tmdb_seasons[season.seasonNumber].episodes:
                            episode._partial = False
                            try:
                                tmdb_episodes[episode.episode_number] = episode
                            except TMDbException:
                                logger.error(f"TMDb Error: An Episode of Season {season.seasonNumber} was Not Found", group=title)

                    for episode in season.episodes():
                        title = f"{item.title}\nEpisode {episode.seasonEpisode.upper()}: {episode.title}"
                        logger.separator(f"Resetting {title}", start="reset")
                        try:
                            reload(episode)
                        except Failed as e:
                            logger.error(e, group=title)
                            continue
                        tmdb_poster = tmdb_episodes[episode.episodeNumber].still_url if episode.episodeNumber in tmdb_episodes else None
                        file_name = episode.seasonEpisode.upper()
                        reset_poster(title, episode, tmdb_poster, item_asset_directory, f"{asset_name}_{file_name}" if pmmargs["flat"] else file_name, shape="landscape")
                        logger.info(f"Runtime: {logger.runtime('reset')}")

    current_rk = None
except Failed as e:
    logger.separator()
    logger.critical(e, discord=True)
    logger.separator()
except Exception as e:
    logger.separator()
    logger.stacktrace()
    logger.critical(e, discord=True)
    logger.separator()
except KeyboardInterrupt:
    if current_rk:
        with open(resume_file, "w") as handle:
            handle.write(str(current_rk))
    logger.separator(f"User Canceled Run {script_name}")
    raise

if current_rk:
    with open(resume_file, "w") as handle:
        handle.write(str(current_rk))

logger.error_report()
logger.switch()
report.append([(f"{script_name} Finished", "")])
report.append([("Total Runtime", f"{logger.runtime()}")])
description = f"{pmmargs['library']} Library{' Dry' if pmmargs['dry'] else ''} Run {run_type}Finished"
logger.report(f"{script_name} Summary", description=description, rows=report, width=18, discord=True)
