const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { test } = require('node:test');

// Exercise the actual probe in Node, including failure propagation and cleanup.
for (const failure of ['none', 'launch', 'screenshot']) {
  test(`Chromium readiness: ${failure}`, (t) => {
    const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'exactdocs-probe-'));
    t.after(() => fs.rmSync(dir, { recursive: true, force: true }));
    const probe = path.join(dir, 'probe-chromium.cjs');
    fs.copyFileSync(path.join(__dirname, 'probe-chromium.cjs'), probe);
    const pkg = path.join(dir, 'node_modules', '@playwright', 'test');
    fs.mkdirSync(pkg, { recursive: true });
    fs.writeFileSync(path.join(pkg, 'index.js'), `
      const fs = require('node:fs');
      const event = (name) => fs.appendFileSync(process.env.PROBE_EVENTS, name + '\\n');
      module.exports.chromium = {
        async launch(options) {
          event('launch');
          if (options.timeout !== 10000) throw new Error('launch needs a deadline');
          if (process.env.PROBE_FAILURE === 'launch') throw new Error('launch failed');
          return {
            async newPage() {
              return {
                setDefaultTimeout() {},
                async setContent(html) {
                  if (!html.includes('ExactDocs browser readiness')) throw new Error('missing content');
                  event('render');
                },
                locator() { return { async innerText() { return 'ExactDocs browser readiness'; } }; },
                async screenshot() {
                  event('screenshot');
                  if (process.env.PROBE_FAILURE === 'screenshot') throw new Error('screenshot failed');
                }
              };
            },
            async close() { event('close'); }
          };
        }
      };
    `);
    const events = path.join(dir, 'events');
    const result = spawnSync(process.execPath, [probe], {
      env: { ...process.env, PROBE_FAILURE: failure, PROBE_EVENTS: events },
      encoding: 'utf8',
      timeout: 5000,
    });
    assert.equal(result.error, undefined);
    assert.equal(result.status === 0, failure === 'none', result.stderr);
    assert.deepEqual(fs.readFileSync(events, 'utf8').trim().split('\n'),
      failure === 'launch' ? ['launch'] : ['launch', 'render', 'screenshot', 'close']);
  });
}
