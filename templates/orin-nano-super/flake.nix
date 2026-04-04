{
  description = "NixOS — Jetson Orin Nano Super (devkit) with jetpack-nixos";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-25.11";
    # Change the next line to your fork or to the upstream you track.
    jetpack.url = "github:fr4iser90/nixos-jetson-orin-nano";
    jetpack.inputs.nixpkgs.follows = "nixpkgs";
  };

  outputs =
    { self, nixpkgs, jetpack, ... }:
    {
      nixosConfigurations.nixos = nixpkgs.lib.nixosSystem {
        system = "aarch64-linux";
        modules = [
          ./configuration.nix
          jetpack.nixosModules.default
          jetpack.nixosModules.examples-home
        ];
      };
    };
}
