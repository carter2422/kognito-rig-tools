import bpy
from mathutils import Vector

cached_value = Vector((0.0, 0.028712928295135498, -0.7043251991271973))

for i in range(3):
    def scaler(scale):
        return ((scale - 1) * cached_value)[i]
    bpy.app.driver_namespace['scale_{}'.format(i)] = scaler
