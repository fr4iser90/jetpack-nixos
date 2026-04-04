{ lib, stdenvNoCC }:

stdenvNoCC.mkDerivation {
  pname = "jetpack-nixos-examples";
  version = "0.1";
  src = ../../examples;

  dontConfigure = true;

  installPhase = ''
    mkdir -p $out/share/jetpack-nixos-examples
    shopt -s dotglob nullglob
    cp -r ./* "$out/share/jetpack-nixos-examples/"
  '';

  meta = {
    description = "Docker compose example stacks (agent-layer, ollama, …) copied into user home on first boot";
    license = lib.licenses.mit;
  };
}
