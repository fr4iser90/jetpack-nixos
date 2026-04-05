# Optional native env (no Docker). Requires nixpkgs in NIX_PATH or pass pkgs:
#   nix-shell examples/lora-trainer/nix/shell.nix
# Extend with python312Packages.torch / CUDA overlays for real training on Jetson or desktop.
{ pkgs ? import <nixpkgs> { } }:

pkgs.mkShell {
  packages = with pkgs; [
    python312
    git
  ];

  shellHook = ''
    echo "lora-trainer nix shell: Python only — add torch/peft (nixpkgs or pip venv) for training."
  '';
}
