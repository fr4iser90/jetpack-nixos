# JetPack versions, graphics, firmware

## JetPack major version

Set `hardware.nvidia-jetpack.majorVersion` to change the major JetPack line. It defaults to the latest supported for the board. The `generic` SOM defaults to JetPack 6.

Firmware and rootfs/kernel for one major version are not interchangeable with another (e.g. JetPack 5 firmware vs JetPack 6 kernel). Plan upgrades so firmware and software move together.

If not installing JetPack 6 firmware via the flash scripts, the upstream docs often recommend installing the JetPack 6 bootloader configuration, applying the capsule update, then rebooting so the device transitions firmware in a controlled way.

## Graphical output

Status as of 2023-12-09; if something should work but does not, try other ports (HDMI / DP / USB-C), cables, and cold boot with cables connected vs disconnected.

For DP on Orin AGX in particular: connect when the fan briefly stops during boot.

### Linux console

On Orin AGX / NX / Nano, the Linux console often does not appear on HDMI/DisplayPort (likely upstream, not specific to this repo). **Serial** is the most reliable for troubleshooting.

### X11

Set `hardware.nvidia-jetpack.modesetting.enable = false;` (often the default). LightDM + i3 and LightDM + Gnome have been tested; add the user to the `video` group. GDM may not work.

### Wayland

Set `hardware.nvidia-jetpack.modesetting.enable = true;`. Weston and sway have been tested on Orin.

## Updating firmware from the running system (UEFI capsule)

JetPack ≥ 5.1 can apply firmware updates from the device via UEFI capsule updates (alternative to USB recovery + re-flash). You can enable automatic updates after `nixos-rebuild switch` with `hardware.nvidia-jetpack.bootloader.autoUpdate`.

Check running vs expected firmware:

```shell
ota-check-firmware
```

Build the capsule from your configuration (`config.system.build.uefiCapsuleUpdate`) or use a matching `uefi-capsule-update-*` output from `nix flake show` for supported devkits. Copy the `.Cap` file to the device, then:

```shell
sudo ota-apply-capsule-update example.Cap
sudo reboot
```

Do not remove power during the update. The mechanism updates the non-current A/B slot and reboots; a failed boot can roll back to the previous firmware.

After reboot, `ota-check-firmware` again; for slot details:

```shell
sudo nvbootctrl dump-slots-info
```

Capsule status codes: `0` none, `1` success, `2` installed but new firmware failed to boot, `3` install failed.

## UEFI capsule authentication

To require signed capsules only, generate keys per [EDK2 Capsule Signing](https://github.com/tianocore/tianocore.github.io/wiki/Capsule-Based-System-Firmware-Update-Generate-Keys) and enable `hardware.nvidia-jetpack.firmware.uefi.capsuleAuthentication.enable` with your key options set.
