# Adds install-orin-nano-super + templates to the minimal installer ISO (live session).
{ lib, pkgs, ... }:

let
  helper = pkgs.callPackage ../pkgs/orin-nano-super-install-helper { };

  installHint = ''
    Jetson Orin Nano Super — install (flakes):
      sudo orin-nano-super-install-all           # one wizard: optional disk prep → generate-config → install-orin → nixos-install
    Or step by step:
      sudo prepare-orin-nano-super-disk          # optional: wipe disk + mount /mnt, or print manual steps
      sudo nixos-generate-config --root /mnt
      sudo install-orin-nano-super
      sudo nixos-install --root /mnt --flake /mnt/etc/nixos#nixos
    Dry-run (no disk changes):  prepare-orin-nano-super-disk --dry-run
                                install-orin-nano-super --dry-run [--clean] [--no-nix-check]
    Manual steps only:  prepare-orin-nano-super-disk --manual-only
    Template copy:      /etc/orin-nano-super-template/
  '';
in
{
  environment.systemPackages = [ helper ];

  # Convenience tree on the live system (read-only mirror of the packaged templates).
  environment.etc."orin-nano-super-template".source = "${helper}/share/orin-nano-super";

  # Below the standard installer hints on virtual consoles (passwords, ssh, nmtui, …).
  services.getty.helpLine = lib.mkAfter installHint;

  # tty1 uses autologin and often skips showing /etc/issue — show once per boot after login.
  environment.loginShellInit = lib.mkAfter ''
    stamp=/run/jetpack-nixos-install-welcome
    if [ "''${USER:-}" = nixos ] && [ ! -f "$stamp" ]; then
      touch "$stamp" 2>/dev/null || true
      printf '\n%s\n\n' ${lib.escapeShellArg installHint}
    fi
  '';
}
