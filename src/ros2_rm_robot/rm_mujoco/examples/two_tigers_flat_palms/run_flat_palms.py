import argparse
import math
import platform
import sys
from pathlib import Path
import tempfile
import mujoco as m
import numpy as np

parser = argparse.ArgumentParser(description="Run the flat-palm piano simulation.")
parser.add_argument("package", type=Path, help="rm_mujoco source directory")
parser.add_argument("output", type=Path, help="directory for simulation results")
parser.add_argument("--score", type=Path, help="PPQN MIDI score, channel 0 right and channel 1 left")
parser.add_argument("--fingering", type=Path, default=Path(__file__).with_name("fingering.yaml"))
parser.add_argument("--pose-file", type=Path, help="L20 READY and PRESS pose configuration")
parser.add_argument("--scene-config", type=Path, help="override the MuJoCo scene layout")
parser.add_argument("--tempo-scale", type=float, default=12.0, help="simulation seconds per score second")
parser.add_argument("--attack-duration", type=float, default=0.44,
                    help="seconds for the strike; the key closes on the score grid")
parser.add_argument("--release-duration", type=float, default=0.38,
                    help="seconds for the lift-off; the key opens on the score grid")
parser.add_argument("--transfer-joint-speed", type=float, default=0.16 / 0.30,
                    help="maximum arm joint speed in rad/s for a level wrist shift")
parser.add_argument("--transfer-joint-max-shift", type=float, default=0.16,
                    help="largest arm joint shift in rad a level wrist shift may cover")
parser.add_argument("--level-shift-min-time", type=float, default=0.30,
                    help="minimum seconds a level wrist shift is allowed to take")
parser.add_argument("--contact-offset", action="append", default=[], metavar="NOTE:METERS",
                    help="shift a key's IK contact point along the keyboard axis")
parser.add_argument("--key-press-deg", type=float,
                    help="count a key pressed within this many degrees of full travel")
parser.add_argument("--key-release-deg", type=float,
                    help="release a key once it falls this many degrees below full travel")
parser.add_argument("--allow-alternate-fingering", action="store_true",
                    help="retry thumb notes as index or middle when the fingering fails")
parser.add_argument("--ros-events", action="store_true", help="publish actual key edges to ROS 2")
args = parser.parse_args()
if not math.isfinite(args.tempo_scale) or args.tempo_scale <= 0:
    parser.error("--tempo-scale must be finite and positive")
if not (math.isfinite(args.attack_duration) and args.attack_duration > 0):
    parser.error("--attack-duration must be finite and positive")
if not (math.isfinite(args.release_duration) and args.release_duration > 0):
    parser.error("--release-duration must be finite and positive")
if not (math.isfinite(args.transfer_joint_speed) and args.transfer_joint_speed > 0):
    parser.error("--transfer-joint-speed must be finite and positive")
if not (math.isfinite(args.transfer_joint_max_shift) and args.transfer_joint_max_shift > 0):
    parser.error("--transfer-joint-max-shift must be finite and positive")
if not (math.isfinite(args.level_shift_min_time) and args.level_shift_min_time > 0):
    parser.error("--level-shift-min-time must be finite and positive")
if (args.key_press_deg is None) != (args.key_release_deg is None):
    parser.error("--key-press-deg and --key-release-deg must be given together")
if args.key_press_deg is not None and not 0 <= args.key_press_deg < args.key_release_deg:
    parser.error("key thresholds must satisfy 0 <= --key-press-deg < --key-release-deg")
if args.ros_events and args.score is None:
    parser.error("--ros-events requires --score")
movable_keys = args.score is not None
pkg = args.package.resolve()
output = args.output.resolve()
output.mkdir(parents=True, exist_ok=True)
if args.score is not None and any(output.iterdir()):
    parser.error("Use an empty output directory for a score run")
sys.path.insert(0, str(pkg))
from rm_mujoco.keyboard import KeyEvents
from rm_mujoco.l20_joint_mapping import HAND_JOINT_SUFFIXES, command_positions
from rm_mujoco.scene import build_model, load_layout, key_positions

layout = load_layout(args.scene_config or pkg / 'config/piano_scene.yaml')
with tempfile.TemporaryDirectory(prefix='piano_ik_', dir=output) as tmp:
    model = m.MjModel.from_xml_path(str(build_model(
        pkg / 'models/rm_75_6fb_v_dual_l20.xml', layout, tmp,
        movable_keys=movable_keys)))
press_depth = 0.008 if movable_keys else 0.0022

ready_id = model.key('piano_ready').id
d = m.MjData(model)
m.mj_resetDataKeyframe(model, d, ready_id)
m.mj_forward(model, d)
ready_q, ready_ctrl = d.qpos.copy(), d.ctrl.copy()
points = np.array(key_positions(layout)) + layout['piano_frame']['position']
for entry in args.contact_offset:
    note_text, _, offset_text = entry.partition(":")
    try:
        offset_note, offset = int(note_text), float(offset_text)
    except ValueError:
        parser.error(f"--contact-offset expects NOTE:METERS, got {entry!r}")
    if not 21 <= offset_note <= 108:
        parser.error(f"--contact-offset note {offset_note} is outside 21-108")
    if not math.isfinite(offset):
        parser.error(f"--contact-offset for note {offset_note} must be finite")
    points[offset_note - 21, 0] += offset
geom_names = [model.geom(i).name or model.body(model.geom_bodyid[i]).name for i in range(model.ngeom)]
sides = ('left', 'right')

def contacts(data):
    return {tuple(sorted((int(c.geom1), int(c.geom2)))) for c in data.contact[:data.ncon] if c.dist <= 0}

def relevant(pair):
    a,b = (geom_names[i] for i in pair)
    return ((a.startswith('left_') and b.startswith('right_')) or
            (a.startswith('right_') and b.startswith('left_')) or
            (a.startswith(('left_', 'right_')) != b.startswith(('left_', 'right_'))))

baseline = contacts(d)
tip = {}
for side in sides:
    joints = [model.joint(f'{side}_joint{i}') for i in range(1, 8)]
    qa = np.array([int(j.qposadr[0]) for j in joints])
    da = np.array([int(j.dofadr[0]) for j in joints])
    aa = [int(np.flatnonzero(model.actuator_trnid[:,0] == j.id)[0]) for j in joints]
    mesh = model.mesh('l20_index_link4')
    geom = next(i for i in range(model.ngeom)
                if model.geom_type[i] == m.mjtGeom.mjGEOM_MESH
                and model.geom_dataid[i] == mesh.id and geom_names[i].startswith(side + '_'))
    start = mesh.vertadr[0]
    verts = model.mesh_vert[start:start + mesh.vertnum[0]]
    R = d.geom_xmat[geom].reshape(3,3).copy()
    local = verts[np.argmin((verts @ R.T)[:,2])].copy()
    tip[side] = (qa, da, aa, geom, local, R, model.jnt_range[[j.id for j in joints]].copy())

jp = np.zeros((3, model.nv))
jr = np.zeros_like(jp)

def tip_point(data, side):
    _,_,_,gid,local,_,_ = tip[side]
    return data.geom_xpos[gid] + data.geom_xmat[gid].reshape(3,3) @ local

def describe(pairs):
    return sorted({tuple(sorted((geom_names[a], geom_names[b]))) for a,b in pairs})


tip_ready = tip.copy()

def rotate(axis, degrees):
    theta = np.radians(degrees)
    a, b = np.cos(theta), np.sin(theta)
    if axis == 'z':
        return np.array([[a,-b,0],[b,a,0],[0,0,1]])
    if axis == 'x':
        return np.array([[1,0,0],[0,a,-b],[0,b,a]])
    return np.array([[a,0,b],[0,1,0],[-b,0,a]])


from itertools import product
import collections
import json
import re

melody = [72,74,76,72]*2 + [76,77,79]*2 + [79,81,79,77,76,72]*2 + [72,67,72]*2
lengths = [1]*8 + [1,1,2]*2 + [0.5,0.5,0.5,0.5,1,1]*2 + [1,1,2]*2
bass = [48,48,48,48,48,48,43,48]
assignments = {'left': sorted(set(bass)), 'right': sorted(set(melody))}
old_ready = ready_q.copy()
old_ctrl = ready_ctrl.copy()
key_re = re.compile(r'^piano_key_(\d+)(?:_rear)?$')

def classify(data):
    keys = set()
    other = set()
    for a,b in contacts(data)-baseline:
        ga,gb = geom_names[a],geom_names[b]
        sa = ga.split('_')[0]
        sb = gb.split('_')[0]
        if sa in sides and sb in sides:
            if sa != sb:
                other.add(tuple(sorted((ga,gb))))
            continue
        if sa not in sides and sb not in sides:
            continue
        active_side, robot_geom, other_geom = (sa,ga,gb) if sa in sides else (sb,gb,ga)
        match = key_re.fullmatch(other_geom)
        if match:
            keys.add((active_side,int(match.group(1)),robot_geom))
        else:
            other.add(tuple(sorted((ga,gb))))
    return keys,other


import yaml

sys.path.insert(0, str(pkg.parent / "rm_piano_player"))
from rm_piano_player.midi_file import export_midi, read_score

pose_path = args.pose_file or pkg.parent/'rm_piano_player/config/right_hand_ode_to_joy.yaml'
import hashlib
pose_sha=hashlib.sha256(pose_path.read_bytes()).hexdigest()
original_poses = yaml.safe_load(pose_path.read_text(encoding='utf-8'))['poses']
message_map = {}
for name, pose in original_poses.items():
    q = old_ready.copy()
    ctrl = old_ctrl.copy()
    for suffix, value in zip(HAND_JOINT_SUFFIXES, command_positions(pose['positions'])):
        j = model.joint(f"right_{suffix}")
        q[j.qposadr[0]] = value
        ctrl[np.flatnonzero(model.actuator_trnid[:,0] == j.id)[0]] = value
    message_map[name] = q,ctrl
fingering = {67:('C','thumb'),72:('C','thumb'),74:('D','index'),76:('E','middle'),
             77:('F','ring'),79:('G','little'),81:('G','little')}
score_by_hand = None
if args.score is not None:
    score_by_hand = {"right": [], "left": []}
    hand_channels = {0: "right", 1: "left"}
    for score_note in read_score(args.score):
        if score_note.channel not in hand_channels or not 21 <= score_note.note <= 108:
            raise ValueError("Use channel 0 for right, channel 1 for left, and notes 21–108")
        score_by_hand[hand_channels[score_note.channel]].append(score_note)
    if not all(score_by_hand.values()):
        raise ValueError("The flat-palm demo expects notes for both hands")
    for side, notes in score_by_hand.items():
        if any(first.end > second.start for first, second in zip(notes, notes[1:])):
            raise ValueError(f"The flat-palm demo expects at most one active note on the {side} hand")
    assignments = {side: sorted({note.note for note in notes})
                   for side, notes in score_by_hand.items()}
    if set(assignments["left"]) & set(assignments["right"]):
        raise ValueError("This demo expects distinct pitch ranges for the two hands")
    finger_table = yaml.safe_load(args.fingering.read_text(encoding="utf-8"))
    if not isinstance(finger_table, dict):
        raise ValueError("Fingering file must map each hand to its notes")
    fingering = {}
    fingers = {"C": "thumb", "D": "index", "E": "middle", "F": "ring", "G": "little"}
    for side, notes in assignments.items():
        entries = finger_table.get(side)
        if not isinstance(entries, dict):
            raise ValueError(f"Missing {side} fingering map")
        for note in notes:
            entry = entries.get(note)
            if (not isinstance(entry, list) or len(entry) != 2
                    or not isinstance(entry[0], str) or fingers.get(entry[0]) != entry[1]):
                raise ValueError(f"Missing or invalid {side} fingering for MIDI note {note}")
            fingering[note] = tuple(entry)
print('SCORE',len(melody),'melody',len(bass),'bass','POSES',list(message_map),flush=True)
wrist = model.body('right_l20_base_link').id
d.qpos[:] = old_ready
m.mj_kinematics(model,d)
base_R = np.array([[0.,-1.,0.],[0.,0.,1.],[-1.,0.,0.]])
tip_ready = tip.copy()

def solve(side, target, seed, finger_state=None, desired_wrist=None):
    qa, da, _, gid, _, desired_R, limits = tip[side]
    d.qpos[:] = ready_q if finger_state is None else finger_state
    q = seed.copy()
    for _ in range(140):
        d.qpos[qa] = q
        m.mj_kinematics(model, d)
        m.mj_comPos(model, d)
        p = tip_point(d, side)
        pos_error = target - p
        if desired_wrist is not None:
            actual_R = d.xmat[wrist].reshape(3,3)
            desired_R = desired_wrist
        else:
            actual_R = d.geom_xmat[gid].reshape(3,3)
        rot_error = 0.5 * np.cross(actual_R.T, desired_R.T).sum(axis=0)
        if np.linalg.norm(pos_error) <= 0.00016 and np.linalg.norm(rot_error) <= 0.004:
            return q
        m.mj_jac(model, d, jp, jr, p, model.geom_bodyid[gid])
        J = np.vstack((jp[:, da], 0.13 * jr[:, da]))
        delta = J.T @ np.linalg.solve(J @ J.T + np.eye(6)*0.005**2,
                                      np.r_[pos_error, 0.13 * rot_error])
        scale = min(0.9, 0.15 / max(1e-9, np.max(np.abs(delta))))
        updated = np.clip(q + delta * scale, limits[:,0], limits[:,1])
        if np.max(np.abs(updated - q)) < 1e-7:
            return None
        q = updated
    return None

def valid_route(states, allowed, count=10):
    for a,b in zip(states, states[1:]):
        for step in np.linspace(0, 1, count):
            d.qpos[:] = a + (b-a)*step
            m.mj_forward(model,d)
            ks,other = classify(d)
            if other or (ks-allowed):
                return False
    return True

def is_clean(keys,other,note,finger,side='right'):
    return not other and all(s==side and n==note and g.startswith(side+'_'+finger+'_')
                             for s,n,g in keys)


import copy
import xml.etree.ElementTree as ET
with tempfile.TemporaryDirectory(prefix='l20_hand_search_', dir=output) as tmp:
    xml = ET.parse(build_model(pkg/'models/rm_75_6fb_v_dual_l20.xml',layout,tmp)).getroot()
    world = xml.find('worldbody')
    hand = copy.deepcopy(world.find(".//body[@name='right_l20_base_link']"))
    for attr in ('pos','euler','quat','xyaxes'):
        hand.attrib.pop(attr,None)
    hand.insert(0,ET.Element('freejoint',name='search_wrist'))
    for side in sides:
        world.remove(world.find(f"body[@name='{side}_base_link']"))
    world.append(hand)
    xml.remove(xml.find('actuator'))
    xml.remove(xml.find('keyframe'))
    fm=m.MjModel.from_xml_string(ET.tostring(xml,encoding='unicode'))
fd=m.MjData(fm)
fgeom=[fm.geom(i).name or fm.body(fm.geom_bodyid[i]).name for i in range(fm.ngeom)]
rootadr=fm.joint('search_wrist').qposadr[0]
wide_trials=list(product(range(-20,21,10),(-6,0,6),(-6,0,6)))
wide_trials.sort(key=lambda a:abs(a[0])*.55+abs(a[1])+abs(a[2]))
def free_wrist_trials(note,finger,press):
    mesh=fm.mesh(f'l20_{finger}_link{5 if finger=="thumb" else 4}')
    gid=next(i for i in range(fm.ngeom) if fm.geom_type[i]==m.mjtGeom.mjGEOM_MESH
             and fm.geom_dataid[i]==mesh.id and fgeom[i].startswith('right_'))
    fd.qpos[rootadr:rootadr+7]=[0,0,0,1,0,0,0]
    for suffix in HAND_JOINT_SUFFIXES:
        j=f'right_{suffix}'
        fd.qpos[fm.joint(j).qposadr[0]]=press[model.joint(j).qposadr[0]]
    m.mj_kinematics(fm,fd)
    start=mesh.vertadr[0]
    verts=fm.mesh_vert[start:start+mesh.vertnum[0]]@fd.geom_xmat[gid].reshape(3,3).T+fd.geom_xpos[gid]
    x,y,z=points[note-21]
    for yaw,roll,pitch in wide_trials:
        R=rotate('z',yaw)@rotate('y',pitch)@rotate('x',roll)@base_R
        lowest=verts[np.argmin(verts@R[2])]
        q=np.zeros(4)
        m.mju_mat2Quat(q,R.reshape(-1))
        fd.qpos[rootadr+3:rootadr+7]=q
        rotated=R@lowest
        for target_y,target_x in product((y,.011,.022,.053,.060,.004), (x,x-.006,x+.006)):
            target=np.array([target_x,target_y,z])
            fd.qpos[rootadr:rootadr+3]=target+[0,0,-press_depth]-rotated
            m.mj_forward(fm,fd)
            hit=False
            bad=False
            for c in fd.contact[:fd.ncon]:
                if c.dist>0:
                    continue
                a,b=fgeom[c.geom1],fgeom[c.geom2]
                if a.startswith('right_') == b.startswith('right_'):
                    continue
                robot,env=(a,b) if a.startswith('right_') else (b,a)
                match=key_re.fullmatch(env)
                if not match or int(match.group(1))!=note or not robot.startswith('right_'+finger+'_'):
                    bad=True
                    break
                hit=True
            if hit and not bad:
                yield yaw,roll,pitch,target

def right_candidates(note, seeds):
    letter,finger = fingering[note]
    name = f'PRESS_{letter}'
    press,press_ctrl = message_map[name]
    qa,da,aa,_,_,_,limits = tip_ready['right']
    mesh=model.mesh(f'l20_{finger}_link{5 if finger=="thumb" else 4}')
    gid=next(i for i in range(model.ngeom) if model.geom_type[i]==m.mjtGeom.mjGEOM_MESH
             and model.geom_dataid[i]==mesh.id and geom_names[i].startswith('right_'))
    start=mesh.vertadr[0]
    verts=model.mesh_vert[start:start+mesh.vertnum[0]]
    d.qpos[:] = press
    m.mj_kinematics(model,d)
    relative=d.xmat[wrist].reshape(3,3).T@d.geom_xmat[gid].reshape(3,3)
    counts=collections.Counter()
    examples={}
    for yaw,roll,pitch,pos in free_wrist_trials(note,finger,press):
        wrist_R=rotate('z',yaw)@rotate('y',pitch)@rotate('x',roll)@base_R
        local=verts[np.argmin((verts@(wrist_R@relative).T)[:,2])]
        tip['right']=(qa,da,aa,gid,local,wrist_R,limits)
        for seed in seeds:
            down=solve('right',pos+[0,0,-press_depth],seed,press,wrist_R)
            if down is None:
                counts['ik']+=1
                continue
            down_q=press.copy()
            down_q[qa]=down
            d.qpos[:]=down_q
            m.mj_forward(model,d)
            ks,other=classify(d)
            if not ks or not is_clean(ks,other,note,finger):
                counts['end_contacts']+=1
                examples.setdefault('end_contacts',(sorted(ks)[:4],sorted(other)[:3]))
                continue
            hover=solve('right',pos+[0,0,0.045],down,press,wrist_R)
            if hover is None:
                counts['hover_ik']+=1
                continue
            low=solve('right',pos+[0,0,0.012],down,press,wrist_R)
            if low is None:
                counts['low_ik']+=1
                continue
            hover_q=press.copy()
            hover_q[qa]=hover
            low_q=press.copy()
            low_q[qa]=low
            ready=message_map['READY'][0].copy()
            ready[qa]=hover
            if not valid_route([ready,hover_q,low_q],set(),count=6):
                counts['hover_contacts']+=1
                continue
            safe=True
            for t in np.linspace(0,1,8):
                d.qpos[:]=low_q+(down_q-low_q)*t
                m.mj_forward(model,d)
                ks,other=classify(d)
                if not is_clean(ks,other,note,finger):
                    counts['descent_contacts']+=1
                    safe=False
                    break
            if not safe:
                continue
            play_ready=message_map['READY'][0].copy()
            play_ready[qa]=down
            if not valid_route([ready,play_ready],set(),count=12):
                continue
            yield (yaw,roll,pitch), ready, ready.copy(), play_ready, down_q, pos, tip['right']
            break
    print('SEARCH',note,name,dict(counts),examples,flush=True)


left_wrist_trials=[(0,0,0),(0,12,0)]
def set_fingers(side, curl, q, ctrl):
    for digit in ('thumb','middle','ring','little'):
        for joint,k in ((1,1.0),(2,0.8),(3,0.6)):
            jid = model.joint(f'{side}_{digit}_joint{joint}')
            actuator = np.flatnonzero(model.actuator_trnid[:,0] == jid.id)[0]
            value = curl * k
            q[jid.qposadr[0]] = value
            ctrl[actuator] = value

def left_candidates(side):
    qa,da,aa,gid,_,_,limits = tip_ready[side]
    mesh = model.mesh('l20_index_link4')
    start = mesh.vertadr[0]
    vertices = model.mesh_vert[start:start+mesh.vertnum[0]]
    for curl in (0.55,0.78,1.0,0.35,0.0):
        ready_q[:] = old_ready
        ready_ctrl[:] = old_ctrl
        set_fingers(side,curl,ready_q,ready_ctrl)
        d.qpos[:] = ready_q
        m.mj_kinematics(model,d)
        R = base_R @ d.body('left_l20_base_link').xmat.reshape(3,3).T @ d.geom_xmat[gid].reshape(3,3)
        for yaw,roll,pitch in left_wrist_trials:
            new_R = rotate('z',yaw) @ rotate('y',pitch) @ rotate('x',roll) @ R
            local = vertices[np.argmin((vertices@new_R.T)[:,2])]
            tip[side] = (qa,da,aa,gid,local,new_R,limits)
            poses = {}
            seed = ready_q[qa].copy()
            center = np.median([points[note-21,0] for note in assignments[side]])
            notes = sorted(assignments[side],key=lambda n: abs(points[n-21,0]-center))
            for note in notes:
                point = points[note-21]
                q_up = solve(side,point + [0,0,0.023],seed)
                if q_up is None:
                    break
                q_down = solve(side,point + [0,0,-0.0022],q_up)
                if q_down is None:
                    break
                wrong = False
                for t in np.linspace(0,1,6):
                    d.qpos[:] = ready_q
                    d.qpos[qa] = q_up + t*(q_down-q_up)
                    m.mj_forward(model,d)
                    keys,other = classify(d)
                    if other or any(n != note or not g.startswith(side+'_index_') or s != side
                                    for s,n,g in keys) or (t==1 and not keys):
                        wrong = True
                        break
                if wrong:
                    break
                poses[note] = q_up,q_down
                seed = q_up
            if len(poses)==len(notes):
                yield (curl,yaw,roll,pitch),poses,tip[side]


qctrl=np.array([model.joint(int(jid)).qposadr[0] for jid in model.actuator_trnid[:,0]])
rightqa=tip_ready['right'][0]
right_fingers=np.array([model.joint('right_'+s).qposadr[0] for s in HAND_JOINT_SUFFIXES])
right_indices=np.r_[rightqa,right_fingers]
leftqa=tip_ready['left'][0]
left_fingers=np.array([model.joint('left_'+s).qposadr[0] for s in HAND_JOINT_SUFFIXES])
left_indices=np.r_[leftqa,left_fingers]

def step_to(sim,q,seconds,callback):
    ctrl=q[qctrl]
    start=sim.ctrl.copy()
    num=round(seconds/model.opt.timestep)
    for i in range(1,num+1):
        t=i/num
        sim.ctrl[:]=start+t*t*(3-2*t)*(ctrl-start)
        past=sim.time
        m.mj_step(model,sim)
        if sim.time<=past or sim.warning.number.any():
            raise RuntimeError('unstable MuJoCo trajectory')
        callback(sim)

def probe(note,cand,side='right', *, attack=0.55, hold=0.23, release=0.52):
    _,ready,high,low,down,_,_ = cand
    sim=m.MjData(model)
    m.mj_resetDataKeyframe(model,sim,ready_id)
    sim.qpos[:]=ready
    sim.ctrl[:]=ready[qctrl]
    m.mj_forward(model,sim)
    hits=0
    wrong=set()
    key_events = (KeyEvents(model, press_deg=args.key_press_deg,
                            release_deg=args.key_release_deg) if movable_keys else None)
    edges = []
    finger=fingering[note][1]
    def watch(sim):
        nonlocal hits
        if key_events is not None:
            edges.extend((edge, pitch) for _, edge, pitch in key_events.update(sim))
        ks,other=classify(sim)
        if not is_clean(ks,other,note,finger,side):
            wrong.update(ks)
            wrong.update(other)
        if ks and is_clean(ks,other,note,finger,side):
            hits+=1
    for q,sec in ((ready,.45),(high,.60),(low,.62),(down,attack),(down,hold),
                  (low,release),(high,.56),(ready,.56)):
        step_to(sim,q,sec,watch)
    correct_edges = key_events is None or edges == [('on', note), ('off', note)]
    if not correct_edges:
        wrong.add(('key_edges', tuple(edges)))
    return hits>=8 and not wrong and not classify(sim)[0],hits,list(wrong)[:3]

def run_note_probes(allow_alternate, already=None):
    found={} if already is None else dict(already)
    outcome={}
    order=(74,76,77,79,81,72,67) if score_by_hand is None else assignments["right"]
    for note in order:
        if note in found:
            continue
        initial=fingering[note]
        alternatives=[initial]
        if allow_alternate and initial[1]=='thumb':
            alternatives=[('D','index'),('E','middle')]
        for letter,finger in alternatives:
            fingering[note]=(letter,finger)
            nearest = min(found,key=lambda k:abs(k-note)) if found else None
            seeds=[old_ready[rightqa]] if nearest is None else [found[nearest][1][rightqa],old_ready[rightqa]]
            gen=right_candidates(note,seeds)
            for index,candidate in enumerate(gen):
                ok,hits,wrong=probe(note,candidate)
                if ok:
                    found[note]=candidate
                    outcome[note]={'pose':'PRESS_'+letter,'finger':finger,'touch_samples':hits,
                                   'orientation':candidate[0],'point':candidate[-2].tolist()}
                    break
                if index<2:
                    print('DYNAMIC REJECT',note,letter,hits,wrong,flush=True)
                if index>=13:
                    break
            if note in found:
                break
        if note not in found:
            fingering[note]=initial
            outcome[note]={'pose':'PRESS_'+initial[0],'finger':initial[1],'blocked':True}
        print('PROBE',note,outcome[note],flush=True)
    return found,outcome

original_fingering=dict(fingering)
first,original_results=run_note_probes(False)
right_note_count = len(assignments["right"])
second,alternate_results=run_note_probes(
    True, first) if ((args.score is None or args.allow_alternate_fingering)
                     and len(first)!=right_note_count) else (first,{})
print('COVERAGE',len(first),len(second),'OF',right_note_count,flush=True)

if len(second)!=right_note_count:
    raise SystemExit(2)

def is_clean_left(keys,other,note,finger):
    return not other and all(s=='left' and n==note and g.startswith('left_'+finger+'_') for s,n,g in keys)
def left_pose_candidates(note, seeds):
    letter,finger = fingering[note]
    name = f'PRESS_{letter}'
    press,press_ctrl = message_map[name]
    qa,da,aa,_,_,_,limits = tip_ready['left']
    mesh=model.mesh(f'l20_{finger}_link{5 if finger=="thumb" else 4}')
    gid=next(i for i in range(model.ngeom) if model.geom_type[i]==m.mjtGeom.mjGEOM_MESH
             and model.geom_dataid[i]==mesh.id and geom_names[i].startswith('left_'))
    start=mesh.vertadr[0]
    verts=model.mesh_vert[start:start+mesh.vertnum[0]]
    d.qpos[:] = press
    m.mj_kinematics(model,d)
    relative=d.xmat[wrist].reshape(3,3).T@d.geom_xmat[gid].reshape(3,3)
    counts=collections.Counter()
    examples={}
    for yaw,roll,pitch,pos in free_wrist_trials(note,finger,press):
        wrist_R=rotate('z',yaw)@rotate('y',pitch)@rotate('x',roll)@base_R
        local=verts[np.argmin((verts@(wrist_R@relative).T)[:,2])]
        tip['left']=(qa,da,aa,gid,local,wrist_R,limits)
        for seed in seeds:
            down=solve('left',pos+[0,0,-press_depth],seed,press,wrist_R)
            if down is None:
                counts['ik']+=1
                continue
            down_q=press.copy()
            down_q[qa]=down
            d.qpos[:]=down_q
            m.mj_forward(model,d)
            ks,other=classify(d)
            if not ks or not is_clean_left(ks,other,note,finger):
                counts['end_contacts']+=1
                examples.setdefault('end_contacts',(sorted(ks)[:4],sorted(other)[:3]))
                continue
            hover=solve('left',pos+[0,0,0.045],down,press,wrist_R)
            if hover is None:
                counts['hover_ik']+=1
                continue
            low=solve('left',pos+[0,0,0.012],down,press,wrist_R)
            if low is None:
                counts['low_ik']+=1
                continue
            hover_q=press.copy()
            hover_q[qa]=hover
            low_q=press.copy()
            low_q[qa]=low
            ready=message_map['READY'][0].copy()
            ready[qa]=hover
            if not valid_route([ready,hover_q,low_q],set(),count=6):
                counts['hover_contacts']+=1
                continue
            safe=True
            for t in np.linspace(0,1,8):
                d.qpos[:]=low_q+(down_q-low_q)*t
                m.mj_forward(model,d)
                ks,other=classify(d)
                if not is_clean_left(ks,other,note,finger):
                    counts['descent_contacts']+=1
                    safe=False
                    break
            if not safe:
                continue
            play_ready=message_map['READY'][0].copy()
            play_ready[qa]=down
            if not valid_route([ready,play_ready],set(),count=12):
                continue
            yield (yaw,roll,pitch), ready, ready.copy(), play_ready, down_q, pos, tip['left']
            break
    print('SEARCH',note,name,dict(counts),examples,flush=True)



saved_map=message_map
left_map={}
for name,(q,ctrl) in message_map.items():
    q=q.copy()
    for suffix in HAND_JOINT_SUFFIXES:
        q[model.joint('left_'+suffix).qposadr[0]]=q[model.joint('right_'+suffix).qposadr[0]]
    left_map[name]=q,q[qctrl]
message_map=left_map
wrist=model.body('left_l20_base_link').id
left_plans={}
for note in assignments["left"]:
    if score_by_hand is None:
        fingering[note]=('D','index')
    cand=next(left_pose_candidates(note,[old_ready[leftqa]]),None)
    if cand is None and args.allow_alternate_fingering:
        original=fingering[note]
        for letter,finger in (("D","index"),("E","middle"),("F","ring"),("C","thumb")):
            if (letter,finger)==original:
                continue
            fingering[note]=(letter,finger)
            cand=next(left_pose_candidates(note,[old_ready[leftqa]]),None)
            if cand is not None:
                print('REFINGER LEFT',note,finger,flush=True)
                break
        if cand is None:
            fingering[note]=original
    assert cand is not None,f'Flat left blocked {note}'
    left_plans[note]=cand
    print('FLAT LEFT',note,cand[0],flush=True)
message_map=saved_map
wrist=model.body('right_l20_base_link').id
left_right_home=message_map['READY'][0].copy()
left_right_home[left_fingers]=left_map['READY'][0][left_fingers]
ready_q[:]=left_right_home

def full_song(plans,beat_sec,capture):
    sim=m.MjData(model)
    m.mj_resetDataKeyframe(model,sim,ready_id)
    m.mj_forward(model,sim)
    bad=set()
    events=[]
    expected=[]
    active=set()
    allow={}
    first_unexpected=[]
    def watch(sim):
        nonlocal active
        keys,other=classify(sim)
        bad.update(other)
        for side,note,geom in keys:
            finger='index' if side=='left' else fingering.get(note,('',''))[1]
            if allow.get(side)!=note or not geom.startswith(side+'_'+finger+'_'):
                bad.add((side,note,geom))
                if len(first_unexpected)<10:
                    first_unexpected.append((sim.time,dict(allow),side,note,geom))
        now={(s,n) for s,n,_ in keys}
        events.extend((sim.time,'on',*key) for key in sorted(now-active))
        events.extend((sim.time,'off',*key) for key in sorted(active-now))
        active=now
        capture(sim)
    def drive(q,t):
        step_to(sim,q,t,watch)
    last=left_right_home.copy()
    last[right_indices]=plans[melody[0]][1][right_indices]
    last[left_indices]=left_plans[bass[0]][1][left_indices]
    sim.qpos[:]=last
    sim.ctrl[:]=last[qctrl]
    m.mj_forward(model,sim)
    assert not classify(sim)[0] and not classify(sim)[1]
    drive(last,1.2)
    leftnote=bass[0]
    t=0
    b=0
    used_home=0
    for note,length in zip(melody,lengths):
        simultaneous=t==4*b
        if simultaneous:
            leftnote=bass[b]
            b+=1
        _,rready,rhigh,rlow,rdown,_,_=plans[note]
        left_up,left_down=left_plans[leftnote][1],left_plans[leftnote][4]
        def target(right,left):
            q=left_right_home.copy()
            q[right_indices]=right[right_indices]
            q[left_indices]=left[left_indices]
            return q
        hover=target(rready,left_up)
        if valid_route([last,hover],set(),count=18):
            drive(hover,1.1)
            transfer=1.1
        else:
            assert valid_route([last,left_right_home,hover],set(),count=18), f'Blocked transfer to {note}'
            drive(left_right_home,1.3)
            drive(hover,1.3)
            transfer=2.6
            used_home+=1
        high=target(rhigh,left_up)
        low=target(rlow,left_plans[leftnote][3] if simultaneous else left_up)
        down=target(rdown,left_down if simultaneous else left_up)
        drive(high,.60)
        drive(low,.62)
        allow['right']=note
        expected.append((sim.time,'right',note))
        if simultaneous:
            allow['left']=leftnote
            expected.append((sim.time,'left',leftnote))
        drive(down,.55)
        drive(down,.23)
        drive(low,.52)
        allow.clear()
        drive(high,.56)
        drive(hover,.56)
        rest=length*beat_sec-transfer-3.64
        if rest>0:
            drive(hover,rest)
        t+=length
        last=hover
    drive(last,1.4)
    print('HOME TRANSFERS',used_home,'unexpected details',first_unexpected,flush=True)
    return events,bad,expected,sim.time
def compare(events,expected):
    queues={side:[] for side in sides}
    lengths={side:[] for side in sides}
    pending={}
    for t,kind,side,note in events:
        key=(side,note)
        if kind=='on':
            pending[key]=t
        elif key in pending:
            start=pending.pop(key)
            if t-start>=0.01:
                queues[side].append((start,note,t-start))
    good = True
    for side in sides:
        got=[]
        for start,note,length in sorted(queues[side]):
            if got and got[-1][1]==note and start-(got[-1][0]+got[-1][2])<0.13:
                old=got[-1]
                got[-1]=(old[0],note,start+length-old[0])
            else:
                got.append((start,note,length))
        queues[side]=got
        want=[note for _,s,note in expected if s==side]
        got_notes=[note for _,note,_ in got]
        print('CONTACTS',side,len(got),'of',len(want),'pass',got_notes==want,
              'observed',got_notes,flush=True)
        if got_notes!=want:
            good=False
    return good,queues


def share_wrist(note, anchor, candidate, side, arm):
    """Try a different finger at the previous note's tested arm pose."""
    hover, ready, press = (candidate[index].copy() for index in (1, 3, 4))
    hover[arm] = anchor[1][arm]
    ready[arm] = press[arm] = anchor[3][arm]
    d.qpos[:] = press
    m.mj_forward(model, d)
    keys, collisions = classify(d)
    if not keys or not is_clean(keys, collisions, note, fingering[note][1], side):
        return None
    if not valid_route([hover, ready], set(), count=12):
        return None
    shared = candidate[0], hover, hover, ready, press, candidate[5], candidate[6]
    return shared if probe(note, shared, side, attack=ATTACK_DURATION, hold=2.0,
                           release=RELEASE_DURATION)[0] else None


ATTACK_DURATION = args.attack_duration
RELEASE_DURATION = args.release_duration
# Fraction of each move at which the key edge is crossed. The fractions were
# measured with the original 0.44 s strike and 0.38 s lift-off, so scaling the
# durations keeps key-on and key-off on the score grid while freeing time for
# the wrist transfer.
ATTACK_CONTACT_RATIO = 0.30 / 0.44
RELEASE_CONTACT_RATIO = 0.18 / 0.38
# A note counts as matched when its onset and its release both fall in this window.
TIMING_TOLERANCE_SEC = 0.25


def transfer_is_clear(previous, current, transfer, side, note):
    """Check for overshoot after a strike and through the next strike."""
    sim = m.MjData(model)
    m.mj_resetDataKeyframe(model, sim, ready_id)
    sim.qpos[:] = previous[3]
    sim.ctrl[:] = previous[3][qctrl]
    m.mj_forward(model, sim)
    for pose, duration in ((previous[4], ATTACK_DURATION), (previous[4], 0.60),
                           (previous[3], RELEASE_DURATION)):
        step_to(sim, pose, duration, lambda data: None)
    clean = True
    allowed_note = None

    def watch(data):
        nonlocal clean
        keys, collisions = classify(data)
        if allowed_note is None:
            clean = clean and not (keys or collisions)
        else:
            clean = clean and is_clean(keys, collisions, note, fingering[note][1], side)

    for duration, pose in transfer:
        step_to(sim, pose, duration, watch)
        if not clean:
            return False
    allowed_note = note
    step_to(sim, current[4], ATTACK_DURATION, watch)
    step_to(sim, current[4], 2.0, watch)
    return clean


def transfer_between(previous, current, nearby, arm, side, note, available):
    """Choose a transfer that fits the gap and clears the keys in dynamics."""
    old_hover, old_ready = previous[1], previous[3]
    new_hover, new_ready = current[1], current[3]
    candidates = []
    delta = float(np.max(np.abs(old_ready[arm] - new_ready[arm])))
    if nearby:
        level_time = 0.50
        if available <= level_time:
            level_time = available - 4 * model.opt.timestep
        if (level_time >= args.level_shift_min_time
                and delta <= args.transfer_joint_max_shift
                and delta <= args.transfer_joint_speed * level_time):
            candidates.append(("level_shift", [(level_time, new_ready)]))
    old_lift = old_ready + 0.40 * (old_hover - old_ready)
    new_lift = new_ready + 0.40 * (new_hover - new_ready)
    short_lift = [(0.32, old_lift), (0.45, new_lift), (0.42, new_ready)]
    budget = available - 4 * model.opt.timestep
    if budget * 0.30 >= 4 * model.opt.timestep and budget < sum(
            duration for duration, _ in short_lift):
        # The window is too small for a full lift, so keep the lift-shift-drop
        # shape and scale it to the window instead of sliding along the keys.
        candidates.append(("micro_lift", [
            (budget * 0.30, old_lift),
            (budget * 0.35, new_lift),
            (budget * 0.35, new_ready),
        ]))
        candidates.append(("micro_lift_full", [
            (budget * 0.30, old_hover),
            (budget * 0.35, new_hover),
            (budget * 0.35, new_ready),
        ]))
    candidates.extend((
        ("short_lift", short_lift),
        ("full_lift", [(0.56, old_hover), (1.10, new_hover), (0.62, new_ready)]),
    ))
    for mode, transfer in candidates:
        if sum(duration for duration, _ in transfer) >= available:
            continue
        if (valid_route([old_ready] + [pose for _, pose in transfer], set(), count=18)
                and transfer_is_clear(previous, current, transfer, side, note)):
            return mode, transfer
    return None


def schedule_hand(notes, plans, scale, side):
    """Fit validated wrist transitions between releases and finger strikes."""
    arm = leftqa if side == "left" else rightqa
    waypoints = [(0.0, plans[notes[0].note][1])]
    windows = []
    counts = dict.fromkeys(
        ("repeat", "shared_wrist", "refinger", "level_shift", "micro_lift",
         "micro_lift_full", "short_lift", "full_lift"), 0)
    shared_cache = {}
    transfer_cache = {}

    def can_share(first, second):
        return abs(first - second) <= 3 and fingering[first] != fingering[second]

    def at_wrist(note, anchor):
        key = note, anchor[3][arm].tobytes(), fingering[note][1]
        if key not in shared_cache:
            shared_cache[key] = share_wrist(note, anchor, plans[note], side, arm)
        return shared_cache[key]

    def share_or_refinger(note, anchor, anchor_note):
        """Play `note` without moving the arm, re-fingering it when that is what it takes."""
        if can_share(anchor_note, note) and (shared := at_wrist(note, anchor)) is not None:
            counts["shared_wrist"] += 1
            return shared
        if abs(anchor_note - note) > 3:
            return None
        original = fingering[note]
        used = {original[1], fingering[anchor_note][1]}
        for letter, finger in (("D", "index"), ("E", "middle"), ("F", "ring"), ("G", "little")):
            if finger in used:
                continue
            fingering[note] = (letter, finger)
            shared = at_wrist(note, anchor)
            if shared is not None:
                counts["refinger"] += 1
                print(f"REFINGER {anchor_note}->{note} {finger} ok", flush=True)
                return shared
        fingering[note] = original
        return None

    def find_transfer(source_note, source, target_note, target, available):
        key = (source_note, target_note, source[3][arm].tobytes(),
               target[3][arm].tobytes(), available)
        if key not in transfer_cache:
            transfer_cache[key] = transfer_between(
                source, target, abs(target_note - source_note) <= 3, arm, side,
                target_note, available)
        return transfer_cache[key]

    previous_note = previous = None
    for index, note in enumerate(notes):
        on = 2.20 + note.start * scale
        off = 2.20 + note.end * scale
        attack_start = on - ATTACK_CONTACT_RATIO * ATTACK_DURATION
        release_start = off - RELEASE_CONTACT_RATIO * RELEASE_DURATION
        current = plans[note.note]
        if previous_note == note.note:
            current = previous
            transfer = []
            counts["repeat"] += 1
        elif previous is not None and (
                shared := share_or_refinger(note.note, previous, previous_note)) is not None:
            current = shared
            transfer = []
        else:
            if index + 1 < len(notes):
                next_note = notes[index + 1].note
                if can_share(note.note, next_note) and at_wrist(next_note, current) is None:
                    current = at_wrist(note.note, plans[next_note]) or current
            if previous is None:
                waypoints[0] = (0.0, current[1])
                transfer = [(0.62, current[3])]
            else:
                available = round(attack_start - waypoints[-1][0], 9)
                chosen = find_transfer(previous_note, previous, note.note, current, available)
                if chosen is None and current is not plans[note.note]:
                    current = plans[note.note]
                    chosen = find_transfer(previous_note, previous, note.note, current, available)
                if chosen is None:
                    delta = float(np.max(np.abs(previous[3][arm] - current[3][arm])))
                    raise ValueError(
                        f"No clear {side} wrist transfer from MIDI note {previous_note} to "
                        f"{note.note} in {available:.3f}s (arm shift {delta:.3f} rad needs "
                        f"{delta / args.transfer_joint_speed:.3f}s at "
                        f"{args.transfer_joint_speed:.2f} rad/s); check --tempo-scale")
                mode, transfer = chosen
                counts[mode] += 1

        ready, press = current[3:5]
        release_end = release_start + RELEASE_DURATION
        approach_start = attack_start - sum(duration for duration, _ in transfer)
        approach = [(approach_start, waypoints[-1][1])]
        for duration, pose in transfer:
            approach.append((approach[-1][0] + duration, pose))
        waypoints_for_note = approach + [
            (attack_start + ATTACK_DURATION, press),
            (release_start, press),
            (release_end, ready),
        ]
        for time, pose in waypoints_for_note:
            if time <= waypoints[-1][0]:
                raise ValueError(f"MIDI note {note.note} needs more movement time; increase --tempo-scale")
            waypoints.append((time, pose))
        windows.append((attack_start, release_end, note.note, on, off))
        previous_note, previous = note.note, current
    waypoints.append((waypoints[-1][0] + 0.56, previous[1]))
    return (waypoints, windows), counts


def play_midi(capture, publish=None):
    schedules, transitions = {}, {}
    for side, plans in (("left", left_plans), ("right", second)):
        schedules[side], transitions[side] = schedule_hand(
            score_by_hand[side], plans, args.tempo_scale, side)
    print("WRIST TRANSITIONS", json.dumps(transitions), flush=True)
    actuators = {side: np.flatnonzero(np.isin(qctrl, indices))
                 for side, indices in (("left", left_indices), ("right", right_indices))}
    addresses = {side: qctrl[channels] for side, channels in actuators.items()}
    sim = m.MjData(model)
    m.mj_resetDataKeyframe(model, sim, ready_id)
    sim.qpos[left_indices] = schedules["left"][0][0][1][left_indices]
    sim.qpos[right_indices] = schedules["right"][0][0][1][right_indices]
    sim.ctrl[:] = sim.qpos[qctrl]
    m.mj_forward(model, sim)

    key_events = KeyEvents(model, press_deg=args.key_press_deg,
                           release_deg=args.key_release_deg)
    edges, raw_contacts, bad = [], [], set()
    active = set()
    waypoint_index = dict.fromkeys(sides, 0)
    window_index = dict.fromkeys(sides, 0)
    end = max(waypoints[-1][0] for waypoints, _ in schedules.values()) + 0.4
    while sim.time < end:
        now = sim.time
        for side, (waypoints, _) in schedules.items():
            index = waypoint_index[side]
            while index + 1 < len(waypoints) and now >= waypoints[index + 1][0]:
                index += 1
            waypoint_index[side] = index
            start, pose = waypoints[index]
            channels = actuators[side]
            joints = addresses[side]
            if index + 1 < len(waypoints) and pose is not waypoints[index + 1][1]:
                finish, goal = waypoints[index + 1]
                phase = (now - start) / (finish - start)
                weight = phase * phase * (3 - 2 * phase)
                sim.ctrl[channels] = pose[joints] + weight * (goal[joints] - pose[joints])
            else:
                sim.ctrl[channels] = pose[joints]
        m.mj_step(model, sim)
        if sim.time <= now or sim.warning.number.any():
            raise RuntimeError("Unstable MuJoCo trajectory")
        new_edges = key_events.update(sim)
        edges.extend(new_edges)
        if publish is not None:
            for time, edge, note in new_edges:
                publish(time, edge, note)
        keys, collisions = classify(sim)
        bad.update(collisions)
        allowed = {}
        for side, (_, windows) in schedules.items():
            index = window_index[side]
            while index < len(windows) and sim.time > windows[index][1]:
                index += 1
            window_index[side] = index
            if index < len(windows) and sim.time >= windows[index][0]:
                allowed[side] = windows[index][2]
        for side, note, geom in keys:
            if allowed.get(side) != note or not geom.startswith(f"{side}_{fingering[note][1]}_"):
                contact = (side, note, geom)
                if contact not in bad:
                    print("UNEXPECTED CONTACT", round(sim.time, 3), contact, allowed, flush=True)
                bad.add(contact)
        touching = {(side, note) for side, note, _ in keys}
        raw_contacts.extend((sim.time, "on", *key) for key in sorted(touching - active))
        raw_contacts.extend((sim.time, "off", *key) for key in sorted(active - touching))
        active = touching
        capture(sim)

    side_by_note = {note: side for side, notes in assignments.items() for note in notes}
    queues = {side: [] for side in sides}
    pressed = {}
    for time, edge, note in edges:
        if note not in side_by_note:
            bad.add(("unexpected_key", note))
        elif edge == "on":
            pressed[note] = time
        else:
            start = pressed.pop(note)
            queues[side_by_note[note]].append((start, note, time - start))
    timing = {}
    key_press = {"expected": 0, "observed": 0, "matched": 0, "sequence_mismatch": False}
    ok = not pressed
    for side, (_, windows) in schedules.items():
        queues[side].sort()
        played = queues[side]
        key_press["expected"] += len(windows)
        key_press["observed"] += len(played)
        if [note for _, note, _ in played] != [note for _, _, note, _, _ in windows]:
            ok = False
            key_press["sequence_mismatch"] = True
            continue
        pairs = list(zip(played, windows))
        # A press only counts as a hit when its onset lands in the score window;
        # the release timing is checked separately by `ok`.
        key_press["matched"] += sum(
            1 for (start, _, _), (_, _, _, on, _) in pairs
            if abs(start - on) <= TIMING_TOLERANCE_SEC)
        onset_error = max(abs(start - on) for (start, _, _), (_, _, _, on, _) in pairs)
        release_error = max(abs(start + duration - off)
                            for (start, _, duration), (_, _, _, _, off) in pairs)
        timing[side] = {"max_onset_error_sec": onset_error, "max_release_error_sec": release_error}
        ok = ok and max(onset_error, release_error) <= TIMING_TOLERANCE_SEC
    expected, observed, matched = (key_press[name] for name in ("expected", "observed", "matched"))
    precision = matched / observed if observed else 1.0
    recall = matched / expected if expected else 1.0
    key_press.update(
        precision=precision, recall=recall,
        f1=2 * precision * recall / (precision + recall) if precision + recall else 0.0)
    (output / "key_events.json").write_text(json.dumps(edges), encoding="utf-8")
    return (ok, queues, raw_contacts, bad, sim.time, timing, len(edges), transitions, key_press)


def play_ros_midi(capture):
    import rclpy
    from rclpy.qos import DurabilityPolicy, QoSProfile
    from std_msgs.msg import String

    rclpy.init(args=[])
    node = rclpy.create_node("flat_palm_piano")
    try:
        depth = 2 * sum(len(notes) for notes in score_by_hand.values())
        publisher = node.create_publisher(
            String, "/sim_piano/key_event",
            QoSProfile(depth=depth, durability=DurabilityPolicy.TRANSIENT_LOCAL))

        def publish(time, edge, note):
            publisher.publish(String(data=json.dumps(
                {"sim_time_sec": time, "type": edge, "note": note})))

        return play_midi(capture, publish)
    finally:
        node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


report={'song':args.score.stem if args.score else 'Two Tigers',
        'platform':platform.machine(),'mujoco_version':m.__version__,
        'right_pose_sha256':pose_sha,'original_fingering_probes':original_results,
        'alternate_fingering_probes':alternate_results,
        'left_hand':'Original right READY/PRESS_D values applied to left simulation joints',
        'start_state':'Both arms initialized in validated flat-palm playing poses',
        'strike':'Wrist targets fixed during READY to PRESS and PRESS to READY',
        'contact_offset':args.contact_offset,
        'right_fingering':fingering}
palm_tilt={side:0.0 for side in sides}

import wave

fps=24
speed=args.tempo_scale if args.score else 10.8/(2.9/3.0)
beat_sec=10.8
frame_rate=fps
frames=[]
next_frame=0
def capture(sim):
    global next_frame
    if sim.time+1e-9>=next_frame:
      for side in sides:
        normal=sim.body(side+'_l20_base_link').xmat.reshape(3,3)[:,0]
        tilt=float(np.degrees(np.arccos(np.clip(abs(normal[2]),0,1))))
        palm_tilt[side]=max(palm_tilt[side],tilt)
    if sim.time+1e-9>=next_frame:
        frames.append(sim.qpos.copy())
        next_frame+=speed/fps
key_press = None
if args.score is None:
    events,bad,expected,duration=full_song(second,beat_sec,capture)
    ok,queues=compare(events,expected)
else:
    play = play_ros_midi if args.ros_events else play_midi
    ok, queues, events, bad, duration, timing, edge_count, transitions, key_press = play(capture)
    # A null key_activation_deg means the default fraction thresholds were used.
    report.update(timing=timing, key_state_transitions=edge_count, wrist_transitions=transitions,
                  key_activation_deg={"press": args.key_press_deg,
                                      "release": args.key_release_deg},
                  event_source="passive key joint angles",
                  timing_tolerance_sec=TIMING_TOLERANCE_SEC)
print('RESULT',ok,'BAD',len(bad),sorted(bad,key=str)[:12],
      'RAW',len(events),'DURATION',round(duration,3),flush=True)
report.update(palm_tilt_max_degrees=palm_tilt,sim_seconds=round(duration,3),video_speed=speed,frames=len(frames),
    matched_note_ons_and_releases={side:len(queues[side]) for side in sides}, key_press=key_press,
    unexpected_contacts=sorted(bad,key=str),raw_contact_transitions=len(events),passed=ok and not bad,
    observed={side:[{'time_sec':float(start),'duration_sec':float(length),'note':note}
                  for start,note,length in queues[side]] for side in sides})
(output/'report.json').write_text(json.dumps(report,indent=2),encoding='utf-8')
(output/'raw_contacts.json').write_text(json.dumps(events),encoding='utf-8')
if not ok or bad:
    raise SystemExit(3)
np.savez_compressed(output/'frames.npz',qpos=np.array(frames),fps=fps)
channels={'left':1,'right':0}
volumes={'left':67,'right':85}
def midi(items,label):
    rows=[]
    for t,side,note,length in items:
        for sec,kind in ((t,'on'),(t+length,'off')):
            rows.append({'event':'midi','type':kind,'note':note,'velocity':volumes[side] if kind=='on' else 0,
                         'channel':channels[side],'monotonic_ns':round(sec*1e9)})
    rows.sort(key=lambda item: (item['monotonic_ns'],item['type'] != 'off',item['channel']))
    jsonl=output/f'{label}.jsonl'
    jsonl.write_text(''.join(json.dumps(row)+'\n' for row in rows),encoding='utf-8')
    count=export_midi(jsonl,output/f'{label}.mid')
    assert count==2*len(items),count
if args.score is None:
    score=[]
    t=0
    for note,length in zip(melody,lengths):
        score.append((t*beat_sec/speed,'right',note,length*beat_sec/speed*0.85))
        t+=length
    for i,note in enumerate(bass):
        score.append((4*i*beat_sec/speed,'left',note,0.7))
    midi(score,'two_tigers_original_pose_score')
midi([(start/speed,side,note,length/speed) for side in sides for start,note,length in queues[side]],
     'played_keys' if args.score else 'two_tigers_original_pose_contact')

sample_rate=24000
samples=np.zeros((round(len(frames)/frame_rate*sample_rate),2))
for side in sides:
    for start,note,length in queues[side]:
        pos=round(start/speed*sample_rate)
        seconds=min(0.7,0.25+length/speed)
        count=min(len(samples)-pos,round(seconds*sample_rate))
        sec=np.arange(count)/sample_rate
        f=440*2**((note-69)/12)
        tone=sum(a*np.sin(2*np.pi*f*k*sec)*np.exp(-sec*(k*1.8+2))
                 for k,a in ((1,1),(2,.28),(3,.16),(4,.08)))
        tone*=np.minimum(sec/.006,1)*np.exp(-np.maximum(sec-length/speed,0)*8)
        tone*=np.minimum((seconds-sec)/.05,1)
        pan=np.array((0.82,0.52) if side=='left' else (0.6,0.88))
        samples[pos:pos+count]+=tone[:,None]*pan*(.22 if side=='left' else .34)
samples=np.clip(samples,-.95,.95)
with wave.open(str(output/'contact_audio.wav'),'wb') as audio:
    audio.setnchannels(2)
    audio.setsampwidth(2)
    audio.setframerate(sample_rate)
    audio.writeframes((samples*32767).astype('<i2').tobytes())

print('VERIFIED',json.dumps({'note_count':report['matched_note_ons_and_releases'],
      'unexpected_contacts':len(bad),'frames':len(frames),'video_speed':speed}),flush=True)
