import {Renderers, planarPose} from './renderers.js';

const element = id => document.getElementById(id);
const {Rosbridge, TOPICS, zeroTwist} = window.FastBotBridge;
const bridge = new Rosbridge();
const view = new Renderers(element('map-canvas'), element('robot-canvas'), element('camera-canvas'));
const samples = new Map(), stamps = new Map();
let status = null, pending = false, observedActive = false, pointer = null, driveTimer = null;
let velocity = zeroTwist(), cameraAttempt = -Infinity;
const waypoints = new Map();
const notice = message => { element('notice').textContent = message; };
const fresh = (key, limit = 1500) => bridge.connected && performance.now() - (samples.get(key) ?? -Infinity) < limit;
const idle = () => fresh('status') && status?.active === false && !pending;
const canDrive = () => idle() && !document.hidden;
const canGoal = () => idle() && status.server_ready === true && fresh('pose') && !document.hidden;
function publish(topic, message) {
  try { bridge.publish(topic, message); return true; }
  catch (error) { notice(error.message); return false; }
}
function stop() {
  clearInterval(driveTimer); driveTimer = null;
  const previous = pointer; pointer = null;
  velocity = zeroTwist(); element('joystick').dataset.active = 'false';
  try { bridge.stopManual(); } catch (error) { notice(`零速未送达：${error.message}；依赖服务器watchdog`); }
  if (previous !== null && element('joystick').hasPointerCapture(previous)) element('joystick').releasePointerCapture(previous);
}
function reset() {
  stop(); samples.clear(); stamps.clear(); status = null; pending = false; observedActive = false;
  view.clear(); cameraAttempt = -Infinity;
}
function advancing(key, message) {
  const stamp = message.header?.stamp;
  if (!stamp || !Number.isInteger(stamp.sec) || !Number.isInteger(stamp.nanosec) || stamp.nanosec < 0 || stamp.nanosec >= 1e9) return false;
  const value = stamp.sec * 1e9 + stamp.nanosec;
  if (!Number.isSafeInteger(value) || value <= 0 || value <= (stamps.get(key) ?? -Infinity)) return false;
  stamps.set(key, value); return true;
}
function update() {
  const connected = bridge.connected, navFresh = fresh('status');
  element('connection-status').textContent = bridge.state;
  element('connect').disabled = bridge.state !== 'disconnected';
  element('disconnect').disabled = bridge.state === 'disconnected';
  element('nav-readiness').textContent = navFresh ? (status.server_ready ? 'ready' : 'not ready') : 'unknown / stale';
  element('action-status').textContent = navFresh ? `${status.state}${pending ? ' / 本地等待真实回执' : ''}${status.event ? ` / ${status.event}` : ''}${status.detail ? ` / ${status.detail}` : ''}` : 'unknown / stale';
  element('result-code').textContent = navFresh ? String(status.result_code ?? '—') : '— / stale';
  element('manual-controls').disabled = !canDrive();
  element('initial-pose-controls').disabled = !idle();
  element('waypoint-controls').disabled = false;
  element('cancel-navigation').disabled = !connected || (!pending && !(navFresh && status.active));
  for (const button of element('waypoint-list').querySelectorAll('[data-goal]')) button.disabled = !canGoal();
  for (const [key, ids, limit] of [
    ['map', ['map-status'], Infinity], ['pose', ['pose-status', 'map-position', 'map-heading'], 1500],
    ['odom', ['linear-speed', 'angular-speed'], 1500], ['camera', ['camera-status'], 2000]
  ]) for (const id of ids) {
    const target = element(id), stale = !fresh(key, limit);
    target.dataset.stale = String(stale);
    if (stale && !target.textContent.includes('stale')) target.textContent += ' / stale';
  }
  if (!canDrive()) stop();
  view.robot(fresh('pose') && fresh('map', Infinity) ? view.pose : null);
}
bridge.addEventListener('state', event => {
  if (event.detail.state !== 'connected') reset();
  else notice('已连接；等待实际遥测与导航状态。发布不代表接受或到达。');
  update();
});
bridge.addEventListener('before-disconnect', stop);
bridge.addEventListener('error', event => { stop(); notice(event.detail.message); });
bridge.addEventListener('bridge-status', event => {
  if (['error', 'warning'].includes(event.detail.level)) { stop(); notice(`ROSbridge：${event.detail.msg ?? event.detail.level}`); }
});
bridge.addEventListener('message', event => {
  const {topic, msg, receivedAt} = event.detail;
  try {
    if (topic === TOPICS.status) {
      const value = JSON.parse(msg.data);
      if (!value || typeof value.active !== 'boolean' || typeof value.server_ready !== 'boolean' || typeof value.state !== 'string') throw new Error('无效导航状态');
      const previousState = status?.state; status = value; samples.set('status', receivedAt);
      if (value.state !== previousState && ['succeeded', 'canceled', 'aborted', 'rejected'].includes(value.state)) notice('最近导航结果：' + ({succeeded:'已到达',canceled:'已取消',aborted:'已中止',rejected:'未接受'}[value.state]) + ' · Action ' + (value.result_code ?? '—'));
      if (pending && value.active) observedActive = true;
      if (pending && !value.active && (observedActive || String(value.event).startsWith('goal_rejected_'))) pending = false;
      if (value.active) stop();
    } else if (topic === TOPICS.map) {
      view.map(msg); samples.set('map', receivedAt);
      element('map-status').textContent = `${msg.info.width} × ${msg.info.height}，${Number(msg.info.resolution).toFixed(2)} m/cell`;
    } else if (topic === TOPICS.pose) {
      if (msg.header?.frame_id !== 'map') throw new Error('地图位姿必须来自map帧');
      const pose = planarPose(msg.pose);
      if (!advancing('pose', msg)) return;
      view.pose = pose; samples.set('pose', receivedAt);
      element('pose-status').textContent = 'map TF / fresh';
      element('map-position').textContent = `${pose.x.toFixed(3)}, ${pose.y.toFixed(3)}`;
      element('map-heading').textContent = pose.yaw.toFixed(3);
    } else if (topic === TOPICS.odom) {
      const linear = msg.twist?.twist?.linear?.x, angular = msg.twist?.twist?.angular?.z;
      if (![linear, angular].every(Number.isFinite)) throw new Error('无效里程计速度');
      if (!advancing('odom', msg)) return;
      samples.set('odom', receivedAt);
      element('linear-speed').textContent = linear.toFixed(3);
      element('angular-speed').textContent = angular.toFixed(3);
    } else if (topic === TOPICS.camera) {
      if (receivedAt - cameraAttempt < 500) return;
      cameraAttempt = receivedAt;
      if (!advancing('camera', msg)) return;
      view.camera(msg); samples.set('camera', receivedAt);
      element('camera-status').textContent = `${msg.width} × ${msg.height} ${msg.encoding} / ≤2Hz`;
    }
  } catch (error) {
    const key = Object.keys(TOPICS).find(name => TOPICS[name] === topic);
    samples.delete(key);
    if (key === 'pose') view.pose = null;
    if (key === 'camera') { view.clearCamera(); element('camera-status').textContent = `${error.message} / stale`; }
    notice(error.message);
  }
  update();
});
element('connection-form').addEventListener('submit', event => {
  event.preventDefault();
  try { bridge.connect(element('bridge-url').value.trim()); }
  catch (error) { notice(error.message); }
});
element('disconnect').addEventListener('click', () => { stop(); bridge.disconnect(); });
element('stop-manual').addEventListener('click', stop);
const joystick = element('joystick');
function steer(event) {
  if (pointer !== event.pointerId) return;
  const box = joystick.getBoundingClientRect();
  const clamp = value => Math.max(-1, Math.min(1, value));
  velocity.linear.x = clamp((box.top + box.height / 2 - event.clientY) / (box.height / 2)) * 0.15;
  velocity.angular.z = clamp((box.left + box.width / 2 - event.clientX) / (box.width / 2)) * 0.6;
}
function drive() {
  if (pointer === null || !canDrive()) { stop(); return; }
  if (!publish(TOPICS.manual, velocity)) stop();
}
joystick.addEventListener('pointerdown', event => {
  if (!event.isPrimary || event.button !== 0 || pointer !== null || !canDrive()) return;
  event.preventDefault(); pointer = event.pointerId;
  try { joystick.setPointerCapture(pointer); } catch { stop(); return; }
  joystick.dataset.active = 'true'; steer(event); drive();
  if (pointer !== null) driveTimer = setInterval(drive, 100);
});
joystick.addEventListener('pointermove', steer);
for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) joystick.addEventListener(type, event => { if (event.pointerId === pointer) stop(); });
window.addEventListener('blur', stop);
document.addEventListener('visibilitychange', () => { if (document.hidden) stop(); });
window.addEventListener('pagehide', () => { stop(); bridge.disconnect(); });
function coordinates(prefix) {
  const values = ['x', 'y', 'yaw'].map(key => element(`${prefix}-${key}`).value.trim());
  if (values.some(value => !value) || !values.map(Number).every(Number.isFinite)) throw new Error('请输入有限的X、Y、Yaw');
  return {x: Number(values[0]), y: Number(values[1]), yaw: Number(values[2])};
}
function poseMessage(point) {
  return {header: {frame_id: 'map', stamp: {sec: 0, nanosec: 0}}, pose: {
    position: {x: point.x, y: point.y, z: 0}, orientation: {x: 0, y: 0, z: Math.sin(point.yaw / 2), w: Math.cos(point.yaw / 2)}
  }};
}
element('initial-pose-form').addEventListener('submit', event => {
  event.preventDefault(); if (!idle()) return;
  try {
    const message = poseMessage(coordinates('initial')), covariance = Array(36).fill(0);
    covariance[0] = covariance[7] = 0.25; covariance[35] = 0.0685;
    stop();
    if (publish(TOPICS.initialPose, {header: message.header, pose: {pose: message.pose, covariance}})) notice('初始位姿已发布；定位是否成功尚需实际TF确认。');
  } catch (error) { notice(error.message); }
});
function savePoints() {
  try { localStorage.setItem('fastbot.user-waypoints.v1', JSON.stringify([...waypoints])); }
  catch { notice('浏览器存储不可用；目标仅保留在当前页面。'); }
  listPoints();
}
function listPoints() {
  const list = element('waypoint-list'); list.replaceChildren();
  for (const [name, point] of waypoints) {
    const group = document.createElement('span');
    const button = (label, action) => { const item = document.createElement('button'); item.type = 'button'; item.textContent = label; item.onclick = action; group.append(item); return item; };
    const goal = button(`导航：${name}`, () => {
      if (!canGoal()) return;
      stop(); pending = true; observedActive = false;
      if (!publish(TOPICS.goal, poseMessage(point))) pending = false;
      else notice('目标已发布；等待真实Action状态，不代表已接受或到达。');
      update();
    });
    goal.dataset.goal = 'true'; goal.disabled = !canGoal();
    button('编辑', () => { element('waypoint-name').value = name; for (const key of ['x', 'y', 'yaw']) element(`waypoint-${key}`).value = point[key]; });
    button('删除', () => { waypoints.delete(name); savePoints(); }); list.append(group);
  }
}
element('waypoint-form').addEventListener('submit', event => {
  event.preventDefault();
  try {
    const name = element('waypoint-name').value.trim();
    if (!name || name.length > 48 || (!waypoints.has(name) && waypoints.size >= 50)) throw new Error('名称限48字符，最多50个目标；同名保存覆盖坐标');
    waypoints.set(name, coordinates('waypoint')); savePoints(); notice('目标已保存，未发送导航。');
  } catch (error) { notice(error.message); }
});
element('cancel-navigation').addEventListener('click', () => { stop(); if (publish(TOPICS.cancel, {})) notice('已请求取消；等待真实Action终态。'); });
try {
  const saved = JSON.parse(localStorage.getItem('fastbot.user-waypoints.v1') || '[]');
  if (Array.isArray(saved)) for (const entry of saved.slice(0, 50)) {
    if (!Array.isArray(entry)) continue;
    const [name, point] = entry;
    if (typeof name === 'string' && name.trim() && name.length <= 48 && point && [point.x, point.y, point.yaw].every(Number.isFinite)) waypoints.set(name, point);
  }
} catch { notice('已忽略无效或不可读取的本地目标。'); }
listPoints(); update(); setInterval(update, 100);
notice(view.gl ? '独立参考界面；初始断开。无自动连接、目标或运动；实际运行未验证。' : 'WebGL不可用，无法显示3D机器人；其他功能仍需实际验证。');
