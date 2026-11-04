import assert from 'node:assert/strict';
import fs from 'node:fs';
const code = fs.readFileSync(
  new URL('../simulation/webapp/fastbot_webapp/rosbridge.js', import.meta.url),
  'utf8'
);
const { RosbridgeClient } = await import(
  'data:text/javascript;base64,' + Buffer.from(code).toString('base64')
);
function fixture(limit = 4096) {
  const client = new RosbridgeClient({ maxMessageBytes: limit });
  const values = [],
    errors = [];
  client.subscriptions.set('sub', {
    id: 'sub',
    topic: '/image',
    callback: (value) => values.push(value)
  });
  client.on('error', (error) => errors.push(error.message));
  return { client, values, errors };
}
const payload = JSON.stringify({ op: 'publish', topic: '/image', msg: { data: 'camera sample' } });
const parts = [payload.slice(0, 20), payload.slice(20, 50), payload.slice(50)];
const a = fixture();
for (const num of [2, 0, 0, 1])
  a.client.receive(
    JSON.stringify({ op: 'fragment', id: 'image1', total: 3, num, data: parts[num] })
  );
assert.deepEqual(a.values, [{ data: 'camera sample' }]);
assert.equal(a.client.fragments.size, 0);
assert.deepEqual(a.errors, []);
const b = fixture();
b.client.receive(JSON.stringify({ op: 'fragment', id: 'image2', total: 2, num: 0, data: 'first' }));
b.client.receive(
  JSON.stringify({ op: 'fragment', id: 'image2', total: 2, num: 0, data: 'changed' })
);
assert.match(b.errors[0], /Conflicting duplicate/);
assert.equal(b.values.length, 0);
assert.equal(b.client.fragments.size, 0);
const c = fixture(256);
for (const num of [0, 1])
  c.client.receive(
    JSON.stringify({ op: 'fragment', id: 'oversized', total: 2, num, data: 'x'.repeat(180) })
  );
assert.ok(c.errors.some((value) => /size limit/.test(value)));
assert.equal(c.values.length, 0);
const d = fixture();
d.client.receive(JSON.stringify({ op: 'fragment', id: 'expired', total: 2, num: 0, data: 'old' }));
d.client.fragments.get('expired').started -= 6000;
d.client.receive(JSON.stringify({ op: 'fragment', id: 'new', total: 2, num: 0, data: 'new' }));
assert.equal(d.client.fragments.has('expired'), false);
console.log(
  'PASS: out-of-order assembly, identical duplicate, conflicting duplicate, size bound, expiry'
);

const dropped = fixture();
for (let index = 0; index < 12; index++) {
  dropped.client.receive(
    JSON.stringify({ op: 'fragment', id: 'dropped-' + index, total: 2, num: 0, data: 'partial' })
  );
}
assert.equal(dropped.client.fragments.size, 8);
assert.deepEqual(dropped.errors, []);
console.log('PASS: incomplete camera frames are evicted without closing telemetry');
