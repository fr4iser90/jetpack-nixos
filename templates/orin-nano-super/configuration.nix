# Edit ./local.nix for hostname, user, and passwords (or run install-orin-nano-super from the installer ISO).
{ config, pkgs, ... }:

{
  imports = [
    ./hardware-configuration.nix
    ./local.nix
  ];

  hardware.nvidia-jetpack.enable = true;
  hardware.nvidia-jetpack.som = "orin-nano";
  hardware.nvidia-jetpack.carrierBoard = "devkit";
  hardware.nvidia-jetpack.super = true;
  hardware.graphics.enable = true;

  # Docker + GPU in containers; example stacks are copied into each user's $HOME on first boot.
  virtualisation.docker.enable = true;
  hardware.nvidia-container-toolkit.enable = true;

  jetpack-nixos.examplesHome.enable = true;

  services.openssh.enable = true;

  nix.settings.experimental-features = [
    "nix-command"
    "flakes"
  ];

  system.stateVersion = "25.11";
}
