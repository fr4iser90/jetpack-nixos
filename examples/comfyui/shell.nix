# Native ComfyUI auf Jetson: ComfyUI-Root, dann: nix-shell
#
# Jetpack-Overlay (libcudart/libcublas via nvidia-jetpack) wird geladen aus:
#   1) /etc/nixos/flake.lock — Input „jetpack“ oder „jetpack-nixos“ o. ä.: type github oder path
#   2) optional: JETPACK_NIXOS = lokales Verzeichnis mit flake.nix (wenn 1 fehlt)
# Optional: eigenes pkgs: nix-shell --arg pkgs '…'
#
# nvidia-l4t-cuda ≠ vollständiges CUDA-Toolkit; libcudart/libcublas: nvidia-jetpack.cudaPackages
# Alias: cinstall, crun, ccheck
{
  pkgs ? null,
}:

let
  bootstrap = import <nixpkgs> { };
  inherit (bootstrap) lib;

  envJp = lib.removeSuffix "/" (builtins.getEnv "JETPACK_NIXOS");

  lockPath = "/etc/nixos/flake.lock";
  lockJetpackLocked =
    if builtins.pathExists lockPath then
      let
        lock = builtins.fromJSON (builtins.readFile lockPath);
        nodes = lock.nodes or { };
        name =
          if nodes ? "jetpack" then
            "jetpack"
          else if nodes ? "jetpack-nixos" then
            "jetpack-nixos"
          else
            lib.findFirst (n: lib.hasInfix "jetpack" (lib.toLower n)) null (builtins.attrNames nodes);
      in
      if name != null then (nodes.${name}.locked or null) else null
    else
      null;

  lockJetpackRoot =
    if lockJetpackLocked != null && lockJetpackLocked.type == "path" then
      let
        p = lockJetpackLocked.path;
      in
      if lib.hasPrefix "/" p then p else "/etc/nixos/" + p
    else
      null;

  lockGithubOverlay =
    if
      lockJetpackLocked != null
      && lockJetpackLocked.type == "github"
      && lockJetpackLocked ? owner
      && lockJetpackLocked ? repo
      && lockJetpackLocked ? rev
    then
      let
        r = builtins.tryEval (
          let
            f = builtins.getFlake (
              "github:" + lockJetpackLocked.owner + "/" + lockJetpackLocked.repo + "/" + lockJetpackLocked.rev
            );
          in
          f.overlays.default or (throw "jetpack flake: overlays.default fehlt")
        );
      in
      if r.success then [ r.value ] else [ ]
    else
      [ ];

  jpRoot =
    if envJp != "" then
      envJp
    else if lockJetpackRoot != null then
      lockJetpackRoot
    else
      null;

  flakeOverlay =
    if jpRoot != null && builtins.pathExists (jpRoot + "/flake.nix") then
      let
        r = builtins.tryEval (
          let
            f = builtins.getFlake ("path:" + jpRoot);
          in
          f.overlays.default or (throw "jetpack flake: overlays.default fehlt")
        );
      in
      if r.success then [ r.value ] else [ ]
    else
      [ ];

  legacyOverlayOnly =
    if jpRoot != null && flakeOverlay == [ ] && builtins.pathExists (jpRoot + "/overlay.nix") then
      [ (import (jpRoot + "/overlay.nix")) ]
    else
      [ ];

  overlaysCombined = flakeOverlay ++ legacyOverlayOnly ++ lockGithubOverlay;

  resolvedPkgs =
    if pkgs != null then
      pkgs
    else
      import <nixpkgs> {
        config = {
          allowUnfree = true;
          cudaSupport = true;
          # Orin Nano = SM87. CUDA 12.6 rejects older SMs (e.g. 7.2), so keep only 8.7 here.
          cudaCapabilities = lib.optionals (builtins.currentSystem == "aarch64-linux") [ "8.7" ];
        };
        overlays = overlaysCombined;
      };

  nvTorchJp61 = "https://developer.download.nvidia.com/compute/redist/jp/v61/pytorch/torch-2.5.0a0+872d972e41.nv24.08.17622132-cp310-cp310-linux_aarch64.whl";
  jetpackCuda =
    let
      jp =
        if builtins.hasAttr "nvidia-jetpack6" resolvedPkgs then
          resolvedPkgs.nvidia-jetpack6
        else if builtins.hasAttr "nvidia-jetpack" resolvedPkgs then
          resolvedPkgs.nvidia-jetpack
        else
          null;
      lp = resolvedPkgs.lib;
    in
    if jp != null then
      [
        jp.l4t-cuda
        jp.l4t-core
      ]
      ++ (with jp.cudaPackages; [
        cuda_cudart
        libcublas
        # provides libnvToolsExt.so.1 (NVTX) which torch preloads
        cuda_nvtx
        # torch expects libcudnn.so.9 on JP6
        cudnn
        # provides libcupti.so.12 (CUDA profiling tools interface), which torch may preload
        cuda_cupti
        # provides libcusparse.so.12 (sparse linear algebra), which torch may preload
        libcusparse
        # provides libcufft.so.11 (FFT), which torch may preload
        libcufft
        # common follow-ups for torch on CUDA 12.x
        libcurand
        libcusolver
      ])
      ++ lp.optional (builtins.hasAttr "libcublasLt" jp.cudaPackages) jp.cudaPackages.libcublasLt
      # cuSPARSELt (libcusparseLt.so.0): not in nixpkgs CUDA redist; use PyPI wheel nvidia-cusparselt-cu12
      # and prepend its lib dir in shellHook / ccheck / crun (see _comfyui_add_cusparselt_ld).
    else
      [ ];
  cudaLdPrefix =
    let
      lp = resolvedPkgs.lib;
    in
    lp.optionalString (jetpackCuda != [ ]) ((lp.makeLibraryPath jetpackCuda) + ":");

  jpHint =
    if builtins.hasAttr "nvidia-jetpack6" resolvedPkgs || builtins.hasAttr "nvidia-jetpack" resolvedPkgs then
      "jetpack-Overlay aktiv (JP6 bevorzugt; aus /etc/nixos/flake.lock oder JETPACK_NIXOS)"
    else
      "WARN: kein nvidia-jetpack — braucht /etc/nixos/flake.lock (Input jetpack) oder gesetztes JETPACK_NIXOS";
in
resolvedPkgs.mkShellNoCC {
  packages =
    with resolvedPkgs;
    [
      python310
      python310Packages.pip
      git
      wget
      curl
      ffmpeg
      stdenv.cc.cc.lib
      zlib
      openblas
    ]
    ++ jetpackCuda;

  shellHook = ''
    # Nicht System-Python (z. B. 3.13) — ComfyUI-venv ist 3.10
    export PATH="${resolvedPkgs.python310}/bin:''${PATH}"
    export LD_LIBRARY_PATH="${cudaLdPrefix}${resolvedPkgs.stdenv.cc.cc.lib}/lib:${resolvedPkgs.zlib}/lib:${resolvedPkgs.openblas}/lib''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    for _gpu in /run/opengl-driver/lib /run/opengl-driver-32/lib; do
      [[ -d "$_gpu" ]] && export LD_LIBRARY_PATH="$_gpu''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
    done
    # L4T/CUDA aus laufendem NixOS-System (Overlay sitzt im System, nicht in plain nixpkgs)
    if [[ -e /run/current-system ]] && command -v nix-store >/dev/null 2>&1; then
      while IFS= read -r _p; do
        case "$_p" in
          *-nvidia-l4t-cuda-*|*-nvidia-l4t-core-*|*-cuda-cudart-*|*-libcublas-*|*-libcublas_lt-*|*-cuda_nvtx-*|*-cudnn-*|*-cuda_cupti-*|*-libcusparse-*|*-libcufft-*|*-libcurand-*|*-libcusolver-*)
            [[ -d "$_p/lib" ]] && export LD_LIBRARY_PATH="$_p/lib''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
            [[ -d "$_p/lib64" ]] && export LD_LIBRARY_PATH="$_p/lib64''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
            ;;
        esac
      done < <(nix-store -qR /run/current-system 2>/dev/null)
    fi
    # Store-Glob (falls nix-store nicht geht)
    for _cuda in /nix/store/*-nvidia-l4t-cuda-*/lib; do
      [[ -d "$_cuda" ]] || continue
      [[ -n "$(find "$_cuda" -maxdepth 1 -name 'libcudart.so*' -print -quit)" ]] || continue
      export LD_LIBRARY_PATH="$_cuda''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
      break
    done
    for _core in /nix/store/*-nvidia-l4t-core-*/lib; do
      [[ -e "$_core/libcuda.so" || -e "$_core/libnvcucompat.so" ]] || continue
      export LD_LIBRARY_PATH="$_core''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
      break
    done
    for _cd in /nix/store/*-cuda-cudart-*/lib; do
      [[ -d "$_cd" ]] || continue
      [[ -n "$(find "$_cd" -maxdepth 1 -name 'libcudart.so*' -print -quit)" ]] || continue
      export LD_LIBRARY_PATH="$_cd''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
      break
    done
    for _cd64 in /nix/store/*-cuda-cudart-*/lib64; do
      [[ -d "$_cd64" ]] || continue
      [[ -n "$(find "$_cd64" -maxdepth 1 -name 'libcudart.so*' -print -quit)" ]] || continue
      export LD_LIBRARY_PATH="$_cd64''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
      break
    done
    for _cb in /nix/store/*-libcublas-*/lib; do
      [[ -d "$_cb" ]] || continue
      [[ -n "$(find "$_cb" -maxdepth 1 -name 'libcublas.so*' -print -quit)" ]] || continue
      export LD_LIBRARY_PATH="$_cb''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
      break
    done
    for _cb64 in /nix/store/*-libcublas-*/lib64; do
      [[ -d "$_cb64" ]] || continue
      [[ -n "$(find "$_cb64" -maxdepth 1 -name 'libcublas.so*' -print -quit)" ]] || continue
      export LD_LIBRARY_PATH="$_cb64''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
      break
    done
    for _nvtx in /nix/store/*-cuda_nvtx-*/lib; do
      [[ -d "$_nvtx" ]] || continue
      [[ -n "$(find "$_nvtx" -maxdepth 1 -name 'libnvToolsExt.so*' -print -quit)" ]] || continue
      export LD_LIBRARY_PATH="$_nvtx''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
      break
    done
    for _nvtx64 in /nix/store/*-cuda_nvtx-*/lib64; do
      [[ -d "$_nvtx64" ]] || continue
      [[ -n "$(find "$_nvtx64" -maxdepth 1 -name 'libnvToolsExt.so*' -print -quit)" ]] || continue
      export LD_LIBRARY_PATH="$_nvtx64''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
      break
    done
    for _cudnn in /nix/store/*-cudnn-*/lib; do
      [[ -d "$_cudnn" ]] || continue
      [[ -n "$(find "$_cudnn" -maxdepth 1 -name 'libcudnn.so*' -print -quit)" ]] || continue
      export LD_LIBRARY_PATH="$_cudnn''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
      break
    done
    for _cudnn64 in /nix/store/*-cudnn-*/lib64; do
      [[ -d "$_cudnn64" ]] || continue
      [[ -n "$(find "$_cudnn64" -maxdepth 1 -name 'libcudnn.so*' -print -quit)" ]] || continue
      export LD_LIBRARY_PATH="$_cudnn64''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
      break
    done
    for _cupti in /nix/store/*-cuda_cupti-*/lib; do
      [[ -d "$_cupti" ]] || continue
      [[ -n "$(find "$_cupti" -maxdepth 1 -name 'libcupti.so*' -print -quit)" ]] || continue
      export LD_LIBRARY_PATH="$_cupti''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
      break
    done
    for _cupti64 in /nix/store/*-cuda_cupti-*/lib64; do
      [[ -d "$_cupti64" ]] || continue
      [[ -n "$(find "$_cupti64" -maxdepth 1 -name 'libcupti.so*' -print -quit)" ]] || continue
      export LD_LIBRARY_PATH="$_cupti64''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
      break
    done
    for _csp in /nix/store/*-libcusparse-*/lib; do
      [[ -d "$_csp" ]] || continue
      [[ -n "$(find "$_csp" -maxdepth 1 -name 'libcusparse.so*' -print -quit)" ]] || continue
      export LD_LIBRARY_PATH="$_csp''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
      break
    done
    for _csp64 in /nix/store/*-libcusparse-*/lib64; do
      [[ -d "$_csp64" ]] || continue
      [[ -n "$(find "$_csp64" -maxdepth 1 -name 'libcusparse.so*' -print -quit)" ]] || continue
      export LD_LIBRARY_PATH="$_csp64''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
      break
    done
    for _cufft in /nix/store/*-libcufft-*/lib; do
      [[ -d "$_cufft" ]] || continue
      [[ -n "$(find "$_cufft" -maxdepth 1 -name 'libcufft.so*' -print -quit)" ]] || continue
      export LD_LIBRARY_PATH="$_cufft''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
      break
    done
    for _cufft64 in /nix/store/*-libcufft-*/lib64; do
      [[ -d "$_cufft64" ]] || continue
      [[ -n "$(find "$_cufft64" -maxdepth 1 -name 'libcufft.so*' -print -quit)" ]] || continue
      export LD_LIBRARY_PATH="$_cufft64''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
      break
    done
    for _curand in /nix/store/*-libcurand-*/lib; do
      [[ -d "$_curand" ]] || continue
      [[ -n "$(find "$_curand" -maxdepth 1 -name 'libcurand.so*' -print -quit)" ]] || continue
      export LD_LIBRARY_PATH="$_curand''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
      break
    done
    for _curand64 in /nix/store/*-libcurand-*/lib64; do
      [[ -d "$_curand64" ]] || continue
      [[ -n "$(find "$_curand64" -maxdepth 1 -name 'libcurand.so*' -print -quit)" ]] || continue
      export LD_LIBRARY_PATH="$_curand64''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
      break
    done
    for _cusolver in /nix/store/*-libcusolver-*/lib; do
      [[ -d "$_cusolver" ]] || continue
      [[ -n "$(find "$_cusolver" -maxdepth 1 -name 'libcusolver.so*' -print -quit)" ]] || continue
      export LD_LIBRARY_PATH="$_cusolver''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
      break
    done
    for _cusolver64 in /nix/store/*-libcusolver-*/lib64; do
      [[ -d "$_cusolver64" ]] || continue
      [[ -n "$(find "$_cusolver64" -maxdepth 1 -name 'libcusolver.so*' -print -quit)" ]] || continue
      export LD_LIBRARY_PATH="$_cusolver64''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
      break
    done
    # cuSPARSELt: wheel nvidia-cusparselt-cu12 installs nvidia/cusparselt/lib/libcusparseLt.so.0
    # Must run after pip install too (shellHook only runs once at nix-shell entry).
    _comfyui_add_cusparselt_ld() {
      local _d _csl
      _d=".venv/lib/python3.10/site-packages/nvidia/cusparselt/lib"
      if [[ -f "$_d/libcusparseLt.so.0" || -f "$_d/libcusparseLt.so" ]]; then
        case ":$LD_LIBRARY_PATH:" in *":$_d:"*) ;; *) export LD_LIBRARY_PATH="$_d''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" ;; esac
        return 0
      fi
      _csl="$(find .venv/lib/python3.10/site-packages/nvidia/cusparselt -name 'libcusparseLt.so*' 2>/dev/null | head -n1)"
      if [[ -n "$_csl" ]]; then
        _d="$(dirname "$_csl")"
        case ":$LD_LIBRARY_PATH:" in *":$_d:"*) ;; *) export LD_LIBRARY_PATH="$_d''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}" ;; esac
      fi
    }
    _comfyui_add_cusparselt_ld
    export COMFYUI_NV_TORCH_WHEEL="${nvTorchJp61}"

    comfyui_native_install() {
      if [[ ! -f main.py ]]; then
        echo "comfyui_native_install: main.py fehlt — ins ComfyUI-Clone-Root (git clone …) wechseln."
        return 1
      fi
      if [[ ! -f requirements.txt ]]; then
        echo "comfyui_native_install: requirements.txt fehlt."
        return 1
      fi
      python3 -m venv .venv
      .venv/bin/pip install -U pip setuptools wheel
      .venv/bin/pip install 'numpy<2'
      _lab="https://pypi.jetson-ai-lab.dev/jp6/cu126/+f"
      _lab_ok=0
      if .venv/bin/pip install \
        "$_lab/5cf/9ed17e35cb752/torch-2.5.0-cp310-cp310-linux_aarch64.whl" \
        "$_lab/9d2/6fac77a4e832a/torchvision-0.19.1a0+6194369-cp310-cp310-linux_aarch64.whl" \
        "$_lab/812/4fbc4ba6df0a3/torchaudio-2.5.0-cp310-cp310-linux_aarch64.whl"
      then
        _lab_ok=1
      else
        echo "jetson-ai-lab fehlgeschlagen (DNS?) — Fallback: nur NVIDIA L4T torch"
        .venv/bin/pip install "$COMFYUI_NV_TORCH_WHEEL"
        echo "WARN: torchvision/torchaudio — PyPI-Paare wollen oft torch 2.11; bei Problemen DNS fixen (jetson-ai-lab) oder Docker."
        .venv/bin/pip uninstall -y torchvision torchaudio 2>/dev/null || true
      fi
      _rq=$(mktemp /tmp/comfyui-req-no-torch.XXXXXX.txt)
      _con=$(mktemp /tmp/comfyui-constraints.XXXXXX.txt)
      grep -vE '^(torch|torchvision|torchaudio)(\[|==|>=|$)' requirements.txt > "$_rq"
      if [[ "$_lab_ok" -eq 1 ]]; then
        {
          echo "torch @ $_lab/5cf/9ed17e35cb752/torch-2.5.0-cp310-cp310-linux_aarch64.whl"
          echo "torchvision @ $_lab/9d2/6fac77a4e832a/torchvision-0.19.1a0+6194369-cp310-cp310-linux_aarch64.whl"
          echo "torchaudio @ $_lab/812/4fbc4ba6df0a3/torchaudio-2.5.0-cp310-cp310-linux_aarch64.whl"
        } > "$_con"
      else
        echo "torch @ $COMFYUI_NV_TORCH_WHEEL" > "$_con"
      fi
      .venv/bin/pip install -r "$_rq" -c "$_con"
      rm -f "$_rq" "$_con"
      if [[ "$_lab_ok" -eq 0 ]]; then
        .venv/bin/pip install --force-reinstall --no-deps "$COMFYUI_NV_TORCH_WHEEL"
        .venv/bin/pip install 'sympy==1.13.1' --force-reinstall --no-deps 2>/dev/null || true
      fi
      # Torch may dlopen libcusparseLt.so.0 (not in Nix CUDA redist); wheel matches JP6 cu12.
      .venv/bin/pip install --no-cache-dir nvidia-cusparselt-cu12 || true
      echo "OK — start: crun   (oder: comfyui_run)"
    }

    comfyui_run() {
      if [[ ! -f main.py ]]; then
        echo "comfyui_run: main.py fehlt."
        return 1
      fi
      if [[ ! -x .venv/bin/python ]]; then
        echo "comfyui_run: erst cinstall / comfyui_native_install"
        return 1
      fi
      _comfyui_add_cusparselt_ld
      exec .venv/bin/python main.py --listen 0.0.0.0 --port 8188 "$@"
    }

    alias cinstall=comfyui_native_install
    alias crun=comfyui_run

    ccheck() {
      if [[ -x .venv/bin/python ]]; then
        _comfyui_add_cusparselt_ld
        .venv/bin/python -c "import torch; print('torch.cuda.is_available():', torch.cuda.is_available())"
      else
        echo "Kein .venv — erst cinstall"
      fi
    }

    echo ""
    echo "ComfyUI native — ${jpHint}"
    echo "  python=3.10 | libcudart/libcublas via cudaPackages | Alias: cinstall crun ccheck"
    echo "  Test: ccheck"
    echo ""
  '';
}
