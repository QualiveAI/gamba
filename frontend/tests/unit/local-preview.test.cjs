'use strict';

const test = require('node:test');
const assert = require('node:assert/strict');
const preview = require('../../js/local-preview.js');

const local = pathname => ({ hostname: 'localhost', pathname });
const publicLocation = { hostname: 'windrop.example', pathname: '/preview.html' };
const request = (client, path, options) => client.request(path, options);
const post = body => ({ method: 'POST', body: JSON.stringify(body) });

async function shellRound(client, level, guess) {
  const start = await request(client, '/games/shell/start', post({ bet: 10, level, client_seed: `level-${level}` }));
  const result = await request(client, '/games/shell/pick', post({ session_id: start.session_id, guess }));
  return { start, result };
}

test('preview включается только на loopback preview.html', () => {
  assert.equal(preview.isEnabled(local('/preview.html')), true);
  assert.equal(preview.isEnabled({ hostname: '127.0.0.1', pathname: '/preview.html' }), true);
  assert.equal(preview.isEnabled({ hostname: '::1', pathname: '/preview.html' }), true);
  assert.equal(preview.isEnabled(local('/')), false);
  assert.equal(preview.isEnabled(publicLocation), false);
  assert.throws(() => preview.createClient({ location: publicLocation }), /loopback/);
});

test('preview работает как synthetic Telegram-auth session без transport', async () => {
  const client = preview.createClient({ location: local('/preview.html') });
  await client.authenticate();
  assert.equal(client.getContext(), 'local-preview:account:preview');
  assert.equal(client.getChannel(), 'web');
  assert.deepEqual(await request(client, '/wallet'), { units_minor: 5000, freebets_units: 1200 });
  const cases = await request(client, '/cases');
  assert.equal(cases.length, 14);
  assert.equal(cases.reduce((count, row) => count + row.rewards.length, 0), 210);
  assert.match(cases[0].cover, /^\/assets\/demo\/.*\.webp$/);
  assert.ok(cases.every(row => row.rewards.every(item => /\.webp$/.test(item.image))));
  assert.equal((await request(client, '/meta/payment-methods')).mode, 'disabled');
  assert.equal((await request(client, '/giftcards/catalog')).enabled, false);
});

test('preview Copos respects production levels and multiplier', async () => {
  const client = preview.createClient({ location: local('/preview.html') });
  const level1 = await shellRound(client, 1, 0);
  const level3 = await shellRound(client, 3, 0);
  const level5 = await shellRound(client, 5, 0);
  assert.deepEqual([level1.start.cups, level3.start.cups, level5.start.cups], [3, 4, 5]);
  assert.deepEqual([level1.start.mult, level3.start.mult, level5.start.mult], [2.7, 3.6, 4.5]);
  assert.equal(level1.start.ball, 0);
  assert.equal(level3.result.ball, level3.start.ball);
  assert.equal(level5.result.ball, level5.start.ball);
});

test('preview Copos has real losses and does not credit a wrong guess', async () => {
  const client = preview.createClient({ location: local('/preview.html') });
  const first = await shellRound(client, 1, 0);
  assert.equal(first.result.win, true);
  const before = await request(client, '/wallet');
  const secondStart = await request(client, '/games/shell/start', post({ bet: 10, level: 1, client_seed: 'loss' }));
  const wrongGuess = (secondStart.ball + 1) % secondStart.cups;
  const second = await request(client, '/games/shell/pick', post({ session_id: secondStart.session_id, guess: wrongGuess }));
  assert.equal(second.win, false);
  assert.equal(second.ball, secondStart.ball);
  assert.equal(second.payout, 0);
  assert.deepEqual(await request(client, '/wallet'), { units_minor: before.units_minor - 10, freebets_units: before.freebets_units });
});

test('preview upgrade mutates inventory without changing wallet and supports loss', async () => {
  const client = preview.createClient({ location: local('/preview.html') });
  const before = await request(client, '/wallet');
  const inventory = await request(client, '/inventory');
  const source = inventory[0];
  const success = await request(client, `/inventory/${source.id}/upgrade`, post({
    target_value: source.value_coins + 100, target_label: 'Meta test', target_image: '/assets/demo/robux100.webp', target_rarity: 'normal',
  }));
  assert.equal(success.success, true);
  assert.equal((await request(client, '/wallet')).units_minor, before.units_minor);
  assert.equal((await request(client, '/inventory'))[0].label, 'Meta test');
  const upgraded = (await request(client, '/inventory'))[0];
  const loss = await request(client, `/inventory/${upgraded.id}/upgrade`, post({
    target_value: upgraded.value_coins + 100, target_label: 'Loss target', target_image: '/assets/demo/robux150.webp', target_rarity: 'epic',
  }));
  assert.equal(loss.success, false);
  assert.equal((await request(client, '/wallet')).units_minor, before.units_minor);
  assert.equal((await request(client, '/inventory')).some(row => row.id === upgraded.id), false);
});

test('preview mines uses changing mine layouts per round', async () => {
  const client = preview.createClient({ location: local('/preview.html') });
  const findMine = async () => {
    const start = await request(client, '/games/mines/start', post({ bet: 10, mine_count: 3 }));
    for (let cell = 0; cell < 25; cell++) {
      const row = await request(client, '/games/mines/reveal', post({ session_id: start.session_id, cell }));
      if (row.hit_mine) return row.mines;
    }
    throw new Error('no mine found');
  };
  const first = await findMine();
  const second = await findMine();
  assert.ok(first.length === 3 && second.length === 3);
  assert.notDeepEqual(first, second);
});

test('preview Foguete start varies crash points and cashout is terminal/idempotent', async () => {
  const client = preview.createClient({ location: local('/preview.html') });
  const before = await request(client, '/wallet');
  const starts = [];
  for (let i = 0; i < 6; i++) starts.push(await request(client, '/games/crash/start', post({ bet: 50 })));
  assert.equal(new Set(starts.map(row => row.crash_point)).size > 1, true);
  const start = starts[0];
  assert.equal((await request(client, '/wallet')).units_minor, before.units_minor - 50 * starts.length);
  const win = await request(client, `/games/crash/cash?session_id=${start.session_id}`, { method: 'POST' });
  assert.equal(win.status, 'cashed');
  assert.equal(win.win, true);
  assert.equal(win.session_id, start.session_id);
  assert.ok(win.payout >= 50);
  const repeat = await request(client, `/games/crash/cash?session_id=${start.session_id}`, { method: 'POST' });
  assert.deepEqual(repeat, win);
  const status = await request(client, `/games/crash/status?session_id=${start.session_id}`);
  assert.equal(status.status, 'cashed');
  assert.equal(status.payout, win.payout);
});

test('preview game sessions are isolated per client', async () => {
  const a = preview.createClient({ location: local('/preview.html') });
  const b = preview.createClient({ location: local('/preview.html') });
  const start = post({ bet: 10, level: 1, client_seed: 'local' });
  assert.deepEqual(await request(a, '/games/shell/start', start), await request(b, '/games/shell/start', start));
  assert.deepEqual(await request(a, '/wallet'), await request(b, '/wallet'));
});
