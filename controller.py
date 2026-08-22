#!/usr/bin/env python3

from gpiozero import LED, Button
from signal import pause
from time import sleep

import logging
import re
import signal
import subprocess
import sys
import threading


# ============================================================
# LOGGING
# ============================================================

# systemd captures stdout and stores it in the journal. Each message includes
# a timestamp, severity, and thread name to make diagnosis easier.
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(threadName)s: %(message)s",
    stream=sys.stdout,
)

log = logging.getLogger("door-controller")


# ============================================================
# RELEASE INFO
# ============================================================

APP_NAME = "AJ Speakeasy Door Controller"
VERSION = "v0.2.0"
RELEASE = "Logging and Software Test Release"
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

# Named device prevents card-number changes after reboot.
AUDIO_DEVICE = "hw:Headphones,0"

playing = False
playback_lock = threading.Lock()


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
    try:
        result = subprocess.run(
            [
                "/usr/bin/amixer",
                "sset",
                "PCM",
                "100%",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        log.info("PCM volume set to 100%%")

        if result.stdout.strip():
            log.debug("amixer output: %s", result.stdout.strip())

    except subprocess.CalledProcessError as error:
        log.error(
            "Failed to set PCM volume; exit code=%s, stderr=%s",
            error.returncode,
            (error.stderr or "").strip(),
        )

    except Exception:
        log.exception("Unexpected error while setting PCM volume")


def ensure_max_volume():
    try:
        result = subprocess.run(
            [
                "/usr/bin/amixer",
                "get",
                "PCM",
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        percentages = re.findall(
            r"\[(\d+)%\]",
            result.stdout,
        )

        if not percentages:
            log.warning(
                "Could not determine PCM volume; attempting to set it to 100%%"
            )
            set_max_volume()
            return

        volumes = [int(value) for value in percentages]
        log.info("Current PCM volume levels: %s", volumes)

        if any(volume < 100 for volume in volumes):
            log.warning(
                "Volume is below maximum; attempting to set it to 100%%"
            )
            set_max_volume()
        else:
            log.info("Volume is already at 100%%")

    except subprocess.CalledProcessError as error:
        log.error(
            "Failed to check PCM volume; exit code=%s, stderr=%s",
            error.returncode,
            (error.stderr or "").strip(),
        )
        set_max_volume()

    except Exception:
        log.exception("Unexpected error while checking PCM volume")
        set_max_volume()


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

        result = subprocess.run(
            [
                "/usr/bin/mpg123",
                "-q",
                "-a",
                AUDIO_DEVICE,
                MP3_FILE,
            ],
            capture_output=True,
            text=True,
            check=True,
        )

        if result.stderr.strip():
            log.warning("mpg123 output: %s", result.stderr.strip())

        log.info("Playback finished successfully")

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
