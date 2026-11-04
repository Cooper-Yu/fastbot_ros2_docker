import { RosbridgeClient } from './rosbridge.js?v=cp23-20261104-fragments';
import { MapRenderer, CameraRenderer, RobotRenderer } from './renderers.js?v=cp23-20261104';

const element = identifier => {
  const target = document.getElementById(identifier);
  if (!target) throw new Error(`Missing dashboard element: ${identifier}`);
  return target;
};
const output = (identifier, text, state = '') => {
  const target = element(identifier);
  target.textContent = text;
  target.dataset.state = state;
};
const finite = value => typeof value === 'number' && Number.isFinite(value);
const requireValue = (condition, message) => {
  if (!condition) throw new Error(message);
};
const framePattern = /^[A-Za-z_][A-Za-z0-9_]*(?:\/[A-Za-z_][A-Za-z0-9_]*)*$/;
const topicPattern = /^\/[A-Za-z_][A-Za-z0-9_]*(?:\/[A-Za-z_][A-Za-z0-9_]*)*$/;
const topicKeys = ['map', 'camera', 'odom', 'pose', 'status', 'manual', 'goal', 'cancel', 'initialpose'];
const activeStates = new Set(['awaiting_acceptance', 'accepted', 'executing', 'cancel_requested']);
const terminalStates = new Set(['succeeded', 'canceled', 'aborted', 'rejected', 'unavailable']);
const states = new Set(['idle', ...activeStates, ...terminalStates]);
const waypointStorage = 'fastbot.reference.waypoints.v1';
const navigationStorage = 'fastbot.reference.navigation.v1';
const twistType = 'geometry_msgs/msg/Twist';
const poseType = 'geometry_msgs/msg/PoseStamped';
const zeroTwist = () => ({ linear: { x: 0, y: 0, z: 0 }, angular: { x: 0, y: 0, z: 0 } });
const identifier = () => globalThis.crypto?.randomUUID?.() ?? `${Date.now()}-${Math.random().toString(36).slice(2)}`;

let session = null;
let generation = 0;
let selected = null;
let waypoints = [];
let waypointStoreReady = false;
let waypointSaving = false;
let waypointRevision = 0;
let navigation = null;
let storageHealthy = true;
let storageDiagnostic = '';
let lastStamp = 0;
let pointer = null;
let holdTimer = null;
let manualVector = { linear: 0, angular: 0 };
let stopping = false;

function storageFailure(error) {
  storageHealthy = false;
  storageDiagnostic = `Browser persistence unavailable: ${error.message}. Navigation disabled until storage is restored and the page reloaded.`;
  output('application-status', storageDiagnostic, 'error');
}

function storeNavigation() {
  try {
    if (navigation) localStorage.setItem(navigationStorage, JSON.stringify(navigation));
    else localStorage.removeItem(navigationStorage);
    return true;
  } catch (error) {
    storageFailure(error);
    return false;
  }
}

function readStorage() {
  try {
    const probe = `${navigationStorage}.probe`;
    localStorage.setItem(probe, '1');
    localStorage.removeItem(probe);
    const saved = localStorage.getItem(waypointStorage);
    if (saved !== null) {
      const parsed = JSON.parse(saved);
      requireValue(Array.isArray(parsed) && parsed.length <= 100, 'Invalid saved waypoint collection');
      const identifiers = new Set();
      for (const waypoint of parsed) {
        requireValue(validWaypoint(waypoint) && !identifiers.has(waypoint.id), 'Invalid or duplicate saved waypoint');
        identifiers.add(waypoint.id);
      }
      waypoints = parsed;
    }
    const pending = localStorage.getItem(navigationStorage);
    if (pending !== null) {
      const parsed = JSON.parse(pending);
      requireValue(parsed && typeof parsed.id === 'string' && typeof parsed.endpoint === 'string', 'Invalid saved navigation reservation; inspect robot ownership before clearing browser storage');
      navigation = { ...parsed, uncertain: true, state: 'unknown' };
      storeNavigation();
    }
  } catch (error) {
    storageFailure(error);
  }
}

function validWaypoint(waypoint) {
  return waypoint && typeof waypoint.id === 'string' && waypoint.id.length <= 128
    && typeof waypoint.name === 'string' && waypoint.name.trim().length > 0 && waypoint.name.length <= 48
    && [waypoint.x, waypoint.y, waypoint.yaw].every(finite)
    && typeof waypoint.frame === 'string' && framePattern.test(waypoint.frame)
    && (waypoint.mapId === null || typeof waypoint.mapId === 'string')
    && (waypoint.endpoint === null || typeof waypoint.endpoint === 'string');
}

function saveWaypoints() {
  try {
    localStorage.setItem(waypointStorage, JSON.stringify(waypoints));
  } catch (error) {
    storageFailure(error);
  }
}

function numberInput(name, minimum = -Infinity, maximum = Infinity) {
  const text = element(name).value.trim();
  const value = Number(text);
  requireValue(text !== '' && finite(value) && value >= minimum && value <= maximum, `Enter a finite ${name} between ${minimum} and ${maximum}`);
  return value;
}

function configuration() {
  const topics = {};
  for (const key of topicKeys) {
    topics[key] = element(`${key}-topic`).value.trim();
    requireValue(topicPattern.test(topics[key]) && topics[key].length <= 512, `Invalid absolute ${key} topic`);
  }
  requireValue(new Set(Object.values(topics)).size === topicKeys.length, 'Configured sensor and command topics must all be distinct');
  const frames = {};
  for (const key of ['map', 'odom', 'base']) {
    frames[key] = element(`${key}-frame`).value.trim();
    requireValue(framePattern.test(frames[key]) && frames[key].length <= 256, `Invalid ${key} frame`);
  }
  requireValue(new Set(Object.values(frames)).size === 3, 'Map, odometry and base frames must be distinct');
  const freshness = numberInput('freshness-ms', 200, 2000);
  const throttle = numberInput('camera-throttle-ms', 100, 2000);
  requireValue(Number.isInteger(freshness) && Number.isInteger(throttle), 'Timeout and throttle must be integer milliseconds');
  return Object.freeze({
    topics: Object.freeze(topics), frames: Object.freeze(frames), freshness, throttle,
    transient: element('map-transient-local').checked,
    endpoint: element('rosbridge-url').value.trim()
  });
}

function current(candidate) {
  return session === candidate && candidate.generation === generation;
}

function fresh(candidate, sensor) {
  const sample = candidate?.samples[sensor];
  const maximum = sensor === 'camera' ? Math.max(candidate.config.freshness, candidate.config.throttle * 2) : candidate?.config.freshness;
  return Boolean(candidate?.client.connected && sample && performance.now() - sample.received <= maximum);
}

function statusReady(candidate = session) {
  return Boolean(candidate && !candidate.fault && fresh(candidate, 'status') && candidate.samples.status.value.feedback_valid);
}

function idle(candidate = session) {
  if (!statusReady(candidate)) return false;
  const status = candidate.samples.status.value;
  return status.owner === null && status.manual_allowed && status.manual_released
    && !activeStates.has(status.state);
}

function poseReady(candidate = session) {
  return Boolean(statusReady(candidate) && fresh(candidate, 'pose') && candidate.samples.status.value.pose_valid);
}

function commandReady(candidate = session) {
  return Boolean(candidate?.client.connected && candidate.commandAck
    && performance.now() - candidate.commandAck <= 5000);
}

function manualReady(candidate = session) {
  if (!statusReady(candidate) || !commandReady(candidate) || navigation || document.hidden || candidate.blocked) return false;
  const status = candidate.samples.status.value;
  return status.manual_allowed && status.owner === null && !activeStates.has(status.state);
}

function navigationReady(candidate = session) {
  return Boolean(storageHealthy && waypointStoreReady && !waypointSaving && commandReady(candidate) && candidate && !candidate.blocked && !document.hidden && !navigation && candidate.mapId
    && idle(candidate) && poseReady(candidate) && candidate.samples.status.value.navigation_ready);
}

function initialposeReady(candidate = session) {
  if (!candidate || !commandReady(candidate) || candidate.blocked || document.hidden || navigation || !idle(candidate) || !fresh(candidate, 'odom')) return false;
  const measured = candidate.samples.odom.value.twist.twist;
  return Math.hypot(measured.linear.x, measured.linear.y) < 0.02 && Math.abs(measured.angular.z) < 0.04;
}

function advancedStamp(candidate, sensor, message) {
  const stamp = message?.header?.stamp;
  requireValue(stamp && Number.isSafeInteger(stamp.sec) && stamp.sec >= 0
    && Number.isInteger(stamp.nanosec) && stamp.nanosec >= 0 && stamp.nanosec < 1000000000
    && (stamp.sec !== 0 || stamp.nanosec !== 0), `${sensor}: missing or invalid source stamp`);
  const previous = candidate.stamps[sensor];
  if (previous && stamp.sec === previous.sec && stamp.nanosec === previous.nanosec) return null;
  requireValue(!previous || stamp.sec > previous.sec || (stamp.sec === previous.sec && stamp.nanosec > previous.nanosec), `${sensor}: regressing source stamp; receipt not refreshed`);
  return { sec: stamp.sec, nanosec: stamp.nanosec };
}

function quaternion(rotation) {
  const values = [rotation?.x, rotation?.y, rotation?.z, rotation?.w];
  requireValue(values.every(finite), 'Pose quaternion must be finite');
  const norm = Math.hypot(...values);
  requireValue(Math.abs(norm - 1) <= 0.05, 'Pose quaternion must be normalized');
  return values.map(value => value / norm);
}

function yawOf(rotation) {
  const [quatX, quatY, quatZ, quatW] = quaternion(rotation);
  return Math.atan2(2 * (quatW * quatZ + quatX * quatY), 1 - 2 * (quatY * quatY + quatZ * quatZ));
}

function validatePose(pose) {
  requireValue([pose?.position?.x, pose?.position?.y, pose?.position?.z].every(finite), 'Pose position must be finite');
  quaternion(pose.orientation);
}

async function receiveLive(candidate, sensor, message, validate, render = () => {}) {
  if (!current(candidate)) return;
  try {
    const stamp = advancedStamp(candidate, sensor, message);
    if (stamp === null) { refresh(); return; } // Ignore duplicates without renewing freshness.
    validate(message);
    await render(message);
    if (!current(candidate)) return;
    candidate.stamps[sensor] = stamp;
    candidate.samples[sensor] = { value: message, received: performance.now() };
  } catch (error) {
    candidate.samples[sensor] = null;
    if (sensor === 'camera') candidate.camera?.clear();
    output(`${sensor === 'camera' ? 'camera' : sensor}-status`, error.message, 'error');
    if (sensor === 'pose') hidePose(candidate);
    if (sensor !== 'camera') emergency(candidate, `${sensor} invalid: ${error.message}`, true);
  }
  refresh();
}

function hidePose(candidate) {
  for (const renderer of [candidate.map, candidate.robot]) {
    try { renderer?.updatePose(null); } catch (error) { output('application-status', error.message, 'error'); }
  }
  candidate.poseShown = false;
}

function mapIdentity(message) {
  let hash = 2166136261;
  const metadata = JSON.stringify([message.header.frame_id, message.info.width, message.info.height, message.info.resolution, message.info.origin]);
  for (const character of metadata) hash = Math.imul(hash ^ character.charCodeAt(0), 16777619) >>> 0;
  for (const value of message.data) hash = Math.imul(hash ^ (value + 1), 16777619) >>> 0;
  return `${metadata}:${hash.toString(16)}`;
}

function configureWorldView(candidate, message) {
  const origin = message.info.origin;
  const [quatX, quatY, quatZ, quatW] = quaternion(origin.orientation);
  const width = message.info.width * message.info.resolution;
  const height = message.info.height * message.info.resolution;
  const corners = [[0, 0], [width, 0], [0, height], [width, height]].map(([localX, localY]) => [
    origin.position.x + (1 - 2 * (quatY * quatY + quatZ * quatZ)) * localX + 2 * (quatX * quatY - quatZ * quatW) * localY,
    origin.position.y + 2 * (quatX * quatY + quatZ * quatW) * localX + (1 - 2 * (quatX * quatX + quatZ * quatZ)) * localY,
    origin.position.z + 2 * (quatX * quatZ - quatY * quatW) * localX + 2 * (quatY * quatZ + quatX * quatW) * localY
  ]);
  const center = [0, 1, 2].map(axis => (Math.min(...corners.map(corner => corner[axis])) + Math.max(...corners.map(corner => corner[axis]))) / 2);
  const diagonal = Math.hypot(width, height) + 1;
  candidate.worldView = { center, diagonal };
  updateWorldView(candidate);
}

function updateWorldView(candidate) {
  if (!candidate.worldView || !candidate.robot) return;
  const canvas = element('robot-canvas');
  const rectangle = canvas.getBoundingClientRect();
  const aspect = Math.max(0.01, rectangle.width / Math.max(1, rectangle.height));
  // Keep the measured robot readable; the 2D panel owns the whole-home map.
  candidate.robot.setFollowView(0.5 / Math.min(1, aspect));
}

function receiveMap(candidate, message) {
  if (!current(candidate)) return;
  try {
    candidate.map.updateMap(message);
    configureWorldView(candidate, message);
    const mapId = mapIdentity(message);
    if (candidate.mapId !== mapId) {
      candidate.validated.clear();
      if (candidate.mapId && navigation) emergency(candidate, 'Map changed; stop and revalidate destinations', true);
      candidate.mapId = mapId;
      output('waypoint-status', waypointStoreReady ? 'Project waypoints loaded; matching map is ready' : 'Loading project waypoints', waypointStoreReady ? 'fresh' : 'unavailable');
      renderWaypoints();
    }
  } catch (error) {
    candidate.fault = true;
    output('map-status', error.message, 'error');
    emergency(candidate, `Map/rendering error: ${error.message}`, true);
  }
  refresh();
}

function validateStatus(candidate, message) {
  requireValue(typeof message.data === 'string' && message.data.length <= 32768, 'Invalid adapter status envelope');
  const status = JSON.parse(message.data);
  requireValue(status && !Array.isArray(status) && states.has(status.state), 'Unknown adapter state');
  requireValue(status.map_frame === candidate.config.frames.map && status.base_frame === candidate.config.frames.base, 'Adapter map/base frame mismatch');
  for (const key of ['feedback_valid', 'pose_valid', 'navigation_ready', 'manual_allowed', 'manual_released', 'cancel_requested', 'navigation_enabled']) {
    requireValue(typeof status[key] === 'boolean', `Adapter missing boolean ${key}`);
  }
  requireValue(status.navigation_paused === undefined || typeof status.navigation_paused === 'boolean', 'Invalid navigation pause flag');
  requireValue(!status.navigation_paused || (activeStates.has(status.state) && status.owner !== null && !status.cancel_requested), 'Inconsistent paused navigation');
  requireValue([null, 'browser', 'action'].includes(status.owner), 'Invalid adapter owner');
  requireValue(status.request_id === null || typeof status.request_id === 'string', 'Invalid adapter request_id');
  requireValue(status.goal_uuid === null || typeof status.goal_uuid === 'string', 'Invalid adapter goal_uuid');
  requireValue(status.result === null || [4, 5, 6].includes(status.result), 'Invalid adapter result');
  requireValue(typeof status.diagnostic === 'string', 'Missing adapter diagnostic');
  requireValue(!(activeStates.has(status.state) && status.owner === null), 'Active adapter state without ownership');
  requireValue(!(status.manual_allowed && status.owner !== null), 'Inconsistent manual ownership');
  return status;
}

function matchingNavigation(candidate, status) {
  return navigation && navigation.endpoint === candidate.endpoint && status.request_id === navigation.id;
}

function receiveStatus(candidate, message) {
  if (!current(candidate)) return;
  try {
    const status = validateStatus(candidate, message);
    candidate.samples.status = { value: status, received: performance.now() };
    if (matchingNavigation(candidate, status)) {
      if (activeStates.has(status.state) && status.owner === 'browser') {
        navigation.state = status.state;
        navigation.paused = status.navigation_paused === true;
        navigation.uncertain = false;
        navigation.updated = Date.now();
        storeNavigation();
      } else if (terminalStates.has(status.state) && status.owner === null) {
        const confirmed = (status.state === 'succeeded' && status.result === 4)
          || (status.state === 'canceled' && status.result === 5)
          || (status.state === 'aborted' && status.result === 6)
          || status.state === 'rejected'
          || (status.state === 'unavailable' && status.result === null);
        if (confirmed) {
          output('navigation-status', `${navigation.name}: ${status.state}`, status.state);
          navigation = null;
          storeNavigation();
        }
      }
    }
    if (!status.feedback_valid || !status.manual_allowed || status.owner !== null) {
      if (pointer !== null) emergency(candidate, 'Manual control permission lost', true);
    }
    if (navigation && (!status.feedback_valid || !status.pose_valid) && !status.navigation_paused) emergency(candidate, 'Navigation feedback lost without confirmed backend pause; cancellation requested', true);
    output('adapter-status', `${status.navigation_paused ? 'paused' : status.state} · ${status.owner ?? 'unowned'}`, status.feedback_valid ? 'fresh' : 'stale');
    const detail = status.navigation_paused
      ? `Paused: ${status.pause_reason ?? 'Feedback unavailable'}. Output zero; waiting for stable fresh feedback.`
      : status.state === 'canceled' && status.cancel_reason
      ? `Canceled: ${status.cancel_reason}. ${status.feedback_valid && status.pose_valid
        ? 'Feedback restored; select a goal to start a new request.' : 'Waiting for fresh feedback.'}`
      : status.diagnostic;
    output('navigation-detail', detail);
  } catch (error) {
    candidate.samples.status = null;
    output('adapter-status', error.message, 'error');
    emergency(candidate, 'Invalid adapter feedback; control stopped', true);
  }
  refresh();
}

function publish(candidate, topic, type, message) {
  requireValue(current(candidate) && candidate.client.connected, 'No connected session; no messages queued');
  return candidate.client.publish(candidate.config.topics[topic], type, message);
}

function releasePointer() {
  clearInterval(holdTimer);
  holdTimer = null;
  const previous = pointer;
  pointer = null;
  manualVector = { linear: 0, angular: 0 };
  element('joystick-knob').style.transform = '';
  if (previous !== null && element('joystick').hasPointerCapture(previous)) {
    try { element('joystick').releasePointerCapture(previous); } catch (error) { output('manual-status', error.message, 'error'); }
  }
}

function emergency(candidate, reason, cancel) {
  if (stopping) return;
  stopping = true;
  releasePointer();
  if (navigation) {
    navigation.uncertain = true;
    navigation.state = 'unknown';
    storeNavigation();
  }
  const failures = [];
  if (candidate && current(candidate) && candidate.client.connected) {
    try { publish(candidate, 'manual', twistType, zeroTwist()); } catch (error) { failures.push(`Zero delivery uncertain: ${error.message}`); }
    if (cancel) {
      try { publish(candidate, 'cancel', 'std_msgs/msg/Empty', {}); } catch (error) { failures.push(`Cancel delivery uncertain: ${error.message}`); }
    }
  } else {
    failures.push('Transport unavailable; zero/cancel delivery is not guaranteed. Adapter watchdog is a separate safeguard.');
  }
  output('manual-status', 'Hold released; zero requested', 'unavailable');
  output('application-status', `${reason}${failures.length ? ` ${failures.join(' ')}` : ' Zero/cancel requests do not confirm robot stop.'}`, failures.length ? 'error' : 'unavailable');
  stopping = false;
}

function failSession(candidate, error) {
  if (!current(candidate)) return;
  candidate.fault = true;
  emergency(candidate, error.message, true);
  output('application-status', error.message, 'error');
  refresh();
}

function attachRenderers(candidate) {
  const options = statusElement => ({
    mapFrame: candidate.config.frames.map,
    onStatus: (text, state) => { if (current(candidate)) output(statusElement, text, state); },
    onError: error => failSession(candidate, error)
  });
  candidate.map = new MapRenderer(element('map-canvas'), options('map-status'));
  candidate.camera = new CameraRenderer(element('camera-canvas'), options('camera-status'));
  candidate.robot = new RobotRenderer(element('robot-canvas'), options('model-status'));
  candidate.robot.ready.catch(error => { if (current(candidate)) failSession(candidate, error); });
  if (typeof ResizeObserver === 'function') {
    candidate.viewObserver = new ResizeObserver(() => {
      if (current(candidate)) {
        try { updateWorldView(candidate); } catch (error) { failSession(candidate, error); }
      }
    });
    candidate.viewObserver.observe(element('robot-canvas'));
  }
}

function subscribeAll(candidate) {
  const subscribe = (key, type, callback, options = {}) => {
    candidate.disposers.push(candidate.client.subscribe(candidate.config.topics[key], type, message => {
      if (current(candidate)) callback(message);
    }, { queue_length: 1, ...options }));
  };
  const mapOptions = candidate.config.transient ? { qos: { durability: 'transient_local', reliability: 'reliable', depth: 1 } } : {};
  subscribe('map', 'nav_msgs/msg/OccupancyGrid', message => receiveMap(candidate, message), mapOptions);
  subscribe('status', 'std_msgs/msg/String', message => receiveStatus(candidate, message));
  // Coach support: use measured joint angles from the same simulated robot.
  candidate.disposers.push(candidate.client.subscribe('/fastbot/joint_states', 'sensor_msgs/msg/JointState',
    message => { if (current(candidate)) candidate.robot.updateJointState(message); },
    { queue_length: 1, throttle_rate: 100 }));
  subscribe('odom', 'nav_msgs/msg/Odometry', message => receiveLive(candidate, 'odom', message, incoming => {
    requireValue(incoming.header.frame_id === candidate.config.frames.odom && incoming.child_frame_id === candidate.config.frames.base, 'Odometry frame mismatch');
    const measured = incoming.twist?.twist;
    requireValue([measured?.linear?.x, measured?.linear?.y, measured?.linear?.z, measured?.angular?.x, measured?.angular?.y, measured?.angular?.z].every(finite), 'Invalid measured odometry twist');
  }));
  subscribe('pose', poseType, message => receiveLive(candidate, 'pose', message, incoming => {
    requireValue(incoming.header.frame_id === candidate.config.frames.map, 'Measured pose is not in configured map frame');
    validatePose(incoming.pose);
  }));
  subscribe('camera', candidate.config.topics.camera.endsWith('/compressed') ? 'sensor_msgs/msg/CompressedImage' : 'sensor_msgs/msg/Image', message => receiveLive(candidate, 'camera', message, incoming => {
    requireValue(typeof incoming.header.frame_id === 'string' && (incoming.header.frame_id === '' || framePattern.test(incoming.header.frame_id)), 'Camera source frame must be empty or valid');
    requireValue(candidate.cameraFrame === null || incoming.header.frame_id === candidate.cameraFrame, 'Camera source frame changed; disconnect and check camera settings');
  }, incoming => {
    candidate.cameraFrame = incoming.header.frame_id;
    return incoming.format ? candidate.camera.updateCompressed(incoming) : candidate.camera.updateImage(incoming);
  }), { throttle_rate: candidate.config.throttle });
}

async function connect() {
  if (session) return;
  let candidate;
  try {
    const config = configuration();
    candidate = {
      config, generation: ++generation, client: new RosbridgeClient(), disposers: [],
      samples: { odom: null, pose: null, camera: null, status: null }, stamps: {},
      validated: new Set(), mapId: null, worldView: null, poseShown: false,
      fault: false, blocked: false, endpoint: null, cameraFrame: null, commandAck: 0, commandProbe: identifier()
    };
    session = candidate;
    attachRenderers(candidate);
    candidate.disposers.push(candidate.client.on('connection', notification => {
      if (!current(candidate)) return;
      output('connection-status', notification.state, notification.state);
      if (notification.state === 'disconnected') disconnectSession(candidate, false);
      refresh();
    }));
    candidate.disposers.push(candidate.client.on('error', notification => {
      if (current(candidate)) failSession(candidate, new Error(`ROSbridge error: ${notification.message}. Check the connection and configured topics.`));
    }));
    candidate.disposers.push(candidate.client.on('status', notification => {
      if (current(candidate)) output('application-status', `ROSbridge ${notification.level ?? 'status'}: ${String(notification.msg ?? '')}. Check map delivery if the map is unavailable.`, notification.level === 'warning' ? 'stale' : '');
    }));
    refresh();
    await candidate.client.connect(config.endpoint);
    if (!current(candidate)) return;
    candidate.endpoint = candidate.client.url;
    // Create volatile command publishers before live subscriptions/readiness.
    // Advertising at the first Go click can lose that first command while DDS
    // discovers the adapter subscription. Never latch or replay motion commands.
    for (const [key, type] of [['manual', twistType], ['goal', poseType],
      ['cancel', 'std_msgs/msg/Empty'], ['initialpose', 'geometry_msgs/msg/PoseWithCovarianceStamped']]) {
      candidate.client.advertise(candidate.config.topics[key], type);
    }
    candidate.client.advertise('/fastbot_web/control_ping', 'std_msgs/msg/String');
    candidate.disposers.push(candidate.client.subscribe('/fastbot_web/control_pong', 'std_msgs/msg/String', message => {
      if (current(candidate) && message.data === candidate.commandProbe) {
        candidate.commandAck = performance.now();
        refresh();
      }
    }));
    const ping = () => {
      if (current(candidate) && candidate.client.connected) {
        try { candidate.client.publish('/fastbot_web/control_ping', 'std_msgs/msg/String', { data: candidate.commandProbe }); }
        catch (error) { output('command-status', error.message, 'error'); }
      }
    };
    const pingTimer = setInterval(ping, 1000);
    candidate.disposers.push(() => clearInterval(pingTimer));
    ping(); // Only the idempotent non-motion health probe retries; goals never replay.
    subscribeAll(candidate);
    output('application-status', 'Connected to CP23 simulation. Live feedback enables controls; hold to drive and release to stop.');
  } catch (error) {
    if (candidate && current(candidate)) {
      emergency(candidate, error.message, true);
      disconnectSession(candidate, true);
    }
    output('application-status', error.message, 'error');
  }
  refresh();
}

function disconnectSession(candidate, explicit) {
  if (!current(candidate)) return;
  emergency(candidate, explicit ? 'Explicit disconnect' : 'Connection lost; navigation outcome may be unknown', true);
  generation += 1;
  session = null;
  candidate.viewObserver?.disconnect();
  for (const dispose of candidate.disposers.splice(0)) {
    try { dispose(); } catch (error) { output('application-status', error.message, 'error'); }
  }
  candidate.client.disconnect();
  for (const renderer of [candidate.map, candidate.camera, candidate.robot]) {
    try { renderer?.dispose(); } catch (error) { output('application-status', error.message, 'error'); }
  }
  candidate.samples = {};
  candidate.stamps = {};
  candidate.mapId = null;
  candidate.validated.clear();
  output('connection-status', 'Disconnected', 'disconnected');
  output('map-status', 'No map received');
  output('camera-status', 'No image received');
  output('model-status', 'Disconnected; model hidden');
  output('adapter-status', 'Adapter unavailable');
  element('initialpose-confirm').checked = false;
  renderWaypoints();
  refresh();
}

function freshRequestStamp() {
  const milliseconds = Math.max(Date.now(), lastStamp + 1);
  lastStamp = milliseconds;
  const sec = Math.floor(milliseconds / 1000);
  requireValue(sec <= 2147483647, 'Request stamp exceeds ROS signed seconds range');
  return { sec, nanosec: (milliseconds % 1000) * 1000000 };
}

function planarPose(x, y, yaw) {
  return { position: { x, y, z: 0 }, orientation: { x: 0, y: 0, z: Math.sin(yaw / 2), w: Math.cos(yaw / 2) } };
}

function sendWaypoint(waypoint) {
  const candidate = session;
  requireValue(navigationReady(candidate), 'Navigation requires fresh localized idle feedback, persistence and an actual map');
  requireValue(candidate.validated.has(waypoint.id) && waypoint.mapId === candidate.mapId
    && waypoint.frame === candidate.config.frames.map, 'Waypoint map mismatch; edit and save against the current map');
  const stamp = freshRequestStamp();
  navigation = {
    id: `${stamp.sec}:${stamp.nanosec}`, name: waypoint.name, endpoint: candidate.endpoint,
    mapId: candidate.mapId, state: 'submitted', uncertain: true, submitted: Date.now(), started: performance.now()
  };
  requireValue(storeNavigation(), 'Navigation reservation could not be persisted; goal was not sent');
  refresh();
  releasePointer();
  try {
    publish(candidate, 'manual', twistType, zeroTwist());
    requireValue(idle(candidate) && poseReady(candidate), 'Readiness lost before submission; outcome requires reconciliation');
    publish(candidate, 'goal', poseType, { header: { stamp, frame_id: waypoint.frame }, pose: planarPose(waypoint.x, waypoint.y, waypoint.yaw) });
    output('navigation-status', `${waypoint.name}: submitted; awaiting adapter acceptance`, 'unavailable');
  } catch (error) {
    emergency(candidate, `Goal delivery uncertain: ${error.message}`, true);
    throw error;
  }
  refresh();
}

function cancelOrReconcile() {
  const candidate = session;
  requireValue(candidate?.client.connected, 'Reconnect explicitly before cancellation or reconciliation');
  if (navigation && navigation.uncertain && idle(candidate)) {
    const status = candidate.samples.status.value;
    requireValue(status.owner === null && status.manual_released && status.manual_allowed, 'Fresh authoritative idle/released status is required');
    requireValue(navigation.endpoint === candidate.endpoint, 'Reconnect to the original pending request endpoint before reconciliation');
    if (!globalThis.confirm('Fresh adapter status reports idle and released. Confirm you inspected this robot/session, there is no active navigation ownership, and you accept the previous outcome as UNKNOWN. This does not establish arrival or confirmed cancellation.')) return;
    navigation = null;
    storeNavigation();
    output('navigation-status', 'Operator reconciled idle; previous navigation outcome UNKNOWN', 'unavailable');
  } else {
    emergency(candidate, 'Stop/cancel requested; waiting for matching terminal confirmation', true);
  }
  refresh();
}

function syncWaypointValidity() {
  if (!session) return;
  session.validated.clear();
  if (!waypointStoreReady) return;
  for (const p of waypoints) if (p.mapId === session.mapId && p.frame === session.config.frames.map) session.validated.add(p.id);
}

function acceptProjectPoints(document) {
  requireValue(document?.version === 1 && Number.isSafeInteger(document.revision) && Array.isArray(document.waypoints), 'Invalid project waypoint document');
  const points = document.waypoints.map(p => ({ ...p, endpoint: null }));
  requireValue(points.length <= 100 && points.every(validWaypoint), 'Invalid project waypoint data');
  waypointRevision = document.revision;
  waypoints = points;
  waypointStoreReady = true;
  saveWaypoints(); // Browser copy is a cache; server acknowledgement establishes persistence.
  syncWaypointValidity();
  renderWaypoints();
}

async function waypointApi(method = 'GET', points) {
  const response = await fetch('./api/waypoints', {
    method, cache: 'no-store', signal: AbortSignal.timeout(6000),
    ...(method === 'PUT' ? { headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ revision: waypointRevision, waypoints: points }) } : {})
  });
  const data = await response.json();
  if (response.status === 409 && data.current) acceptProjectPoints(data.current);
  requireValue(response.ok, data.error ?? 'Project waypoint storage unavailable; start the site with python3 server.py 7000');
  return data;
}

async function loadProjectWaypoints() {
  waypointStoreReady = false;
  waypointSaving = true;
  refresh();
  try {
    const legacy = [...waypoints];
    acceptProjectPoints(await waypointApi());
    // Import browser-only points once into a new project. Later, the project is authoritative,
    // so a stale browser cache must never resurrect a point deleted elsewhere.
    const additions = waypointRevision === 0 ? legacy.filter(p => p.mapId && !waypoints.some(q => q.id === p.id || q.name === p.name)) : [];
    if (additions.length) {
      localStorage.setItem(`${waypointStorage}.migration-backup`, JSON.stringify(legacy));
      acceptProjectPoints(await waypointApi('PUT', [...waypoints, ...additions]));
    }
    output('waypoint-status', 'Waypoints saved in the project; ready on the same map', 'fresh');
  } catch (error) {
    waypointStoreReady = false;
    output('waypoint-status', `Project waypoints unavailable: ${error.message}`, 'error');
  } finally {
    waypointSaving = false;
    renderWaypoints(); refresh();
  }
}

function newWaypoint() {
  requireValue(waypointStoreReady && !navigation && pointer === null, 'Load project waypoints and finish the current control request first');
  selected = null;
  for (const key of ['name', 'x', 'y', 'yaw']) element(`waypoint-${key}`).value = '';
  element('waypoint-frame').value = session?.config.frames.map ?? 'map';
  output('waypoint-editor-status', 'Enter map coordinates or choose Use current robot pose');
  element('waypoint-dialog-title').textContent = 'Add waypoint';
  element('waypoint-dialog').showModal();
  element('waypoint-name').focus();
  refresh();
}

function selectWaypoint(waypoint) {
  selected = waypoint.id;
  for (const key of ['name', 'x', 'y', 'yaw', 'frame']) element(`waypoint-${key}`).value = waypoint[key];
  element('waypoint-dialog-title').textContent = `Edit waypoint: ${waypoint.name}`;
  output('waypoint-editor-status', 'Save your changes. Saving does not move the robot.');
  element('waypoint-dialog').showModal();
  refresh();
}

function renderWaypoints() {
  syncWaypointValidity();
  const container = element('waypoint-list');
  container.replaceChildren();
  if (!waypoints.length) {
    const empty = document.createElement('p');
    empty.textContent = 'No waypoints saved. Choose + Add waypoint to create one.';
    container.append(empty);
  }
  for (const waypoint of waypoints) {
    const card = document.createElement('article'); card.className = 'waypoint-card';
    const info = document.createElement('div'); info.className = 'waypoint-info';
    const name = document.createElement('strong'); name.textContent = waypoint.name;
    const detail = document.createElement('small'); detail.textContent = `X ${waypoint.x.toFixed(3)} · Y ${waypoint.y.toFixed(3)} · Yaw ${waypoint.yaw.toFixed(3)} rad`;
    const status = document.createElement('small'); status.dataset.pointStatus = waypoint.id;
    info.append(name, detail, status);
    const actions = document.createElement('div'); actions.className = 'waypoint-actions';
    const go = document.createElement('button'); go.type = 'button'; go.textContent = 'Go'; go.dataset.destination = waypoint.id;
    go.setAttribute('aria-label', `Go ${waypoint.name}`); go.addEventListener('click', guarded(() => sendWaypoint(waypoint)));
    const edit = document.createElement('button'); edit.type = 'button'; edit.textContent = 'Edit'; edit.setAttribute('aria-label', `Edit ${waypoint.name}`); edit.addEventListener('click', guarded(() => selectWaypoint(waypoint)));
    const remove = document.createElement('button'); remove.type = 'button'; remove.textContent = 'Delete'; remove.setAttribute('aria-label', `Delete ${waypoint.name}`); remove.addEventListener('click', guarded(() => deleteWaypoint(waypoint)));
    actions.append(go, edit, remove); card.append(info, actions); container.append(card);
  }
}

async function saveWaypoint() {
  requireValue(waypointStoreReady && !waypointSaving && !navigation && pointer === null, 'Load project waypoints and finish the current control request first');
  const existing = waypoints.find(p => p.id === selected);
  const frame = element('waypoint-frame').value.trim();
  const name = element('waypoint-name').value.trim();
  requireValue(name.length > 0 && name.length <= 48, 'Waypoint name must contain 1-48 characters');
  requireValue(!waypoints.some(p => p.name === name && p.id !== selected), 'Choose a unique waypoint name');
  const mapId = session?.mapId ?? existing?.mapId;
  requireValue(mapId && frame === (session?.config.frames.map ?? existing?.frame), 'Connect and load the current map first');
  const point = { id: selected ?? identifier(), name, frame, mapId, endpoint: null,
    x: numberInput('waypoint-x'), y: numberInput('waypoint-y'), yaw: numberInput('waypoint-yaw') };
  const next = existing ? waypoints.map(p => p.id === point.id ? point : p) : [...waypoints, point];
  waypointSaving = true; refresh();
  try {
    acceptProjectPoints(await waypointApi('PUT', next));
    element('waypoint-dialog').close(); selected = null;
    output('waypoint-status', `${name} saved in the project; it will load next time`, 'fresh');
  } finally { waypointSaving = false; refresh(); }
}

function capturePose() {
  requireValue(poseReady() && !navigation && pointer === null, 'A fresh map pose and no active control request are required');
  const pose = session.samples.pose.value.pose;
  element('waypoint-x').value = pose.position.x;
  element('waypoint-y').value = pose.position.y;
  element('waypoint-yaw').value = yawOf(pose.orientation);
  element('waypoint-frame').value = session.config.frames.map;
  output('waypoint-editor-status', 'Current pose captured. Name retained; choose Save waypoint to persist it.');
}

async function deleteWaypoint(waypoint) {
  requireValue(waypointStoreReady && !waypointSaving && !navigation && pointer === null, 'Waypoints cannot be changed during the current request');
  if (!globalThis.confirm(`Delete waypoint "${waypoint.name}"?`)) return;
  waypointSaving = true; refresh();
  try {
    acceptProjectPoints(await waypointApi('PUT', waypoints.filter(p => p.id !== waypoint.id)));
    if (selected === waypoint.id) selected = null;
    output('waypoint-status', `${waypoint.name} deleted from the project`, 'fresh');
  } finally { waypointSaving = false; refresh(); }
}

function sendInitialpose() {
  const candidate = session;
  requireValue(initialposeReady(candidate) && element('initialpose-confirm').checked, 'Confirm an observed pose with fresh idle/released adapter feedback and measured stop');
  const positionX = numberInput('initialpose-x');
  const positionY = numberInput('initialpose-y');
  const yaw = numberInput('initialpose-yaw');
  const covariance = new Array(36).fill(0);
  covariance[0] = numberInput('initialpose-var-x', 0);
  covariance[7] = numberInput('initialpose-var-y', 0);
  covariance[35] = numberInput('initialpose-var-yaw', 0);
  releasePointer();
  publish(candidate, 'manual', twistType, zeroTwist());
  publish(candidate, 'initialpose', 'geometry_msgs/msg/PoseWithCovarianceStamped', {
    header: { stamp: { sec: 0, nanosec: 0 }, frame_id: candidate.config.frames.map },
    pose: { pose: planarPose(positionX, positionY, yaw), covariance }
  });
  candidate.samples.pose = null;
  candidate.validated.clear();
  hidePose(candidate);
  element('initialpose-confirm').checked = false;
  output('initialpose-status', 'Initial pose sent. Waiting for fresh localization feedback.', 'unavailable');
  output('waypoint-status', 'Waiting for localization; matching-map waypoints will be ready automatically');
}

function pointerVector(event) {
  const rectangle = element('joystick').getBoundingClientRect();
  const radius = Math.max(1, Math.min(rectangle.width, rectangle.height) / 2 - 20);
  let horizontal = (event.clientX - rectangle.left - rectangle.width / 2) / radius;
  let vertical = (event.clientY - rectangle.top - rectangle.height / 2) / radius;
  const length = Math.max(1, Math.hypot(horizontal, vertical));
  horizontal /= length;
  vertical /= length;
  manualVector = { linear: Math.max(-0.05, Math.min(0.05, -vertical * 0.05)), angular: Math.max(-0.30, Math.min(0.30, -horizontal * 0.30)) };
  element('joystick-knob').style.transform = `translate(${horizontal * radius}px, ${vertical * radius}px)`;
}

function manualTick() {
  const candidate = session;
  if (pointer === null) return;
  if (!manualReady(candidate)) {
    emergency(candidate, 'Required manual feedback lost; hold will not resume automatically', true);
    refresh();
    return;
  }
  try {
    const command = zeroTwist();
    command.linear.x = manualVector.linear;
    command.angular.z = manualVector.angular;
    publish(candidate, 'manual', twistType, command);
    output('manual-status', 'Holding · bounded adapter input at 10 Hz', 'fresh');
  } catch (error) {
    failSession(candidate, error);
  }
}

function guarded(action) {
  return async event => {
    try { await action(event); }
    catch (error) {
      output('application-status', error.message, 'error');
      if (element('waypoint-dialog').open) output('waypoint-editor-status', error.message, 'error');
      else output('waypoint-status', error.message, 'error');
    }
    refresh();
  };
}

function refresh() {
  syncWaypointValidity();
  const candidate = session;
  const connected = Boolean(candidate?.client.connected);
  element('connect').disabled = candidate !== null;
  element('disconnect').disabled = candidate === null;
  element('rosbridge-url').disabled = candidate !== null;
  element('topic-settings').disabled = candidate !== null;
  element('joystick').disabled = !manualReady(candidate);
  if (pointer === null) output('manual-status',
    !connected ? 'Disconnected' : manualReady(candidate) ? 'Ready · hold to drive'
      : navigation ? 'Navigation active' : 'Waiting for live feedback',
    manualReady(candidate) ? 'fresh' : 'unavailable');
  element('stop').disabled = !connected;
  element('cancel-goal').disabled = !connected;
  element('cancel-goal').textContent = navigation?.uncertain && idle(candidate) ? 'Reconcile idle' : 'Cancel goal';
  element('initialpose-send').disabled = !initialposeReady(candidate) || !element('initialpose-confirm').checked;
  element('waypoint-capture').disabled = !poseReady(candidate) || Boolean(navigation) || pointer !== null;
  element('waypoint-save').disabled = !waypointStoreReady || waypointSaving || Boolean(navigation) || pointer !== null;
  element('waypoint-add').disabled = !waypointStoreReady || waypointSaving || Boolean(navigation) || pointer !== null;
  element('waypoint-reload').disabled = waypointSaving || Boolean(navigation) || pointer !== null;
  for (const key of ['name', 'x', 'y', 'yaw', 'frame']) element(`waypoint-${key}`).disabled = Boolean(navigation) || pointer !== null;
  for (const button of element('waypoint-list').querySelectorAll('button')) {
    if (button.dataset.destination) button.disabled = !navigationReady(candidate) || !candidate.validated.has(button.dataset.destination);
    else button.disabled = !waypointStoreReady || waypointSaving || Boolean(navigation) || pointer !== null;
  }
  for (const label of element('waypoint-list').querySelectorAll('[data-point-status]')) {
    const point = waypoints.find(p => p.id === label.dataset.pointStatus);
    const matched = candidate?.mapId && point?.mapId === candidate.mapId && point?.frame === candidate.config.frames.map;
    const reason = !waypointStoreReady ? 'Project waypoints not loaded' : !candidate?.mapId ? 'Waiting for a map connection' : !matched ? 'Map mismatch; edit and save to confirm' : !commandReady(candidate) ? 'Waiting for verified command delivery' : !navigationReady(candidate) ? 'Map matches; waiting for localization or the current task to finish' : 'Map matches; ready to go';
    label.textContent = reason;
    const button = label.closest('.waypoint-card').querySelector('[data-destination]');
    button.title = reason;
  }
  if (connected && !navigation && element('navigation-status').textContent.startsWith('Disconnected')) output('navigation-status', 'No task started from this page');
  output('command-status', !connected ? 'Disconnected' : commandReady(candidate)
    ? 'Command channel verified' : 'Commands unverified; restart Rosbridge if this persists',
    commandReady(candidate) ? 'fresh' : 'stale');
  const odometryFresh = fresh(candidate, 'odom');
  const localized = poseReady(candidate);
  output('odom-status', odometryFresh ? 'fresh measured data' : 'unavailable / stale', odometryFresh ? 'fresh' : 'stale');
  output('pose-status', localized ? 'fresh actual map TF' : 'unavailable / stale', localized ? 'fresh' : 'stale');
  if (odometryFresh) {
    const measured = candidate.samples.odom.value.twist.twist;
    output('linear-speed', measured.linear.x.toFixed(3));
    output('angular-speed', measured.angular.z.toFixed(3));
  } else {
    output('linear-speed', '—');
    output('angular-speed', '—');
  }
  if (localized) {
    const pose = candidate.samples.pose.value;
    output('robot-position', `${pose.pose.position.x.toFixed(3)}, ${pose.pose.position.y.toFixed(3)}`);
    output('robot-orientation', yawOf(pose.pose.orientation).toFixed(3));
    try {
      candidate.map?.updatePose(pose);
      candidate.robot?.updatePose(pose);
      candidate.poseShown = true;
    } catch (error) {
      candidate.fault = true;
      emergency(candidate, error.message, true);
    }
  } else {
    const sample = connected && candidate.samples.pose;
    if (sample && candidate.poseShown && !candidate.fault) {
      const age = ((performance.now() - sample.received) / 1000).toFixed(1);
      output('robot-position', `${sample.value.pose.position.x.toFixed(3)}, ${sample.value.pose.position.y.toFixed(3)} (last measured)`);
      output('robot-orientation', `${yawOf(sample.value.pose.orientation).toFixed(3)} (last measured)`);
      output('model-status', `Last measured pose · STALE · ${age}s since receipt`, 'stale');
    } else {
      output('robot-position', 'Unavailable');
      output('robot-orientation', 'Unavailable');
      if (candidate?.poseShown) hidePose(candidate);
    }
  }
  output('telemetry-status', odometryFresh && localized ? 'Measured · fresh' : 'Partial / unavailable', odometryFresh && localized ? 'fresh' : 'stale');
  if (candidate && !fresh(candidate, 'camera') && candidate.samples.camera) {
    const age = ((performance.now() - candidate.samples.camera.received) / 1000).toFixed(1);
    output('camera-status', `Last received image · STALE · ${age}s`, 'stale');
  }
  if (candidate && !fresh(candidate, 'status')) output('adapter-status', 'Adapter status unavailable / stale', 'stale');
  if (navigation) {
    output('navigation-status', `${navigation.name ?? 'Previous request'}: ${navigation.uncertain ? 'UNKNOWN outcome — lock retained' : navigation.paused ? 'paused — waiting for feedback' : navigation.state}`, 'unavailable');
  } else if (!connected) {
    output('navigation-status', 'Disconnected — no current browser request');
  }
  if (storageDiagnostic) output('application-status', storageDiagnostic, 'error');
}

function lossOfControl(reason) {
  const candidate = session;
  if (!candidate) return;
  candidate.blocked = true;
  if (navigation || pointer !== null) emergency(candidate, reason, Boolean(navigation));
  else output('application-status', `${reason}; manual input blocked. No navigation owned by this page.`, 'unavailable');
  refresh();
}

readStorage();
renderWaypoints();
void loadProjectWaypoints();
element('connect').addEventListener('click', () => { void connect(); });
element('disconnect').addEventListener('click', () => { if (session) disconnectSession(session, true); });
element('stop').addEventListener('click', () => {
  emergency(session, 'Explicit Stop: zero and navigation cancellation requested', true);
  refresh();
});
element('cancel-goal').addEventListener('click', guarded(cancelOrReconcile));
element('waypoint-save').addEventListener('click', guarded(saveWaypoint));
element('waypoint-capture').addEventListener('click', guarded(capturePose));
element('waypoint-add').addEventListener('click', guarded(newWaypoint));
element('waypoint-reload').addEventListener('click', guarded(loadProjectWaypoints));
element('waypoint-close').addEventListener('click', () => element('waypoint-dialog').close());
element('initialpose-send').addEventListener('click', guarded(sendInitialpose));
element('initialpose-confirm').addEventListener('change', refresh);
for (const key of ['x', 'y', 'yaw', 'var-x', 'var-y', 'var-yaw']) {
  element(`initialpose-${key}`).addEventListener('input', () => {
    element('initialpose-confirm').checked = false;
    refresh();
  });
}
element('joystick').addEventListener('pointerdown', guarded(event => {
  requireValue(event.isPrimary && event.button === 0 && pointer === null && manualReady(), 'Manual hold is not available');
  event.preventDefault();
  pointer = event.pointerId;
  try {
    element('joystick').setPointerCapture(pointer);
    pointerVector(event);
    holdTimer = setInterval(manualTick, 100);
    manualTick();
  } catch (error) {
    emergency(session, error.message, true);
    throw error;
  }
}));
element('joystick').addEventListener('pointermove', event => {
  if (pointer !== event.pointerId) return;
  event.preventDefault();
  pointerVector(event);
});
for (const eventName of ['pointerup', 'pointercancel', 'lostpointercapture']) {
  element('joystick').addEventListener(eventName, event => {
    if (pointer !== event.pointerId) return;
    emergency(session, 'Joystick released', false);
    refresh();
  });
}
element('joystick').addEventListener('contextmenu', event => event.preventDefault());
globalThis.addEventListener('blur', () => lossOfControl('Window focus lost; zero/cancel requested'));
globalThis.addEventListener('focus', () => {
  if (session && !document.hidden) session.blocked = false;
  refresh();
});
document.addEventListener('visibilitychange', () => {
  if (document.hidden) lossOfControl('Page hidden; zero/cancel requested');
  else {
    if (session) session.blocked = false;
    refresh();
  }
});
for (const eventName of ['pagehide', 'beforeunload']) {
  globalThis.addEventListener(eventName, () => {
    if (session) disconnectSession(session, true);
  });
}
globalThis.addEventListener('error', event => { if (session) failSession(session, new Error(event.message || 'Unhandled application error')); });
globalThis.addEventListener('unhandledrejection', event => {
  if (session) failSession(session, new Error(String(event.reason?.message ?? event.reason)));
});
globalThis.addEventListener('storage', event => {
  if (![waypointStorage, navigationStorage, null].includes(event.key)) return;
  if (session) lossOfControl('Another browser context changed shared control storage; disconnect and inspect ownership');
  storageHealthy = false;
  storageDiagnostic = 'Shared browser control storage changed externally. Reload only after inspecting robot ownership; do not run competing dashboard tabs.';
  refresh();
});
setInterval(() => {
  const candidate = session;
  if (candidate) {
    if (pointer !== null && !manualReady(candidate)) emergency(candidate, 'Manual feedback stale; hold canceled', true);
    if (navigation && fresh(candidate, 'status') === false && !navigation.uncertain) emergency(candidate, 'Adapter status stale; navigation outcome unknown', true);
    if (navigation && navigation.endpoint === candidate.endpoint && navigation.started !== undefined
      && performance.now() - navigation.started > 15000 && ['submitted', 'awaiting_acceptance', 'cancel_requested'].includes(navigation.state)) {
      emergency(candidate, 'Acceptance/cancellation timeout; inspect authoritative ownership, never replay', true);
    }
  }
  refresh();
}, 100);
refresh();
