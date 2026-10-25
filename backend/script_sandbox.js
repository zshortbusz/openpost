/**
 * OpenPost Sandboxed JavaScript Runtime for Postman Scripts (`pm.*`).
 *
 * Runs via Node.js stdio JSON IPC inside an isolated V8 VM context with
 * zero host object references passed across the realm boundary.
 */

const fs = require('fs');
const vm = require('vm');

function runSandbox() {
  const inputRaw = fs.readFileSync(0, 'utf-8');
  let input;
  try {
    input = JSON.parse(inputRaw);
  } catch (err) {
    process.stdout.write(JSON.stringify({ ok: false, error: 'Invalid JSON input: ' + err.message }));
    process.exit(1);
  }

  const scriptCode = String(input.script || '');
  const initPayloadJson = JSON.stringify({
    request: {
      url: (input.request && input.request.url) || '',
      method: (input.request && input.request.method) || 'GET',
      headers: (input.request && input.request.headers) || {},
      body: (input.request && input.request.body) || '',
    },
    response: input.response ? {
      status_code: input.response.status_code,
      status_text: input.response.status_text || input.response.reason_phrase || '',
      elapsed_ms: input.response.elapsed_ms || 0,
      headers: input.response.headers || {},
      body_text: input.response.body_text || '',
    } : null,
    environment: input.environment || {},
    collection_variables: input.collection_variables || {},
    globals: input.globals || {},
  });

  // Bootstrap pm.* and console completely inside the isolated VM realm using only a JSON string primitive
  const bootstrapCode = `
    (function(initJson) {
      "use strict";
      const _JSON_parse = JSON.parse;
      const _JSON_stringify = JSON.stringify;
      const _Object_assign = Object.assign;
      const _Object_entries = Object.entries;
      const _Object_freeze = Object.freeze;
      const _String = String;
      const _Boolean = Boolean;
      const _Array_isArray = Array.isArray;

      const initData = _JSON_parse(initJson);
      const reqData = initData.request || {};
      const respData = initData.response || null;

      const env = _Object_assign({}, initData.environment || {});
      const colVars = _Object_assign({}, initData.collection_variables || {});
      const globals = _Object_assign({}, initData.globals || {});
      const logs = [];
      const testResults = [];

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
          this._assert(this.actual === expected, "expected " + _JSON_stringify(this.actual) + " to equal " + _JSON_stringify(expected));
          return this;
        }

        eql(expected) {
          const a = _JSON_stringify(this.actual);
          const b = _JSON_stringify(expected);
          this._assert(a === b, "expected " + a + " to deeply equal " + b);
          return this;
        }

        status(code) {
          const actualCode = respData ? respData.status_code : null;
          this._assert(actualCode === code, "expected response status " + actualCode + " to equal " + code);
          return this;
        }

        property(prop) {
          const hasProp = _Boolean(this.actual && typeof this.actual === "object" && prop in this.actual);
          this._assert(hasProp, "expected object to have property '" + prop + "'");
          return this;
        }

        include(val) {
          const incl = typeof this.actual === "string"
            ? this.actual.includes(val)
            : _Array_isArray(this.actual)
            ? this.actual.includes(val)
            : false;
          this._assert(incl, "expected " + _JSON_stringify(this.actual) + " to include " + _JSON_stringify(val));
          return this;
        }

        get true() {
          this._assert(this.actual === true, "expected " + _JSON_stringify(this.actual) + " to be true");
          return new Proxy(() => this, { get: (_, prop) => this[prop] });
        }

        get false() {
          this._assert(this.actual === false, "expected " + _JSON_stringify(this.actual) + " to be false");
          return new Proxy(() => this, { get: (_, prop) => this[prop] });
        }

        get null() {
          this._assert(this.actual === null, "expected " + _JSON_stringify(this.actual) + " to be null");
          return new Proxy(() => this, { get: (_, prop) => this[prop] });
        }

        get undefined() {
          this._assert(this.actual === undefined, "expected " + _JSON_stringify(this.actual) + " to be undefined");
          return new Proxy(() => this, { get: (_, prop) => this[prop] });
        }

        get ok() {
          this._assert(_Boolean(this.actual), "expected " + _JSON_stringify(this.actual) + " to be truthy");
          return new Proxy(() => this, { get: (_, prop) => this[prop] });
        }
      }

      const pmResponse = respData ? {
        code: respData.status_code,
        status: respData.status_text || "",
        responseTime: respData.elapsed_ms || 0,
        headers: {
          get: (headerName) => {
            if (!respData.headers) return null;
            const target = _String(headerName).toLowerCase();
            for (const [k, v] of _Object_entries(respData.headers)) {
              if (k.toLowerCase() === target) return v;
            }
            return null;
          }
        },
        text: () => respData.body_text || "",
        json: () => {
          try {
            return _JSON_parse(respData.body_text || "{}");
          } catch (err) {
            throw new Error("Failed to parse response body as JSON: " + err.message);
          }
        },
        to: {
          have: {
            status: (code) => {
              if (respData.status_code !== code) {
                throw new Error("expected response to have status code " + code + " but got " + respData.status_code);
              }
            },
            header: (headerName) => {
              const val = pmResponse.headers.get(headerName);
              if (val === null || val === undefined) {
                throw new Error("expected response to have header '" + headerName + "'");
              }
            }
          },
          be: {
            get success() {
              if (respData.status_code < 200 || respData.status_code >= 300) {
                throw new Error("expected response code " + respData.status_code + " to be 2xx success");
              }
            },
            get clientError() {
              if (respData.status_code < 400 || respData.status_code >= 500) {
                throw new Error("expected response code " + respData.status_code + " to be 4xx client error");
              }
            },
            get serverError() {
              if (respData.status_code < 500) {
                throw new Error("expected response code " + respData.status_code + " to be 5xx server error");
              }
            }
          }
        }
      } : null;

      const pm = _Object_freeze({
        environment: _Object_freeze({
          get: (k) => env[_String(k)],
          set: (k, v) => { env[_String(k)] = _String(v); },
          unset: (k) => { delete env[_String(k)]; },
          has: (k) => _String(k) in env,
          toObject: () => _Object_assign({}, env),
        }),
        collectionVariables: _Object_freeze({
          get: (k) => colVars[_String(k)],
          set: (k, v) => { colVars[_String(k)] = _String(v); },
          unset: (k) => { delete colVars[_String(k)]; },
          has: (k) => _String(k) in colVars,
          toObject: () => _Object_assign({}, colVars),
        }),
        globals: _Object_freeze({
          get: (k) => globals[_String(k)],
          set: (k, v) => { globals[_String(k)] = _String(v); },
          unset: (k) => { delete globals[_String(k)]; },
          has: (k) => _String(k) in globals,
          toObject: () => _Object_assign({}, globals),
        }),
        variables: _Object_freeze({
          get: (k) => {
            const key = _String(k);
            return env[key] !== undefined ? env[key] : colVars[key] !== undefined ? colVars[key] : globals[key];
          },
          set: (k, v) => { env[_String(k)] = _String(v); },
        }),
        request: _Object_freeze({
          url: reqData.url || "",
          method: reqData.method || "GET",
          headers: _Object_freeze(_Object_assign({}, reqData.headers || {})),
          body: reqData.body || "",
        }),
        response: pmResponse ? _Object_freeze(pmResponse) : null,
        test: (name, testFn) => {
          try {
            testFn();
            testResults.push({ name: _String(name), passed: true, error: null });
          } catch (err) {
            testResults.push({ name: _String(name), passed: false, error: err && err.message ? _String(err.message) : _String(err) });
          }
        },
        expect: (actual) => new Expectation(actual),
      });

      const formatArgs = (args) => args.map(a => typeof a === "object" ? _JSON_stringify(a) : _String(a)).join(" ");
      const sandboxConsole = _Object_freeze({
        log: (...args) => logs.push(formatArgs(args)),
        warn: (...args) => logs.push("[WARN] " + formatArgs(args)),
        error: (...args) => logs.push("[ERROR] " + formatArgs(args)),
      });

      globalThis.pm = pm;
      globalThis.console = sandboxConsole;
      globalThis.process = undefined;
      globalThis.require = undefined;
      globalThis.Buffer = undefined;
      globalThis.fetch = undefined;

      return function collectState() {
        return _JSON_stringify({
          test_results: testResults,
          updated_environment: env,
          updated_collection_variables: colVars,
          logs: logs,
        });
      };
    })
  `;

  let collectState = null;
  try {
    const context = vm.createContext(Object.create(null), {
      codeGeneration: { strings: false, wasm: false },
    });
    const initFn = vm.runInContext(bootstrapCode, context, { timeout: 1000 });
    collectState = initFn(initPayloadJson);
    vm.runInContext(scriptCode, context, { timeout: 4500 });

    const finalState = JSON.parse(collectState());
    process.stdout.write(JSON.stringify({
      ok: true,
      test_results: finalState.test_results,
      updated_environment: finalState.updated_environment,
      updated_collection_variables: finalState.updated_collection_variables,
      logs: finalState.logs,
    }));
  } catch (err) {
    let partialState = {
      test_results: [],
      updated_environment: input.environment || {},
      updated_collection_variables: input.collection_variables || {},
      logs: [],
    };
    if (typeof collectState === 'function') {
      try {
        partialState = JSON.parse(collectState());
      } catch {
        // Ignore state collection error if VM terminated abnormally
      }
    }
    process.stdout.write(JSON.stringify({
      ok: false,
      error: err && err.message ? String(err.message) : String(err),
      stack: err && err.stack ? String(err.stack) : '',
      test_results: partialState.test_results,
      updated_environment: partialState.updated_environment,
      updated_collection_variables: partialState.updated_collection_variables,
      logs: partialState.logs,
    }));
  }
}

runSandbox();
