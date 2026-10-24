/**
 * OpenPost Sandboxed JavaScript Runtime for Postman Scripts (`pm.*`).
 *
 * Runs via Node.js stdio JSON IPC:
 * Input (JSON on stdin):
 * {
 *   "script": "string",
 *   "listen": "prerequest" | "test",
 *   "request": { "url": "...", "method": "...", "headers": {...}, "body": "..." },
 *   "response": { "status_code": 200, "status_text": "OK", "headers": {...}, "body_text": "...", "elapsed_ms": 15 },
 *   "environment": { "key": "value" },
 *   "collection_variables": { "key": "value" },
 *   "globals": { "key": "value" }
 * }
 *
 * Output (JSON on stdout):
 * {
 *   "ok": true,
 *   "test_results": [ { "name": "...", "passed": true|false, "error": null|"..." } ],
 *   "updated_environment": { ... },
 *   "updated_collection_variables": { ... },
 *   "logs": [ ... ]
 * }
 */

const fs = require('fs');

function runSandbox() {
  const inputRaw = fs.readFileSync(0, 'utf-8');
  let input;
  try {
    input = JSON.parse(inputRaw);
  } catch (err) {
    process.stdout.write(JSON.stringify({ ok: false, error: 'Invalid JSON input: ' + err.message }));
    process.exit(1);
  }

  const scriptCode = input.script || '';
  const listen = input.listen || 'test';
  const reqData = input.request || {};
  const respData = input.response || null;

  const env = { ...(input.environment || {}) };
  const colVars = { ...(input.collection_variables || {}) };
  const globals = { ...(input.globals || {}) };
  const logs = [];
  const testResults = [];

  // Chai-like expect implementation
  class Expectation {
    constructor(actual, isNegated = false) {
      this.actual = actual;
      this.isNegated = isNegated;
    }

    get to() { return this; }
    get be() { return this; }
    get have() { return this; }
    get not() { return new Expectation(this.actual, !this.isNegated); }

    _assert(passed, message) {
      const condition = this.isNegated ? !passed : passed;
      if (!condition) {
        throw new Error(message);
      }
    }

    equal(expected) {
      this._assert(this.actual === expected, `expected ${JSON.stringify(this.actual)} to equal ${JSON.stringify(expected)}`);
    }

    eql(expected) {
      const a = JSON.stringify(this.actual);
      const b = JSON.stringify(expected);
      this._assert(a === b, `expected ${a} to deeply equal ${b}`);
    }

    status(code) {
      const actualCode = respData ? respData.status_code : null;
      this._assert(actualCode === code, `expected response status ${actualCode} to equal ${code}`);
    }

    property(prop) {
      const hasProp = this.actual && typeof this.actual === 'object' && prop in this.actual;
      this._assert(hasProp, `expected object to have property '${prop}'`);
    }

    include(val) {
      const incl = typeof this.actual === 'string' ? this.actual.includes(val) : Array.isArray(this.actual) ? this.actual.includes(val) : false;
      this._assert(incl, `expected ${JSON.stringify(this.actual)} to include ${JSON.stringify(val)}`);
    }

    true() {
      this._assert(this.actual === true, `expected ${this.actual} to be true`);
    }

    false() {
      this._assert(this.actual === false, `expected ${this.actual} to be false`);
    }

    null() {
      this._assert(this.actual === null, `expected ${this.actual} to be null`);
    }
  }

  // Response object wrapper
  const pmResponse = respData ? {
    code: respData.status_code,
    status: respData.status_text || '',
    responseTime: respData.elapsed_ms || 0,
    headers: {
      get: (headerName) => {
        if (!respData.headers) return null;
        const target = headerName.toLowerCase();
        for (const [k, v] of Object.entries(respData.headers)) {
          if (k.toLowerCase() === target) return v;
        }
        return null;
      }
    },
    text: () => respData.body_text || '',
    json: () => {
      try {
        return JSON.parse(respData.body_text || '{}');
      } catch (err) {
        throw new Error('Failed to parse response body as JSON: ' + err.message);
      }
    },
    to: {
      have: {
        status: (code) => {
          if (respData.status_code !== code) {
            throw new Error(`expected response to have status code ${code} but got ${respData.status_code}`);
          }
        },
        header: (headerName) => {
          const val = pmResponse.headers.get(headerName);
          if (val === null || val === undefined) {
            throw new Error(`expected response to have header '${headerName}'`);
          }
        }
      },
      be: {
        get success() {
          if (respData.status_code < 200 || respData.status_code >= 300) {
            throw new Error(`expected response code ${respData.status_code} to be 2xx success`);
          }
        },
        get clientError() {
          if (respData.status_code < 400 || respData.status_code >= 500) {
            throw new Error(`expected response code ${respData.status_code} to be 4xx client error`);
          }
        },
        get serverError() {
          if (respData.status_code < 500) {
            throw new Error(`expected response code ${respData.status_code} to be 5xx server error`);
          }
        }
      }
    }
  } : null;

  // Global `pm` object
  const pm = {
    environment: {
      get: (k) => env[k],
      set: (k, v) => { env[k] = String(v); },
      unset: (k) => { delete env[k]; },
      has: (k) => k in env,
      toObject: () => ({ ...env }),
    },
    collectionVariables: {
      get: (k) => colVars[k],
      set: (k, v) => { colVars[k] = String(v); },
      unset: (k) => { delete colVars[k]; },
      has: (k) => k in colVars,
      toObject: () => ({ ...colVars }),
    },
    globals: {
      get: (k) => globals[k],
      set: (k, v) => { globals[k] = String(v); },
      unset: (k) => { delete globals[k]; },
      has: (k) => k in globals,
      toObject: () => ({ ...globals }),
    },
    variables: {
      get: (k) => env[k] !== undefined ? env[k] : colVars[k] !== undefined ? colVars[k] : globals[k],
      set: (k, v) => { env[k] = String(v); },
    },
    request: {
      url: reqData.url || '',
      method: reqData.method || 'GET',
      headers: { ...(reqData.headers || {}) },
      body: reqData.body || '',
    },
    response: pmResponse,
    test: (name, testFn) => {
      try {
        testFn();
        testResults.push({ name: String(name), passed: true, error: null });
      } catch (err) {
        testResults.push({ name: String(name), passed: false, error: err.message });
      }
    },
    expect: (actual) => new Expectation(actual),
  };

  const sandboxConsole = {
    log: (...args) => logs.push(args.map(a => typeof a === 'object' ? JSON.stringify(a) : String(a)).join(' ')),
    warn: (...args) => logs.push('[WARN] ' + args.map(a => typeof a === 'object' ? JSON.stringify(a) : String(a)).join(' ')),
    error: (...args) => logs.push('[ERROR] ' + args.map(a => typeof a === 'object' ? JSON.stringify(a) : String(a)).join(' ')),
  };

  try {
    const fn = new Function('pm', 'console', scriptCode);
    fn(pm, sandboxConsole);
    process.stdout.write(JSON.stringify({
      ok: true,
      test_results: testResults,
      updated_environment: env,
      updated_collection_variables: colVars,
      logs: logs,
    }));
  } catch (err) {
    process.stdout.write(JSON.stringify({
      ok: false,
      error: err.message,
      stack: err.stack,
      test_results: testResults,
      updated_environment: env,
      updated_collection_variables: colVars,
      logs: logs,
    }));
  }
}

runSandbox();
