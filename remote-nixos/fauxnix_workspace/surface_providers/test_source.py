import inspect
import fauxnix_workspace.surface_providers.xwayland_per_app as m

with open(m.__file__) as f:
    src = f.read()
print("file has DEBUG:", "DEBUG send_input entered" in src)
print("inspect has DEBUG:", "DEBUG send_input entered" in inspect.getsource(m.XwaylandPerApp.send_input))
print("file has X.event:", "X.event = X.ButtonPress" in src)
print("inspect has X.event:", "X.event = X.ButtonPress" in inspect.getsource(m.XwaylandPerApp.send_input))
