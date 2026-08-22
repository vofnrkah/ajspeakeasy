#!/usr/bin/env python3

"""Configure a Hubspace switch without storing the account password."""

import asyncio
import getpass
import json
import os
from pathlib import Path

from aiohubspace import v1


CONFIG_FILE = Path.home() / ".config" / "ajspeakeasy" / "hubspace.json"


def device_name(device):
    info = device.device_information
    return info.name or info.default_name or device.id


async def configure():
    print("Hubspace credentials are used only to create a refresh token.")
    username = input("Hubspace email: ").strip()
    password = getpass.getpass("Hubspace password (hidden): ")

    bridge = v1.HubspaceBridgeV1(username, password, polling_interval=30)

    try:
        print("Signing in and finding switches...")
        await bridge.initialize()
        switches = bridge.switches.items

        if not switches:
            raise RuntimeError("No Hubspace switches were found on this account")

        print("\nAvailable Hubspace switches:")
        for number, switch in enumerate(switches, start=1):
            info = switch.device_information
            print(
                f"  {number}. {device_name(switch)} "
                f"(model={info.model}, id={switch.id})"
            )

        while True:
            raw_choice = input("Select the light's switch number: ").strip()
            try:
                selected = switches[int(raw_choice) - 1]
                break
            except (ValueError, IndexError):
                print("Enter one of the numbers shown above.")

        instance = next(iter(selected.on), None)
        config = {
            "username": username,
            "refresh_token": bridge.refresh_token,
            "device_id": selected.id,
            "instance": instance,
            "device_name": device_name(selected),
        }

        CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
        CONFIG_FILE.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
        os.chmod(CONFIG_FILE, 0o600)

        print(f"Configured: {config['device_name']}")
        print(f"Saved secure configuration to: {CONFIG_FILE}")
        print("Your Hubspace password was not saved.")

    finally:
        await bridge.close()


if __name__ == "__main__":
    asyncio.run(configure())
