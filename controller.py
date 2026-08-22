#!/usr/bin/env python3

from gpiozero import LED, Button
from signal import pause
from time import sleep

import asyncio
import json
import logging
import os
import signal
import subprocess
import sys
import threading
from logging.handlers import RotatingFileHandler
from pathlib import Path

from aiohubspace import v1


# ============================================================
# LOGGING
# ============================================================

# Keep application logs out of journald and rotate them before the complete
# set can exceed 100 MB. The active file plus eight backups can use at most
# 90,000,000 bytes total.
LOG_DIRECTORY = Path("/home/admin/Desktop/door/logs")
LOG_FILE = LOG_DIRECTORY / "door-controller.log"
MAX_LOG_BYTES = 10_000_000
LOG_BACKUP_COUNT = 8

LOG_DIRECTORY.mkdir(parents=True, exist_ok=True)

file_handler = RotatingFileHandler(
    LOG_FILE,
    maxBytes=MAX_LOG_BYTES,
    backupCount=LOG_BACKUP_COUNT,
    encoding="utf-8",
)
os.chmod(LOG_FILE, 0o600)
file_handler.setFormatter(
    logging.Formatter("%(asctime)s %(levelname)s %(threadName)s: %(message)s")
)

logging.basicConfig(
    level=logging.INFO,
    handlers=[file_handler],
    force=True,
)

log = logging.getLogger("door-controller")

# Keep third-party HTTP chatter out of the application log while preserving
# warnings and errors that are useful for troubleshooting Hubspace failures.
logging.getLogger("aiohubspace").setLevel(logging.WARNING)


# ============================================================
# RELEASE INFO
# ============================================================

APP_NAME = "AJ Speakeasy Door Controller"
VERSION = "v0.4.1"
RELEASE = "26-Second Light Timer Release"
CREATED_BY = "Y00$ung g00s3"


# ============================================================
# GPIO CONFIGURATION
# ============================================================

GREEN_GPIO = 17
YELLOW_GPIO = 22
BUTTON_GPIO = 27

green_led = None
yellow_led = None
button = None


# ============================================================
# AUDIO CONFIGURATION
# ============================================================

MP3_FILE = "/home/admin/Desktop/door/jukebox.mp3"
ANALOG_AUDIO_DEVICE = "hw:Headphones,0"

# A system service does not automatically inherit the user's PipeWire runtime
# path. Setting it here lets mpg123 and wpctl reach admin's default audio sink,
# including a connected Bluetooth speaker.
os.environ.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")

playing = False
playback_lock = threading.Lock()


# ============================================================
# HUBSPACE LIGHT CONFIGURATION
# ============================================================

HUBSPACE_CONFIG_FILE = Path.home() / ".config" / "ajspeakeasy" / "hubspace.json"
LIGHT_ON_SECONDS = 26


def load_hubspace_config():
    if not HUBSPACE_CONFIG_FILE.exists():
        log.warning(
            "Hubspace light is not configured; run hubspace_setup.py"
        )
        return None

    try:
        with HUBSPACE_CONFIG_FILE.open("r", encoding="utf-8") as config_file:
            config = json.load(config_file)

        required = {"username", "refresh_token", "device_id"}
        missing = sorted(required.difference(config))
        if missing:
            raise ValueError(f"missing configuration keys: {', '.join(missing)}")

        return config

    except Exception:
        log.exception("Could not load Hubspace configuration")
        return None


async def hubspace_light_cycle_async(config):
    bridge = None
    device_id = config["device_id"]
    instance = config.get("instance")

    try:
        bridge = v1.HubspaceBridgeV1(
            config["username"],
            "",
            refresh_token=config["refresh_token"],
            polling_interval=30,
        )

        # aiohubspace adds a console handler by default. Remove it so library
        # messages follow this application's rotating file-only logging.
        for logger_name, logger_object in logging.root.manager.loggerDict.items():
            if logger_name.startswith("aiohubspace") and isinstance(
                logger_object, logging.Logger
            ):
                logger_object.handlers.clear()
                logger_object.propagate = True

        await bridge.initialize()
        await bridge.switches.turn_on(device_id, instance=instance)
        log.info("HUBSPACE LIGHT ON for %s seconds", LIGHT_ON_SECONDS)
        await asyncio.sleep(LIGHT_ON_SECONDS)

    except Exception:
        log.exception("Hubspace light cycle failed")

    finally:
        if bridge is not None:
            try:
                await bridge.switches.turn_off(device_id, instance=instance)
                log.info("HUBSPACE LIGHT OFF")
            except Exception:
                log.exception("Could not turn Hubspace light off")

            try:
                await bridge.close()
            except Exception:
                log.exception("Could not close Hubspace connection")


def hubspace_light_cycle():
    config = load_hubspace_config()
    if config is None:
        return

    asyncio.run(hubspace_light_cycle_async(config))


# ============================================================
# RELEASE BANNER
# ============================================================

def show_release_info():
    log.info("=" * 52)
    log.info(APP_NAME)
    log.info("Version: %s", VERSION)
    log.info("Release: %s", RELEASE)
    log.info("Created by: %s", CREATED_BY)
    log.info("=" * 52)


# ============================================================
# VOLUME CONTROL
# ============================================================

def set_max_volume():
    # Prefer PipeWire so volume is applied to the current default output,
    # including Bluetooth. Fall back to ALSA for an analog-only setup.
    try:
        subprocess.run(
            [
                "/usr/bin/wpctl",
                "set-mute",
                "@DEFAULT_AUDIO_SINK@",
                "0",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        subprocess.run(
            [
                "/usr/bin/wpctl",
                "set-volume",
                "@DEFAULT_AUDIO_SINK@",
                "1.0",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        log.info("Default PipeWire audio sink unmuted and set to 100%%")

    except subprocess.CalledProcessError as error:
        log.warning(
            "Could not set PipeWire volume; exit code=%s, stderr=%s; "
            "falling back to ALSA",
            error.returncode,
            (error.stderr or "").strip(),
        )

    except Exception:
        log.exception(
            "Unexpected error while setting PipeWire volume; "
            "falling back to ALSA"
        )

    try:
        subprocess.run(
            [
                "/usr/bin/amixer",
                "sset",
                "PCM",
                "100%",
                "unmute",
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        log.info("ALSA PCM volume unmuted and set to 100%%")

    except subprocess.CalledProcessError as error:
        log.error(
            "Failed to set ALSA PCM volume; exit code=%s, stderr=%s",
            error.returncode,
            (error.stderr or "").strip(),
        )

    except Exception:
        log.exception("Unexpected error while setting ALSA PCM volume")


def ensure_max_volume():
    set_max_volume()


def default_sink_is_bluetooth():
    try:
        result = subprocess.run(
            [
                "/usr/bin/wpctl",
                "inspect",
                "@DEFAULT_AUDIO_SINK@",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        is_bluetooth = "bluez" in result.stdout.lower()

        if is_bluetooth:
            log.info("Default PipeWire sink is Bluetooth")
        else:
            log.info("Default PipeWire sink is not Bluetooth")

        return is_bluetooth

    except Exception:
        log.exception("Could not inspect the default PipeWire audio sink")
        return False


# ============================================================
# YELLOW BUTTON INDICATOR
# ============================================================

def yellow_flash():
    try:
        yellow_led.on()
        log.info("YELLOW LED ON")

        sleep(0.25)

    except Exception:
        log.exception("Error while flashing yellow LED")

    finally:
        try:
            if yellow_led is not None:
                yellow_led.off()
                log.info("YELLOW LED OFF")
        except Exception:
            log.exception("Could not turn yellow LED off")


# ============================================================
# AUDIO PLAYBACK
# ============================================================

def play_audio():
    global playing

    try:
        ensure_max_volume()
        log.info("Playing audio file: %s", MP3_FILE)

        # Use exactly one output. When Bluetooth is the PipeWire default,
        # mpg123 follows that default. Otherwise, force the analog ALSA device.
        if default_sink_is_bluetooth():
            output_name = "Bluetooth default"
            command = [
                "/usr/bin/mpg123",
                "-q",
                MP3_FILE,
            ]
        else:
            output_name = "analog headphones"
            command = [
                "/usr/bin/mpg123",
                "-q",
                "-o",
                "alsa",
                "-a",
                ANALOG_AUDIO_DEVICE,
                MP3_FILE,
            ]

        log.info("Starting playback on %s", output_name)

        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            check=True,
        )

        if result.stdout.strip():
            log.debug("mpg123 output: %s", result.stdout.strip())

        if result.stderr.strip():
            log.warning("mpg123 output: %s", result.stderr.strip())

        log.info("Playback finished successfully on %s", output_name)

    except FileNotFoundError:
        log.exception(
            "Audio command or MP3 file was not found; file=%s",
            MP3_FILE,
        )

    except subprocess.CalledProcessError as error:
        log.error(
            "Audio playback failed; exit code=%s, stderr=%s",
            error.returncode,
            (error.stderr or "").strip(),
        )

    except Exception:
        log.exception("Unexpected audio playback error")

    finally:
        with playback_lock:
            playing = False

        log.info("Ready for next button press")


# ============================================================
# BUTTON HANDLER
# ============================================================

def button_pressed():
    global playing

    try:
        log.info("BUTTON PRESSED")

        # Flash yellow on every physical or simulated button press.
        threading.Thread(
            target=yellow_flash,
            name="yellow-flash",
            daemon=True,
        ).start()

        with playback_lock:
            if playing:
                log.warning("BUTTON ACKNOWLEDGED - song is already playing")
                return

            playing = True

        threading.Thread(
            target=play_audio,
            name="audio-playback",
            daemon=True,
        ).start()

        # Light control runs independently so cloud latency cannot delay audio.
        threading.Thread(
            target=hubspace_light_cycle,
            name="hubspace-light",
            daemon=True,
        ).start()

    except Exception:
        log.exception("Unhandled error in button handler")

        with playback_lock:
            playing = False


# ============================================================
# SIGNAL HANDLERS
# ============================================================

def simulated_button_pressed(signum, frame):
    """Handle SIGUSR1 by simulating the GPIO button callback."""
    log.info("TEST BUTTON SIGNAL RECEIVED")
    button_pressed()


def shutdown_requested(signum, frame):
    signal_name = signal.Signals(signum).name
    log.info("Shutdown requested by %s", signal_name)
    raise SystemExit(0)


# ============================================================
# CLEANUP
# ============================================================

def cleanup():
    log.info("Cleaning up GPIO resources")

    try:
        if button is not None:
            button.close()
    except Exception:
        log.exception("Error while closing button input")

    try:
        if yellow_led is not None:
            yellow_led.off()
            yellow_led.close()
    except Exception:
        log.exception("Error while closing yellow LED")

    try:
        if green_led is not None:
            green_led.off()
            green_led.close()
    except Exception:
        log.exception("Error while closing green LED")

    log.info("Door controller stopped")


# ============================================================
# STARTUP
# ============================================================

def main():
    global green_led
    global yellow_led
    global button

    show_release_info()
    log.info("Door controller starting")

    try:
        green_led = LED(GREEN_GPIO)
        yellow_led = LED(YELLOW_GPIO)

        button = Button(
            BUTTON_GPIO,
            pull_up=True,
            bounce_time=0.1,
        )

        green_led.off()
        yellow_led.off()

        ensure_max_volume()

        green_led.on()
        log.info("GREEN LED ON - controller running")

        button.when_pressed = button_pressed
        log.info("Waiting for button on BCM GPIO %s", BUTTON_GPIO)

        # SIGUSR1 triggers the same code path as a physical button press.
        signal.signal(signal.SIGUSR1, simulated_button_pressed)

        # Allow systemd and Ctrl+C to stop the program cleanly.
        signal.signal(signal.SIGTERM, shutdown_requested)
        signal.signal(signal.SIGINT, shutdown_requested)

        # pause() returns after a handled signal, so keep waiting in a loop.
        while True:
            pause()

    except SystemExit:
        raise

    except Exception:
        log.exception("Fatal controller error")
        return 1

    finally:
        cleanup()

    return 0


if __name__ == "__main__":
    sys.exit(main())
