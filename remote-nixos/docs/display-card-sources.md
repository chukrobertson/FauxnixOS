# Display Cards And Sources

## Product Model

A Fauxnix Display card is a monitor on the infinite workspace. It is not an app
window. Apps, VMs, remote desktops, and Fauxpass streams are sources plugged into
that monitor.

```
Workspace canvas
  -> Display card
      -> DisplaySource descriptor
          -> local app, VM framebuffer, Fauxpass app, remote stream, etc.
```

The Display card owns workspace behavior:

- position on the infinite canvas
- zoom and fit/fullscreen behavior
- selection and focus affordances
- continuity sockets
- frame scaling and presentation

The source owns runtime behavior:

- launching or connecting to the app, VM, or remote service
- producing RGBA frames
- accepting keyboard, pointer, and gesture input
- resize/focus/minimize/close lifecycle
- source-specific health and metadata

## Current Code Shape

The compatibility API is still named `SurfaceProvider`, but new code should
think and speak in terms of Display sources. The registry exposes both
vocabularies:

- preferred: `create_source`, `normalize_source_spec`, `source_descriptors`
- compatibility: `create_provider`, `normalize_provider_spec`,
  `provider_descriptors`

Source descriptors are plain JSON-shaped dictionaries. Important fields:

- `kind`: source backend, such as `local-app` or `fauxpass-app`
- `source_kind`: same as `kind`; accepted as an alias for source descriptors
- `surface_name`: display title shown on the card
- `surface_kind`: broad card role, such as `app`, `vm`, or `fauxpass-remote`
- `width`, `height`: requested source framebuffer size
- `context`: continuity metadata exposed through card sockets

The Display card accepts source descriptors over its `control` socket using:

- `{ "action": "attach-source", "source_spec": { ... } }`
- `{ "action": "launch", "source_spec": { ... } }`
- compatibility aliases such as `provider_spec` and `attach-provider`

It emits status/context with both new and old names:

- new: `display`, `display_kind`, `source`, `source_spec`, `available_sources`
- old: `surface`, `surface_kind`, `provider`, `provider_spec`,
  `available_providers`

## Local Apps

The Apps launcher now spawns an app-wrapped `Display` card and plugs in a
`local-app` source. It is still the same Display/source engine, but the wrapper
uses the app name, icon, source badge, and a wider 16:9 viewport so launched apps
feel like app cards instead of blank monitors.

`local-app` is currently implemented by the `XwaylandPerApp` backend:

```
Display card
  -> local-app source descriptor
      -> rootful Xwayland display
          -> launched desktop app
```

This is an implementation detail. The card should not know or care whether the
local app source is backed by Xwayland, Xvfb, cage, gamescope, or a future
wlroots headless compositor.

## Host Window Manager Boundary

Wayfire is still useful as the outer session layer:

- SDDM autologin starts the session
- Wayfire owns the real monitor, seat, and compositor process
- the PyQt workspace runs as an XWayland client under it

Wayfire should not be the app-card window manager. Any WM/compositor needed by a
local app belongs inside the source layer. If a private source window appears on
the real desktop, that is a layer leak.

## Current Caveats

- `local-app` uses rootful Xwayland, which creates a host-visible toplevel that
  must be hidden/minimized by the provider. This should be replaced by a more
  headless source backend when practical.
- Input forwarding into Xwayland is partial. Pointer input and many synthetic
  key events work, but interactive terminal/readline behavior still needs a
  better backend or focus/input strategy.
- The old `App` card and native-window fallback remain available for restored
  sessions and debugging, but the preferred app path is `Apps -> app-wrapped
  Display card -> local-app source`.

## Future Sources

The same Display card should be able to host:

- `fauxpass-app`: an app source from another connected computer
- `looking-glass-vm`: a GPU-passthrough VM framebuffer
- `spice-vm` or `rdp-vm`: VM display and input channels
- `moonlight-stream`: game or desktop stream
- `native-window-thumbnail`: fallback capture of a host-managed window

These should register as sources without requiring a new card type.
