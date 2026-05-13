// Smoke tests for the system API client — verifies the shape of URL bindings
// without hitting a real backend. Mocks axios via the client module.

jest.mock("../api/client", () => {
  const calls = [];
  const make = (method) => (url, ...rest) => {
    calls.push({ method, url, rest });
    return Promise.resolve({ data: { method, url } });
  };
  return {
    __esModule: true,
    default: {
      get: make("GET"),
      post: make("POST"),
      put: make("PUT"),
      delete: make("DELETE"),
      _calls: calls,
    },
  };
});

import client from "../api/client";
import * as sysApi from "../api/system";

beforeEach(() => { client._calls.length = 0; });

test("getLicenseStatus hits /system/license/status", async () => {
  await sysApi.getLicenseStatus();
  expect(client._calls[0]).toMatchObject({ method: "GET", url: "/system/license/status" });
});

test("setNTPServer POSTs server name", async () => {
  await sysApi.setNTPServer("pool.ntp.org");
  expect(client._calls[0].method).toBe("POST");
  expect(client._calls[0].url).toBe("/system/ntp/sync");
});

test("revokeOtherSessions POSTs to correct path", async () => {
  await sysApi.revokeOtherSessions();
  expect(client._calls[0]).toMatchObject({
    method: "POST",
    url: "/auth/sessions/revoke-others",
  });
});

test("issueDownloadToken POSTs per-recording path", async () => {
  await sysApi.issueDownloadToken("rec-1");
  expect(client._calls[0].url).toBe("/recordings/rec-1/download-token");
});

test("verifyRecording POSTs to verify endpoint", async () => {
  await sysApi.verifyRecording("rec-2");
  expect(client._calls[0]).toMatchObject({
    method: "POST",
    url: "/recordings/rec-2/verify",
  });
});
