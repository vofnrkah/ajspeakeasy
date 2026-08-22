from gpiozero import LED, Button
from signal import pause
from time import sleep
import subprocess
import threading
import re

# ============================================================
# RELEASE INFO
# ============================================================

APP_NAME = "AJ Speakeasy Door Controller"
VERSION = "v0.1.0"
RELEASE = "Prototype Release"
CREATED_BY = "Y00$ung g00s3"

# ============================================================
# GPIO CONFIGURATION
# ============================================================

GREEN_GPIO = 17
YELLOW_GPIO = 22
BUTTON_GPIO = 27

green_led = LED(GREEN_GPIO)
yellow_led = LED(YELLOW_GPIO)

button = Button(
    BUTTON_GPIO,
    pull_up=True,
    bounce_time=0.1
)

# ============================================================
# AUDIO CONFIGURATION
# ============================================================

MP3_FILE = "/home/admin/Desktop/door/jukebox.mp3"

# Named device prevents card-number changes after reboot
AUDIO_DEVICE = "hw:Headphones,0"

playing = False
playback_lock = threading.Lock()


# ============================================================
# RELEASE BANNER
# ============================================================

def show_release_info():
    print("=" * 52, flush=True)
    print(f"{APP_NAME}", flush=True)
    print(f"Version:    {VERSION}", flush=True)
    print(f"Release:    {RELEASE}", flush=True)
    print(f"Created by: {CREATED_BY}", flush=True)
    print("=" * 52, flush=True)


# ============================================================
# VOLUME CONTROL
# ============================================================

def set_max_volume():
    try:
        subprocess.run(
            [
                "/usr/bin/amixer",
                "sset",
                "PCM",
                "100%"
            ],
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )

        print("PCM volume set to 100%", flush=True)

    except Exception as error:
        print(
            f"VOLUME ERROR: {error}",
            flush=True
        )


def ensure_max_volume():
    try:
        result = subprocess.run(
            [
                "/usr/bin/amixer",
                "get",
                "PCM"
            ],
            capture_output=True,
            text=True,
            check=True
        )

        percentages = re.findall(
            r"\[(\d+)%\]",
            result.stdout
        )

        if not percentages:
            print(
                "Could not determine PCM volume - setting to 100%",
                flush=True
            )

            set_max_volume()
            return

        volumes = [int(value) for value in percentages]

        print(
            f"Current PCM volume: {volumes}%",
            flush=True
        )

        if any(volume < 100 for volume in volumes):

            print(
                "Volume below maximum - setting to 100%",
                flush=True
            )

            set_max_volume()

        else:
            print(
                "Volume already at 100%",
                flush=True
            )

    except Exception as error:

        print(
            f"Could not check volume: {error}",
            flush=True
        )

        set_max_volume()


# ============================================================
# YELLOW BUTTON INDICATOR
# ============================================================

def yellow_flash():
    yellow_led.on()

    print(
        "YELLOW LED ON",
        flush=True
    )

    sleep(0.25)

    yellow_led.off()

    print(
        "YELLOW LED OFF",
        flush=True
    )


# ============================================================
# AUDIO PLAYBACK
# ============================================================

def play_audio():
    global playing

    try:
        ensure_max_volume()

        print(
            f"Playing: {MP3_FILE}",
            flush=True
        )

        subprocess.run(
            [
                "/usr/bin/mpg123",
                "-q",
                "-a",
                AUDIO_DEVICE,
                MP3_FILE
            ],
            check=True
        )

        print(
            "Playback finished",
            flush=True
        )

    except Exception as error:

        print(
            f"PLAYBACK ERROR: {error}",
            flush=True
        )

    finally:

        with playback_lock:
            playing = False

        print(
            "Ready for next button press",
            flush=True
        )


# ============================================================
# BUTTON HANDLER
# ============================================================

def button_pressed():
    global playing

    print(
        "BUTTON PRESSED",
        flush=True
    )

    # Flash yellow on EVERY button press
    threading.Thread(
        target=yellow_flash,
        daemon=True
    ).start()

    with playback_lock:

        if playing:

            print(
                "BUTTON ACKNOWLEDGED - song already playing",
                flush=True
            )

            return

        playing = True

    threading.Thread(
        target=play_audio,
        daemon=True
    ).start()


# ============================================================
# STARTUP
# ============================================================

show_release_info()

print(
    "Door controller starting...",
    flush=True
)

green_led.off()
yellow_led.off()

ensure_max_volume()

green_led.on()

print(
    "GREEN LED ON - Controller running",
    flush=True
)

button.when_pressed = button_pressed

print(
    "Waiting for button...",
    flush=True
)

pause()
