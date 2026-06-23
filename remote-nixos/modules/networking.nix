{ config, ... }:

{
  # Tailscale config
  services.tailscale.enable = true;

  networking.firewall.trustedInterfaces = [ "tailscale0" ];
  networking.firewall.allowedUDPPorts = [ config.services.tailscale.port ];

  # Enable networking
  networking.networkmanager.enable = true;
  networking.networkmanager.wifi.powersave = false;

  # Stabilize the TP-Link 2357:0115 / Realtek RTL8822BU USB Wi-Fi adapter.
  boot.extraModprobeConfig = ''
    options rtw88_core disable_lps_deep=Y
  '';
  services.udev.extraRules = ''
    ACTION=="add", SUBSYSTEM=="usb", ATTR{idVendor}=="2357", ATTR{idProduct}=="0115", TEST=="power/control", ATTR{power/control}="on"
  '';
}
