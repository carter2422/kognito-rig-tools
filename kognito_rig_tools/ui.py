"""
Animation tools and UI
Also contains UI for rigging related tools
"""
import bpy
from mathutils import Vector, Matrix, Euler, Quaternion
from mathutils.geometry import normal, intersect_point_line
from bpy.app.handlers import persistent


class RigToggleHandFollow(bpy.types.Operator):
    """Toggle Hand Follows Torso for IK hands"""
    bl_idname = "pose.rig_toggle_hand_follow"
    bl_label = "Toggle IK hand follow torso"
    bl_context = "pose"

    hands = ["arm_IK.L", "arm_IK.R", "forearm_ik_pole.R", "forearm_ik_pole.L"]

    @classmethod
    def poll(cls, context):
        return (
            context.mode == 'POSE' and
            context.active_object.name == 'rig_ctrl')

    def execute(self, context):
        ob = context.object
        # copy the world position of the hands before it changes
        bone_locations = {
            hand: ob.pose.bones[hand].matrix.copy() for hand in self.hands}

        # toggle the follow
        context.object.pose.bones["props"]["arms_follow"] = (
            1 - context.object.pose.bones["props"]["arms_follow"])
        context.scene.frame_set(context.scene.frame_current)

        # write the world position to the local hand position
        for bone_name, bone_matrix in bone_locations.items():
            bone = ob.pose.bones[bone_name]
            new_matrix = genericmat(bone, bone_matrix, False)
            bone.location = new_matrix.to_translation()
            bone_rotation(bone, new_matrix)
            # bone.scale = new_matrix.to_scale() Don't scale

        return {'FINISHED'}


class RigToggleHandInheritRotation(bpy.types.Operator):
    """Toggle Hands inheriting rotation"""
    bl_idname = "pose.rig_toggle_hand_inherit_rotation"
    bl_label = "Toggle Hand inherit rotation"
    bl_context = "pose"

    @classmethod
    def poll(cls, context):
        return (
            context.mode == 'POSE'and
            context.active_object.name == 'rig_ctrl')

    def execute(self, context):
        rotate = context.object.pose.bones["props"]["hands_rotate"] = (
            1 - context.object.pose.bones["props"]["hands_rotate"])
        for bone in ("hand.R", "hand.L"):
            context.object.data.bones[bone].use_inherit_rotation = rotate
        return {'FINISHED'}


class FKIKSwitcher(bpy.types.Operator):
    """
    Universal IKFK methods coupled with explict rig bone/constraint definitions
    """

    bl_idname = 'pose.kognito_fkik'
    bl_label = 'Kognito Rig FK IK Switch'
    bl_description = 'Kognito rig FK IK seamless switcher'

    ik = bpy.props.BoolProperty(default=True)
    side = bpy.props.EnumProperty(
        items=[('left', 'left', 'left'), ('right', 'right', 'right')])

    # should later use some kind of preset/config system
    chain = ['upper_arm', 'forearm', 'hand']
    iks = ['forearm_ik_pole', 'arm_IK']
    suffixes = {'left': '.L', 'right': '.R'}
    prop = ['props', 'IK_arms']
    layers = {'left': [6, 5], 'right': [9, 8]}

    @classmethod
    def poll(cls, context):
        return (
            context.mode == 'POSE' and 'kognito_rig' in context.object.keys()
            )


    def fk_match(self, ob, chain, iks):
        """ Match the FK chain to the IK constrained position """
        for bone in chain:
            pose_bone = ob.pose.bones[bone]
            bake_rotation_scale(pose_bone)

    def ik_match(self, ob, chain, iks):
        """ Place the IK handles to as close as possible match the FK angles"""
        # TODO take into account the child of constraints when enabled
        target = ob.pose.bones[iks[-1]]
        source = ob.pose.bones[chain[-1]]
        constraints = (
            c for c in ob.pose.bones[chain[-2]].constraints if c.type == 'IK'
            )
        for constraint in constraints:
            pole_angle = constraint.pole_angle
            actual_ik = ob.pose.bones[constraint.subtarget]
        use_tail = False
        if not actual_ik is target:
            # calculate offset
            target_rest = ob.data.bones[target.name].matrix_local
            actual_rest = ob.data.bones[actual_ik.name].matrix_local
            offset = actual_rest.inverted() * target_rest
        else:
            offset = None
        loc_copy(source, target, use_tail, offset)
        rot_copy(source, target, offset)
        # use the pole angle to figure out the rest
        pole_position(
            [ob.pose.bones[b] for b in chain],
            ob.pose.bones[iks[0]],
            pole_angle)
        for bone in chain:
            ob.pose.bones[bone].matrix_basis = Matrix()

    def execute(self, context):
        ob = context.object
        suffix = self.suffixes[self.side]
        chain = ["{}{}".format(c, suffix) for c in self.chain]
        iks = ["{}{}".format(c, suffix) for c in self.iks]
        prop_holder = ob.pose.bones[self.prop[0]]
        prop = '{}{}'.format(self.prop[1], suffix)
        influence = prop_holder[prop]
        if self.ik and prop_holder[prop] < 0.00001:
            ob.data.layers[self.layers[self.side][-1]] = True
            ob.data.layers[self.layers[self.side][0]] = False
            self.ik_match(ob, chain, iks)
            prop_holder[prop] = 1.0
        elif prop_holder[prop] > 0.999999 and not self.ik:
            ob.data.layers[self.layers[self.side][-1]] = False
            ob.data.layers[self.layers[self.side][0]] = True
            self.fk_match(ob, chain, iks)
            prop_holder[prop] = 0.0
        return {'FINISHED'}


def find_or_add_constraint(bone, constraint):
    con = [con for con in bone.constraints if con.type in constraint]
    if not con:
        con = bone.constraints.new(type=constraint)
    else:
        con = con[0]
    return con


def constraints_toggle_child_of(bones):
    for bone in bones:
        child_of = find_or_add_constraint(bone, 'CHILD_OF')
        child_of.influence = 1 if child_of.influence == 0 else 0


def bones_toggle_property(bones, property_name):
    for bone in bones:
        prop_value = getattr(bone.bone, property_name)
        setattr(bone.bone, property_name, not prop_value)

def getparentmats(bone):
    """ Get parent matrices for bones in many conditions """
    child_of = [c for c in bone.constraints if c.type == 'CHILD_OF']
    data_bone = bone.id_data.data.bones[bone.name]
    if len(child_of) > 0 and not child_of[0].mute and child_of[0].influence > 0.99:
        child_of = child_of[0]
        parent = child_of.target.pose.bones[child_of.subtarget]
        parentposemat = parent.matrix
        data_parent = child_of.target.data.bones[child_of.subtarget]
        parentbonemat = data_parent.matrix_local
    elif bone.parent:
        parentposemat = bone.parent.matrix
        parentbonemat = data_bone.parent.matrix_local
    else:
        parentposemat = None
        parentbonemat = None
    return parentposemat, parentbonemat


def genericmat(bone, mat, ignoreparent):
    '''
    Puts the matrix mat from armature space into bone space
    '''
    data_bone = bone.id_data.data.bones[bone.name]
    bonemat_local = data_bone.matrix_local  # self rest matrix
    parentposemat, parentbonemat = getparentmats(bone)
    if parentbonemat is None or ignoreparent:
        newmat = bonemat_local.inverted() * mat
    else:
        bonemat = parentbonemat.inverted() * bonemat_local
        newmat = bonemat.inverted() * parentposemat.inverted() * mat
    return newmat


def bone_rotation(bone, mat):
    """ copy rotation part of matrix into appropriate rotation channels """

    if bone.rotation_mode == 'AXIS_ANGLE':
        axis_angle = mat.to_quaternion().to_axis_angle()
        bone.rotation_axis_angle[0] = axis_angle[-1]
        bone.rotation_axis_angle[1] = axis_angle[0][0]
        bone.rotation_axis_angle[2] = axis_angle[0][1]
        bone.rotation_axis_angle[3] = axis_angle[0][2]
    elif bone.rotation_mode == 'QUATERNION':
        bone.rotation_quaternion = mat.to_quaternion()
    else:
        bone.rotation_euler = mat.to_euler(
            bone.rotation_mode, bone.rotation_euler)


def bake_rotation_scale(bone):
    """ bake constrained transform into bone rot/scale """

    data_bone = bone.id_data.data.bones[bone.name]
    bone_mat = data_bone.matrix_local
    parentless_mat = bone_mat.inverted() * bone.matrix
    if not bone.parent:
        rot_mat = scale_mat = parentless_mat
    else:
        parentposemat = bone.parent.matrix
        parentbonemat = data_bone.parent.matrix_local
        parented_mat = (
            (parentbonemat.inverted() * bone_mat).inverted() *
            parentposemat.inverted() *
            bone.matrix
            )
        rot_mat = (
            parented_mat if data_bone.use_inherit_rotation else parentless_mat)
        scale_mat = (
            parented_mat if data_bone.use_inherit_scale else parentless_mat)

    bone_rotation(bone, rot_mat)
    bone.scale = scale_mat.to_scale()


def loc_copy(source, target, use_tail, offset):
    data_target = target.id_data.data.bones[target.name]
    target_mat = data_target.matrix_local
    if not data_target.use_local_location:
        target_mat = Matrix.Translation(target_mat.to_translation())
    if use_tail:
        location = source.tail
    else:
        location = source.matrix.to_translation()
    parentposemat, parentbonemat = getparentmats(target)
    if parentposemat:
        target.location = (
            (parentbonemat.inverted() * target_mat).inverted() *
            parentposemat.inverted() *
            location
            )
    else:
        target.location = target_mat.inverted() * location
    if offset:
        target.location = target.location + offset.to_translation()


def rot_copy(source, target, offset):
    """ duplicates code from loc_copy, should be refactored """
    data_target = target.id_data.data.bones[target.name]
    target_mat = data_target.matrix_local
    parentless_mat = target_mat.inverted() * source.matrix
    parentposemat, parentbonemat = getparentmats(target)
    if not parentposemat:
        mat = parentless_mat
    else:
        parented_mat = (
            (parentbonemat.inverted() * target_mat).inverted() *
            parentposemat.inverted() *
            source.matrix
            )
        mat = (
            parented_mat if data_target.use_inherit_rotation else parentless_mat)
    if offset:
        offset_rot = offset.to_3x3()
        quat = mat.to_quaternion()
        offset_rot.rotate(quat)
        mat = offset_rot
    if target.rotation_mode == 'AXIS_ANGLE':
        target.rotation_axis_angle = mat.to_quaternion().to_axis_angle()
    elif target.rotation_mode == 'QUATERNION':
        target.rotation_quaternion = mat.to_quaternion()
    else:
        target.rotation_euler = mat.to_euler(
            target.rotation_mode, target.rotation_euler)


def adjust_childof(pose_bone):
    """ returns the amount of displacement due to a child_of constraint """
    child_of = [c for c in pose_bone.constraints if c.type == 'CHILD_OF']
    if len(child_of) == 0:
        return
    child_of = child_of[0] # we can only deal with one for now
    if child_of.mute or child_of.influence < 0.0001:
        return
    target = child_of.target
    subtarget = target.pose.bones[child_of.subtarget]
    subtarget_data = target.data.bones[child_of.subtarget]
    mat = child_of.inverse_matrix
    # we're going to assume target and pose_bone are in the same object
    displacement = subtarget_data.matrix_local.inverted() * subtarget.matrix
    return displacement


def pole_position(chain, pole, pole_angle):
    """
    pole target based on roll angle of chain base
    """
    # Poll target for elbow is on the + X axis, for the knee we need to lock
    # the elbow to rotate along one axis only
    order = 0
    chain_0_data = chain[order].id_data.data.bones[chain[order].name]
    pole_data = pole.id_data.data.bones[pole.name]
    offmatelbow = chain_0_data.matrix_local.inverted() * pole_data.matrix_local
    vec = offmatelbow.to_translation()
    # vec = Vector((4, 0.0, 0.0))
    # vec.rotate(Euler((0, -pole_angle, 0)))
    offmatelbow = Matrix.Translation(vec)
    offmatarm = chain[order].matrix * offmatelbow
    child_mat = adjust_childof(pole)
    if child_mat is None:
        pole.location = genericmat(pole, offmatarm, True).to_translation()
    else:
        pole.location = genericmat(pole, offmatarm, False).to_translation()
    return


class KognitoShapePanel(bpy.types.Panel):
    """Kognito Shape Manipulation tools"""
    bl_label = "Shape Control"
    bl_idname = "VIEW_3D_PT_KOGNITO_SHAPE"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    bl_category = "Kognito"
    bl_context = "posemode"


    @classmethod
    def poll(cls, context):
        return 'kognito_rig' in context.object.keys()

    def draw(self, context):
        layout = self.layout
        ob = context.object
        props = ob.pose.bones["props"]

        box = layout.box()
        col = box.column(align=True)
        row = col.row(align=True)
        row.prop(props, '["up_nosebridge"]', text="Nose Length")
        row.prop(props, '["out_nosebridge"]', text="Nose Bridge")
        row = col.row(align=True)
        row.prop(props, '["out_sockets"]', text= "eyes protrude")
        row.prop(props, '["socket_distance"]', text="eyes distance")
        row = col.row(align=True)
        row.prop(props, '["philtrum"]', text= "philtrum")
        row = layout.row(align=True)
        row.prop(props, '["scale_head"]', text="Scale Head")
        row = layout.row(align=True)
        row.prop(props, '["scale_neck"]', text="Scale Neck")
        row = layout.row(align=True)
        row.prop(props, '["scale_arms"]', text="Scale Upper Arms")
        row.prop(props, '["scale_arms_2"]', text="Scale Lower Arms")
        row = layout.row(align=True)
        row.prop(props, '["scale_hands"]', text="Scale Hands")
        row = layout.row(align=True)
        row.prop(props, '["scale_torso"]', text="Scale Torso")
        row.prop(props, '["scale_chest"]', text="Chest amount")
        row = layout.row(align=True)
        row.prop(props, '["scale_legs"]', text="Scale Legs")
        row = layout.row(align=True)
        row.prop(props, '["leg_proportion"]', text="Knee Height")
        row = layout.row(align=True)
        row.prop(props, '["scale_feet"]', text="Scale Feet")


class KognitoPanel(bpy.types.Panel):
    """Kognito Animator's tools"""
    bl_label = "Rig Control"
    bl_idname = "VIEW_3D_PT_KOGNITO"
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'TOOLS'
    bl_category = "Kognito"
    bl_context = "posemode"

    @classmethod
    def poll(cls, context):
        return 'kognito_rig' in context.object.keys()

    def draw(self, context):
        layout = self.layout
        ob = context.object
        switcher = FKIKSwitcher.bl_idname
        props = ob.pose.bones["props"]
        box = layout.box()
        box.label("IK/FK arms:")

        def fk_ik_controls(layout, side, prop):

            def clicker(layout, side, state, icon):
                suffix = {"left": "L", "right": "R"}
                col = layout.column(align=True)
                level = props["IK_arms.{}".format(suffix[side])]
                if state and level < .00001:
                    col.enabled = True
                elif not state and level > .99999:
                    col.enabled = True
                else:
                    col.enabled = False
                clicker = col.operator(switcher, text="", icon=icon)
                clicker.side, clicker.ik = side, state

            row = layout.row(align=True)
            clicker(row, side, False, 'TRIA_LEFT')
            col = row.column(align=True)
            col.prop(props, prop, text=side)
            clicker(row, side, True, 'TRIA_RIGHT')

        fk_ik_controls(box, 'right', '["IK_arms.R"]')
        fk_ik_controls(box, 'left', '["IK_arms.L"]')

        box = layout.box()
        box.label("Toggles:")
        row = box.row(align=True)
        row.operator(
            'pose.rig_toggle_hand_follow',
            text="Hands follow",
            icon="CHECKBOX_HLT" if props["arms_follow"] else "CHECKBOX_DEHLT")
        row.operator(
            'pose.rig_toggle_hand_inherit_rotation',
            text="Hands rotate",
            icon="CHECKBOX_HLT" if props["hands_rotate"] else "CHECKBOX_DEHLT")

        box = layout.box()
        box.label("Show/Hide:")

        row = box.row(align=True)
        row.scale_y = 2
        row.prop(ob.data, "layers", index=0, text="Head FK", toggle=True)

        col = box.column(align=True)
        row = col.row(align=True)
        row.label("  Face:")
        row = col.row(align=True)
        row.prop(ob.data, "layers", index=23, text="main", toggle=True)
        row = col.row(align=True)
        row.prop(ob.data, "layers", index=24, text="tweak", toggle=True)

        col = box.column(align=True)
        row = col.row(align=True)
        row.label("  Arms:")
        row = col.row(align=True)
        row.prop(ob.data, "layers", index=9, text="FK Right", toggle=True)
        row.prop(ob.data, "layers", index=6, text="FK Left", toggle=True)
        row = col.row(align=True)
        row.prop(ob.data, "layers", index=8, text="IK Right", toggle=True)
        row.prop(ob.data, "layers", index=5, text="IK Left", toggle=True)

        col = box.column(align=True)
        row = col.row(align=True)
        row.label("  Fingers:")
        row = col.row(align=True)
        row.prop(ob.data, "layers", index=4, text="Main", toggle=True)
        row = col.row(align=True)
        row.prop(ob.data, "layers", index=3, text="Tweak", toggle=True)

        row = box.row(align=True)
        row.scale_y = 2
        row.prop(ob.data, "layers", index=2, text="Torso FK", toggle=True)

        col = box.column(align=True)
        row = col.row(align=True)
        row.label("  Legs:")
        row = col.row(align=True)
        row.scale_y = 2
        row.prop(ob.data, "layers", index=15, text="IK Right", toggle=True)
        row.prop(ob.data, "layers", index=12, text="IK Left", toggle=True)


@persistent
def load_handler(dummy):
    # add the driver functions to the namespace
    cached_value = Vector((0.0, 0.028712928295135498, -0.7043251991271973))
    #XXX cached value is rig dependent and must be adjusted to base_mesh.blend
    # do the following in a terminal and copy to cached_value:
    # must be in edit mode!
    # rig = D.objects["rig_ctrl"].data.edit_bones
    # cached_value = rig["shin_ik.L"].head - rig["heel_roll.L"].head
    for i in range(3):
        def scaler(scale_legs, scale_feet):
            return ((scale_feet-scale_legs) * cached_value)[i]
        bpy.app.driver_namespace['scale_{}'.format(i)] = scaler


def register():
    bpy.utils.register_class(RigToggleHandFollow)
    bpy.utils.register_class(RigToggleHandInheritRotation)
    bpy.utils.register_class(FKIKSwitcher)
    bpy.utils.register_class(KognitoPanel)
    bpy.utils.register_class(KognitoShapePanel)
    load_handler(None)
    bpy.app.handlers.load_post.append(load_handler)




def unregister():
    bpy.utils.unregister_class(KognitoShapePanel)
    bpy.utils.unregister_class(KognitoPanel)
    bpy.utils.unregister_class(FKIKSwitcher)
    bpy.utils.unregister_class(RigToggleHandFollow)
    bpy.utils.unregister_class(RigToggleHandInheritRotation)
    bpy.app.handlers.load_post.remove(load_handler)

if __name__ == "__main__":
    register()
