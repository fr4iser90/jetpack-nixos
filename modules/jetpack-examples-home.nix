# One-time copy of packaged examples/ into each login user's $HOME (writable; supports .env etc.).
{ config, lib, pkgs, ... }:

let
  inherit (lib) mkEnableOption mkIf mkOption types;
  cfg = config.jetpack-nixos.examplesHome;

  defaultExamples = pkgs.callPackage ../pkgs/jetpack-nixos-examples { };

  layout = {
    agent-layer = "agent-layer";
    comfyui = "ComfyUI";
    faster-whisper = "faster-whisper";
    homarr = "Homarr";
    librechat = "LibreChat";
    llama-server = "llama-server";
    localai = "LocalAI";
    n8n = "n8n";
    ollama = "Ollama";
    open-webui = "OpenWebUI";
    openai-whisper = "openai-whisper";
    pipeline-core = "pipeline-core";
    tensorrt-llm = "TensorRT-LLM";
    whisper-cpp = "whisper-cpp";
    wireguard = "WireGuard";
  };

  copyBlocks = lib.concatStringsSep "\n" (
    lib.mapAttrsToList (
      srcName: destName:
      let
        s = lib.escapeShellArg srcName;
        d = lib.escapeShellArg destName;
      in
      ''
        if [[ -d "$SRC/${s}" && ! -e "$h/${d}" ]]; then
          cp -a "$SRC/${s}" "$h/${d}"
        fi
      ''
    ) layout
  );
in
{
  options.jetpack-nixos.examplesHome = {
    enable = mkEnableOption ''
      copy packaged Docker example stacks into each normal user's home directory once (writable copies).
      Delete ~/.config/jetpack-nixos/examples-copied-v* and the stack dirs to re-copy after a major update.
    '';
    package = mkOption {
      type = types.package;
      default = defaultExamples;
      description = "Derivation providing share/jetpack-nixos-examples/{lib,<stacks>}/.";
    };
  };

  config = mkIf cfg.enable (
    let
      srcRoot = "${cfg.package}/share/jetpack-nixos-examples";
      copyScript = pkgs.writeShellScript "jetpack-nixos-copy-examples" ''
        set -euo pipefail
        SRC=${lib.escapeShellArg srcRoot}
        STAMP_REL=".config/jetpack-nixos/examples-copied-v1"
        while IFS=: read -r login _ uid _ _ home shell; do
          [[ "$uid" =~ ^[0-9]+$ ]] || continue
          (( uid >= 1000 && uid < 65000 )) || continue
          [[ "$home" == /home/* ]] || continue
          [[ -d "$home" ]] || continue
          [[ "$shell" == */nologin ]] && continue
          h="$home"
          stamp="$h/$STAMP_REL"
          [[ -f "$stamp" ]] && continue
          mkdir -p "$(dirname "$stamp")"
          ${copyBlocks}
          if [[ -d "$SRC/lib" && ! -e "$h/lib" ]]; then
            cp -a "$SRC/lib" "$h/lib"
          fi
          touch "$stamp"
        done < /etc/passwd
      '';
    in
    {
      environment.systemPackages = [ cfg.package ];

      system.activationScripts.jetpack-nixos-examples-home = {
        deps = [ "users" ];
        text = ''
          echo "jetpack-nixos: copying example stacks into user homes (if needed)..."
          ${copyScript}
        '';
      };
    }
  );
}
