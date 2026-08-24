# AJ Speakeasy Door Controller

Raspberry Pi door controller that responds to either a physical GPIO button or
a software-generated button press. A trigger flashes the yellow status LED,
plays the next song in a four-song rotation, and keeps a Hubspace-controlled
Defiant smart plug on until that song finishes.

The application runs continuously as a `systemd` service and writes structured,
rotating logs to disk. Physical and software button presses use the same code
path, so the complete system can be tested without the button connected.

## Current release

- Version: `v0.5.0`
- Release: `Four-Song Rotation Release`
- Tested smart plug: Defiant HPPA11CWB
- Tested Raspberry Pi: Raspberry Pi 3 Model B+
- Tested Python: Python 3.13

## Trigger behavior

Each accepted button press performs these operations:

1. Flash the yellow LED for 0.25 seconds.
2. Select the next available MP3 in the rotation.
3. Read and log the MP3's metadata duration.
4. Authenticate to Hubspace using the saved refresh token.
5. Turn on the configured smart plug.
6. Start the selected song after the ON command is confirmed. If Hubspace
   fails or does not respond within 15 seconds, audio proceeds without it.
7. Wait for the actual `mpg123` playback process to finish.
8. Attempt to turn off the smart plug, including when another Hubspace error
   occurs during the light cycle.

The rotation order is:

1. `jukebox.mp3`
2. `Chattahoochee.mp3`
3. `Drive.mp3`
4. `Good Time.mp3`

The next press returns to `jukebox.mp3`. The rotation begins at the first song
again whenever the service restarts. Missing files are logged and skipped.

While a song is already playing, additional button presses are acknowledged in
the log but do not start overlapping audio or another light cycle.

## Hardware

### GPIO assignment

The code uses BCM GPIO numbering.

| Component | BCM GPIO | Connection |
| --- | ---: | --- |
| Green status LED | 17 | GPIO 17 through a current-limiting resistor to the LED; LED returns to GND |
| Yellow activity LED | 22 | GPIO 22 through a current-limiting resistor to the LED; LED returns to GND |
| Door button | 27 | Button between GPIO 27 and GND; internal pull-up is enabled |

Do not connect an LED directly to a GPIO pin without an appropriate
current-limiting resistor.

### Smart plug safety

The Defiant HPPA11CWB is an indoor 10 A / 1200 W smart plug. Do not exceed its
rated load, use it outdoors, immerse it, or use it with damaged wiring. The
Hubspace integration is cloud-dependent. If connectivity is lost after an ON
command reaches the plug but before the OFF command succeeds, the plug could
remain on. Configure the plug's own Auto-Off feature as an additional safeguard
when the Hubspace app permits an appropriate duration.

## Repository files

| File | Purpose |
| --- | --- |
| `controller.py` | Main GPIO, audio, signal, Hubspace, and logging application |
| `hubspace_setup.py` | One-time private Hubspace login and smart-plug selection |
| `door-controller.service` | `systemd` unit for running the controller at boot |
| `requirements.txt` | Python dependencies |
| `button_test.py` | Standalone physical button test |
| `led_test.py` | Standalone LED test |

The MP3 file, virtual environment, runtime logs, and account configuration are
intentionally excluded from Git.

## Raspberry Pi installation

Clone the repository into the path expected by the controller:

```bash
cd ~/Desktop
git clone git@github.com:vofnrkah/ajspeakeasy.git door
cd ~/Desktop/door
```

Install the required operating-system tools. Package names can vary slightly
between Raspberry Pi OS releases.

```bash
sudo apt update
sudo apt install python3-venv mpg123 alsa-utils pipewire-bin
```

Create the virtual environment with access to Raspberry Pi OS system packages.
The `--system-site-packages` option is important because it exposes the Pi's
installed GPIO backend to `gpiozero`.

```bash
python3 -m venv --system-site-packages .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

Copy all four MP3 files to the configured locations:

```text
/home/admin/Desktop/door/jukebox.mp3
/home/admin/Desktop/door/Chattahoochee.mp3
/home/admin/Desktop/door/Drive.mp3
/home/admin/Desktop/door/Good Time.mp3
```

From a Mac terminal, the three additional files can be copied in one command:

```bash
scp "$HOME/Desktop/Chattahoochee.mp3" "$HOME/Desktop/Drive.mp3" \
  "$HOME/Desktop/Good Time.mp3" \
  admin@ajspeakeasypi.local:/home/admin/Desktop/door/
```

Run this on the Pi afterward to confirm the names and sizes:

```bash
ls -lh ~/Desktop/door/*.mp3
```

Install and enable the service:

```bash
sudo cp door-controller.service /etc/systemd/system/door-controller.service
sudo systemctl daemon-reload
sudo systemctl enable --now door-controller
systemctl is-active door-controller
```

The expected result from the final command is `active`.

## Hubspace configuration

Hubspace support uses the unofficial `aiohubspace` Python package. It connects
to the Afero/Hubspace cloud and therefore requires working internet access.

Run the one-time setup utility directly in the Pi terminal:

```bash
cd ~/Desktop/door
.venv/bin/python hubspace_setup.py
```

The utility will:

1. Prompt for the Hubspace email address.
2. Prompt for the password without displaying it.
3. Authenticate and list the account's compatible switches.
4. Ask which switch controls the light.
5. Store the username, selected device, switch instance, and refresh token.

The Hubspace password is not stored. The protected configuration is written to:

```text
/home/admin/.config/ajspeakeasy/hubspace.json
```

Its file mode is set to `600`, so only the `admin` account can read or change
it. Treat the refresh token as a password: never paste it into chat, commit it
to Git, or include it in a bug report.

The library automatically exchanges the saved refresh token for temporary
access tokens. There is no routine password prompt. If Hubspace invalidates the
refresh token, rerun `hubspace_setup.py`; the service does not need to be
restarted because the configuration is loaded on every accepted button press.

## Audio output

The controller deliberately uses exactly one output per playback:

- If the current PipeWire default sink is Bluetooth, `mpg123` follows that
  default and plays through the Bluetooth speaker.
- Otherwise, playback is forced to the Raspberry Pi analog headphones device,
  `hw:Headphones,0`.

This prevents sending two streams to the same Bluetooth speaker. The service
sets `XDG_RUNTIME_DIR` so PipeWire is reachable from the system service.

Inspect available audio devices and the default sink:

```bash
wpctl status
wpctl inspect @DEFAULT_AUDIO_SINK@
```

Set an output as the default using the sink ID displayed by `wpctl status`:

```bash
wpctl set-default SINK_ID
```

Test the MP3 independently of the controller:

```bash
mpg123 -q /home/admin/Desktop/door/jukebox.mp3
```

## Testing without the physical button

Send `SIGUSR1` to the service's main process:

```bash
sudo systemctl kill --kill-whom=main --signal=SIGUSR1 door-controller
```

This executes the same `button_pressed()` function used by the GPIO button. It
should flash the yellow LED, select the next song, turn the configured plug on,
play one audio stream, and turn the plug off when playback ends.

Follow the log during the test:

```bash
tail -f /home/admin/Desktop/door/logs/door-controller.log
```

Successful events include:

```text
TEST BUTTON SIGNAL RECEIVED
BUTTON PRESSED
Selected song 1 of 4: jukebox.mp3
Song length: jukebox.mp3 = 27.500 seconds
HUBSPACE LIGHT ON for song: jukebox.mp3
Starting playback on Bluetooth default
Playback finished successfully; song=jukebox.mp3 output=Bluetooth default elapsed=27.500s
HUBSPACE LIGHT OFF
Ready for next button press
```

## Testing GPIO hardware separately

Stop the main service before running a standalone hardware test so two
processes do not attempt to control the same GPIO pins:

```bash
sudo systemctl stop door-controller
.venv/bin/python led_test.py
.venv/bin/python button_test.py
sudo systemctl start door-controller
```

Run the test scripts one at a time and stop each one before starting the next.

## Logs

Application logs are written only to:

```text
/home/admin/Desktop/door/logs/door-controller.log
```

The active file rotates at 10,000,000 bytes. Eight backups are retained, so the
complete application log set is capped at approximately 90 MB. Rotated files
are named `door-controller.log.1` through `door-controller.log.8`.

Useful commands:

```bash
# Follow new messages
tail -f ~/Desktop/door/logs/door-controller.log

# Show the latest 100 messages
tail -n 100 ~/Desktop/door/logs/door-controller.log

# Search current and rotated logs for failures
grep -i -E 'error|exception|failed|traceback' ~/Desktop/door/logs/door-controller.log*

# Show log sizes
du -h ~/Desktop/door/logs/door-controller.log*
```

Normal Python application messages do not go to `journalctl`.
`journalctl -u door-controller` may still contain systemd lifecycle events such
as service starts, stops, and restart failures.

## Service management

```bash
# Check whether it is running
systemctl is-active door-controller

# Display service metadata
systemctl status door-controller --no-pager

# Restart after a code or service-file update
sudo systemctl restart door-controller

# Stop and start manually
sudo systemctl stop door-controller
sudo systemctl start door-controller

# Enable startup at boot
sudo systemctl enable door-controller
```

When `door-controller.service` changes, reinstall it before restarting:

```bash
cd ~/Desktop/door
sudo cp door-controller.service /etc/systemd/system/door-controller.service
sudo systemctl daemon-reload
sudo systemctl restart door-controller
```

## Updating the Pi from GitHub

```bash
cd ~/Desktop/door
git pull --ff-only
.venv/bin/pip install -r requirements.txt
sudo cp door-controller.service /etc/systemd/system/door-controller.service
sudo systemctl daemon-reload
sudo systemctl restart door-controller
systemctl is-active door-controller
tail -n 30 logs/door-controller.log
```

`git pull --ff-only` avoids silently creating a merge commit on the Pi. Review
and commit any intentional Pi-side changes before pulling.

## Troubleshooting

### Service does not stay active

```bash
systemctl status door-controller --no-pager
tail -n 100 ~/Desktop/door/logs/door-controller.log
.venv/bin/python -m py_compile controller.py hubspace_setup.py
```

Confirm the service uses the virtual-environment interpreter:

```bash
systemctl show door-controller -p ExecStart --no-pager
```

### GPIO errors

Confirm the virtual environment can see the Pi's GPIO backends:

```bash
.venv/bin/python -c "import importlib.util; print(importlib.util.find_spec('RPi.GPIO')); print(importlib.util.find_spec('lgpio'))"
```

If both results are `None`, recreate or upgrade the environment with system
packages enabled:

```bash
python3 -m venv --upgrade --system-site-packages .venv
sudo systemctl restart door-controller
```

### Song does not play

```bash
ls -lh /home/admin/Desktop/door/*.mp3
command -v mpg123
wpctl status
wpctl inspect @DEFAULT_AUDIO_SINK@
mpg123 -q /home/admin/Desktop/door/jukebox.mp3
```

If Bluetooth is expected, confirm the speaker is connected and is the default
PipeWire sink. If no Bluetooth sink is selected, the controller attempts the
configured analog headphones device.

### Light does not turn on or off

```bash
ls -l /home/admin/.config/ajspeakeasy/hubspace.json
grep -i -E 'hubspace|error|failed|exception' ~/Desktop/door/logs/door-controller.log*
```

Do not display the configuration file with `cat`; it contains the refresh
token. If authentication is rejected, rerun:

```bash
cd ~/Desktop/door
.venv/bin/python hubspace_setup.py
```

Hubspace commands require internet access and can be delayed or rejected by
cloud availability or API rate limiting. Audio and GPIO operation remain
independent of a Hubspace failure.

### Raspberry Pi low-voltage warning

Check the throttle status:

```bash
vcgencmd get_throttled
```

A nonzero result can indicate current or historical under-voltage/throttling.
Use a stable, appropriately rated Raspberry Pi power supply and a short,
high-quality power cable. Unstable power can cause unreliable USB, Bluetooth,
audio, storage, and GPIO behavior.

## Security notes

- The Hubspace integration is unofficial and may change if Hubspace changes its
  private cloud API.
- Never commit `hubspace.json`, passwords, refresh tokens, MP3 files, `.env`
  files, runtime logs, or the `.venv` directory.
- The Hubspace configuration lives outside the repository and is mode `600`.
- Application log files are also created with mode `600`.
- If a refresh token is exposed, revoke account sessions or change the Hubspace
  password, then rerun `hubspace_setup.py`.
- Keep Raspberry Pi OS and Python dependencies updated, but test updates before
  relying on the controller for unattended operation.

## Development notes

Before committing controller changes:

```bash
.venv/bin/python -m py_compile controller.py hubspace_setup.py
git diff --check
git status
```

After committing and pushing:

```bash
git push origin main
```

The service's software-button signal is the preferred full integration test
because it exercises the production process without requiring the physical
button.
