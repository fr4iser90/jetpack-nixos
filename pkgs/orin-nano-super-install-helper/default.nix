{ lib
, stdenvNoCC
, makeWrapper
, bash
, coreutils
, openssl
, util-linux
, parted
, dosfstools
, e2fsprogs
, nixos-install-tools
, nix
,
}:

let
  templates = ../../templates/orin-nano-super;
  installScript = ../../scripts/install-orin-nano-super.sh;
  prepareScript = ../../scripts/prepare-orin-nano-super-disk.sh;
  installAllScript = ../../scripts/orin-nano-super-install-all.sh;
  diskTools = lib.makeBinPath [
    coreutils
    bash
    util-linux
    parted
    dosfstools
    e2fsprogs
  ];
  wizardPath = lib.makeBinPath [
    coreutils
    bash
    util-linux
    nixos-install-tools
    nix
  ];
in
stdenvNoCC.mkDerivation {
  pname = "orin-nano-super-install-helper";
  version = "0.1";

  dontUnpack = true;

  nativeBuildInputs = [ makeWrapper ];

  installPhase = ''
    mkdir -p $out/share/orin-nano-super
    cp -Lr ${templates}/* $out/share/orin-nano-super/
    install -Dm755 ${installScript} $out/libexec/install-orin-nano-super.sh
    install -Dm755 ${prepareScript} $out/libexec/prepare-orin-nano-super-disk.sh
    install -Dm755 ${installAllScript} $out/libexec/orin-nano-super-install-all.sh
    makeWrapper $out/libexec/install-orin-nano-super.sh $out/bin/install-orin-nano-super \
      --set TEMPLATES_DIR $out/share/orin-nano-super \
      --prefix PATH : ${lib.makeBinPath [
        coreutils
        bash
        openssl
      ]}
    makeWrapper $out/libexec/prepare-orin-nano-super-disk.sh $out/bin/prepare-orin-nano-super-disk \
      --prefix PATH : ${diskTools}
    makeWrapper $out/libexec/orin-nano-super-install-all.sh $out/bin/orin-nano-super-install-all \
      --prefix PATH : ${wizardPath}:$out/bin
  '';
}
