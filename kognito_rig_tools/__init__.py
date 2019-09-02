bl_info = {
    "name":        "Kognito Rig Tools",
    "description":
                   "A set of tools to aid in the generation of"
                   " effective rigs for Unity characters",
    "author":      "Jonathan Williamson, Bassam Kurdali",
    "version":     (0, 5, 6),
    "blender":     (2, 7, 8),
    "location":    "View 3D > Properties",
    "warning":     "",  # used for warning icon and text in addons panel
    "wiki_url":    "",
    "tracker_url": "",
    "category":    "Rigging"
    }

# messy import stuff ensures import works both during testing and when
# running as a proper addon

if "bpy" in locals():
    import importlib
    importlib.reload(ui)
    importlib.reload(tools)

else:
    from . import ui
    from . import tools

import bpy


def register():
    """ register the addon's submodules """
    ui.register()
    tools.register()



def unregister():
    """ register the addon's submodules """
    tools.unregister()
    ui.unregister()
