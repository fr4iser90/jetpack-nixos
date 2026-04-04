# OCI containers, kernel, CUDA / Nixpkgs

## OCI containers (Docker / Podman + GPU)

Enable:

```nix
{
  hardware.nvidia-container-toolkit.enable = true;
  virtualisation = {
    docker.enable = true;
    podman.enable = true;
  };
}
```

On newer nixpkgs, prefer `hardware.nvidia-container-toolkit.enable` over deprecated `virtualisation.{docker,podman}.enableNvidia`.

Pass GPU into containers using [CDI](https://github.com/cncf-tags/container-device-interface/blob/main/SPEC.md#overview). The default device is typically `nvidia.com/gpu=all`:

```shell
docker run --device=nvidia.com/gpu=all ...
```

For Podman systemd units, add `After=nvidia-container-toolkit-cdi-generator.service` so CDI files exist before the container starts.

## Kernel package sets

Predefined sets (Jetson Linux sources):

- `pkgs.nvidia-jetpack.kernelPackages`
- `pkgs.nvidia-jetpack.rtkernelPackages`

The NixOS module uses these by default. On JetPack 6+ you may use a mainline kernel per NVIDIA’s [Bring Your Own Kernel](https://docs.nvidia.com/jetson/archives/r36.4.4/DeveloperGuide/SD/Kernel/BringYourOwnKernel.html) notes; out-of-tree modules still need this overlay.

Example:

```nix
{ pkgs, ... }:

{
  config.boot.kernelPackages = pkgs.nvidia-jetpack.kernelPackages.extend pkgs.nvidia-jetpack.kernelPackagesOverlay;
}
```

## Configuring CUDA for Nixpkgs

> [!NOTE]
>
> NixOS configurations that use the JetPack modules normally get CUDA-enabled Nixpkgs automatically. Turn that off with `hardware.nvidia-jetpack.configureCuda = false` and apply the import rules below yourself.

### Importing Nixpkgs

```nix
{
  config = {
    allowUnfree = true;
    cudaSupport = true;
    cudaCapabilities = [ "7.2" "8.7" ];
  };
}
```

> [!IMPORTANT]
>
> The `config` attribute set is not part of Nixpkgs’ fixed-point; use `pkgs.extend` when you need changes to take effect. For Jetsons, `cudaCapabilities` is effectively required because Jetson arches are not in the defaults.

- `allowUnfree` — CUDA redistributables are unfree.
- `cudaSupport` — enables CUDA-backed packages where applicable.
- `cudaCapabilities` — [GPU architectures](https://developer.nvidia.com/cuda-gpus) for which code is generated; Orin uses `"8.7"`.

### Defaulting to this repo’s CUDA package set

The overlay exposes `pkgs.nvidia-jetpack.cudaPackages`. Many packages do not pick it up automatically. To make it the default CUDA set:

```nix
final: _: { inherit (final.nvidia-jetpack) cudaPackages; }
```
