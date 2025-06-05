"""Main CLI for Russian Fishing 4 Script.

This module provides the command-line interface and main execution logic
for automating fishing in Russian Fishing 4. It handles configuration,
argument parsing, window management, and fishing automation.

.. moduleauthor:: Derek Lee <dereklee0310@gmail.com>
"""

# pylint: disable=no-member

import logging
import os
import shlex
import signal
import smtplib
import sys
from argparse import ArgumentParser, Namespace
from pathlib import Path
from socket import gaierror

from pynput import keyboard
from rich import box, print
from rich.logging import RichHandler
from rich.panel import Panel
from rich.style import Style
from rich.table import Column, Table
from yacs.config import CfgNode as CN

sys.path.append(".")  # python -m module -> python file

from rf4s import utils
from rf4s.config import config
from rf4s.controller.window import Window
from rf4s.player import Player

# Ignore %(name)s because it's verbose
logging.basicConfig(
    level=logging.INFO,
    format="%(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[RichHandler(rich_tracebacks=True)],
)
logger = logging.getLogger("rich")
# Reference: https://rich.readthedocs.io/en/latest/logging.html

ARGUMENTS = (
    ("c", "coffee", "drink coffee if stamina is low"),
    ("A", "alcohol", "drink alcohol before keeping the fish regularly"),
    ("r", "refill", "refill hunger and comfort by consuming tea and carrot"),
    ("H", "harvest", "harvest baits before casting"),
    ("g", "gear_ratio", "switch the gear ratio after the retrieval timed out"),
    ("f", "friction_brake", "enable auto friction brake"),
    ("l", "lift", "lift the tackle constantly while pulling a fish"),
    ("C", "skip_cast", "Immediately start retrieving for the first fish"),
    ("o", "spod_rod", "recast spod rod regularly"),
    ("L", "lure", "change current lure with a random one regularly, mode: spin"),
    ("x", "mouse", "move mouse randomly before casting the rod"),
    ("X", "pause", "pause the script before casting the rod regularly"),
    ("b", "bite", "take a screenshot after casting in screenshots/ (for fish spot)"),
    ("S", "screenshot", "take a screenshot of every fish you caught in screenshots/"),
    ("e", "email", "send email noticication after the script stop"),
    ("P", "plot", "save fishing data in /logs"),
    ("M", "miaotixing", "send miaotixing notification after the script stop"),
    ("s", "shutdown", "shutdown computer after the script stop"),
    ("so", "signout", "Sign out instead of closing the game"),
    ("gb", "groundbait", "enable groundbait refill, mode: bottom"),
    ("dm", "dry_mix", "enable dry mix refill, mode: bottom"),
    ("pva", "pva", "enable pva refill, mode: bottom"),
    ("E", "electro", "enable electric mode for Electro Raptor series reel"),
)

LOGO = """
██████╗ ███████╗██╗  ██╗███████╗
██╔══██╗██╔════╝██║  ██║██╔════╝
██████╔╝█████╗  ███████║███████╗
██╔══██╗██╔══╝  ╚════██║╚════██║
██║  ██║██║          ██║███████║
╚═╝  ╚═╝╚═╝          ╚═╝╚══════╝"""
GITHUB_LINK = "GitHub: https://github.com/dereklee0310/RussianFishing4Script"
DISCORD_LINK = "Discord: https://discord.gg/BZQWQnAMbY"
# https://patorjk.com/software/taag/#p=testall&f=3D-ASCII&t=RF4S%0A, ANSI Shadow

ROOT = Path(__file__).resolve().parents[1]


class Rf4sApp:
    """Main application class for Russian Fishing 4 automation.

    This class orchestrates the entire automation process, from parsing command-line
    arguments to configuring the environment and executing the fishing routine.

    Attributes:
        cfg (CfgNode): Configuration node merged from YAML and CLI arguments.
        args (Namespace): Parsed command-line arguments.
        window (Window): Game window controller instance.
        player (Player): Player instance for fishing automation.
    """

    def __init__(self):
        """Initialize the application.

        Loads configuration, parses command-line arguments, and sets up the environment.
        """
        print(Panel.fit(LOGO, box=box.HEAVY), GITHUB_LINK, DISCORD_LINK, sep="\n")
        self.cfg = config.setup_cfg()
        self.cfg.merge_from_file(ROOT / "config.yaml")

        # Parser will use the last occurence if the arguments are duplicated,
        # so put argv at the end to overwrite launch options.
        args_list = shlex.split(self.cfg.SCRIPT.LAUNCH_OPTIONS) + sys.argv[1:]
        self.parser = self._setup_parser()
        args = self.parser.parse_args(args_list)
        if not self._is_args_valid(args):
            sys.exit(1)

        args_cfg = CN({"ARGS": config.dict_to_cfg(vars(args))})
        self.cfg.merge_from_other_cfg(args_cfg)
        self.args = args

    def _setup_parser(self) -> ArgumentParser:
        """Configure the argument parser with all supported command-line options.

        :return: Configured ArgumentParser instance with all options and flags.
        :rtype: ArgumentParser
        """
        parser = ArgumentParser(description="Start AFK script for Russian Fishing 4")
        parser.add_argument("opts", nargs="*", help="overwrite configuration")

        for argument in ARGUMENTS:
            flag1 = f"-{argument[0]}"
            flag2 = f"--{argument[1]}"
            help_message = argument[2]
            parser.add_argument(flag1, flag2, action="store_true", help=help_message)

        # ----------------------------- release strategy ----------------------------- #
        release_strategy = parser.add_mutually_exclusive_group()
        release_strategy.add_argument(
            "-a",
            "--all",
            action="store_true",
            help="keep all captured fishes, used by default",
        )
        release_strategy.add_argument(
            "-m", "--marked", action="store_true", help="keep only the marked fishes"
        )

        # ----------------------- retrieval detection strategy ----------------------- #
        retrieval_detecton_strategy = parser.add_mutually_exclusive_group()
        retrieval_detecton_strategy.add_argument(
            "-d",
            "--default-spool",
            action="store_true",
            help="use default spool icon for retrieval detection, used by default",
        )
        retrieval_detecton_strategy.add_argument(
            "-R",
            "--rainbow-line",
            action="store_true",
            help="use rainbow line meter for retrieval detection",
        )

        # -------------------------- arguments with metavar -------------------------- #
        profile_selection_strategy = parser.add_mutually_exclusive_group()
        profile_selection_strategy.add_argument(
            "-p",
            "--pid",
            type=int,
            help="id of the profile you want to use",
            metavar="PID",
        )
        profile_selection_strategy.add_argument(
            "-N",
            "--pname",
            type=str,
            help="name of the profile you want to use",
            metavar="PROFILE_NAME",
        )

        parser.add_argument(
            "-n",
            "--fishes-in-keepnet",
            default=0,
            type=int,
            help="number of fishes in your keepnet, 0 by default",
            metavar="FISH_COUNT",
        )
        parser.add_argument(
            "-t",
            "--boat-ticket",
            nargs="?",
            const=5,
            type=int,
            choices=[1, 2, 3, 5],
            help=(
                "enable boat ticket auto renewal, DURATION: '1', '2', '3' or '5', "
                "will use a 5 hour ticket if duration is not specified"
            ),
            metavar="DURATION",
        )

        parser.add_argument(
            "-T",
            "--trolling",
            nargs="?",
            const="forward",
            type=str,
            choices=["forward", "left", "right"],
            help=(
                "enable trolling mode, DIRECTION: 'forward',''left', or 'right', "
                "will only move forward by press 'j' if direction is not specified"
            ),
            metavar="DIRECTION",
        )

        parser.add_argument(
            "-bl",
            "--broken-lure",
            nargs="?",
            const="replace",
            type=str,
            choices=["replace", "alarm"],
            help=(
                "enable broken lure auto-replace, ACTION: 'replace' or 'alarm', "
                "will replace the broken lure if action is not specified"
            ),  # TODO
            metavar="ACTION",
        )
        return parser

    def _is_args_valid(self, args: Namespace) -> bool:
        """Validate provided command-line arguments.

        :param args: Parsed command-line arguments to validate.
        :type args: Namespace
        :return: Whether the arguments are valid.
        :rtype: bool
        """
        if not 0 <= args.fishes_in_keepnet < self.cfg.KEEPNET.CAPACITY:
            logger.critical(
                "Invalid number of fishes in keepnet: '%s'", args.fishes_in_keepnet
            )
            return False

        if args.pid is not None and not self._is_pid_valid(str(args.pid)):
            logger.critical("Invalid profile id: '%s'", args.pid)
            return False

        if args.pname is not None and args.pname not in self.cfg.PROFILE:
            logger.critical("Invalid profile name: '%s'", args.pname)
            return False

        # boat_ticket_duration already checked by choices[...]
        return True

    def _is_pid_valid(self, pid: str) -> bool:
        """Check if the profile ID is valid.

        :param pid: Profile ID to validate.
        :type pid: str
        :return: Whether the profile ID is valid.
        :rtype: bool
        """
        return pid.isdigit() and 0 <= int(pid) < len(self.cfg.PROFILE)

    def _is_smtp_valid(self) -> bool:
        """Verify SMTP server connection for email notifications.

        Tests the connection to the configured SMTP server using stored
        credentials if email notifications are enabled.

        :return: Whether the SMTP configuration is valid or not needed.
        :rtype: bool
        """
        if not self.cfg.ARGS.EMAIL or not self.cfg.SCRIPT.SMTP_VERIFICATION:
            return True

        logger.info("Verifying SMTP connection")

        email = self.cfg.NOTIFICATION.EMAIL
        password = self.cfg.NOTIFICATION.PASSWORD
        smtp_server_name = self.cfg.NOTIFICATION.SMTP_SERVER

        try:
            with smtplib.SMTP_SSL(smtp_server_name, 465) as smtp_server:
                smtp_server.login(email, password)
        except smtplib.SMTPAuthenticationError:
            logger.critical(
                "Email address or app password not accepted,\n"
                "please check your email address and password.\n"
                "Try another SMTP server and email or refer to\n"
                "https://support.google.com/accounts/answer/185833\n"
            )
            return False
        except (TimeoutError, gaierror):
            logger.critical("Invalid SMTP Server or connection timed out")
            return False
        return True

    def _is_images_valid(self) -> bool:
        """Verify that all required image files exist for the selected language.

        Compares files in the reference 'en' directory with those in the current
        language directory and reports any missing files.

        :return: Whether all required image files are present.
        :rtype: bool
        """
        if not self.cfg.SCRIPT.IMAGE_VERIFICATION:
            return True

        logger.info("Verifying image files")
        if self.cfg.SCRIPT.LANGUAGE == "en":
            return True
        logger.warning(
            "Language '%s' is not fully supported, consider using EN version",
            self.cfg.SCRIPT.LANGUAGE,
        )
        image_dir = ROOT / "static" / self.cfg.SCRIPT.LANGUAGE
        try:
            current_images = [f.name for f in image_dir.iterdir() if f.is_file()]
        except FileNotFoundError:
            logger.critical("Invalid language: '%s'", self.cfg.SCRIPT.LANGUAGE)
            return False
        template_dir = ROOT / "static" / "en"
        target_images = [f.name for f in template_dir.iterdir() if f.is_file()]
        missing_images = set(target_images) - set(current_images)
        if len(missing_images) > 0:
            logger.critical("Some images are missing, please add them manually")
            table = Table(
                # "Filename",
                Column("Filename", style=Style(color="red")),
                title="Missing Images",
                box=box.DOUBLE,
                show_header=False,
            )
            for filename in missing_images:
                table.add_row(f"static/{self.cfg.SCRIPT.LANGUAGE}/{filename}")
            print(table)
            return False
        return True

    def _is_profile_valid(self, profile_name: str) -> bool:
        """Check if a profile configuration is valid and complete.

        :param profile_name: Name of the profile to validate.
        :type profile_name: str
        :return: Whether the profile is valid.
        :rtype: bool
        """
        if profile_name not in self.cfg.PROFILE:
            logger.critical("Invalid profile name: '%s'", profile_name)
            return False

        mode = self.cfg.PROFILE[profile_name].MODE
        if mode.upper() not in self.cfg.PROFILE:
            logger.critical("Invalid mode: '%s'", mode)
            return False

        expected_keys = set(self.cfg.PROFILE[mode.upper()])
        actual_keys = set(self.cfg.PROFILE[profile_name])

        invalid_keys = actual_keys - expected_keys
        missing_keys = expected_keys - actual_keys

        if invalid_keys or missing_keys:
            for key in invalid_keys:
                logger.critical("Invalid setting: '%s'", key)
            for key in missing_keys:
                logger.critical("Missing setting: '%s'", key)
            return False
        return True

    def _display_available_profiles(self) -> None:
        """Display a table of available profiles for user selection.

        Shows a formatted table with profile IDs and names.
        """
        table = Table(
            "Profile",
            title="Select a profile to start :rocket:",
            show_header=False,
            min_width=36,
        )
        for i, profile in enumerate(self.cfg.PROFILE):
            table.add_row(f"{i:>2}. {profile}")
        print(table)

    def _get_pid(self) -> None:
        """Prompt the user to enter a profile ID and validate the input.

        Continuously prompts until a valid profile ID is entered or the
        user chooses to exit.
        """
        print("Enter profile id to use, h to see help message, q to exit:")

        while True:
            user_input = input(">>> ")
            if self._is_pid_valid(user_input):
                break
            if user_input == "q":
                print("Bye.")
                sys.exit()
            if user_input == "h":
                self.parser.print_help()
                continue
            utils.print_error("Invalid profile id, please try again.")

        self.cfg.ARGS.PID = int(user_input)

    def setup_user_profile(self) -> None:
        """Configure the user profile based on arguments or interactive selection.

        Selects a profile based on command-line arguments or user input,
        validates the profile, and merges it with the configuration.
        """
        if self.cfg.ARGS.PNAME is not None:
            profile_name = self.cfg.ARGS.PNAME
        else:
            if self.cfg.ARGS.PID is None:
                self._display_available_profiles()
                self._get_pid()
            profile_name = list(self.cfg.PROFILE)[self.cfg.ARGS.PID]

        if not self._is_profile_valid(profile_name):
            sys.exit(1)

        self.cfg.SELECTED = CN({"NAME": profile_name})
        self.cfg.SELECTED.set_new_allowed(True)
        self.cfg.SELECTED.merge_from_other_cfg(self.cfg.PROFILE[profile_name])

        # Merge args.opts here because we can only overwrite cfg.SELECTED
        # after it's constructed using profile id or name.
        # Process list-like values if possible
        if "KEY.BOTTOM_RODS" in self.args.opts:
            value_idx = self.args.opts.index("KEY.BOTTOM_RODS") + 1
            self.args.opts[value_idx] = [
                x.strip() for x in self.args.opts[value_idx].split(",")
            ]
        self.cfg.merge_from_list(self.args.opts)
        # Check here because config might got overwritten
        if not self._is_smtp_valid() or not self._is_images_valid():
            sys.exit(1)
        config.print_cfg(self.cfg.SELECTED)

    def setup_window(self) -> None:
        """Set up and validate the game window.

        Creates a Window object, checks if the window size is supported,
        and disables incompatible features if needed.
        """
        self.window = Window()
        width, height = self.window.box[:2]
        if self.window.title_bar_exist:
            logger.info("Window mode detected. Please don't move the game window")
        if not self.window.supported:
            logger.warning('Window mode must be "Borderless windowed" or "Window mode"')
            logger.warning(
                "Invalid window size '%s', use '2560x1440', '1920x1080' or '1600x900'",
                f"{width}x{height}",
            )
            logger.error("Snag detection will be disabled")
            logger.error("Spooling detection will be disabled")
            logger.error("Auto friction brake will be disabled")

            self.cfg.ARGS.FRICTION_BRAKE = False
            self.cfg.SCRIPT.SNAG_DETECTION = False
            self.cfg.SCRIPT.SPOOLING_DETECTION = False

        if (
            self.cfg.SELECTED.MODE in ("telescopic", "bolognese")
            and not self.window.supported
        ):
            logger.critical(
                "Fishing mode '%s' doesn't support window size '%s'",
                self.cfg.SELECTED.MODE,
                f"{width}x{height}",
            )
            sys.exit(1)

    def setup_player(self) -> None:
        """Initialize the Player object with current configuration.

        Creates a new Player instance using the current config and window.
        """
        self.player = Player(self.cfg, self.window)

    def print_hints(self):
        """Display helpful information about the current configuration.

        Checks configuration compatibility and prints warnings for
        potential issues.
        """
        if self.cfg.ARGS.ELECTRO:
            if self.cfg.SELECTED.MODE not in ("pirk", "elevator"):
                logger.error(
                    "Electric mode is not compatible with mode '%s'",
                    self.cfg.SELECTED.MODE,
                )
                logger.error("Electric mode will be disabled")
                self.cfg.ARGS.ELECTRO = False
            else:
                logger.info(
                    "Electric mode is enabled, make sure you're using Electro Raptor"
                )

    def _on_release(self, key: keyboard.KeyCode) -> None:
        """Handle key release events for application control.

        :param key: The key that was released.
        :type key: keyboard.KeyCode

        Exits the application when the configured quit key is pressed.
        """
        # CTRL_C_EVENT: https://stackoverflow.com/questions/58455684/
        if key == keyboard.KeyCode.from_char(self.cfg.KEY.QUIT):
            os.kill(os.getpid(), signal.CTRL_C_EVENT)
            sys.exit()

    def start(self) -> None:
        """Start the fishing automation process.

        Sets up all required components, activates the game window,
        registers key listeners, and begins the fishing automation.
        Handles termination and displays results.
        """
        self.setup_user_profile()
        self.setup_window()
        self.setup_player()
        self.print_hints()
        self.cfg.freeze()
        self.window.activate_game_window()

        if self.cfg.KEY.QUIT != "CTRL-C":
            listener = keyboard.Listener(on_release=self._on_release)
            listener.start()
        try:
            self.player.start_fishing()
        except KeyboardInterrupt:
            pass

        # self.player.friction_brake_monitor_process.join()
        print(self.player.gen_result("Terminated by user"))
        if self.cfg.ARGS.PLOT:
            self.player.plot_and_save()


if __name__ == "__main__":
    Rf4sApp().start()
