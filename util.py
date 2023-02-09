import argparse, glob, logging, time, os, platform, psutil, requests, sys, uuid
from dotenv import load_dotenv
from logging.handlers import RotatingFileHandler
from pathvalidate import is_valid_filename, sanitize_filename

repo = ""
spacing = 100
separating_character = "="
logger = logging.getLogger()
choices = {}
options = {}
base_dir = os.path.dirname(os.path.abspath(__file__))
config_dir = os.path.join(base_dir, "config")

class Failed(Exception):
    pass

def get_arg(env_str, default, arg_bool=False, arg_int=False):
    env_value = os.environ.get(env_str)
    if env_value or (arg_int and env_value == 0):
        if arg_bool:
            if env_value is True or env_value is False:
                return env_value
            elif env_value.lower() in ["t", "true"]:
                return True
            else:
                return False
        elif arg_int:
            try:
                return int(env_value)
            except ValueError:
                return default
        else:
            return str(env_value)
    else:
        return default

def init(options_in, repo_name):
    global choices
    global options
    global repo
    repo = repo_name
    options = options_in
    parser = argparse.ArgumentParser()
    for o in options:
        if o["type"] == "int":
            parser.add_argument(f"-{o['arg']}", f"--{o['key']}", dest=o["key"], help=o["help"], type=int, default=o["default"])
        elif o["type"] == "bool":
            parser.add_argument(f"-{o['arg']}", f"--{o['key']}", dest=o["key"], help=o["help"], action="store_true", default=o["default"])
        else:
            parser.add_argument(f"-{o['arg']}", f"--{o['key']}", dest=o["key"], help=o["help"])
    args_parsed = parser.parse_args()
    load_dotenv(os.path.join(config_dir, ".env"))

    for o in options:
        choices[o["key"]] = get_arg(o["env"], getattr(args_parsed, o["key"]), arg_int=isinstance(o["default"], int), arg_bool=isinstance(o["default"], bool))
    return choices

def get_uuid():
    uuid_file = os.path.join(config_dir, "UUID")
    uuid_num = None
    if os.path.exists(uuid_file):
        with open(uuid_file) as handle:
            for line in handle.readlines():
                line = line.strip()
                if len(line) > 0:
                    uuid_num = str(line)
                    break
    if not uuid_num:
        uuid_num = str(uuid.uuid4())
        with open(uuid_file, "w") as handle:
            handle.write(uuid_num)
    return uuid_num

class RedactingFormatter(logging.Formatter):
    def __init__(self, orig_formatter, patterns):
        self.orig_formatter = orig_formatter
        self._patterns = patterns
        super().__init__()

    def format(self, record):
        msg = self.orig_formatter.format(record)
        for pattern in self._patterns:
            if pattern:
                msg = msg.replace(pattern, "(redacted)")
        return msg

    def __getattr__(self, attr):
        return getattr(self.orig_formatter, attr)

def fmt_filter(record):
    record.levelname = f"[{record.levelname}]"
    record.filename = f"[{record.filename}:{record.lineno}]"
    return True

def init_logger(name, secrets=None, trace=False):
    global logger
    if not trace:
        logger = logging.getLogger(name)

    logger.setLevel(logging.DEBUG)
    ch = logging.StreamHandler()
    ch.setLevel(logging.DEBUG)
    logger.addHandler(ch)

    os.makedirs(os.path.join(config_dir, "logs"), exist_ok=True)
    log_file = os.path.join(config_dir, "logs", f"{name}.log")
    fh = RotatingFileHandler(log_file, delay=True, mode="w", backupCount=10, encoding="utf-8")
    if os.path.exists(log_file):
        fh.doRollover()
    fh.setLevel(logging.DEBUG)
    fh.addFilter(fmt_filter)
    fh.setFormatter(RedactingFormatter(logging.Formatter("[%(asctime)s] %(filename)-27s %(levelname)-10s | %(message)s"), patterns=secrets))
    logger.addHandler(fh)

def my_except_hook(exctype, value, tb):
    if issubclass(exctype, KeyboardInterrupt):
        sys.__excepthook__(exctype, value, tb)
    else:
        logger.critical(value, exc_info=(exctype, value, tb))

def update_send(old_send, timeout):
    def new_send(*send_args, **kwargs):
        if kwargs.get("timeout", None) is None:
            kwargs["timeout"] = timeout
        return old_send(*send_args, **kwargs)
    return new_send

def separator():
    return separating_character * spacing

def centered(text, sep=" ", width=spacing, side=False):
    if len(text) > width - (0 if side else 2):
        return text
    space = width - len(text)
    text = f"{sep}{text}{sep}"
    if space % 2 == 1:
        text += sep
        space -= 1
    side_space = int(space / 2) - 1 - (1 if side else 0)
    return f"{separating_character if side else ''}{sep * side_space}{text}{sep * side_space}{separating_character if side else ''}"

def glob_filter(filter_in):
    filter_in = filter_in.translate({ord("["): "[[]", ord("]"): "[]]"}) if "[" in filter_in else filter_in
    return glob.glob(filter_in)

def is_locked(filepath):
    locked = None
    file_object = None
    if os.path.exists(filepath):
        try:
            file_object = open(filepath, 'a', 8)
            if file_object:
                locked = False
        except IOError:
            locked = True
        finally:
            if file_object:
                file_object.close()
    return locked

def validate_filename(filename):
    if not is_valid_filename(str(filename)):
        filename = sanitize_filename(str(filename))
    return filename

def download_image(download_image_url, path=None, name="temp"):
    image_response = requests.get(download_image_url)
    if image_response.status_code >= 400:
        raise Failed("Image Error: Image Download Failed")
    if image_response.headers["Content-Type"] not in ["image/png", "image/jpeg", "image/webp"]:
        raise Failed("Image Error: Image Not PNG, JPG, or WEBP")
    if image_response.headers["Content-Type"] == "image/jpeg":
        temp_image_name = f"{name}.jpg"
    elif image_response.headers["Content-Type"] == "image/webp":
        temp_image_name = f"{name}.webp"
    else:
        temp_image_name = f"{name}.png"
    temp_image_name = os.path.join(path if path else base_dir, temp_image_name)
    with open(temp_image_name, "wb") as handler:
        handler.write(image_response.content)
    while is_locked(temp_image_name):
        time.sleep(1)
    return temp_image_name

def get_version(level):
    global repo
    if repo:
        try:
            url = f"https://raw.githubusercontent.com/{repo}/{level}/VERSION"
            return parse_version(requests.get(url).content.decode().strip(), text=level)
        except requests.exceptions.ConnectionError:
            pass
    return "Unknown", "Unknown", 0

def parse_version(version, text="develop"):
    version = version.replace("develop", text)
    split_version = version.split(f"-{text}")
    return version, split_version[0], int(split_version[1]) if len(split_version) > 1 else 0

def header(name):
    global choices
    global options
    version = ("Unknown", "Unknown", 0)
    with open(os.path.join(base_dir, "VERSION")) as handle:
        for line in handle.readlines():
            line = line.strip()
            if len(line) > 0:
                version = parse_version(line)
                break
    try:
        from git import Repo, InvalidGitRepositoryError
        try:
            git_branch = Repo(path=".").head.ref.name
        except InvalidGitRepositoryError:
            git_branch = None
    except ImportError:
        git_branch = None
    env_version = get_arg("BRANCH_NAME", "master")
    branch = git_branch if git_branch else "develop" if env_version == "develop" or version[2] > 0 else "master"
    logger.info(separator())
    logger.info(centered(" ____  _             __  __      _          __  __                                   "))
    logger.info(centered("|  _ \\| | _____  __ |  \\/  | ___| |_ __ _  |  \\/  | __ _ _ __   __ _  __ _  ___ _ __ "))
    logger.info(centered("| |_) | |/ _ \\ \\/ / | |\\/| |/ _ \\ __/ _` | | |\\/| |/ _` | '_ \\ / _` |/ _` |/ _ \\ '__|"))
    logger.info(centered("|  __/| |  __/>  <  | |  | |  __/ || (_| | | |  | | (_| | | | | (_| | (_| |  __/ |   "))
    logger.info(centered("|_|   |_|\\___/_/\\_\\ |_|  |_|\\___|\\__\\__,_| |_|  |_|\\__,_|_| |_|\\__,_|\\__, |\\___|_|   "))
    logger.info(centered("                                                                     |___/           "))
    logger.info(centered(name))
    system_ver = "Docker" if get_arg("PMM_DOCKER", False, arg_bool=True) else "Linuxserver" if get_arg("PMM_LINUXSERVER", False, arg_bool=True) else f"Python {platform.python_version()}"
    logger.info(f"    Version: {version[0]} ({system_ver}){f' (Git: {git_branch})' if git_branch else ''}")
    latest_version = get_version(branch)
    new_version = latest_version[0] if latest_version and latest_version[0] != "Unknown" and (version[1] != latest_version[1] or (version[2] and version[2] < latest_version[2])) else None
    if new_version:
        logger.info(f"    Newest Version: {new_version}")
    logger.info(f"    Platform: {platform.platform()}")
    logger.info(f"    Memory: {round(psutil.virtual_memory().total / (1024.0 ** 3))} GB")
    logger.info(separator())

    run_arg = " ".join([f'"{s}"' if " " in s else s for s in sys.argv[:]])
    logger.info(f"Run Command: {run_arg}")
    for o in options:
        logger.info(f"--{o['key']} ({o['env']}): {choices[o['key']]}")
